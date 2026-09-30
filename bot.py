#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
رادار DNS — بات تلگرام
=========================================================================
باتی که برای کاربر اسکن واقعی DNS انجام می‌دهد، بهترین‌ها را پیشنهاد می‌دهد،
DNS زنده را تست می‌کند و گزارش HTML می‌سازد.

اجرا:
    export TELEGRAM_BOT_TOKEN="توکن‌بات‌تو"
    python3 bot.py

دستورها:
    /start      راهنما و دکمه‌ها
    /check      اسکن سریع (پیشنهادی برای موبایل)
    /scan       اسکن کامل با انتخاب مجموعه
    /report     ساخت و ارسال گزارش HTML
    /ping IP    تأخیر TCP/443 تا یک آی‌پی (سرور بازی، سایت، ...)
    /dns IP     تست زنده‌ی یک DNS مشخص [نمونه: /dns 10.202.10.10]
    /guide      چک‌لیست بهینه‌سازی و نکات واقعی
    /help       همین راهنما

فقط با کتابخانه‌ی استاندارد پایتون ۳.۹+ کار می‌کند (بدون نصب پکیج).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import statistics
import struct
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCANNER = HERE / "dnsscan.py"
REPORT_ROOT = HERE / "reports"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}"

PRESETS = {
    "quick": "cloudflare,google,quad9,shecan,radar,electro,adguard,dnssb",
    "gaming": "radar,electro,cloudflare,google,quad9,dnssb,adguard,shelter,zeus,vanilla",
    "iran": "shecan,radar,electro,begzar,403online,vanilla,zeus,shelter,tci",
    "global": "cloudflare,google,quad9,adguard,dnssb,opendns,nextdns,controld,level3,verisign",
    "family": "cloudflare-family,adguard-family,cleanbrowsing,opendns-family,quad9",
}

GUIDE = """🎮 <b>راهنمای واقعی کم کردن پینگ — بدون شایعه</b>

<b>۱) حقیقت تلخ:</b> عوض کردن DNS پینگ داخل مچ بازی را کم نمی‌کند. بازی با IP سرور بازی وصل می‌شود.
DNS این‌ها را بهتر می‌کند: ✅ ورود به بازی و رفع تحریم ✅ سرعت دانلود آپدیت و باز شدن لانچر ✅ کیفیت مسیر CDN.

<b>۲) برای پینگ واقعی، این‌ها مؤثرند (به ترتیب اهمیت):</b>
• <b>محل خروجی تونل</b>: برای سرورهای خاورمیانه (دبی/بحرین/عربستان) خروجی ترکیه/عراق/امارات = ۶۰–۹۰ms؛ خروجی آلمان/هلند = ۱۲۰–۱۵۰ms. فیلترشکن غلط، پینگ را خراب می‌کند.
• <b>پروتکل:</b> WireGuard/UDP نه OpenVPN/TCP.
• <b>افت بسته (<i>packet loss</i>)</b> از خود پینگ مهم‌تر است؛ اینترنت ناپایدار = لگ و «تلپورت» حریف.
• <b>MTU</b>: اگر MTU اشتباه باشد، پکت‌ها تکه‌تکه می‌شوند و پینگ می‌جهد.
• <b>گوشی/مودم</b>: وای‌فای ۵GHz، بستن اپ‌های پس‌زمینه، بستن VPN/فیلترشکن دیگر، خنک بودن گوشی، ری‌استارت مودم.
• <b>NAT:</b> در بازی گزینه‌های شبکه را چک کن؛ Open/Moderate بهتر از Strict است.

<b>۳) انتخاب درست سرور داخل بازی:</b> نزدیک‌ترین رِیجن را بزن (Middle East / Asia)، نه Europe/US.

<b>۴) افسانه‌ها:</b> «DNS پینگ را ۵۰٪ کم می‌کند» ❌ — «پاک کردن کش DNS پینگ را کم می‌کند» ❌ — «حذف اپ‌ها پینگ را نصف می‌کند» ❌

<b>۵) امنیت:</b> از DNS ناشناس استفاده نکن (خطر هدایت به سایت جعلی/جاسوسی). اگر DNS مخدوش («هیجک») شد، پسورد اکانت بازی‌ات را عوض کن.
"""


def fa(x) -> str:
    return str(x).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def fmt_ms(v, dec=1):
    return "—" if v is None else fa(f"{v:.{dec}f}")


# ----------------------------------------------------------------------------- لایه HTTP تلگرام

