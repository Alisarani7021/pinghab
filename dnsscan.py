#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
رادار DNS — اسکنر چندکاناله سرورهای DNS برای گیمرها و کاربران ایران
=========================================================================
قابلیت‌ها:
  * اسکن UDP/53 و TCP/53 با آمار واقعی: تأخیر میانه، میانه قدرمطلق انحراف (MAD)،
    جیتر، درصد از دست رفتن بسته، پاسخ‌های نامعتبر
  * اسکن DoT (پورت 853) و DoH (HTTPS، پیام DNS خام) با اعتبارسنجی گواهی TLS
  * تشخیص DNS مخدوش/دستکاری‌شده (Hijack) و بررسی NXDOMAIN
  * تشخیص DNS مخصوص اپراتور (IPهای CDN داخلی مثل 10.x)
  * تست تأخیر لبه‌ی (edge) CDNها و سرورهای بازی با TCP/443
  * امتیازدهی ۰ تا ۱۰۰ و پیشنهاد کاربردی برای هر سرور
  * خروجی: گزارش HTML فارسی، JSON، CSV (سازگار با اکسل)، Markdown

استفاده:
  python3 dnsscan.py --preset global
  python3 dnsscan.py --preset all --name "ایرانسل من"
  python3 dnsscan.py --servers radar,electro,shecan,cloudflare,google
  python3 dnsscan.py --tag gaming --attempts 12
  python3 dnsscan.py --game-ips 1.2.3.4:"PUBG ME",5.6.7.8:"PUBG SG"

نکته علمی: DNS روی «پینگ خود بازی» اثر مستقیم ندارد (بازی با IP وصل می‌شود).
آنچه DNS عوض می‌کند: سرعت باز شدن، سرعت دانلود آپدیت، رفع تحریم/خطای ورود،
و مسیری که CDN به تو می‌دهد. تأخیر لبه‌ی CDN نزدیک‌ترین تقریب به «مسیر شبکه» است.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import html
import json
import os
import random
import socket
import ssl
import statistics
import struct
import sys
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVERS_FILE = HERE / "servers.json"

# ----------------------------------------------------------------------------- ابزارها

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def fa(text) -> str:
    """تبدیل ارقام لاتین به فارسی برای نمایش."""
    return str(text).translate(FA_DIGITS)


# ----------------------------------------------------------------------------- ساخت/تحلیل پکت DNS

QTYPES = {"A": 1, "AAAA": 28, "TXT": 16, "NS": 2}


def _enc_label(p: str) -> bytes:
    try:
        return p.encode("idna")
    except Exception:
        return p.encode("ascii", "ignore")


def build_query(name: str, qtype: int = 1, txid: int | None = None, rd: bool = True) -> tuple[bytes, int]:
    txid = random.randint(0, 0xFFFF) if txid is None else txid
    flags = 0x0100 if rd else 0x0000
    header = struct.pack(">HHHHHH", txid, flags, 1, 0, 0, 0)
    qname = b"".join(bytes([len(l)]) + l for l in (_enc_label(p) for p in name.split(".") if p)) + b"\x00"
    return header + qname + struct.pack(">HH", qtype, 1), txid


def parse_response(data: bytes) -> dict:
    """تحلیل حداقلی پاسخ DNS: rcode، تعداد پاسخ‌ها، رکوردهای A، TTL کمینه."""
    out = {"rcode": None, "ancount": 0, "a": [], "min_ttl": None, "valid": False}
    if len(data) < 12:
        return out
    txid, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    out["rcode"] = flags & 0xF
    out["ancount"] = an
    out["aa"] = bool(flags & 0x0400)
    out["tc"] = bool(flags & 0x0200)
    i = 12
    # رد کردن بخش سؤال
    for _ in range(qd):
        while i < len(data) and data[i] != 0:
            if data[i] & 0xC0:
                i += 2
                break
            i += data[i] + 1
        else:
            i += 1
        i += 4
    # رکوردهای پاسخ
    for _ in range(an):
        if i >= len(data):
            break
        while i < len(data) and data[i] != 0:
            if data[i] & 0xC0:
                i += 2
                break
            i += data[i] + 1
        else:
            i += 1
        if i + 10 > len(data):
            break
        rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", data[i:i + 10])
        i += 10
        rdata = data[i:i + rdlen]
        i += rdlen
        if rtype == 1 and rdlen == 4:
            out["a"].append(socket.inet_ntoa(rdata))
            out["min_ttl"] = ttl if out["min_ttl"] is None else min(out["min_ttl"], ttl)
    out["valid"] = True
    return out


def is_private(ip: str) -> bool:
    try:
        p = [int(x) for x in ip.split(".")]
    except Exception:
        return False
    return (p[0] == 10 or (p[0] == 172 and 16 <= p[1] <= 31) or (p[0] == 192 and p[1] == 168)
            or p[0] == 127 or (p[0] == 100 and 64 <= p[1] <= 127))


# ----------------------------------------------------------------------------- پروب‌ها

class UdpDnsProbe:
    """پروب UDP/53 با سوکت غیرمسدودکننده و آمارگیری."""

    def __init__(self, loop):
        self.loop = loop
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

    async def query(self, ip: str, name: str, timeout: float, qtype: int = 1):
        """یک کوئری؛ برمی‌گرداند (latency_ms یا None، پاسخ تحلیل‌شده یا None)."""
        pkt, txid = build_query(name, qtype)
        t0 = time.perf_counter()
        try:
            await self.loop.sock_sendto(self.sock, pkt, (ip, 53))
        except OSError as e:
            return None, None, f"send:{type(e).__name__}"
        deadline = time.perf_counter() + timeout
        while True:
            remain = deadline - time.perf_counter()
            if remain <= 0:
                return None, None, "timeout"
            try:
                data, addr = await asyncio.wait_for(self.loop.sock_recvfrom(self.sock, 4096), remain)
            except (asyncio.TimeoutError, TimeoutError):
                return None, None, "timeout"
            except OSError as e:
                return None, None, f"recv:{type(e).__name__}"
            if len(data) < 12 or struct.unpack(">H", data[:2])[0] != txid:
                continue  # پاسخ نامعتبر یا مربوط به کوئری قدیمی؛ نادیده بگیر
            ms = (time.perf_counter() - t0) * 1000
            return ms, parse_response(data), None

    def close(self):
        try:
            self.sock.close()
        except Exception:
            pass


