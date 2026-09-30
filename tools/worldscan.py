#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorldScan · اسکنر DNS جهانی با «سنجش اثر»
=========================================================================
چیزی که این ابزار را از هر dnseval/dnsping/dnsping موجود جدا می‌کند:

  ۱) «سنجش اثر» (impact): رزولور را با پینگ خودش نمی‌سنجیم؛ می‌سنجیم
     **کدام آی‌پی را برای دامنهٔ مقصد برمی‌گرداند** و بعد تأخیر تا همان آی‌پی را
     اندازه می‌گیریم. دو رزولور با RTT یکسان می‌توانند PoP متفاوتی بدهند و
     تجربهٔ بازی‌شان ۴۰ms فرق کند. این همان چیزی است که واقعاً پینگ بازی را
     تغییر می‌دهد — و در هیچ ابزار دیگری اندازه‌گیری نمی‌شود.
  ۲) تشخیص دست‌کاری: پاسخ‌ها با «اجماع» (consensus) مقایسه می‌شوند؛ رزولوری که
     آی‌پی متفاوت بدهد علامت می‌خورد (با آی‌پی‌های واقعی، برای بازرسی دستی).
  ۳) مسیر سرد/گرم: تفکیک «پاسخ از کش» و «پاسخ با بازگشت کامل». بازی‌ها در
     ۹۰٪ مواقع مسیر گرم را می‌بینند؛ سنجیدن فقط مسیر سرد گمراه‌کننده است.
  ۴) IPv4 و IPv6 با تشخیص خودکار دسترسی‌پذیری + EDNS0 + پرچم DNSSEC.

اخلاق سنجش: نرخ ارسال قابل محدودسازی است (--rate)، پروب‌ها کوچک‌اند و فقط از
خودمان به یک سرور عمومی می‌رود؛ هیچ باری روی سرویس‌دهنده تحمیل نمی‌شود.

اجرا:
    python3 tools/worldscan.py --countries IR,DE,TR,AE --limit-per-country 20
    python3 tools/worldscan.py --curated --v6
    python3 tools/worldscan.py --countries IR --limit-per-country 24 --targets cdn
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import socket
import statistics
import struct
import time
from dataclasses import dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data", "dns_world")

A, AAAA, CNAME, OPT = 1, 28, 5, 41
RCODES = {0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL", 3: "NXDOMAIN", 4: "NOTIMP", 5: "REFUSED",
          9: "NOTAUTH", 10: "NOTZONE"}

# دامنه‌های سنجش اثر: جایی که تغییر PoP واقعاً روی تجربه اثر می‌گذارد
TARGETS = {
    "cdn": [
        ("cdn.cloudflare.steamstatic.com", "استیم CDN (کلودفلر)"),
        ("steamcdn-a.akamaihd.net", "استیم (آکامای)"),
        ("prod-live-cdn.riotgames.com", "رایت/لیگ آو لجندز"),
        ("cdn-live.epicgames.com", "اپیک/فورتنایت"),
        ("discord.com", "دیسکورد"),
    ],
    "games": [
        ("pubgmobile.com", "پابجی موبایل"),
        ("activision.com", "کالاف دیوتی"),
        ("ea.com", "الکترونیک آرتز"),
        ("minecraft.net", "ماینکرفت"),
        ("roblox.com", "رابلوكس"),
    ],
    "general": [
        ("google.com", "گوگل"),
        ("cloudflare.com", "کلودفلر"),
        ("wikipedia.org", "ویکی‌پدیا"),
    ],
}
CONSENSUS_DOMAINS = ["google.com", "cloudflare.com", "wikipedia.org", "discord.com", "ea.com"]