async def tg(method: str, **params):
    """فراخوانی API تلگرام با urllib در استریم اجرایی (بدون وابستگی خارجی)."""
    url = f"{API}/{method}"
    data = json.dumps(params).encode("utf-8") if params else b"{}"
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})

    def do():
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            print("TG error", e.code, body[:300], flush=True)
            try:
                return json.loads(body)
            except Exception:
                return {"ok": False}
        except Exception as e:
            print("TG net error", type(e).__name__, e, flush=True)
            return {"ok": False}

    return await asyncio.get_running_loop().run_in_executor(None, do)


async def send(chat_id, text, keyboard=None, disable_preview=True):
    params = dict(chat_id=chat_id, text=text, parse_mode="HTML",
                  disable_web_page_preview=disable_preview)
    if keyboard:
        params["reply_markup"] = keyboard
    return await tg("sendMessage", **params)


async def edit(chat_id, message_id, text, keyboard=None):
    params = dict(chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML",
                  disable_web_page_preview=True)
    if keyboard:
        params["reply_markup"] = keyboard
    return await tg("editMessageText", **params)


async def send_document(chat_id, path: Path, caption=""):
    """ارسال فایل با multipart/form-data."""
    boundary = "----dnsradar" + str(int(time.time()))
    body = b""

    def field(name, value):
        nonlocal body
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                 f"{value}\r\n").encode("utf-8")

    field("chat_id", str(chat_id))
    if caption:
        field("caption", caption)
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; "
             f"filename=\"{path.name}\"\r\nContent-Type: text/html; charset=utf-8\r\n\r\n").encode()
    body += path.read_bytes() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()

    req = urllib.request.Request(f"{API}/sendDocument", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def do():
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except Exception as e:
            print("sendDocument error", type(e).__name__, e, flush=True)
            return {"ok": False}

    return await asyncio.get_running_loop().run_in_executor(None, do)


# ----------------------------------------------------------------------------- اجرای اسکنر

async def run_scanner(servers: str, out_dir: Path, attempts: int, label: str,
                      on_progress=None, extra_args=()):
    """dnsscan.py را به‌عنوان پروسه اجرا می‌کند و خطوط پیشرفت را می‌خواند."""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, str(SCANNER), "--servers", servers, "--attempts", str(attempts),
           "--timeout", "2", "--out-dir", str(out_dir), "--formats", "html,json", "--name", label,
           *extra_args]
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(HERE), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    lines = []
    last_push = 0.0
    async for raw in proc.stdout:
        line = raw.decode("utf-8", "ignore").rstrip()
        lines.append(line)
        now = time.time()
        if on_progress and now - last_push > 4.0 and line.strip().startswith("["):
            last_push = now
            await on_progress(line.strip())
    await proc.wait()
    return lines


def summarize(report: dict, limit=8) -> str:
    res = [r for r in report["results"] if r["udp_median"] is not None or r["doh_ok"]]
    meta = report["meta"]
    if not res:
        return ("😕 هیچ سروری از این شبکه پاسخ نداد.\n"
                "احتمالاً اینترنت قطع است یا اپراتور همه‌چیز را می‌بندد.\n"
                "با /scan مجموعه‌ی دیگری را امتحان کن.")
    out = ["📡 <b>نتیجه اسکن رادار DNS</b>", f"🕒 {meta['time_pretty']} · مبنا 8.8.8.8: "
           f"{fmt_ms(meta.get('baseline'))} ms", ""]
    medals = ["🥇", "🥈", "🥉"] + ["▫️"] * 20
    for i, r in enumerate(res[:limit]):
        ms = r["udp_median"] if r["udp_median"] is not None else r["doh_ms"]
        kind = "UDP" if r["udp_median"] is not None else "DoH فقط"
        flags = []
        if r["hijacked"]:
            flags.append("⚠️دستکاری‌شده")
        if r["loss"] and r["loss"] > 0.25:
            flags.append(f"⚠️افت‌بسته {fa(round(r['loss']*100))}٪")
        if r["doh_ok"]:
            flags.append("DoH✓")
        if r["dot_ok"]:
            flags.append("DoT✓")
        out.append(
            f"{medals[i]} <b>{r['name']}</b>\n"
            f"     <code>{r['ip']}{' / ' + r['ip2'] if r.get('ip2') else ''}</code>\n"
            f"     {kind} <b>{fmt_ms(ms)}</b> ms · جیتر {fmt_ms(r['jitter'])} · امتیاز "
            f"<b>{fa(round(r['score']))}</b>/۱۰۰ · {r['grade']} {' '.join(flags)}"
        )
    best = res[0]
    out += ["", "—" * 22, "💡 <b>پیشنهاد:</b>"]
    tips = best.get("recommend") or []
    out.append(f"• <b>{best['name']}</b> → <code>{best['ip']}</code>"
               + (f" و <code>{best['ip2']}</code>" if best.get("ip2") else ""))
    if tips:
        out.append("• " + "، ".join(tips[:3]))
    out += ["", "⚠️ یادت باشد: DNS پینگ داخل بازی را کم نمی‌کند؛ فقط ورود/آپدیت/مسیر CDN را بهتر می‌کند. /guide"]
    return "\n".join(out)


