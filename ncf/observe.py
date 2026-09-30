#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCF · لایهٔ مشاهده (Observation Layer)
=========================================================================
پروب‌های واقعی و بدون نیاز به روت که به‌عنوان «حسگر» به کار می‌روند:

  probe_udp_dns(ip, name, ...)        → RTT + rcode + پاسخ‌ها (UDP/53)
  probe_udp_padded(ip, size)          → آیا پکت UDP با حجم مشخص زنده می‌رسد؟ (EDNS0 padding)
  sweep_udp_payload(ip, sizes)        → بزرگ‌ترین حجم UDP که از مسیر رد می‌شود
  probe_tcp(ip, port)                 → زمان دست‌دادن TCP
  probe_tls(ip, sni)                  → زمان دست‌دادن TLS (اختلافش با TCP = cost رمزنگاری/دستکاری)
  probe_gateway_rtt()                 → RTT تا گیت‌وی محلی (تفکیک مشکل «محلی» از «بیرونی»)
  probe_ipv6()                        → سلامت مسیر IPv6
  observe_path(...)                   → یک بردار مشاهدهٔ کامل از یک مسیر نامزد

هیچ payloadی ذخیره نمی‌شود؛ فقط telemetry (زمان، تأخیر، از دست رفتن) برگردانده می‌شود.

اجرا برای تست سریع:
    python3 ncf/observe.py