# آی‌پی‌هایی که نشانهٔ سانسور/سینک‌هول‌اند، نه PoP متفاوت.
# 10.10.34.0/24 و 10.10.35.0/24 صفحهٔ رسمی فیلترینگ ایران‌اند؛ 0.0.0.0/127.0.0.1 هم پاسخ بی‌معناست.
SINKHOLE_PREFIXES = ("10.10.34.", "10.10.35.", "10.202.10.1", "127.", "0.0.0.0", "::1")
# بازه‌های CDN معتبر: تفاوت آی‌پی درون این بازه‌ها = PoP متفاوت (خبر خوب، نه دست‌کاری)
CDN_PREFIXES = ("23.", "104.", "142.", "172.", "2.16.", "2.17.", "2.18.", "2.19.", "2.20.",
                "2.21.", "2.22.", "2.23.", "185.", "104.16.", "104.17.", "104.18.", "104.19.",
                "13.32.", "13.224.", "13.225.", "18.64.", "52.", "54.", "99.84.", "151.101.",
                "188.114.", "199.232.")


# ----------------------------------------------------------------------------- پروتکل DNS (بدون وابستگی)
def enc_name(name: str) -> bytes:
    return b"".join(bytes([len(l)]) + l.encode() for l in name.split(".") if l) + b"\x00"


def build_query(name: str, qtype: int = A, txid: int | None = None, rd: bool = True,
                edns: bool = True, do: bool = False, payload: int = 1232) -> tuple[bytes, int]:
    txid = random.randint(0, 0xFFFF) if txid is None else txid
    flags = 0x0100 if rd else 0
    ar = 1 if edns else 0
    msg = struct.pack(">HHHHHH", txid, flags, 1, 0, 0, ar) + enc_name(name) + struct.pack(">HH", qtype, 1)
    if edns:
        ttl = 0x8000 if do else 0
        msg += b"\x00" + struct.pack(">HHIH", OPT, payload, ttl, 0)
    return msg, txid


def _parse_name(data: bytes, off: int, depth: int = 0) -> tuple[str, int]:
    labels, jumped, end = [], False, off
    while True:
        if off >= len(data) or depth > 12:
            break
        ln = data[off]
        if ln == 0:
            off += 1
            break
        if ln & 0xC0 == 0xC0:
            ptr = struct.unpack(">H", data[off:off + 2])[0] & 0x3FFF
            if not jumped:
                end = off + 2
            off, jumped = ptr, True
            depth += 1
            continue
        labels.append(data[off + 1:off + 1 + ln].decode("latin-1"))
        off += 1 + ln
    return ".".join(labels), (end if jumped else off)


def parse(data: bytes) -> dict:
    out = {"valid": False, "rcode": None, "answers": [], "a": [], "aaaa": [], "cname": [],
           "min_ttl": None, "ad": False, "ra": False, "aa": False, "tc": False,
           "edns": False, "edns_payload": None, "edns_do": False, "size": len(data)}
    if len(data) < 12:
        return out
    txid, flags, qd, an, ns, ar = struct.unpack(">HHHHHH", data[:12])
    out.update(txid=txid, rcode=flags & 0xF, ad=bool(flags & 0x20), aa=bool(flags & 0x400),
               tc=bool(flags & 0x200), ra=bool(flags & 0x80), ancount=an)
    off = 12
    for _ in range(qd):
        _, off = _parse_name(data, off)
        off += 4
    for _ in range(an):
        if off >= len(data):
            break
        _, off = _parse_name(data, off)
        if off + 10 > len(data):
            break
        rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", data[off:off + 10])
        off += 10
        rdata = data[off:off + rdlen]
        out["answers"].append({"type": rtype, "ttl": ttl})
        if out["min_ttl"] is None or ttl < out["min_ttl"]:
            out["min_ttl"] = ttl
        if rtype == A and rdlen == 4:
            out["a"].append(socket.inet_ntoa(rdata))
        elif rtype == AAAA and rdlen == 16:
            out["aaaa"].append(socket.inet_ntop(socket.AF_INET6, rdata))
        elif rtype == CNAME:
            n, _ = _parse_name(data, off)
            out["cname"].append(n)
        off += rdlen
    for _ in range(ar):
        if off >= len(data):
            break
        nm, off = _parse_name(data, off)
        if off + 10 > len(data):
            break
        rtype, rclass, ttl, rdlen = struct.unpack(">HHIH", data[off:off + 10])
        off += 10
        if rtype == OPT and nm == "":
            out["edns"] = True
            out["edns_payload"] = rclass
            out["edns_do"] = bool(ttl & 0x8000)
        off += rdlen
    out["valid"] = bool(out["a"] or out["aaaa"] or out["cname"] or out["rcode"] is not None)
    return out