# ----------------------------------------------------------------------------- دستورها

def main_keyboard():
    return {"inline_keyboard": [
        [{"text": "⚡️ اسکن سریع", "callback_data": "scan:quick"},
         {"text": "🎮 مخصوص گیم", "callback_data": "scan:gaming"}],
        [{"text": "🇮🇷 ایرانی / رفع تحریم", "callback_data": "scan:iran"},
         {"text": "🌍 جهانی", "callback_data": "scan:global"}],
        [{"text": "🛡 خانواده", "callback_data": "scan:family"},
         {"text": "📄 گزارش HTML", "callback_data": "report:gaming"}],
        [{"text": "📘 راهنمای پینگ", "callback_data": "cmd:guide"},
         {"text": "❓ راهنما", "callback_data": "cmd:help"}],
    ]}


async def do_scan(chat_id, message_id, preset, label_extra=""):
    servers = PRESETS.get(preset, PRESETS["quick"])
    attempts = 8 if preset in ("gaming", "iran", "global") else 6
    label = f"تلگرام-{preset}{label_extra}"
    out_dir = REPORT_ROOT / str(chat_id)

    async def progress(line):
        m = re.match(r"\[(\d+)/(\d+)\]", line)
        if m:
            pct = int(m.group(1)) / max(1, int(m.group(2))) * 100
            bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            try:
                await edit(chat_id, message_id,
                           f"⏳ <b>در حال اسکن واقعی {fa(m.group(2))} سرور…</b>\n{bar} {fa(int(pct))}٪\n"
                           f"<i>کمی صبر کن؛ اندازه‌گیری تأخیر و افت بسته زمان می‌برد.</i>")
            except Exception:
                pass

    await edit(chat_id, message_id, "⏳ شروع اسکن… چند ثانیه صبر کن.")
    lines = await run_scanner(servers, out_dir, attempts, label, on_progress=progress)
    rj = out_dir / "report.json"
    if not rj.exists():
        tail = "\n".join(lines[-6:])
        await edit(chat_id, message_id, "❌ اسکنر خروجی نداد.\n<code>" + tail[-900:] + "</code>")
        return None
    report = json.loads(rj.read_text(encoding="utf-8"))
    await edit(chat_id, message_id, summarize(report), keyboard=main_keyboard())
    return report


async def cmd_ping(chat_id, target: str):
    ip = target.strip().split()[0] if target.strip() else ""
    if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
        await send(chat_id, "شکل آی‌پی درست نیست. نمونه:\n<code>/ping 8.8.8.8</code>")
        return
    msg = await send(chat_id, f"⏳ در حال اندازه‌گیری مسیر تا <code>{ip}</code>…")

    def measure():
        import socket as sk
        lat = []
        for _ in range(8):
            try:
                t0 = time.perf_counter()
                s = sk.create_connection((ip, 443), timeout=3)
                lat.append((time.perf_counter() - t0) * 1000)
                s.close()
            except Exception:
                pass
        return lat

    lat = await asyncio.get_running_loop().run_in_executor(None, measure)
    if not lat:
        await edit(chat_id, msg["result"]["message_id"],
                   f"❌ به <code>{ip}</code> روی پورت ۴۴۳ وصل نشدم (فایروال/مسدود).")
        return
    med = statistics.median(lat)
    jit = statistics.mean(abs(x - med) for x in lat)
    verdict = ("🟢 عالی (مناسب گیم)" if med < 60 else
               "🟡 قابل قبول" if med < 110 else "🟠 بالا — لگ محسوس" if med < 180 else
               "🔴 خیلی بالا — برای این سرور بازی نکن")
    await edit(chat_id, msg["result"]["message_id"],
               f"📶 <b>مسیر تا <code>{ip}</code></b>\n"
               f"تأخیر میانه: <b>{fmt_ms(med)}</b> ms\n"
               f"جیتر: {fmt_ms(jit)} ms\n"
               f"کم‌ترین: {fmt_ms(min(lat))} ms · بیشترین: {fmt_ms(max(lat))} ms\n"
               f"افت: {fa(8 - len(lat))} از ۸\n\n{verdict}\n"
               f"<i>این همان تأخیر رفت‌وبرگشت شبکه‌ی توست؛ پینگ داخل بازی معمولاً چند برابر همین است.</i>")