async def tcp53_latency(ip: str, name: str, timeout: float):
    """تست سریع دسترس‌پذیری TCP/53 (پکت‌های بزرگ/فایروال‌ها)."""
    try:
        t0 = time.perf_counter()
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, 53), timeout)
        pkt, _ = build_query(name, 1)
        framed = struct.pack(">H", len(pkt)) + pkt
        writer.write(framed)
        await asyncio.wait_for(writer.drain(), timeout)
        head = await asyncio.wait_for(reader.readexactly(2), timeout)
        n = struct.unpack(">H", head)[0]
        await asyncio.wait_for(reader.readexactly(n), timeout)
        ms = (time.perf_counter() - t0) * 1000
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return ms
    except Exception:
        return None


async def tls_connect(ip: str, port: int, sni: str, timeout: float, verify: bool = True):
    ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(ip, port, ssl=ctx, server_hostname=sni), timeout)
    return reader, writer


async def dot_probe(ip: str, sni: str, name: str, timeout: float, samples: int = 3):
    """پروب DoT (پورت 853): اعتبار گواهی + تأخیر میانه + امکان اتصال پایدار."""
    res = {"ok": False, "cert": None, "ms": None, "error": None}
    try:
        reader, writer = await tls_connect(ip, 853, sni, timeout, verify=True)
        res["cert"] = "valid"
    except ssl.SSLCertVerificationError:
        res["cert"] = "invalid"
        try:
            reader, writer = await tls_connect(ip, 853, sni, timeout, verify=False)
        except Exception as e:
            res["error"] = type(e).__name__
            return res
    except Exception as e:
        res["error"] = type(e).__name__
        return res

    lat = []
    try:
        for _ in range(samples):
            pkt, txid = build_query(name, 1)
            t0 = time.perf_counter()
            writer.write(struct.pack(">H", len(pkt)) + pkt)
            await asyncio.wait_for(writer.drain(), timeout)
            head = await asyncio.wait_for(reader.readexactly(2), timeout)
            n = struct.unpack(">H", head)[0]
            await asyncio.wait_for(reader.readexactly(n), timeout)
            lat.append((time.perf_counter() - t0) * 1000)
        res["ms"] = statistics.median(lat)
        res["ok"] = True
    except Exception as e:
        res["error"] = type(e).__name__
        if lat:
            res["ms"] = statistics.median(lat)
            res["ok"] = True
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    return res


class DohSession:
    """نشست DoH با اتصال TLS پایدار (HTTP/1.1) برای اندازه‌گیری زمان واقعی resolve."""

    def __init__(self, ip, port, sni, verify=True):
        self.ip, self.port, self.sni = ip, port, sni
        self.verify = verify
        self.ctx = ssl.create_default_context() if verify else ssl._create_unverified_context()
        self.sock = None
        self.cert = None

    async def connect(self, timeout, loop):
        await loop.run_in_executor(None, self._connect_blocking, timeout)

    def _connect_blocking(self, timeout):
        raw = socket.create_connection((self.ip, self.port), timeout=timeout)
        raw.settimeout(timeout)
        self.sock = self.ctx.wrap_socket(raw, server_hostname=self.sni)
        try:
            self.cert = self.sock.getpeercert()
        except Exception:
            self.cert = None

    def _read_exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(min(4096, n - len(buf)))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    def query(self, name: str, timeout: float):
        import base64
        pkt, _ = build_query(name, 1)
        b64 = base64.urlsafe_b64encode(pkt).decode().rstrip("=")
        path = f"/dns-query?dns={b64}"
        req = (f"GET {path} HTTP/1.1\r\nHost: {self.sni}\r\nAccept: application/dns-message\r\n"
               f"User-Agent: dnsradar/1.0\r\nConnection: keep-alive\r\n\r\n").encode()
        t0 = time.perf_counter()
        self.sock.sendall(req)
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(2048)
            if not chunk:
                raise ConnectionError("closed")
            head += chunk
        head_b, rest = head.split(b"\r\n\r\n", 1)
        status = int(head_b.split(b" ")[1])
        clen = None
        chunked = False
        for line in head_b.split(b"\r\n")[1:]:
            k, _, v = line.partition(b":")
            k, v = k.strip().lower(), v.strip().lower()
            if k == b"content-length":
                clen = int(v)
            elif k == b"transfer-encoding" and b"chunked" in v:
                chunked = True
        if clen is not None:
            body = rest + self._read_exact(max(0, clen - len(rest))) if len(rest) < clen else rest
        elif chunked:
            body = rest
            while b"0\r\n\r\n" not in body:
                chunk = self.sock.recv(2048)
                if not chunk:
                    break
                body += chunk
        else:
            body = rest
        ms = (time.perf_counter() - t0) * 1000
        return status, ms, body[:512]

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except Exception:
            pass


async def doh_probe(url: str, sni: str, name: str, timeout: float, samples: int = 3):
    """پروب DoH؛ اگر URL با IP باشد، IP به‌عنوان مقصد سوکت و sni به‌عنوان Host استفاده می‌شود."""
    from urllib.parse import urlparse
    u = urlparse(url)
    host = u.hostname
    port = u.port or 443
    path = u.path or "/dns-query"
    target_ip = host
    if not host.replace(".", "").isdigit():
        try:
            target_ip = await asyncio.get_running_loop().getaddrinfo(host, None)
            target_ip = target_ip[0][4][0]
        except Exception as e:
            return {"ok": False, "ms": None, "cert": None, "error": f"dns:{type(e).__name__}"}

    res = {"ok": False, "ms": None, "cert": None, "error": None, "status": None}
    loop = asyncio.get_running_loop()
    sess = DohSession(target_ip, port, sni or host, verify=True)
    try:
        await sess.connect(timeout, loop)
        res["cert"] = "valid"
    except ssl.SSLCertVerificationError:
        res["cert"] = "invalid"
        sess = DohSession(target_ip, port, sni or host, verify=False)
        try:
            await sess.connect(timeout, loop)
        except Exception as e:
            res["error"] = type(e).__name__
            return res
    except Exception as e:
        res["error"] = f"{type(e).__name__}"
        return res

    lat = []
    try:
        for i in range(samples):
            status, ms, body = await loop.run_in_executor(None, lambda: sess.query(name, timeout))
            res["status"] = status
            if status != 200:
                res["error"] = f"http{status}"
                break
            if i > 0:
                lat.append(ms)
            await asyncio.sleep(0.02)
        if lat:
            res["ms"] = statistics.median(lat)
            res["ok"] = True
    except Exception as e:
        res["error"] = type(e).__name__
        if lat:
            res["ms"] = statistics.median(lat)
            res["ok"] = True
    finally:
        sess.close()
    return res