# ----------------------------------------------------------------------------- ساختار نتیجه
@dataclass
class Resolver:
    ip: str
    cc: str = ""
    as_org: str = ""
    name: str = ""
    source: str = "catalog"
    group: str = ""

    @property
    def v6(self) -> bool:
        return ":" in self.ip


@dataclass
class Result:
    ip: str
    cc: str = ""
    as_org: str = ""
    name: str = ""
    source: str = ""
    v: int = 4
    ok: bool = False
    rcode: str | None = None
    rtt_p50: float | None = None
    rtt_p95: float | None = None
    rtt_min: float | None = None
    jitter: float | None = None
    loss: float = 1.0
    n_ok: int = 0
    cold_p50: float | None = None
    cold_ok: bool = False
    a_example: list = field(default_factory=list)
    edns: bool = False
    edns_payload: int | None = None
    dnssec_ad: bool = False
    min_ttl: int | None = None
    consensus: dict = field(default_factory=dict)
    hijack: bool = False          # سانسور/سینک‌هول/پاسخ بی‌معنا (بد)
    hijack_detail: list = field(default_factory=list)
    divergent: bool = False       # PoP متفاوت (خبر، نه جرم) — مادهٔ خام سنجش اثر
    divergent_detail: list = field(default_factory=list)
    impact: dict = field(default_factory=dict)
    error: str = ""

    def to_row(self) -> dict:
        d = self.__dict__.copy()
        d["a_example"] = ",".join(self.a_example[:3])
        d["hijack_detail"] = " | ".join(self.hijack_detail[:3])
        d["divergent_detail"] = " | ".join(self.divergent_detail[:3])
        d["consensus"] = json.dumps(self.consensus, ensure_ascii=False)[:300]
        d["impact"] = json.dumps(self.impact, ensure_ascii=False)[:600]
        return d