"""

from __future__ import annotations

import json
import os
import random
import socket
import struct
import sys
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

# موتور بسته‌سازی DNS را از پروژهٔ اصلی قرض می‌گیریم (همان کدی که تست شده است)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dnsscan import build_query, parse_response  # noqa: E402

DEFAULT_NAME = "www.wikipedia.org"
PUBLIC_TEST_NAME = "www.wikipedia.org"


# ----------------------------------------------------------------------------- انواع داده

@dataclass
class Obs:
    """یک مشاهدهٔ خام از یک مسیر: فقط عدد، بدون محتوا."""
    ts: float
    kind: str                 # dns_udp | dns_udp_padded | tcp | tls | gateway | ipv6
    target: str               # مسیر/سرور
    ok: bool
    rtt_ms: float | None = None
    loss: bool = False
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------- کوئری پد‌شده (EDNS0 Padding)

def build_query_padded(name: str, total_size: int = 1232, txid: int | None = None,
                       udp_payload: int = 4096) -> tuple[bytes, int]:
    """
    ساخت کوئری DNS با EDNS0 + گزینهٔ PADDING (RFC 7830) تا به حجم کل مشخصی برسد.
    اگر مسیر/فایروال بسته‌های UDP بزرگ را حذف کند، پاسخ نمی‌رسد → نشانهٔ فیلترینگ حجمی یا MTU.
    """
    txid = random.randint(0, 0xFFFF) if txid is None else txid
    header = struct.pack(">HHHHHH", txid, 0x0100, 1, 0, 0, 1)  # arcount=1
    labels = [p for p in name.split(".") if p]
    qname = b"".join(bytes([len(l)]) + l.encode("ascii", "ignore") for l in labels) + b"\x00"
    question = qname + struct.pack(">HH", 1, 1)
    base = len(header) + len(question) + 11          # 11 = OPT: name(1)+type(2)+class(2)+ttl(4)+rdlen(2)
    pad = max(0, total_size - base - 4)              # 4 = هدر گزینهٔ PADDING
    opt = (b"\x00" + struct.pack(">HHIH", 41, udp_payload, 0, 4 + pad)
           + struct.pack(">HH", 12, pad) + b"\x00" * pad)
    return header + question + opt, txid


# ----------------------------------------------------------------------------- پروب‌های پایه

def probe_udp_dns(ip: str, name: str = DEFAULT_NAME, timeout: float = 1.5,
                  payload_size: int | None = None) -> Obs:
    """یک کوئری واقعی UDP/53. payload_size اگر داده شود، از EDNS0 padding استفاده می‌شود."""
    try:
        if payload_size:
            pkt, txid = build_query_padded(name, payload_size)
        else:
            pkt, txid = build_query(name, 1)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(timeout)
        t0 = time.perf_counter()
        s.sendto(pkt, (ip, 53))
        while True:
            data, _ = s.recvfrom(4096)
            if len(data) >= 12 and struct.unpack(">H", data[:2])[0] == txid:
                rtt = (time.perf_counter() - t0) * 1000
                p = parse_response(data)
                return Obs(time.time(), "dns_udp", ip, bool(p.get("valid")), round(rtt, 2),
                           not p.get("valid"),
                           {"rcode": p.get("rcode"), "a": p.get("a", [])[:3], "size": len(data),
                            "qsize": len(pkt)})
    except Exception:
        return Obs(time.time(), "dns_udp", ip, False, None, True, {"qsize": payload_size or 0})
    finally:
        try:
            s.close()
        except Exception:
            pass
    return Obs(time.time(), "dns_udp", ip, False, None, True, {})


def sweep_udp_payload(ip: str, sizes: tuple[int, ...] = (512, 900, 1232, 1400, 1500),
                      timeout: float = 1.5) -> dict:
    """
    بزرگ‌ترین حجم UDP که از مسیر رد می‌شود را پیدا می‌کند.
    کاربرد: تشخیص فیلترینگ حجمی DNS و مسائل PMTU بدون نیاز به روت.
    """
    out = {}
    for size in sizes:
        o = probe_udp_dns(ip, payload_size=size, timeout=timeout)
        out[size] = {"ok": o.ok, "rtt_ms": o.rtt_ms}
        time.sleep(0.05)
    oks = [s for s, v in out.items() if v["ok"]]
    return {"sizes": out, "max_ok": max(oks) if oks else None,
            "min_fail": min([s for s in sizes if not out[s]["ok"]], default=None)}


def probe_tcp(ip: str, port: int = 443, timeout: float = 3.0) -> Obs:
    """زمان برقراری TCP (دست‌دادن سه‌مرحله‌ای). اتصال رد‌شده هم RTT معتبر می‌دهد."""
    t0 = time.perf_counter()
    try:
        s = socket.create_connection((ip, port), timeout=timeout)
        rtt = (time.perf_counter() - t0) * 1000
        s.close()
        return Obs(time.time(), "tcp", f"{ip}:{port}", True, round(rtt, 2), False, {"refused": False})
    except ConnectionRefusedError:
        rtt = (time.perf_counter() - t0) * 1000      # RST فوری = مسیر سالم است
        return Obs(time.time(), "tcp", f"{ip}:{port}", True, round(rtt, 2), False, {"refused": True})
    except Exception as e:
        return Obs(time.time(), "tcp", f"{ip}:{port}", False, None, True, {"err": type(e).__name__})


def probe_tls(ip: str, sni: str = "www.cloudflare.com", port: int = 443, timeout: float = 4.0) -> Obs:
    """زمان کامل دست‌دادن TLS؛ اختلاف آن با TCP هزینهٔ رمزنگاری/دستکاری مسیر را نشان می‌دهد."""
    import ssl
    ctx = ssl.create_default_context()
    t0 = time.perf_counter()
    try:
        raw = socket.create_connection((ip, port), timeout=timeout)
        raw.settimeout(timeout)
        with ctx.wrap_socket(raw, server_hostname=sni) as ss:
            rtt = (time.perf_counter() - t0) * 1000
            cert = {}
            try:
                c = ss.getpeercert() or {}
                cert = {"subject": str(c.get("subject")), "notAfter": c.get("notAfter")}
            except Exception:
                pass
            return Obs(time.time(), "tls", f"{ip}/{sni}", True, round(rtt, 2), False, cert)
    except Exception as e:
        return Obs(time.time(), "tls", f"{ip}/{sni}", False, None, True, {"err": type(e).__name__})


def probe_gateway_rtt(timeout: float = 1.0) -> Obs:
    """
    RTT تا گیت‌وی محلی (بدون روت): از /proc/net/route خوانده می‌شود و با یک تلاش TCP اندازه‌گیری می‌شود.
    اگر گیت‌وی به RST جواب بدهد، همان زمان = RTT محلی است.
    """
    gw = None
    try:
        for line in Path("/proc/net/route").read_text().splitlines()[1:]:
            f = line.split()
            if len(f) > 2 and f[1] == "00000000" and f[7] == "00000000":
                gw = ".".join(str(int(f[2][i:i + 2], 16)) for i in (6, 4, 2, 0))
                break
    except Exception:
        gw = None
    if not gw:
        return Obs(time.time(), "gateway", "unknown", False, None, True, {"err": "no_route"})
    for port in (80, 443, 53):
        o = probe_tcp(gw, port, timeout=timeout)
        if o.ok:
            o.kind = "gateway"
            o.meta["gw"] = gw
            return o
    return Obs(time.time(), "gateway", gw, False, None, True, {"gw": gw, "err": "no_response"})


def probe_ipv6(host: str = "dns.google", timeout: float = 3.0) -> Obs:
    """سلامت مسیر IPv6 (اگر شبکه IPv6 نداشته باشد، شکست معنی‌دار نیست)."""
    try:
        infos = socket.getaddrinfo(host, 443, socket.AF_INET6, socket.SOCK_STREAM)
        if not infos:
            return Obs(time.time(), "ipv6", host, False, None, True, {"err": "no_aaaa"})
        target = infos[0][4][0]
        t0 = time.perf_counter()
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((target, 443))
        rtt = (time.perf_counter() - t0) * 1000
        s.close()
        return Obs(time.time(), "ipv6", host, True, round(rtt, 2), False, {"addr": target})
    except Exception as e:
        return Obs(time.time(), "ipv6", host, False, None, True, {"err": type(e).__name__})


# ----------------------------------------------------------------------------- مشاهدهٔ یک مسیر کامل

@dataclass
class PathObsSpec:
    """مسیر نامزد: یک نقطهٔ خروجی/حل‌کننده که می‌خواهیم کیفیتش را بسنجیم."""
    id: str
    label: str
    dns_ip: str | None = None          # برای سنجش UDP/53
    tcp_ip: str | None = None          # برای سنجش TCP/TLS
    tcp_port: int = 443
    sni: str | None = None


def observe_path(spec: PathObsSpec, name: str = DEFAULT_NAME, deep: bool = False) -> dict:
    """بردار مشاهدهٔ یک مسیر: چند پروب مستقل + telemetry ترکیبی."""
    out = {"path": spec.id, "label": spec.label, "ts": time.time(), "obs": []}

    if spec.dns_ip:
        for _ in range(3):
            out["obs"].append(probe_udp_dns(spec.dns_ip, name).to_dict())
            time.sleep(0.03)
        if deep:
            out["payload_sweep"] = sweep_udp_payload(spec.dns_ip)

    if spec.tcp_ip:
        for _ in range(2):
            out["obs"].append(probe_tcp(spec.tcp_ip, spec.tcp_port).to_dict())
            time.sleep(0.03)
        if spec.sni:
            out["obs"].append(probe_tls(spec.tcp_ip, spec.sni, spec.tcp_port).to_dict())

    ok = [o for o in out["obs"] if o["ok"]]
    rtts = [o["rtt_ms"] for o in ok if o["rtt_ms"] is not None]
    out["summary"] = {
        "n": len(out["obs"]),
        "ok": len(ok),
        "loss": round(1 - len(ok) / max(1, len(out["obs"])), 3),
        "rtt_p50": round(sorted(rtts)[len(rtts) // 2], 2) if rtts else None,
        "rtt_min": round(min(rtts), 2) if rtts else None,
        "rtt_max": round(max(rtts), 2) if rtts else None,
    }
    if spec.dns_ip:
        out["summary"]["urltest_target"] = spec.dns_ip
    return out


def environment_snapshot() -> dict:
    """یک عکس فوری از محیط: گیت‌وی محلی + IPv4/IPv6 + زمان."""
    gw = probe_gateway_rtt()
    v6 = probe_ipv6()
    return {
        "ts": time.time(),
        "gateway": gw.to_dict(),
        "ipv6": v6.to_dict(),
        "pid": os.getpid(),
    }


# ----------------------------------------------------------------------------- اجرای مستقیم

if __name__ == "__main__":
    print("=" * 74)
    print("NCF · تست لایهٔ مشاهده (روی شبکهٔ واقعی این ماشین)")
    print("=" * 74)
    env = environment_snapshot()
    print(f"\nمحیط: گیت‌وی محلی → "
          f"{'✅ ' + str(env['gateway']['rtt_ms']) + ' ms' if env['gateway']['ok'] else '❌ در دسترس نبود'}"
          f" | IPv6 → {'✅ ' + str(env['ipv6']['rtt_ms']) + ' ms' if env['ipv6']['ok'] else '❌ ندارد/خراب'}")

    print("\n۱) پینگ UDP/53:")
    for ip in ("1.1.1.1", "8.8.8.8", "9.9.9.9", "185.222.222.222"):
        o = probe_udp_dns(ip)
        print(f"   {ip:16s} {'✅' if o.ok else '❌'} {str(o.rtt_ms) + ' ms' if o.rtt_ms else '—'}")

    print("\n۲) جاروب حجم UDP (تشخیص فیلترینگ حجمی/MTU):")
    sw = sweep_udp_payload("8.8.8.8", sizes=(512, 900, 1232, 1400, 1500))
    for size, r in sw["sizes"].items():
        print(f"   {size:5d} بایت → {'✅' if r['ok'] else '❌'} {str(r['rtt_ms']) + ' ms' if r['rtt_ms'] else ''}")
    print(f"   بیشترین حجم زنده: {sw['max_ok']}")

    print("\n۳) TCP و TLS و اختلافشان (هزینهٔ رمزنگاری/دستکاری):")
    t = probe_tcp("1.1.1.1", 443)
    tl = probe_tls("1.1.1.1", "one.one.one.one")
    print(f"   TCP: {t.rtt_ms} ms | TLS: {tl.rtt_ms} ms | اختلاف: "
          f"{None if not (t.rtt_ms and tl.rtt_ms) else round(tl.rtt_ms - t.rtt_ms, 1)} ms")

    print("\n۴) نمونهٔ مشاهدهٔ کامل یک مسیر:")
    spec = PathObsSpec(id="cf", label="کلودفلر", dns_ip="1.1.1.1", tcp_ip="1.1.1.1", sni="one.one.one.one")
    obs = observe_path(spec, deep=True)
    print(json.dumps(obs["summary"], ensure_ascii=False, indent=2))