async def tcp443_probe(ip: str, timeout: float, samples: int = 3):
    """تأخیر TCP به پورت 443 (هرچند سرور فقط SYN-ACK می‌دهد؛ برای سنجش مسیر)."""
    lat = []
    for _ in range(samples):
        try:
            t0 = time.perf_counter()
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, 443), timeout)
            lat.append((time.perf_counter() - t0) * 1000)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        except Exception:
            continue
    return statistics.median(lat) if lat else None


# ----------------------------------------------------------------------------- اسکن یک سرور

@dataclass
class ServerResult:
    id: str
    name: str
    ip: str
    ip2: str = ""
    region: str = ""
    tags: list = field(default_factory=list)
    verified: bool = False
    note: str = ""
    homepage: str = ""
    score: float = 0.0
    grade: str = ""
    udp_ok: int = 0
    udp_total: int = 0
    ok_ratio: float = 0.0
    udp_median: float | None = None
    udp_min: float | None = None
    udp_p90: float | None = None
    jitter: float | None = None
    loss: float = 1.0
    tcp53: float | None = None
    ever_ok: bool = False
    dns_ok: bool = False          # رفع تحریم: دامنه تست پاسخ داد؟
    hijacked: bool = False        # زیردامنه تصادفی جواب گرفت؟ (دستکاری)
    hijack_ip: str | None = None
    local_cdn: bool = False       # IP داخلی برگرداند؟ (DNS مخصوص اپراتور)
    min_ttl: int | None = None
    dot_ok: bool = False
    dot_ms: float | None = None
    dot_cert: str | None = None
    doh_ok: bool = False
    doh_ms: float | None = None
    doh_cert: str | None = None
    doh_url: str | None = None
    edge_ms: float | None = None
    errors: list = field(default_factory=list)


async def scan_server(srv: dict, cfg, sem_udp: asyncio.Semaphore, sem_tls: asyncio.Semaphore,
                      progress: dict) -> ServerResult:
    r = ServerResult(
        id=srv["id"], name=srv.get("name", srv["id"]), ip=srv["ip"], ip2=srv.get("ip2", ""),
        region=srv.get("region", ""), tags=srv.get("tags", []), verified=srv.get("verified", False),
        note=srv.get("note", ""), homepage=srv.get("homepage", ""),
    )
    ip = srv["ip"]
    name_ok = cfg.test_domain       # دامنه‌ای که باید همیشه جواب بدهد
    n = cfg.attempts
    probe = UdpDnsProbe(asyncio.get_running_loop())   # سوکت اختصاصی همین سرور

    async with sem_udp:
        # --- ۱) اسکن UDP با n تلاش
        lat = []
        ok = 0
        bad = 0
        for _ in range(n):
            ms, parsed, err = await probe.query(ip, name_ok, cfg.timeout)
            if ms is None:
                if err == "timeout":
                    bad += 1
                else:
                    r.errors.append(err)
                continue
            if parsed and parsed.get("rcode") == 0 and parsed.get("a"):
                ok += 1
                lat.append(ms)
            elif parsed and parsed.get("rcode") == 0:
                ok += 1
                lat.append(ms)
            else:
                bad += 1
            await asyncio.sleep(0.01)

        r.udp_total, r.udp_ok = n, ok
        r.ok_ratio = ok / n if n else 0
        r.ever_ok = ok > 0
        r.dns_ok = ok > 0
        r.loss = max(0.0, 1 - r.ok_ratio)
        if lat:
            r.udp_median = statistics.median(lat)
            r.udp_min = min(lat)
            r.udp_p90 = sorted(lat)[max(0, int(len(lat) * 0.9) - 1)]
            r.jitter = (statistics.mean(abs(x - r.udp_median) for x in lat))  # MAD

        # --- ۲) تست دستکاری DNS
        if r.ever_ok:
            bogus = f"nxf-{random.randint(10**6, 10**7)}.{cfg.iran_domain}"
            ms, parsed, err = await probe.query(ip, bogus, cfg.timeout)
            if parsed and parsed.get("rcode") == 0 and parsed.get("a"):
                # فقط پاسخ A واقعی به یک دامنه‌ی قطعاً ناموجود = ریدایرکت/دستکاری
                r.hijacked = True
                r.hijack_ip = parsed["a"][0]
            ms, parsed, err = await probe.query(ip, f"www.{cfg.iran_domain}", cfg.timeout)
            if parsed and parsed.get("a"):
                ips = parsed["a"]
                r.local_cdn = any(is_private(x) for x in ips)
                if parsed.get("min_ttl") is not None:
                    r.min_ttl = parsed["min_ttl"]

        # --- ۳) TCP/53
        r.tcp53 = await tcp53_latency(ip, name_ok, cfg.timeout)

    probe.close()

    # --- ۴) DoT و DoH
    if cfg.do_dot and srv.get("dot") and r.ever_ok:
        async with sem_tls:
            d = await dot_probe(srv["dot"]["ip"], srv["dot"].get("sni", ""), name_ok, cfg.tls_timeout)
        r.dot_ok, r.dot_ms, r.dot_cert = d["ok"], d["ms"], d["cert"]
        if d.get("error"):
            r.errors.append("dot:" + d["error"])

    if cfg.do_doh and srv.get("doh"):
        async with sem_tls:
            for cand in srv["doh"]:
                d = await doh_probe(cand["url"], cand.get("sni", ""), name_ok, cfg.tls_timeout)
                if d["ok"]:
                    r.doh_ok, r.doh_ms, r.doh_cert, r.doh_url = d["ok"], d["ms"], d["cert"], cand["url"]
                    break
            else:
                if d.get("error"):
                    r.errors.append("doh:" + str(d["error"]))

    progress["done"] += 1
    print(f"  [{progress['done']:>2}/{progress['total']}] {r.id:<18} "
          f"ok={r.udp_ok}/{r.udp_total} "
          f"مدین={'—' if r.udp_median is None else format(r.udp_median, '.1f')}ms "
          f"جیتر={'—' if r.jitter is None else format(r.jitter, '.1f')} "
          f"{'DoT✓' if r.dot_ok else ''} {'DoH✓' if r.doh_ok else ''} "
          f"{'⚠هیجک' if r.hijacked else ''}", flush=True)
    return r