# ----------------------------------------------------------------------------- موتور اسکن
class Scanner:
    def __init__(self, timeout: float = 1.2, count: int = 5, rate: float = 150.0,
                 concurrency: int = 200):
        self.timeout, self.count = timeout, count
        self.rate, self.concurrency = rate, concurrency
        self._tokens = rate
        self._last = time.monotonic()

    async def _throttle(self) -> None:
        while True:
            now = time.monotonic()
            self._tokens = min(self.rate, self._tokens + (now - self._last) * self.rate)
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
                return
            await asyncio.sleep(0.5 / self.rate)

    async def _one(self, ip: str, name: str, qtype: int = A, timeout: float | None = None,
                   do: bool = False) -> tuple[float | None, dict | None, str]:
        """یک کوئری: RTT، پاسخ تحلیل‌شده، خطا."""
        await self._throttle()
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        loop = asyncio.get_running_loop()
        s = socket.socket(fam, socket.SOCK_DGRAM)
        s.setblocking(False)
        try:
            pkt, txid = build_query(name, qtype, rd=True, edns=True, do=do)
            t0 = loop.time()
            try:
                await loop.sock_sendto(s, pkt, (ip, 53))
            except OSError as e:
                return None, None, f"send:{e.__class__.__name__}"
            deadline = t0 + (timeout or self.timeout)
            while True:
                remain = deadline - loop.time()
                if remain <= 0:
                    return None, None, "timeout"
                try:
                    data, _ = await asyncio.wait_for(loop.sock_recvfrom(s, 4096), remain)
                except asyncio.TimeoutError:
                    return None, None, "timeout"
                except OSError as e:
                    return None, None, f"recv:{e.__class__.__name__}"
                if len(data) >= 12 and struct.unpack(">H", data[:2])[0] == txid:
                    rtt = (loop.time() - t0) * 1000
                    return rtt, parse(data), ""
        finally:
            s.close()

    async def probe(self, ip: str, name: str = "example.com", qtype: int = A) -> Result:
        r = Result(ip=ip, v=6 if ":" in ip else 4)
        rtts: list[float] = []
        misses = 0
        last = None
        for i in range(self.count):
            rtt, resp, err = await self._one(ip, name, qtype)
            if rtt is None:
                misses += 1
                r.error = err
            else:
                rtts.append(rtt)
                last = resp
            if i < self.count - 1:
                await asyncio.sleep(0.02)
        r.loss = round(misses / max(self.count, 1), 3)
        if rtts:
            s = sorted(rtts)
            r.ok = True
            r.rtt_p50 = round(statistics.median(rtts), 2)
            r.rtt_min = round(s[0], 2)
            r.rtt_p95 = round(s[min(len(s) - 1, int(0.95 * len(s)))], 2)
            r.jitter = round(statistics.fmean([abs(b - a) for a, b in zip(rtts, rtts[1:])]), 2) \
                if len(rtts) > 1 else 0.0
            r.n_ok = len(rtts)
        if last:
            r.rcode = RCODES.get(last["rcode"], str(last["rcode"]))
            r.edns, r.edns_payload, r.dnssec_ad = last["edns"], last["edns_payload"], last["ad"]
            r.min_ttl, r.a_example = last["min_ttl"], last["a"]
        return r

    async def sem_probe(self, sem: asyncio.Semaphore, rv: Resolver, name: str = "example.com") -> Result:
        async with sem:
            r = await self.probe(rv.ip, name)
        r.cc, r.as_org, r.name, r.source = rv.cc, rv.as_org, rv.name, rv.source
        return r

    async def resolve(self, ip: str, name: str, qtype: int = A) -> tuple[list[str], float | None, int | None]:
        """یک resolution ساده: آی‌پی‌های پاسخ + RTT + rcode."""
        rtt, resp, _ = await self._one(ip, name, qtype)
        if not resp:
            return [], None, None
        ips = resp["a"] if qtype == A else resp["aaaa"]
        if not ips and resp["cname"]:
            rtt2, resp2, _ = await self._one(ip, resp["cname"][0], qtype)
            if resp2:
                resp = resp2
            ips = (resp2 or {}).get("a" if qtype == A else "aaaa", [])
        return ips, rtt, resp.get("rcode")

    async def tcp_rtt(self, ip: str, port: int = 443, timeout: float = 2.0) -> float | None:
        """تأخیر دست‌دادن TCP تا آی‌پی مقصد (بدون root و بدون ICMP)."""
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        loop = asyncio.get_running_loop()
        try:
            t0 = loop.time()
            fut = asyncio.open_connection(host=ip, port=port, family=fam)
            reader, writer = await asyncio.wait_for(fut, timeout)
            rtt = (loop.time() - t0) * 1000
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return round(rtt, 2)
        except Exception:
            return None


# ----------------------------------------------------------------------------- بارگذاری کاندیدها
def load_candidates(args) -> list[Resolver]:
    out: list[Resolver] = []
    seen = set()
    if args.curated or args.all or args.curated_only:
        cur = json.load(open(os.path.join(DATA, "curated.json"), encoding="utf-8"))
        for g in cur["groups"]:
            for e in g["entries"]:
                for ip in (e.get("v4") or []) + ((e.get("v6") or []) if args.v6 or args.all else []):
                    if ip in seen:
                        continue
                    seen.add(ip)
                    out.append(Resolver(ip=ip, cc="IR" if g["id"] == "iran" else "GL",
                                        as_org=e["name"], name=e["name"], source="curated",
                                        group=g["id"]))
    if not args.curated_only:
        cat = json.load(open(os.path.join(DATA, "catalog.json"), encoding="utf-8"))
        ccs = [c.strip().upper() for c in args.countries.split(",")] if args.countries else \
            ["IR", "DE", "TR", "AE", "RU", "US", "GB", "NL", "FR"]
        for cc in ccs:
            c = cat["countries"].get(cc)
            if not c:
                continue
            n = 0
            for s in c["top"]:
                if s["v"] == 6 and not (args.v6 or args.all):
                    continue
                if s["ip"] in seen:
                    continue
                seen.add(s["ip"])
                out.append(Resolver(ip=s["ip"], cc=cc, as_org=s["as"], name=s["city"] or "",
                                    source="catalog"))
                n += 1
                if n >= args.limit_per_country:
                    break
    return out