async def cmd_dns(chat_id, arg: str):
    parts = arg.split()
    if not parts or not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", parts[0]):
        await send(chat_id, "نمونه:\n<code>/dns 10.202.10.10</code>\nیا\n"
                            "<code>/dns 10.202.10.10 mydomain.com</code>")
        return
    ip = parts[0]
    domain = parts[1] if len(parts) > 1 else "www.wikipedia.org"
    msg = await send(chat_id, f"⏳ تست زنده <code>{ip}</code> روی <code>{domain}</code>…")

    def live():
        sys.path.insert(0, str(HERE))
        from dnsscan import build_query, parse_response
        import socket as sk
        s = sk.socket(sk.AF_INET, sk.SOCK_DGRAM)
        s.settimeout(2.5)
        lat, answers, rcode, err = [], [], None, None
        for _ in range(6):
            pkt, txid = build_query(domain, 1)
            try:
                t0 = time.perf_counter()
                s.sendto(pkt, (ip, 53))
                data, _ = s.recvfrom(4096)
                if struct.unpack(">H", data[:2])[0] != txid:
                    continue
                lat.append((time.perf_counter() - t0) * 1000)
                p = parse_response(data)
                rcode = p["rcode"]
                answers = p["a"]
            except Exception as e:
                err = type(e).__name__
        s.close()
        # تست دستکاری
        hijack = None
        try:
            s2 = sk.socket(sk.AF_INET, sk.SOCK_DGRAM)
            s2.settimeout(2.5)
            pkt, txid = build_query(f"zz{int(time.time())}.example.com", 1)
            s2.sendto(pkt, (ip, 53))
            data, _ = s2.recvfrom(4096)
            p = parse_response(data)
            if p["rcode"] == 0 and p["a"]:
                hijack = p["a"][0]
            s2.close()
        except Exception:
            pass
        return lat, answers, rcode, err, hijack

    lat, answers, rcode, err, hijack = await asyncio.get_running_loop().run_in_executor(None, live)
    if not lat:
        await edit(chat_id, msg["result"]["message_id"],
                   f"❌ <code>{ip}</code> جواب نداد ({fa(err or 'timeout')}).\n"
                   f"یعنی از شبکه‌ی تو قابل استفاده نیست.")
        return
    med = statistics.median(lat)
    lines = [f"🔎 <b>تست زنده <code>{ip}</code></b>",
             f"دامنه: <code>{domain}</code>",
             f"تأخیر میانه: <b>{fmt_ms(med)}</b> ms  (کم‌ترین {fmt_ms(min(lat))})",
             f"پاسخ‌ها: {'، '.join(answers[:4]) if answers else '—'}",
             f"کد پاسخ: {fa(rcode)} (۰ = موفق)"]
    if hijack:
        lines.append(f"⚠️ <b>هشدار دستکاری DNS:</b> برای دامنه‌ی ساختگی هم پاسخ داد ({hijack}) — این سرور ترافیک را هدایت می‌کند.")
    else:
        lines.append("✅ تست دستکاری: پاک (برای دامنه‌ی ساختگی پاسخ نداد)")
    await edit(chat_id, msg["result"]["message_id"], "\n".join(lines))


async def cmd_report(chat_id, preset):
    servers = PRESETS.get(preset, PRESETS["gaming"])
    out_dir = REPORT_ROOT / str(chat_id)
    msg = await send(chat_id, "⏳ در حال ساخت گزارش کامل (۳۰–۶۰ ثانیه)…")
    mid = msg["result"]["message_id"]

    async def progress(line):
        m = re.match(r"\[(\d+)/(\d+)\]", line)
        if m:
            try:
                await edit(chat_id, mid, f"⏳ ساخت گزارش… {fa(m.group(1))} از {fa(m.group(2))} سرور")
            except Exception:
                pass

    await run_scanner(servers, out_dir, 10, f"گزارش-{preset}", on_progress=progress,
                      extra_args=("--edges",))
    html_file = out_dir / "report.html"
    if html_file.exists():
        await send_document(chat_id, html_file,
                            caption="📄 گزارش HTML رادار DNS — با مرورگر گوشی بازش کن.")
        await edit(chat_id, mid, "✅ گزارش آماده شد و بالا برایت فرستادم.")
    else:
        await edit(chat_id, mid, "❌ ساخت گزارش ناموفق بود.")


# ----------------------------------------------------------------------------- حلقه اصلی