# ----------------------------------------------------------------------------- امتیازدهی

def grade_of(score: float) -> str:
    if score >= 88:
        return "عالی"
    if score >= 75:
        return "خیلی خوب"
    if score >= 60:
        return "خوب"
    if score >= 42:
        return "متوسط"
    if score > 0:
        return "ضعیف"
    return "بدون پاسخ"


def score_results(results: list[ServerResult], baseline: float | None) -> None:
    for r in results:
        if r.udp_median is None:
            if r.doh_ok and r.doh_ms is not None:
                # UDP/53 مسدود یا مخدوش است، اما تونل رمزنگاری‌شده جواب می‌دهد → ارزشمند در ایران
                s2 = 78.0 - min(38.0, r.doh_ms / 4.0)
                if r.doh_cert == "valid":
                    s2 += 4
                r.score = round(max(0.0, min(92.0, s2)), 1)
                r.grade = grade_of(r.score)
                r.tags = list(r.tags) + ["doh-only"]
            else:
                r.score = 0.0
                r.grade = grade_of(0)
            continue
        s = 100.0
        s -= (1 - r.ok_ratio) * 45                      # از دست رفتن بسته، سنگین
        s -= min(40.0, r.udp_median / 4.0)              # تأخیر: هر ۴ms یک امتیاز
        if r.jitter is not None:
            s -= min(15.0, r.jitter * 1.5)              # نوسان
        if not r.dns_ok:
            s -= 12
        if r.hijacked:
            s -= 25                                     # دستکاری DNS = خطر امنیتی
        if r.local_cdn:
            s += 4                                      # CDN داخلی = مسیر بهتر داخل ایران
        if baseline is not None and baseline > 0:
            s += max(-10.0, min(10.0, (baseline - r.udp_median) / baseline * 10))
        if r.doh_ok:
            s += 4
        if r.dot_ok:
            s += 2
        if r.doh_cert == "valid" or r.dot_cert == "valid":
            s += 2
        r.score = round(max(0.0, min(100.0, s)), 1)
        r.grade = grade_of(r.score)


def recommend(r: ServerResult) -> list[str]:
    out = []
    if r.udp_median is None:
        if r.doh_ok:
            out.append("UDP/53 در شبکه‌ات باز نیست، ولی DoH جواب می‌دهد — از حالت رمزنگاری‌شده استفاده کن")
        else:
            out.append("از شبکه تو در دسترس نیست")
        return out
    if r.hijacked:
        out.append("⚠️ پاسخ‌های جعلی می‌دهد — استفاده نکن")
    if r.loss > 0.25:
        out.append("⚠️ افت شدید بسته")
    if "gaming" in r.tags:
        out.append("مناسب گیم و مچ‌میکینگ")
    if "anti-sanction" in r.tags:
        out.append("مناسب رفع تحریم (ورود/خرید/آپدیت)")
    if "adblock" in r.tags:
        out.append("تبلیغات را بلاک می‌کند")
    if "family" in r.tags:
        out.append("فیلتر محتوای بزرگسال")
    if "privacy" in r.tags:
        out.append("حریم خصوصی/بدون لاگ")
    if r.local_cdn:
        out.append("CDN داخلی می‌دهد (شبکه تو را می‌شناسد)")
    if r.doh_ok:
        out.append("DoH فعال (ضد دستکاری شنود)")
    if r.dot_ok:
        out.append("DoT فعال")
    if r.udp_median is not None and r.udp_median < 25 and r.loss == 0:
        out.append("سرعت پاسخ‌دهی ممتاز")
    return out


# ----------------------------------------------------------------------------- نام‌گذاری مقصدهای لبه

DEFAULT_EDGES = [
    ("1.1.1.1", "Cloudflare"),
    ("8.8.8.8", "Google"),
    ("151.101.1.140", "Fastly"),
    ("23.62.36.100", "Akamai"),
    ("13.224.0.1", "CloudFront"),
    ("13.107.42.16", "Azure FD"),
    ("185.199.108.153", "GitHub Pages"),
    ("104.21.0.1", "Cloudflare Hosting"),
]


# ----------------------------------------------------------------------------- گزارش‌سازی

def fmt(v, unit="", dec=1, dash="—"):
    if v is None:
        return dash
    if isinstance(v, float):
        return fa(f"{v:.{dec}f}") + unit
    return fa(v) + unit