def targets_for(kind: str) -> list[tuple[str, str]]:
    if kind in TARGETS:
        return TARGETS[kind]
    if kind == "all":
        seen, out = set(), []
        for v in TARGETS.values():
            for d, l in v:
                if d not in seen:
                    seen.add(d)
                    out.append((d, l))
        return out
    return TARGETS["cdn"] + TARGETS["games"] + TARGETS["general"]


# ----------------------------------------------------------------------------- اجرای کامل
async def run(args) -> dict:
    sc = Scanner(timeout=args.timeout, count=args.count, rate=args.rate)
    cands = load_candidates(args)
    if not cands:
        print("❌ کاندیدی برای اسکن نیست")
        return {}
    print(f"▸ {len(cands)} کاندید | کوئری: {args.count} × {args.timeout}s | نرخ: {args.rate}/s | "
          f"هم‌زمانی: {args.concurrency}")
    t0 = time.time()
    sem = asyncio.Semaphore(args.concurrency)
    tasks = [asyncio.create_task(sc.sem_probe(sem, c, args.query_name)) for c in cands]
    results: list[Result] = []
    done = 0
    for fut in asyncio.as_completed(tasks):
        r = await fut
        results.append(r)
        done += 1
        if done % 50 == 0 or done == len(tasks):
            okn = sum(1 for x in results if x.ok)
            print(f"   {done}/{len(tasks)} | پاسخ‌داده: {okn} | {time.time() - t0:.0f}s", flush=True)

    live = [r for r in results if r.ok and r.rtt_p50 is not None]

    # --- مسیر سرد (NXDOMAIN) روی بهترین‌ها
    if live and args.cold:
        print(f"▸ سنجش مسیر سرد روی {min(len(live), args.cold_top)} رزولور برتر...")
        live.sort(key=lambda r: r.rtt_p50)
        cold_sem = asyncio.Semaphore(max(20, args.concurrency // 4))

        async def cold(r: Result):
            async with cold_sem:
                rnd = "".join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(12))
                rtt, resp, _ = await sc._one(r.ip, f"{rnd}.does-not-exist-pinghab.invalid", A)
                r.cold_p50 = round(rtt, 2) if rtt else None
                r.cold_ok = bool(resp and resp.get("rcode") == 3)

        await asyncio.gather(*[cold(r) for r in live[:args.cold_top]])

    # --- اجماع و تشخیص دست‌کاری
    if live:
        print("▸ ساخت اجماع پاسخ‌ها (برای تشخیص دست‌کاری)...")
        base_ips: dict[str, list[str]] = {}
        base_sc = Scanner(timeout=2.0, count=1, rate=400)
        for ip in ("1.1.1.1", "8.8.8.8", "9.9.9.9"):
            for dom in CONSENSUS_DOMAINS:
                ips, _, _rc = await base_sc.resolve(ip, dom)
                if ips:
                    base_ips.setdefault(dom, []).extend(ips)
        for dom in CONSENSUS_DOMAINS:
            base_ips[dom] = sorted(set(base_ips[dom]))

        sem2 = asyncio.Semaphore(max(20, args.concurrency // 2))

        async def cons(r: Result):
            async with sem2:
                r.consensus, bad, diff = {}, [], []
                for dom in CONSENSUS_DOMAINS:
                    ips, _r, rcode = await sc.resolve(r.ip, dom)
                    ref = set(base_ips.get(dom) or [])
                    # ۱) رد صریح: NXDOMAIN/REFUSED/SERVFAIL جایی که مرجع پاسخ داشت.
                    #    REFUSED می‌تواند rate-limit باشد نه سانسور → یک تلاش دوباره با تأخیر.
                    if rcode in (2, 3, 5) and ref:
                        await asyncio.sleep(1.2)
                        ips2, _r2, rc2 = await sc.resolve(r.ip, dom)
                        if rc2 in (2, 3, 5):
                            bad.append(f"{dom}→{RCODES.get(rc2, rc2)} (بعد از تلاش دوباره)")
                            continue
                        ips, rcode = ips2, rc2
                    if not ips:
                        continue
                    r.consensus[dom] = ips[:3]
                    # ۲) آی‌پی سینک‌هول/بی‌معنا
                    if any(ip.startswith(SINKHOLE_PREFIXES) for ip in ips):
                        bad.append(f"{dom}→سینک‌هول {ips[0]}")
                    # ۳) تفاوت با اجماع = فقط «اطلاعاتی» (PoP متفاوت یا CDN دیگر).
                    #    تفاوت PoP دست‌کاری نیست؛ سنجش اثر همان را به عدد تبدیل می‌کند.
                    elif ref and not (set(ips) & ref):
                        hint = "CDN" if any(ip.startswith(CDN_PREFIXES) for ip in ips) else "?"
                        diff.append(f"{dom}→{ips[0]} ({hint})")
                r.hijack_detail, r.hijack = bad, bool(bad)
                r.divergent_detail, r.divergent = diff, bool(diff)

        top = sorted(live, key=lambda r: r.rtt_p50)[:args.consensus_top]
        await asyncio.gather(*[cons(r) for r in top])

    # --- سنجش اثر: رزولور → آی‌پی → تأخیر تا آن آی‌پی
    if live and args.targets:
        tgs = targets_for(args.targets)
        print(f"▸ سنجش اثر روی {min(len(live), args.impact_top)} رزولور × {len(tgs)} دامنه...")
        pool = sorted(live, key=lambda r: r.rtt_p50)[:args.impact_top]
        sem3 = asyncio.Semaphore(max(16, args.concurrency // 4))
        conn_cache: dict[str, float | None] = {}

        async def impact(r: Result):
            async with sem3:
                r.impact = {}
                for dom, label in tgs:
                    ips, dns_rtt, _rc = await sc.resolve(r.ip, dom)
                    if not ips:
                        continue
                    ip = ips[0]
                    if ip not in conn_cache:
                        conn_cache[ip] = await sc.tcp_rtt(ip)
                    c = conn_cache[ip]
                    r.impact[dom] = {
                        "ip": ip, "dns_ms": round(dns_rtt or 0, 1),
                        "conn_ms": c, "total_ms": round((dns_rtt or 0) + c, 1) if c else None,
                        "label": label,
                    }

        await asyncio.gather(*[impact(r) for r in pool])

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "args": {k: v for k, v in vars(args).items()},
        "duration_s": round(time.time() - t0, 1),
        "candidates": len(cands),
        "responded": len(live),
        "results": [r.__dict__ for r in results],
    }


# ----------------------------------------------------------------------------- گزارش
def save_and_report(data: dict, args) -> str:
    os.makedirs(DATA, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    jp = os.path.join(DATA, f"scan-{stamp}.json")
    cp = os.path.join(DATA, f"scan-{stamp}.csv")
    with open(jp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    rows = [Result(**{k: v for k, v in r.items() if k in Result.__dataclass_fields__}).to_row()
            for r in data["results"]]
    if rows:
        with open(cp, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    live = [r for r in data["results"] if r.get("ok")]
    live.sort(key=lambda r: r["rtt_p50"])
    print(f"\n{'=' * 96}")
    print(f"▸ {data['responded']}/{data['candidates']} پاسخ دادند | {data['duration_s']}s | "
          f"JSON: {jp}")
    print(f"{'=' * 96}")
    print(f"  {'آی‌پی':<40}{'کشور':<6}{'RTT p50':>9}{'p95':>8}{'تلفات':>8}{'EDNS':>6}{'DNSSEC':>8}"
          f"{'سانسور':>9}{'PoP متفاوت':>12}")
    print("  " + "-" * 104)
    for r in live[:40]:
        print(f"  {r['ip']:<40}{r.get('cc', ''):<6}{r['rtt_p50']:>9.2f}"
              f"{(r.get('rtt_p95') or 0):>8.2f}{(r.get('loss') or 0) * 100:>7.0f}%"
              f"{'✅' if r.get('edns') else '—':>6}{'✅' if r.get('dnssec_ad') else '—':>8}"
              f"{'🚨' if r.get('hijack') else '—':>9}{'◆' if r.get('divergent') else '—':>12}")
    div = [r for r in live if r.get("divergent")]
    if div:
        print(f"\n◆ رزولورهایی که PoP دیگری می‌دهند ({len(div)}) — این «خبر» است نه «جرم»؛ "
              f"اثرش در سنجش اثر دیده می‌شود:")
        for r in div[:6]:
            print(f"   {r['ip']:<40} {r['divergent_detail'][:2]}")
    hij = [r for r in live if r.get("hijack")]
    if hij:
        print(f"\n🚨 رد صریح یا سینک‌هول ({len(hij)}) — سانسور یا سیاست/ACL؛ نیازمند بازرسی دستی:")
        for r in hij[:10]:
            print(f"   {r['ip']:<40} {r['hijack_detail'][:2]}")
    imp = [r for r in live if r.get("impact")]
    if imp:
        print("\n▸ سنجش اثر (رزولور → آی‌پی → تأخیر تا همان آی‌پی):")
        for dom, label in targets_for(args.targets)[:3]:
            cand = [(r, r["impact"][dom]) for r in imp if dom in (r.get("impact") or {})]
            if not cand:
                continue
            cand.sort(key=lambda x: (x[1]["total_ms"] or 9e9))
            print(f"\n   ◆ {dom} ({label})")
            for r, im in cand[:5]:
                print(f"     {r['ip']:<38} → {im['ip']:<16} dns={im['dns_ms']:>6.1f}ms "
                      f"conn={im['conn_ms']}ms مجموع={im['total_ms']}ms")
    return jp


def ipv6_available() -> bool:
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        s.settimeout(1.0)
        s.connect(("2001:4860:4860::8888", 53))
        s.close()
        return True
    except OSError:
        return False


async def amain(args) -> int:
    if args.v6 and not ipv6_available():
        print("⚠️  IPv6 روی این ماشین مسیر ندارد — رزولورهای v6 رد می‌شوند. "
              "این محدودیت محیط سنجش است، نه نبود آن رزولورها.")
        args.v6 = False
    data = await run(args)
    if not data:
        return 1
    save_and_report(data, args)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="WorldScan — اسکنر DNS جهانی با سنجش اثر")
    ap.add_argument("--countries", default="", help="کد کشورها با کاما: IR,DE,TR")
    ap.add_argument("--limit-per-country", type=int, default=15)
    ap.add_argument("--curated", action="store_true", help="لایهٔ منتخب را هم اضافه کن")
    ap.add_argument("--curated-only", action="store_true", help="فقط لایهٔ منتخب")
    ap.add_argument("--all", action="store_true", help="همه‌چیز (منتخب + همهٔ کشورهای پیش‌فرض)")
    ap.add_argument("--v6", action="store_true", help="IPv6 را هم اسکن کن")
    ap.add_argument("--count", type=int, default=5, help="تعداد کوئری هر رزولور")
    ap.add_argument("--timeout", type=float, default=1.2)
    ap.add_argument("--rate", type=float, default=150.0, help="حداکثر کوئری در ثانیه (اخلاق سنجش)")
    ap.add_argument("--concurrency", type=int, default=200)
    ap.add_argument("--query-name", default="example.com")
    ap.add_argument("--cold", action="store_true", default=True, help="سنجش مسیر سرد (NXDOMAIN)")
    ap.add_argument("--cold-top", type=int, default=40)
    ap.add_argument("--consensus-top", type=int, default=40)
    ap.add_argument("--targets", default="cdn", help="cdn|games|general|all|off")
    ap.add_argument("--impact-top", type=int, default=25)
    args = ap.parse_args()
    try:
        return asyncio.run(amain(args))
    except KeyboardInterrupt:
        print("\n⏹ متوقف شد")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