async def handle_update(u: dict):
    try:
        if "callback_query" in u:
            cq = u["callback_query"]
            chat_id = cq["message"]["chat"]["id"]
            mid = cq["message"]["message_id"]
            data = cq.get("data", "")
            await tg("answerCallbackQuery", callback_query_id=cq["id"])
            if data.startswith("scan:"):
                await do_scan(chat_id, mid, data.split(":", 1)[1])
            elif data.startswith("report:"):
                await cmd_report(chat_id, data.split(":", 1)[1])
            elif data == "cmd:guide":
                await send(chat_id, GUIDE)
            elif data == "cmd:help":
                await send(chat_id, HELP, keyboard=main_keyboard())
            return

        msg = u.get("message") or u.get("edited_message")
        if not msg:
            return
        chat_id = msg["chat"]["id"]
        text = (msg.get("text") or "").strip()
        if not text:
            return
        cmd, _, arg = text.partition(" ")
        cmd = cmd.split("@")[0].lower()

        if cmd in ("/start", "/help"):
            await send(chat_id, HELP, keyboard=main_keyboard())
        elif cmd in ("/check", "/scan"):
            m = await send(chat_id, "⏳ آماده‌سازی…")
            await do_scan(chat_id, m["result"]["message_id"], "quick")
        elif cmd == "/report":
            await cmd_report(chat_id, "gaming")
        elif cmd == "/ping":
            await cmd_ping(chat_id, arg)
        elif cmd == "/dns":
            await cmd_dns(chat_id, arg)
        elif cmd == "/guide":
            await send(chat_id, GUIDE)
        else:
            await send(chat_id, "دستور را نفهمیدم 🤔\n" + HELP, keyboard=main_keyboard())
    except Exception as e:
        print("handle error:", type(e).__name__, e, flush=True)


HELP = """📡 <b>رادار DNS</b> — ابزار واقعی انتخاب DNS برای گیمرهای ایران

من فقط حرف نمی‌زنم: <b>واقعاً</b> به DNSها کوئری می‌فرستم، تأخیر میانه، جیتر، افت بسته،
پاسخ جعلی (هیجک) و پشتیبانی DoH/DoT را اندازه می‌گیرم و بهترین را برایت انتخاب می‌کنم.

<b>دستورها</b>
/check — اسکن سریع (۱۵ ثانیه) ⚡️
/scan — مجموعه‌ی کامل (ایرانی، گیم، جهانی، خانواده)
/report — گزارش HTML کامل با نمودار 📄
/ping 8.8.8.8 — اندازه‌گیری تأخیر مسیر تا یک آی‌پی (سرور بازی، سایت…)
/dns 10.202.10.10 — تست زنده‌ی یک DNS + تشخیص دستکاری
/guide — راهنمای واقعی کم کردن پینگ (و افسانه‌ها) 📘

⚙️ <b>چطور از نتیجه استفاده کنم؟</b>
اندروید ۹+: تنظیمات › شبکه و اینترنت › DNS خصوصی › «نام میزبان ارائه‌دهنده» → آدرس را وارد کن.
آیفون: تنظیمات › وای‌فای › (i) شبکه › Configure DNS › Manual.
ویندوز: تنظیمات آداپتور › IPv4 › DNS دستی.

⚠️ <b>صادقانه:</b> DNS پینگ داخل مچ بازی را کم نمی‌کند. برای پینگ واقعی، محل خروجی تونل و
کیفیت مسیر مهم است. من مسیر و کیفیت را اندازه می‌گیرم و بهترین گزینه را نشانت می‌دهم.
"""


async def main():
    if not TOKEN:
        print("❌ متغیر محیطی TELEGRAM_BOT_TOKEN تنظیم نشده.\n"
              "   export TELEGRAM_BOT_TOKEN=\"123:ABC\" و دوباره اجرا کن.")
        sys.exit(1)
    me = await tg("getMe")
    if not me.get("ok"):
        print("❌ توکن نامعتبر است یا دسترسی به api.telegram.org نیست.", me)
        sys.exit(1)
    print(f"✅ بات @{me['result']['username']} آماده است. Ctrl+C برای توقف.")
    offset = None
    await tg("deleteWebhook", drop_pending_updates=False)
    while True:
        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset
            r = await tg("getUpdates", **params)
            if not r.get("ok"):
                await asyncio.sleep(3)
                continue
            for u in r["result"]:
                offset = u["update_id"] + 1
                asyncio.create_task(handle_update(u))
        except KeyboardInterrupt:
            print("\nخداحافظ 👋")
            return
        except Exception as e:
            print("poll error:", type(e).__name__, e, flush=True)
            await asyncio.sleep(3)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nخداحافظ 👋")
