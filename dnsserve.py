#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
رادار DNS — سرور پایش زنده (Live)
=========================================================================
یک سرور کوچک و سبک که مدام (هر چند ثانیه) به DNS سرورهای هر منطقه کوئری
واقعی می‌زند و یک داشبورد زنده در مرورگر نشان می‌دهد:

  * پینگ لحظه‌ای هر سرور + «قدرت» (امتیاز کیفیت ۰–۱۰۰) با نمودار زنده
  * جدا کردن همه‌چیز بر اساس منطقه (ایران / ترکیه / اروپا / آمریکا / آسیا / anycast)
  * جیتر، افت بسته، و تاریخچهٔ ۶۰ نمونهٔ اخیر برای هر سرور
  * امکان اضافه‌کردن «سرور بازی من» با آی‌پی دلخواه و دیدن پینگ زنده‌اش

اجرا:
    python3 dnsserve.py                 # پیش‌فرض روی پورت 8777
    python3 dnsserve.py --port 8080 --cycle 3
    python3 dnsserve.py --open          # مرورگر را هم باز می‌کند

فقط کتابخانهٔ استاندارد پایتون لازم است (بدون هیچ پکیج اضافه).
"""

from __future__ import annotations

import argparse
import json
import random
import socket
import statistics
import sys
import threading
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from dnsscan import build_query, parse_response  # موتور DNS خودمان

SERVERS_FILE = HERE / "servers.json"
REGIONS_FILE = HERE / "regions.json"
CUSTOM_FILE = HERE / "custom_targets.json"
LIVE_HTML = HERE / "web" / "live.html"

# دامنه‌های تست (چرخشی تا کش یک دامنه نتیجه را تحریف نکند)
TEST_DOMAINS = ["www.wikipedia.org", "www.google.com", "www.instagram.com",
                "www.youtube.com", "www.microsoft.com", "www.cloudflare.com"]

WINDOW_SECONDS = 90       # پنجرهٔ محاسبهٔ آمار (پینگ میانه، جیتر، افت)
HISTORY_LEN = 60          # تعداد نمونه‌های نگه‌داشته‌شده برای نمودار


def fa_num(x) -> str:
    return str(x).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


# ----------------------------------------------------------------------------- هدف‌ها

class Target:
    """یک مقصد اندازه‌گیری (سرور DNS یا آی‌پی دلخواه کاربر)."""

    def __init__(self, tid, label, ip, region, proto="dns", port=53, note="", family="dns"):
        self.id = tid
        self.label = label
        self.ip = ip
        self.region = region
        self.proto = proto           # dns (UDP/53) | tcp (TCP/port) | auto
        self.port = port
        self.note = note
        self.family = family         # dns | custom
        self.samples = deque()       # (ts, rtt_ms|None)
        self.history = deque(maxlen=HISTORY_LEN)
        self.detected = None         # proto واقعی برای حالت auto
        self.added = time.time()

    def to_dict(self):
        return {"id": self.id, "label": self.label, "ip": self.ip, "region": self.region,
                "proto": self.proto, "port": self.port, "note": self.note,
                "family": self.family, "detected": self.detected}


def load_targets() -> list[Target]:
    servers = json.loads(SERVERS_FILE.read_text(encoding="utf-8"))["servers"]
    by_id = {s["id"]: s for s in servers}
    regions = json.loads(REGIONS_FILE.read_text(encoding="utf-8"))["regions"]
    targets, used = [], set()
    for reg in regions:
        for sid in reg["servers"]:
            s = by_id.get(sid)
            if not s:
                continue
            targets.append(Target(sid, s.get("name", sid), s["ip"], reg["key"],
                                  proto="dns", port=53, note=s.get("note", ""), family="dns"))
            used.add(sid)
    # هر سروری که در نگاشت منطقه نبود، در گروه «سایر» بیاید
    for s in servers:
        if s["id"] not in used:
            targets.append(Target(s["id"], s.get("name", s["id"]), s["ip"], "other",
                                  proto="dns", port=53, note=s.get("note", ""), family="dns"))
    # هدف‌های دلخواه کاربر که قبلاً ذخیره شده‌اند
    if CUSTOM_FILE.exists():
        try:
            for c in json.loads(CUSTOM_FILE.read_text(encoding="utf-8")):
                targets.append(Target(c["id"], c["label"], c["ip"], "mine",
                                      proto=c.get("proto", "auto"), port=c.get("port", 443),
                                      note=c.get("note", "هدف دلخواه کاربر"), family="custom"))
        except Exception as e:
            print("خطا در خواندن custom_targets.json:", e)
    return targets


def save_custom(targets: list[Target]):
    data = [t.to_dict() for t in targets if t.family == "custom"]
    CUSTOM_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------------- اندازه‌گیری

def measure_dns(ip: str, timeout: float = 1.5) -> float | None:
    """یک کوئری واقعی UDP/53 و برگرداندن زمان رفت‌وبرگشت (میلی‌ثانیه)."""
    name = TEST_DOMAINS[random.randrange(len(TEST_DOMAINS))]
    pkt, txid = build_query(name, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        t0 = time.perf_counter()
        s.sendto(pkt, (ip, 53))
        while True:
            data, _ = s.recvfrom(2048)
            if len(data) >= 12 and int.from_bytes(data[:2], "big") == txid:
                rtt = (time.perf_counter() - t0) * 1000
                p = parse_response(data)
                # پاسخ معتبر با rcode صفر (0) یا NXDOMAIN (3) هر دو یعنی سرور زنده است
                return rtt if p.get("valid") else None
    except Exception:
        return None
    finally:
        s.close()


def measure_tcp(ip: str, port: int = 443, timeout: float = 2.0) -> float | None:
    """زمان برقراری TCP (برای آی‌پی‌هایی که DNS نیستند، مثل سرور بازی)."""
    try:
        t0 = time.perf_counter()
        s = socket.create_connection((ip, port), timeout=timeout)
        rtt = (time.perf_counter() - t0) * 1000
        s.close()
        return rtt
    except Exception:
        return None


# ----------------------------------------------------------------------------- موتور زنده

class Engine:
    def __init__(self, targets: list[Target], cycle: float = 3.0, workers: int = 20, timeout: float = 1.5):
        self.targets = targets
        self.cycle = cycle
        self.timeout = timeout
        self.lock = threading.RLock()   # بازگشتی: متد stats داخل خودش هم قفل می‌گیرد
        self.stop_flag = threading.Event()
        self.cycle_no = 0
        self.started = time.time()
        self.last_cycle_ts = 0.0
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="probe")

    # --- یک نمونه‌گیری برای یک هدف
    def sample(self, t: Target):
        proto = t.proto
        if proto == "auto" and t.detected:
            proto = t.detected
        rtt = None
        if proto in ("dns", "auto"):
            rtt = measure_dns(t.ip, self.timeout)
            if rtt is not None and t.proto == "auto":
                t.detected = "dns"
            elif rtt is None and t.proto == "auto" and t.detected is None:
                # اگر DNS جواب نداد، TCP را امتحان کن و اگر جواب داد همان را بچسبان
                rtt_tcp = measure_tcp(t.ip, t.port)
                if rtt_tcp is not None:
                    t.detected = "tcp"
                    rtt = rtt_tcp
        elif proto == "tcp":
            rtt = measure_tcp(t.ip, t.port)
        with self.lock:
            t.samples.append((time.time(), rtt))

    # --- آمار پنجره‌ای
    def stats(self, t: Target) -> dict:
        now = time.time()
        with self.lock:
            while t.samples and now - t.samples[0][0] > WINDOW_SECONDS:
                t.samples.popleft()
            vals = [r for _, r in t.samples]
        got = [v for v in vals if v is not None]
        total = len(vals)
        if not got:
            return {"median": None, "jitter": None, "loss": 1.0 if total else None,
                    "samples": total, "min": None, "max": None, "last": None}
        med = statistics.median(got)
        jit = statistics.mean(abs(v - med) for v in got)
        return {"median": round(med, 1), "jitter": round(jit, 1),
                "loss": round(1 - len(got) / total, 3) if total else None,
                "samples": total, "min": round(min(got), 1), "max": round(max(got), 1),
                "last": round(got[-1], 1)}

    @staticmethod
    def quality(st: dict) -> tuple[int, str, str]:
        """«قدرت» = امتیاز ۰..۱۰۰ و برچسب کیفیت و رنگ."""
        if st["median"] is None:
            return 0, "قطع", "dead"
        s = 100.0
        s -= min(55.0, st["median"] * 0.45)
        if st["jitter"] is not None:
            s -= min(20.0, st["jitter"] * 1.2)
        if st["loss"]:
            s -= st["loss"] * 60
        score = int(max(0, min(100, round(s))))
        if score >= 85:
            return score, "عالی", "great"
        if score >= 70:
            return score, "خیلی خوب", "good"
        if score >= 55:
            return score, "خوب", "ok"
        if score >= 38:
            return score, "متوسط", "meh"
        return score, "ضعیف", "weak"

    def run(self):
        """حلقهٔ اصلی: هر cycle ثانیه یک نمونه از هر هدف می‌گیرد."""
        while not self.stop_flag.is_set():
            t0 = time.time()
            self.cycle_no += 1
            try:
                list(self._pool.map(self.sample, list(self.targets)))
            except Exception as e:
                print("خطای نمونه‌گیری:", type(e).__name__, e)
            # ثبت تاریخچه برای نمودار
            for t in self.targets:            # stats خودش قفل می‌گیرد (RLock)
                st = self.stats(t)
                t.history.append(st["median"])
            self.last_cycle_ts = time.time()
            wait = self.cycle - (time.time() - t0)
            if wait > 0:
                self.stop_flag.wait(wait)

    # --- ساخت خروجی JSON برای داشبورد
    def state(self) -> dict:
        regions_meta = json.loads(REGIONS_FILE.read_text(encoding="utf-8"))
        reg_info = {r["key"]: r for r in regions_meta["regions"]}
        reg_info["mine"] = regions_meta["custom_region"]
        reg_info["other"] = {"key": "other", "label": "سایر", "flag": "⚪", "note": ""}

        items, by_region = [], {}
        for t in self.targets:
            st = self.stats(t)
            score, grade, color = self.quality(st)
            item = {
                **t.to_dict(),
                **st,
                "quality": score, "grade": grade, "color": color,
                "history": list(t.history),
                "age": round(time.time() - self.last_cycle_ts, 1),
            }
            items.append(item)
            by_region.setdefault(t.region, []).append(item)

        regions = []
        for key, arr in by_region.items():
            meta = reg_info.get(key, {"key": key, "label": key, "flag": "⚪", "note": ""})
            alive = [x for x in arr if x["median"] is not None]
            best = min(alive, key=lambda x: x["median"]) if alive else None
            regions.append({
                "key": key, "label": meta.get("label", key), "flag": meta.get("flag", "⚪"),
                "note": meta.get("note", ""),
                "count": len(arr), "alive": len(alive),
                "best_median": best["median"] if best else None,
                "best_name": best["label"] if best else None,
                "best_ip": best["ip"] if best else None,
                "best_id": best["id"] if best else None,
                "avg_median": round(statistics.mean([x["median"] for x in alive]), 1) if alive else None,
                "avg_quality": int(statistics.mean([x["quality"] for x in arr])) if arr else 0,
                "best_history": best["history"] if best else [],
            })

        alive_all = [x for x in items if x["median"] is not None]
        best_overall = min(alive_all, key=lambda x: x["median"]) if alive_all else None
        # اگر همهٔ سرورهای ایرانی و هیچ‌کدام از جهانی‌ها جواب ندادند → احتمالاً داخل ایرانیم
        iran = [x for x in items if x["region"] == "iran"]
        world = [x for x in items if x["region"] in ("europe", "america", "anycast", "asia")]
        inside_iran = bool(iran) and any(x["median"] is not None for x in iran) and \
            not any(x["median"] is not None for x in world)
        outside_iran = bool(iran) and not any(x["median"] is not None for x in iran) and \
            any(x["median"] is not None for x in world)
        return {
            "now": time.time(),
            "uptime": round(time.time() - self.started),
            "cycle": self.cycle_no,
            "cycle_seconds": self.cycle,
            "cycles_per_min": round(60 / self.cycle, 1),
            "window_seconds": WINDOW_SECONDS,
            "targets": items,
            "regions": sorted(regions, key=lambda r: (r["best_median"] is None, r["best_median"] or 9e9)),
            "summary": {
                "total": len(items), "alive": len(alive_all),
                "best_median": best_overall["median"] if best_overall else None,
                "best_name": best_overall["label"] if best_overall else None,
                "best_ip": best_overall["ip"] if best_overall else None,
                "best_id": best_overall["id"] if best_overall else None,
                "best_quality": best_overall["quality"] if best_overall else 0,
                "avg_jitter": round(statistics.mean([x["jitter"] for x in alive_all if x["jitter"] is not None]), 1)
                if alive_all else None,
                "made_for_iran": inside_iran,
                "outside_iran_banner": outside_iran,
            },
        }


# ----------------------------------------------------------------------------- وب

class Handler(BaseHTTPRequestHandler):
    engine: Engine = None
    server_version = "dnsradar-live/1.0"

    def log_message(self, fmt, *args):
        pass  # لاگ ترمینال را شلوغ نکن

    # --- ابزار پاسخ
    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            if LIVE_HTML.exists():
                self._send(200, LIVE_HTML.read_bytes(), "text/html; charset=utf-8")
            else:
                self._send(500, "فایل web/live.html پیدا نشد.".encode(), "text/plain; charset=utf-8")
        elif path == "/api/state":
            self._json(self.engine.state())
        elif path == "/api/targets":
            self._json([t.to_dict() for t in self.engine.targets if t.family == "custom"])
        elif path == "/api/health":
            self._json({"ok": True, "cycle": self.engine.cycle_no, "targets": len(self.engine.targets)})
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            return self._json({"ok": False, "error": "بدنهٔ JSON نامعتبر"}, 400)

        if path == "/api/targets":
            ip = str(payload.get("ip", "")).strip()
            parts = ip.split(".")
            if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                return self._json({"ok": False, "error": "آی‌پی نامعتبر"}, 400)
            label = str(payload.get("label") or f"هدف من {len([t for t in self.engine.targets if t.family=='custom'])+1}")[:40]
            tid = "custom-" + str(int(time.time() * 1000))[-8:]
            t = Target(tid, label, ip, "mine", proto="auto",
                       port=int(payload.get("port") or 443),
                       note="هدف دلخواه کاربر", family="custom")
            self.engine.targets.append(t)
            save_custom(self.engine.targets)
            print(f"➕ هدف جدید: {label} ({ip})")
            return self._json({"ok": True, "target": t.to_dict()})

        if path == "/api/targets/remove":
            tid = payload.get("id")
            before = len(self.engine.targets)
            self.engine.targets = [t for t in self.engine.targets if not (t.id == tid and t.family == "custom")]
            save_custom(self.engine.targets)
            return self._json({"ok": len(self.engine.targets) < before})

        self._json({"error": "not found"}, 404)


# ----------------------------------------------------------------------------- اجرا

def main():
    ap = argparse.ArgumentParser(description="رادار DNS — پایش زندهٔ DNS به تفکیک منطقه")
    ap.add_argument("--port", type=int, default=8777)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--cycle", type=float, default=3.0, help="فاصلهٔ بین نمونه‌گیری‌ها (ثانیه)")
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--timeout", type=float, default=1.5)
    ap.add_argument("--open", action="store_true", help="باز کردن مرورگر")
    args = ap.parse_args()

    targets = load_targets()
    engine = Engine(targets, cycle=args.cycle, workers=args.workers, timeout=args.timeout)
    Handler.engine = engine

    th = threading.Thread(target=engine.run, daemon=True)
    th.start()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    httpd.daemon_threads = True
    url = f"http://127.0.0.1:{args.port}/"
    print("=" * 74)
    print(f"📡 رادار DNS — پایش زنده  |  {len(targets)} هدف  |  هر {args.cycle:g} ثانیه یک نمونه")
    print(f"   داشبورد: {url}")
    print(f"   API    : {url}api/state")
    print("   (برای توقف: Ctrl+C)")
    print("=" * 74)
    if args.open:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass

    def watchdog():
        """اگر موتور نمونه‌گیری به هر دلیلی مرد، دوباره بالا بیاید."""
        while True:
            time.sleep(3)
            if not th.is_alive():
                print("⚠️ موتور نمونه‌گیری متوقف شد؛ اجرای مجدد…", flush=True)
                engine.stop_flag.clear()
                t2 = threading.Thread(target=engine.run, daemon=True)
                t2.start()

    threading.Thread(target=watchdog, daemon=True).start()

    try:
        httpd.serve_forever(poll_interval=0.5)   # حلقهٔ پذیرش درخواست‌ها
    except KeyboardInterrupt:
        print("\nتوقف…")
    finally:
        engine.stop_flag.set()
        try:
            httpd.shutdown()
        except Exception:
            pass
        engine._pool.shutdown(wait=False)


if __name__ == "__main__":
    main()