def render_json(results, meta, out: Path):
    out.write_text(json.dumps({
        "meta": meta,
        "results": [asdict(r) | {"recommend": recommend(r)} for r in results],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def render_csv(results, meta, out: Path):
    cols = ["rank", "name", "id", "ip", "ip2", "score", "grade", "udp_median", "jitter", "loss_pct",
            "ok_ratio", "tcp53", "dns_ok", "hijacked", "local_cdn", "dot_ok", "dot_ms", "doh_ok", "doh_ms",
            "edge_ms", "tags", "note"]
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for i, r in enumerate(results, 1):
            w.writerow({
                "rank": i, "name": r.name, "id": r.id, "ip": r.ip, "ip2": r.ip2,
                "score": r.score, "grade": r.grade,
                "udp_median": "" if r.udp_median is None else round(r.udp_median, 2),
                "jitter": "" if r.jitter is None else round(r.jitter, 2),
                "loss_pct": round(r.loss * 100), "ok_ratio": round(r.ok_ratio, 2),
                "tcp53": "" if r.tcp53 is None else round(r.tcp53, 1),
                "dns_ok": int(r.dns_ok), "hijacked": int(r.hijacked), "local_cdn": int(r.local_cdn),
                "dot_ok": int(r.dot_ok), "dot_ms": "" if r.dot_ms is None else round(r.dot_ms, 1),
                "doh_ok": int(r.doh_ok), "doh_ms": "" if r.doh_ms is None else round(r.doh_ms, 1),
                "edge_ms": "" if r.edge_ms is None else round(r.edge_ms, 1),
                "tags": ",".join(r.tags), "note": r.note,
            })


def _bar(value, best, worst, color):
    if value is None:
        return "<span class='muted'>—</span>"
    lo, hi = min(best, worst), max(best, worst)
    pct = 100.0 if hi == lo else max(4.0, min(100.0, (hi - value) / (hi - lo) * 100))
    return (f"<div class='barwrap'><div class='bar' style='width:{pct:.1f}%;background:{color}'></div>"
            f"<span class='barval'>{fa(f'{value:.1f}')}</span></div>")


def render_html(results, meta, edge_results, out: Path):
    good = [r for r in results if r.udp_median is not None]
    best = good[0] if good else None
    worst_med = max((r.udp_median for r in good), default=1)
    best_med = min((r.udp_median for r in good), default=0)

    def chip(r):
        c = []
        if r.hijacked:
            c.append("<span class='chip danger'>⚠ دستکاری‌شده</span>")
        if r.dns_ok and not r.hijacked:
            c.append("<span class='chip ok'>رفع تحریم</span>")
        if "gaming" in r.tags:
            c.append("<span class='chip game'>گیمینگ</span>")
        if "adblock" in r.tags:
            c.append("<span class='chip ad'>ضد تبلیغ</span>")
        if "family" in r.tags:
            c.append("<span class='chip fam'>خانواده</span>")
        if "privacy" in r.tags:
            c.append("<span class='chip priv'>بدون لاگ</span>")
        if "iran" in r.tags:
            c.append("<span class='chip ir'>ایرانی</span>")
        if r.doh_ok:
            c.append("<span class='chip doh'>DoH</span>")
        if r.dot_ok:
            c.append("<span class='chip dot'>DoT</span>")
        if r.local_cdn:
            c.append("<span class='chip cdn'>CDN داخلی</span>")
        if not r.verified:
            c.append("<span class='chip unv'>تأییدنشده</span>")
        return "".join(c)

    rows = []
    for i, r in enumerate(results, 1):
        reach = ("<span class='ok'>✓</span>" if r.ever_ok else "<span class='no'>✗</span>")
        rows.append(f"""
      <tr class="{'r-top' if i == 1 and r.score > 0 else ''}">
        <td class="num">{fa(i)}</td>
        <td class="name"><b>{html.escape(r.name)}</b><div class="sub">{html.escape(r.ip)}{' / ' + html.escape(r.ip2) if r.ip2 else ''}</div>
            <div class="chips">{chip(r)}</div>
            <div class="rec">{'، '.join(html.escape(x) for x in recommend(r))}</div></td>
        <td class="num big">{fa(f'{r.score:.0f}')}<div class="sub">{r.grade}</div></td>
        <td>{reach}<div class="sub">{fa(r.udp_ok)}/{fa(r.udp_total)}</div></td>
        <td>{_bar(r.udp_median, best_med, worst_med, 'linear-gradient(90deg,#12b981,#0ea5e9)')}</td>
        <td>{_bar(r.jitter, min((x.jitter for x in good), default=0), max((x.jitter for x in good), default=1), 'linear-gradient(90deg,#f59e0b,#ef4444)')}</td>
        <td class="num">{fa(round(r.loss*100))}٪</td>
        <td class="num">{fmt(r.tcp53, '', 0)}</td>
        <td class="num">{fmt(r.dot_ms, '', 0)}</td>
        <td class="num">{fmt(r.doh_ms, '', 0)}</td>
        <td class="num">{'—' if r.min_ttl is None else fa(r.min_ttl // 60)}</td>
      </tr>""")

    edge_rows = []
    for label, ms in edge_results:
        edge_rows.append(f"""
        <div class='erow'><span class='elabel'>{html.escape(label)}</span>
        {_bar(ms, 20, 300, 'linear-gradient(90deg,#8b5cf6,#06b6d4)')}</div>""")

    top3 = good[:3]
    podium = "".join(
        f"<div class='podium'><div class='p1'>{html.escape(r.name)}</div>"
        f"<div class='p2'>{fa(f'{r.udp_median:.1f}')} میلی‌ثانیه</div>"
        f"<div class='p3'>امتیاز {fa(f'{r.score:.0f}')} از ۱۰۰ — {r.grade}</div>"
        f"<div class='p4'>{html.escape(r.ip)}{' یا ' + html.escape(r.ip2) if r.ip2 else ''}</div></div>"
        for r in top3) or "<div class='muted'>هیچ سروری پاسخ نداد — اتصال شبکه را بررسی کن.</div>"

    doc = f"""<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>گزارش رادار DNS — {html.escape(meta['label'])}</title>
<style>
  :root {{ --bg:#0b1120; --card:#111c33; --line:#1e2d4a; --tx:#e8eefc; --mut:#8ba0c4;
           --ok:#12b981; --bad:#ef4444; --warn:#f59e0b; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:linear-gradient(180deg,#070d1a,#0b1120 300px); color:var(--tx);
         font-family:Tahoma,"Segoe UI",Vazirmatn,system-ui,sans-serif; font-size:15px; line-height:1.7; }}
  .wrap {{ max-width:1180px; margin:0 auto; padding:24px 16px 60px; }}
  h1 {{ font-size:26px; margin:0 0 6px; }}
  h2 {{ font-size:19px; margin:34px 0 12px; border-right:4px solid #0ea5e9; padding-right:10px; }}
  .head {{ background:linear-gradient(135deg,#122341,#0d1a30); border:1px solid var(--line);
          border-radius:18px; padding:20px 22px; }}
  .meta {{ color:var(--mut); font-size:13.5px; }}
  .kpis {{ display:flex; gap:12px; flex-wrap:wrap; margin-top:16px; }}
  .kpi {{ background:#0e1a2e; border:1px solid var(--line); border-radius:14px; padding:10px 16px; min-width:150px; }}
  .kpi b {{ display:block; font-size:22px; }}
  .kpi span {{ color:var(--mut); font-size:12.5px; }}
  .podiums {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:12px; margin-top:16px; }}
  .podium {{ background:linear-gradient(160deg,#123b2f,#0e1a2e); border:1px solid #1d4d3d;
            border-radius:16px; padding:14px 16px; }}
  .p1 {{ font-weight:700; font-size:17px; }}
  .p2 {{ color:#34d399; font-size:15px; }}
  .p3 {{ color:var(--mut); font-size:13px; }}
  .p4 {{ margin-top:6px; direction:ltr; text-align:left; font-family:ui-monospace,Consolas,monospace;
        font-size:13px; color:#93c5fd; }}
  table {{ width:100%; border-collapse:separate; border-spacing:0 6px; font-size:14px; }}
  th {{ text-align:right; color:var(--mut); font-weight:600; font-size:12.5px; padding:6px 10px; }}
  td {{ background:var(--card); padding:10px 10px; vertical-align:top; border-top:1px solid var(--line);
        border-bottom:1px solid var(--line); }}
  td:first-child {{ border-right:1px solid var(--line); border-radius:0 12px 12px 0; }}
  td:last-child {{ border-left:1px solid var(--line); border-radius:12px 0 0 12px; }}
  tr.r-top td {{ background:linear-gradient(90deg,#10243a,#111c33); box-shadow:inset 0 0 0 1px #1d7a5f; }}
  .num {{ font-variant-numeric:tabular-nums; direction:ltr; text-align:center; }}
  .big {{ font-size:19px; font-weight:700; }}
  .sub {{ color:var(--mut); font-size:12px; direction:ltr; }}
  .chips {{ margin-top:4px; }}
  .chip {{ display:inline-block; font-size:11px; padding:1px 7px; border-radius:999px; margin:2px 2px 0 0;
          border:1px solid var(--line); color:#cbd5e1; background:#0e1a2e; }}
  .chip.ok {{ border-color:#1d7a5f; color:#7ff0c0; }}
  .chip.danger {{ border-color:#7f1d1d; color:#fca5a5; background:#2a1113; }}
  .chip.game {{ border-color:#6d28d9; color:#c4b5fd; }}
  .chip.ad {{ border-color:#b45309; color:#fcd34d; }}
  .chip.fam {{ border-color:#be185d; color:#f9a8d4; }}
  .chip.priv {{ border-color:#0e7490; color:#67e8f9; }}
  .chip.ir {{ border-color:#166534; color:#86efac; }}
  .chip.doh {{ border-color:#4338ca; color:#a5b4fc; }}
  .chip.dot {{ border-color:#4338ca; color:#a5b4fc; }}
  .chip.cdn {{ border-color:#0f766e; color:#5eead4; }}
  .chip.unv {{ border-color:#78350f; color:#fdba74; }}
  .rec {{ color:#9fb3d4; font-size:12px; margin-top:3px; }}
  .ok {{ color:var(--ok); font-weight:700; }}
  .no {{ color:var(--bad); font-weight:700; }}
  .muted {{ color:var(--mut); }}
  .barwrap {{ position:relative; height:20px; background:#0e1a2e; border-radius:6px; overflow:hidden;
             border:1px solid var(--line); min-width:80px; }}
  .bar {{ height:100%; }}
  .barval {{ position:absolute; inset:0; text-align:center; font-size:12px; color:#e8eefc;
            font-variant-numeric:tabular-nums; }}
  .erow {{ display:grid; grid-template-columns:170px 1fr; align-items:center; gap:10px; margin-bottom:6px; }}
  .elabel {{ color:#cbd5e1; font-size:13.5px; }}
  .note {{ background:#0e1a2e; border:1px dashed var(--line); border-radius:14px; padding:14px 16px;
          color:#c3d3ee; font-size:13.5px; }}
  .warn {{ border-color:#7c2d12; background:#1f1206; }}
  .foot {{ color:var(--mut); font-size:12.5px; margin-top:26px; text-align:center; }}
  code {{ background:#0e1a2e; padding:1px 6px; border-radius:6px; direction:ltr; display:inline-block; }}
</style>
</head>
<body><div class="wrap">

  <div class="head">
    <h1>📡 گزارش رادار DNS</h1>
    <div class="meta">
      برچسب اجرا: <b>{html.escape(meta['label'])}</b> · زمان: {fa(meta['time_pretty'])} ·
      تعداد سرور: {fa(meta['count'])} · تلاش UDP برای هر سرور: {fa(meta['attempts'])} ·
      مبنای مقایسه (8.8.8.8): {fmt(meta.get('baseline'), ' میلی‌ثانیه')}
      <div>خروجی‌های همراه: <code>report.json</code> · <code>report.csv</code> · <code>report.md</code></div>
    </div>
    <div class="kpis">
      <div class="kpi"><b>{fa(meta['reachable'])}</b><span>سرور پاسخ‌ده</span></div>
      <div class="kpi"><b>{fa(meta['hijacked'])}</b><span>سرور دستکاری‌شده ⚠</span></div>
      <div class="kpi"><b>{fmt(meta.get('best_ms'), ' ms')}</b><span>کم‌ترین تأخیر</span></div>
      <div class="kpi"><b>{html.escape(best.name if best else '—')}</b><span>پیشنهاد اصلی</span></div>
    </div>
    <div class="podiums">{podium}</div>
  </div>

  <h2>🏆 جدول کامل نتایج</h2>
  <table>
    <thead><tr>
      <th>#</th><th>سرور</th><th>امتیاز</th><th>دسترسی</th><th>تأخیر UDP (ms)</th>
      <th>جیتر (ms)</th><th>افت بسته</th><th>TCP53</th><th>DoT</th><th>DoH</th><th>TTL (دقیقه)</th>
    </tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>

  <h2>🌍 تأخیر مسیر تا لبه‌های جهانی (TCP/443)</h2>
  <div class="note">این اعداد نشان می‌دهد شبکه‌ی تو در لحظه‌ی اسکن، تا لبه‌های بزرگ اینترنت چه تأخیری دارد.
  هرچه کمتر و یکنواخت‌تر باشد، تجربه‌ی بازی و دانلود بهتر است.</div>
  <div style="margin-top:12px">{''.join(edge_rows) or '<span class="muted">در دسترس نبود</span>'}</div>

  <h2>🎯 چه چیزی برای تو بهتر است؟</h2>
  <div class="note">
    <b>۱)</b> برای <b>ورود به بازی و رفع تحریم</b>: سروری را انتخاب کن که در جدول تگ «رفع تحریم» دارد و
    تأخیرش پایین است.<br>
    <b>۲)</b> برای <b>دانلود آپدیت</b>: کمترین «افت بسته» و کمترین جیتر مهم‌تر از تأخیر خام است.<br>
    <b>۳)</b> اگر سروری در ستون «افت بسته» عدد بزرگ دارد، هرچقدر هم سریع باشد در بازی لگ می‌دهد.<br>
    <b>۴)</b> اگر جایی «⚠ دستکاری‌شده» دیدی، آن DNS در شبکه‌ی تو ریدایرکت می‌شود؛ استفاده نکن.<br>
    <b>۵)</b> بهترین حالت برای مقاومت در برابر اختلال: <b>DoH</b> (تگ DoH دارد) — رمزنگاری‌شده و سخت‌تر قابل دستکاری.
  </div>

  <h2>⚠️ نکته‌ی مهم و صادقانه</h2>
  <div class="note warn">
    عوض کردن DNS <b>پینگ داخل مچ بازی را کم نمی‌کند</b>؛ بازی بعد از پیدا کردن سرور، با IP بازی می‌کند.
    DNS فقط زمان ورود، دانلود آپدیت، رفع تحریم، و کیفیت مسیر CDN را بهبود می‌دهد.
    برای کاهش واقعی پینگ بازی باید مسیر شبکه (تونل با خروجی نزدیک سرور بازی، پروتکل UDP، MTU درست) اصلاح شود.
    این گزارش ابزار سنجش و انتخاب است، نه معجزه.
  </div>

  <div class="foot">ساخته‌شده با «رادار DNS» — اسکنر چندکاناله DNS · {fa(meta['time_pretty'])}</div>
</div></body></html>"""
    out.write_text(doc, encoding="utf-8")


def render_md(results, meta, edge_results, out: Path):
    lines = [f"# 📡 گزارش رادار DNS — {meta['label']}", "",
             f"- زمان: {meta['time_pretty']}",
             f"- سرورهای اسکن‌شده: {meta['count']} (پاسخ‌ده: {meta['reachable']})",
             f"- مبنای مقایسه 8.8.8.8: {meta.get('baseline') and round(meta['baseline'], 1)} ms", "",
             "| # | سرور | امتیاز | وضعیت | تأخیر | جیتر | افت بسته | DoH | DoT | یادداشت |",
             "|---|------|-------:|-------|------:|-----:|---------:|:---:|:---:|---------|"]
    for i, r in enumerate(results, 1):
        lines.append("| {} | {} | {} | {} | {} | {} | {}٪ | {} | {} | {} |".format(
            i, r.name, r.score, r.grade,
            "—" if r.udp_median is None else round(r.udp_median, 1),
            "—" if r.jitter is None else round(r.jitter, 1),
            round(r.loss * 100), "✓" if r.doh_ok else "✗", "✓" if r.dot_ok else "✗",
            "؛ ".join(recommend(r))))
    lines += ["", "## تأخیر لبه‌های جهانی (TCP/443)", "",
              "| مقصد | تأخیر |", "|------|------:|"]
    for label, ms in edge_results:
        lines.append(f"| {label} | {'—' if ms is None else round(ms, 1)} |")
    lines += ["", "> نکته: DNS پینگ داخل بازی را کم نمی‌کند؛ برای پینگ، مسیر شبکه/تونل مهم است.", ""]
    out.write_text("\n".join(lines), encoding="utf-8")


# ----------------------------------------------------------------------------- اجرای اصلی

@dataclass
class Cfg:
    attempts: int = 8
    timeout: float = 2.0
    tls_timeout: float = 4.0
    concurrency: int = 24
    tls_concurrency: int = 8
    do_dot: bool = True
    do_doh: bool = True
    test_domain: str = "www.wikipedia.org"
    iran_domain: str = "www.aparat.com"
    label: str = "پیش‌فرض"


PRESETS = {
    "global": ["cloudflare", "cloudflare-malware", "cloudflare-family", "google", "quad9", "quad9-unsec",
               "opendns", "opendns-family", "adguard", "adguard-unfiltered", "adguard-family", "nextdns",
               "controld", "dnssb", "mullvad", "dns0", "dns0-kids", "yandex", "comodo", "level3",
               "verisign", "he", "fdn", "uncensored", "dnswatch", "neustar", "cleanbrowsing", "safedns",
               "alidns", "dnspod", "dns114", "quad101", "seznam", "ttnet"],
    "iran": ["radar", "electro", "shecan", "begzar", "403online", "vanilla", "zeus", "shelter", "shatel",
             "hostiran", "serverir", "tci", "parsonline", "greenteam"],
    "gaming": ["radar", "electro", "vanilla", "zeus", "shelter", "cloudflare", "google", "quad9",
               "adguard", "dnssb", "ttnet"],
    "privacy": ["cloudflare", "quad9", "mullvad", "dnssb", "dns0", "controld", "uncensored", "dnswatch",
                "fdn", "nextdns", "adguard"],
    "family": ["cloudflare-family", "adguard-family", "cleanbrowsing", "opendns-family", "dns0-kids"],
    "turkey": ["ttnet", "google", "cloudflare", "quad9"],
}


def load_servers() -> dict:
    data = json.loads(SERVERS_FILE.read_text(encoding="utf-8"))
    return {s["id"]: s for s in data["servers"]}


async def run(args):
    all_servers = load_servers()
    if args.servers:
        ids = [x.strip() for x in args.servers.split(",") if x.strip()]
    elif args.preset in PRESETS:
        ids = PRESETS[args.preset]
    elif args.tag:
        ids = [s["id"] for s in all_servers.values() if args.tag in s.get("tags", [])]
    else:
        ids = list(all_servers)

    unknown = [i for i in ids if i not in all_servers]
    if unknown:
        print("سرورهای ناشناس (نادیده گرفته شد):", ", ".join(unknown))
    servers = [all_servers[i] for i in ids if i in all_servers]
    if not servers:
        print("هیچ سروری انتخاب نشد.")
        return

    cfg = Cfg(attempts=args.attempts, timeout=args.timeout, tls_timeout=args.tls_timeout,
              concurrency=args.concurrency, tls_concurrency=args.tls_concurrency,
              do_dot=not args.no_dot, do_doh=not args.no_doh, label=args.name)

    print(f"\n📡 رادار DNS — {len(servers)} سرور | تلاش: {cfg.attempts} | تایم‌اوت: {cfg.timeout}s | "
          f"مخروطی: {cfg.concurrency}\n" + "-" * 78)

    # مبنای مقایسه
    loop = asyncio.get_running_loop()
    baseline_probe = UdpDnsProbe(loop)
    base_lat = []
    for _ in range(max(4, cfg.attempts // 2)):
        ms, _, _ = await baseline_probe.query("8.8.8.8", cfg.test_domain, cfg.timeout)
        if ms is not None:
            base_lat.append(ms)
    baseline = statistics.median(base_lat) if base_lat else None
    print(f"  مبنا (8.8.8.8): {'قابل دسترس نیست' if baseline is None else format(baseline, '.1f') + ' ms'}\n")

    sem_udp = asyncio.Semaphore(cfg.concurrency)
    sem_tls = asyncio.Semaphore(cfg.tls_concurrency)
    progress = {"done": 0, "total": len(servers)}

    tasks = [scan_server(s, cfg, sem_udp, sem_tls, progress) for s in servers]
    results = await asyncio.gather(*tasks)

    # --- تست لبه‌ها
    edge_results = []
    if not args.no_edges:
        edges = DEFAULT_EDGES
        if args.edges:
            edges = []
            for item in args.edges.split(","):
                ip, _, label = item.partition(":")
                edges.append((ip.strip(), label.strip() or ip.strip()))
        if args.game_ips:
            for item in args.game_ips.split(","):
                ip, _, label = item.partition(":")
                edges.insert(0, (ip.strip(), "🎮 " + (label.strip() or ip.strip())))
        print("\n🌍 تست لبه‌ها ...")
        sem_e = asyncio.Semaphore(6)
        async def one(ip, label):
            async with sem_e:
                ms = await tcp443_probe(ip, cfg.timeout + 1)
                print(f"  {label:<24} {('—' if ms is None else format(ms, '.1f') + ' ms')}")
                return (label, ms)
        edge_results = await asyncio.gather(*[one(ip, lb) for ip, lb in edges])

    # --- امتیازدهی و مرتب‌سازی
    score_results(results, baseline)
    # اگر latency لبه اندازه‌گیری شده، به‌عنوان ستون کمکی به سرورها وصل کن (برای گزارش)
    edge_best = min((ms for _, ms in edge_results if ms), default=None)
    for r in results:
        r.edge_ms = edge_best
    def sort_key(r):
        ms = r.udp_median if r.udp_median is not None else (
            (r.doh_ms + 30) if (r.doh_ok and r.doh_ms is not None) else 9e9)
        return (-r.score, ms)
    results.sort(key=sort_key)

    now = datetime.now(timezone.utc).astimezone()
    meta = {
        "label": args.name,
        "time": now.isoformat(),
        "time_pretty": now.strftime("%Y-%m-%d %H:%M"),
        "count": len(results),
        "reachable": sum(1 for r in results if r.ever_ok),
        "hijacked": sum(1 for r in results if r.hijacked),
        "attempts": cfg.attempts,
        "baseline": baseline,
        "best_ms": min((r.udp_median for r in results if r.udp_median is not None), default=None),
        "edges": edge_results,
        "test_domain": cfg.test_domain,
        "tool": "dnsradar 1.1",
    }

    outdir = Path(args.out_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    formats = set((args.formats or "html,json,csv,md").split(","))
    written = []
    if "json" in formats:
        render_json(results, meta, outdir / "report.json"); written.append("report.json")
    if "csv" in formats:
        render_csv(results, meta, outdir / "report.csv"); written.append("report.csv")
    if "md" in formats:
        render_md(results, meta, edge_results, outdir / "report.md"); written.append("report.md")
    if "html" in formats:
        render_html(results, meta, edge_results, outdir / "report.html"); written.append("report.html")

    print("\n" + "=" * 78)
    print(f"🥇 بهترین‌ها برای «{cfg.label}»:")
    for i, r in enumerate(results[:8], 1):
        if r.udp_median is None:
            continue
        print(f"  {i}. {r.name:<28} {r.udp_median:6.1f} ms  امتیاز {r.score:5.1f}  {r.grade:<9} "
              f"{'⚠ دستکاری‌شده ' if r.hijacked else ''}{'⚠ افت بسته ' if r.loss > .25 else ''}")
    print("=" * 78)
    print("📁 فایل‌های گزارش:", ", ".join(str(outdir / w) for w in written))
    return results, meta


def main():
    ap = argparse.ArgumentParser(description="رادار DNS — اسکنر چندکاناله DNS برای ایران و گیمینگ")
    ap.add_argument("--preset", default="global", choices=list(PRESETS) + ["all"],
                    help="مجموعه آماده: global / iran / gaming / privacy / family / turkey / all")
    ap.add_argument("--servers", help="لیست شناسه‌ها با کاما: radar,electro,cloudflare")
    ap.add_argument("--tag", help="فیلتر بر اساس تگ: gaming, iran, adblock, privacy, family")
    ap.add_argument("--attempts", type=int, default=8, help="تعداد تلاش UDP برای هر سرور (پیش‌فرض ۸)")
    ap.add_argument("--timeout", type=float, default=2.0, help="تایم‌اوت هر تلاش UDP (ثانیه)")
    ap.add_argument("--tls-timeout", type=float, default=4.0, help="تایم‌اوت DoT/DoH")
    ap.add_argument("--concurrency", type=int, default=24, help="همزمانی اسکن UDP")
    ap.add_argument("--tls-concurrency", type=int, default=8, help="همزمانی اتصال‌های TLS")
    ap.add_argument("--no-dot", action="store_true", help="DoT را اسکن نکن")
    ap.add_argument("--no-doh", action="store_true", help="DoH را اسکن نکن")
    ap.add_argument("--no-edges", action="store_true", help="تست لبه‌های CDN را انجام نده")
    ap.add_argument("--edges", help="مقصدهای دلخواه: ip:label,ip:label")
    ap.add_argument("--game-ips", help="آی‌پی سرورهای بازی برای تست مسیر: ip:label,ip:label")
    ap.add_argument("--out-dir", default=str(HERE / "reports"), help="پوشه خروجی گزارش")
    ap.add_argument("--name", default="پیش‌فرض", help="برچسب اجرا (مثلاً: ایرانسل مشهد)")
    ap.add_argument("--formats", default="html,json,csv,md", help="html,json,csv,md")
    args = ap.parse_args()
    if args.preset == "all":
        args.servers = ",".join(load_servers().keys())
    asyncio.run(run(args))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nلغو شد.")
        sys.exit(130)
