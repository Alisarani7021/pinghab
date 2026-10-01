#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_games_catalog.py — کاتالوگ سرورهای بازی «پینگ‌هاب» را می‌سازد.

قاعده‌ها:
  • بخش pingdiff (۹ بازی / ۱۴۱ سرور) دست‌نخورده می‌ماند (MIT).
  • بازی‌های تازه فقط اگر «با پینگ واقعی تأیید شده باشند» وارد می‌شوند؛
    عدد هر سرور = میانگین پینگ‌های سنجیده‌شده از سه نقطهٔ دید (DE/SG/TR) با Globalping.
  • هر رکورد منبع دارد (src) و تاریخ تأیید (v_at).
  • سرویس‌هایی که سرورشان ICMP را بلاک می‌کند در بخش «services» می‌آیند،
    با معنی دقیق عدد (زمان کل درخواست HTTPS، نه پینگ) + منبع و تاریخ.

اجرا:  python3 tools/build_games_catalog.py
خروجی: data/games/servers.json  (بازنویسی‌شده) + چاپ خلاصه
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
P = ROOT / "data" / "games" / "servers.json"

V_AT = "2026-10-01"
PROBE_NOTE = "میانگین پینگ ICMP از Globalping — فرانکفورت/سینگاپور/استانبول"

# ---------------------------------------------------------------- بازی‌های تأییدشده
# probe = {vantage: ms یا None}  |  None یعنی از آن نقطه پاسخ ICMP نیامد (بلاک/فیلتر)
NEW_GAMES = {
    "pubg-mobile": {
        "name": "PUBG Mobile",
        "name_fa": "پابجی موبایل",
        "publisher": "Tencent / Lightspeed (Level Infinite)",
        "src": "https://www.netify.ai/resources/ips/162.62.115.42",
        "note": "سرور موبایل روی Tencent Cloud است، نه AWS. بسیاری از گره‌های آسیا/خاورمیانه ICMP را بلاک می‌کنند؛ برای همان‌ها عدد نمی‌سازیم و «قابل سنجش نیست» می‌نویسیم. پینگ داخل مچ = RTT به آی‌پی سرور بازی؛ DNS فقط سرعت اتصال را بهتر می‌کند، نه پینگ داخل مچ.",
        "regions": {
            "EU": [
                {"id": "pubgm-eu-fra", "loc": "Frankfurt (Tencent Cloud)", "ip": "162.62.115.42", "port": 443,
                 "asn": "AS132203 Tencent", "v": True, "probe": {"DE": 7, "SG": 248, "TR": 40}},
            ],
            "ASIA": [
                {"id": "pubgm-as-tencent", "loc": "گرهٔ Tencent Cloud (از سینگاپور ۲۴۵ms ⇒ دور از SEA)", "ip": "162.62.116.5",
                 "port": 443, "asn": "AS132203 Tencent", "v": True, "probe": {"DE": None, "SG": 245, "TR": None}},
            ],
        },
        "unmeasurable": [
            {"loc": "Asia (سینگاپور)", "why": "ICMP بسته — از سه نقطهٔ دید پاسخی نیامد"},
            {"loc": "Middle East (بحرین)", "why": "ICMP بسته"},
            {"loc": "KRJP (سئول/توکیو)", "why": "ICMP بسته"},
        ],
    },
    "mobile-legends": {
        "name": "Mobile Legends: Bang Bang",
        "name_fa": "موبایل لجندز (MLBB)",
        "publisher": "Moonton (ByteDance)",
        "src": "https://forums.mudfish.net/t/request-add-jakarta-destination-for-mobile-legends-bang-bang/84016 + فهرست عمومی آی‌پی/پورت نسخهٔ ۲.۱.۴۰",
        "note": "میزبان اصلی Moonton = IBM Cloud (SoftLayer) و گره‌های Jakarta روی Zenlayer/BytePlus. پورت‌های اتصال: TCP 30021/30104 و UDP 30190 (طبق فهرست عمومی نسخه). سنجش ما ICMP است، پس پورت در عدد اثر ندارد و فقط برای کپی/فایروال آمده.",
        "regions": {
            "SEA": [
                {"id": "mlbb-sg-a", "loc": "سینگاپور (IBM Cloud)", "ip": "161.202.221.155", "port": 30021, "asn": "AS36351 IBM Cloud", "v": True, "probe": {"DE": 175, "SG": 1, "TR": 245}},
                {"id": "mlbb-sg-b", "loc": "سینگاپور (IBM Cloud)", "ip": "161.202.222.25", "port": 30021, "asn": "AS36351 IBM Cloud", "v": True, "probe": {"DE": 175, "SG": 1, "TR": 246}},
                {"id": "mlbb-sg-c", "loc": "سینگاپور (CDS/Zenlayer)", "ip": "148.153.196.5", "port": 30190, "asn": "AS63199", "v": True, "probe": {"DE": 164, "SG": 2, "TR": 191}},
                {"id": "mlbb-sg-d", "loc": "سینگاپور (CDS/Zenlayer)", "ip": "148.153.196.16", "port": 30190, "asn": "AS63199", "v": True, "probe": {"DE": 168, "SG": 2, "TR": 192}},
                {"id": "mlbb-sg-e", "loc": "سینگاپور (Kaopu)", "ip": "154.93.119.148", "port": 30190, "asn": "AS138915", "v": True, "probe": {"DE": 222, "SG": 27, "TR": 210}},
                {"id": "mlbb-sg-f", "loc": "سینگاپور (Zenlayer)", "ip": "45.198.233.14", "port": 30190, "asn": "AS141109 (SC)", "v": True, "probe": {"DE": 204, "SG": 32, "TR": 213}},
            ],
            "ASIA": [
                {"id": "mlbb-jkt-a", "loc": "جاکارتا (Zenlayer)", "ip": "216.133.157.41", "port": 30021, "asn": "AS62610", "v": True, "probe": {"DE": 176, "SG": 18, "TR": 209}},
                {"id": "mlbb-jkt-b", "loc": "جاکارتا (Zenlayer-ID)", "ip": "103.157.33.35", "port": 30021, "asn": "AS141109 (ID)", "v": True, "probe": {"DE": 173, "SG": 13, "TR": 190}},
                {"id": "mlbb-asia-a", "loc": "آسیا (IBM Cloud)", "ip": "169.55.210.238", "port": 30021, "asn": "AS36351 IBM Cloud", "v": True, "probe": {"DE": 126, "SG": 253, "TR": 165}},
                {"id": "mlbb-asia-b", "loc": "آسیا (IBM Cloud)", "ip": "169.55.210.227", "port": 30021, "asn": "AS36351 IBM Cloud", "v": True, "probe": {"DE": 127, "SG": 241, "TR": 162}},
            ],
            "EU": [
                {"id": "mlbb-eu-a", "loc": "اروپا (IBM Cloud)", "ip": "158.177.196.162", "port": 30021, "asn": "AS36351 IBM Cloud", "v": True, "probe": {"DE": 16, "SG": 151, "TR": 42}},
            ],
            "ME": [
                {"id": "mlbb-me-login", "loc": "گرهٔ ورود خاورمیانه (IBM Cloud)", "ip": "169.46.198.121", "port": 30021, "asn": "AS36351 IBM Cloud", "v": False, "probe": {"DE": None, "SG": None, "TR": None},
                 "why": "کاندید از فهرست عمومی — ICMP پاسخ نداد؛ فقط به‌عنوان کاندید نگه داشته شد"},
            ],
        },
        "unmeasurable": [
            {"loc": "Mumbai (هند/جنوب آسیا)", "why": "ICMP بسته (169.38.97.1 پاسخ نداد)"},
        ],
    },
    "pubg-pc": {
        "name": "PUBG: Battlegrounds (PC)",
        "name_fa": "پابجی کامپیوتر",
        "publisher": "Krafton (میزبانی AWS)",
        "src": "https://gist.github.com/kirankotari/938cb9452caca2d6c312be91a39e9f79 (فهرست AWS عمومی، تأیید با پینگ ما)",
        "note": "این‌ها میزبان‌های AWS سبک PC‑era هستند و پابجی موبایل با آن‌ها کار نمی‌کند — جدا نگه داشته شده‌اند. فقط آی‌پی‌هایی که خودمان پاسخ گرفتیم آمده‌اند (فرانکفورت و نیویورک پاسخ ندادند).",
        "regions": {
            "ASIA": [
                {"id": "pubgpc-seoul", "loc": "سئول (AWS)", "ip": "52.79.52.64", "port": 443, "asn": "AS16509 AWS", "v": True, "probe": {"DE": 295, "SG": 68, "TR": 343}},
                {"id": "pubgpc-tokyo", "loc": "توکیو (AWS)", "ip": "13.112.63.251", "port": 443, "asn": "AS16509 AWS", "v": True, "probe": {"DE": 240, "SG": 69, "TR": 351}},
                {"id": "pubgpc-sg", "loc": "سینگاپور (AWS)", "ip": "13.228.0.251", "port": 443, "asn": "AS16509 AWS", "v": True, "probe": {"DE": 159, "SG": 2, "TR": 363}},
                {"id": "pubgpc-mumbai", "loc": "بمبئی (AWS)", "ip": "13.126.0.252", "port": 443, "asn": "AS16509 AWS", "v": True, "probe": {"DE": 131, "SG": 56, "TR": 256}},
            ],
            "EU": [
                {"id": "pubgpc-london", "loc": "لندن (AWS)", "ip": "35.176.0.252", "port": 443, "asn": "AS16509 AWS", "v": True, "probe": {"DE": 17, "SG": 161, "TR": 57}},
                {"id": "pubgpc-fra", "loc": "فرانکفورت (AWS)", "ip": "52.58.95.114", "port": 443, "asn": "AS16509 AWS", "v": True, "probe": {"DE": None, "SG": 174, "TR": 64}},
            ],
            "OCE": [
                {"id": "pubgpc-sydney", "loc": "سیدنی (AWS)", "ip": "13.54.63.252", "port": 443, "asn": "AS16509 AWS", "v": True, "probe": {"DE": 308, "SG": 337, "TR": 343}},
            ],
        },
    },
    "dota-2": {
        "name": "Dota 2 / CS2 (Valve)",
        "name_fa": "دوتا ۲ / CS۲ (سرورهای Valve)",
        "publisher": "Valve (AS32590)",
        "src": "سرورهای ثابت Valve — تأیید با پینگ ما از سه نقطهٔ دید",
        "note": "دبی و استکلهم و سینگاپور پاسخ دادند؛ فرانکفورت Valve از دو نقطه عدد پرت داد (۳۸۰ms) که نشانهٔ فیلتر/مسیریابی عجیب است — همان را هم صادقانه نشان می‌دهیم.",
        "regions": {
            "ME": [
                {"id": "valve-dubai-a", "loc": "دبی (Valve)", "ip": "185.25.182.1", "port": 27015, "asn": "AS32590 Valve", "v": True, "probe": {"DE": 15, "SG": 162, "TR": 43}},
                {"id": "valve-dubai-b", "loc": "دبی (Valve)", "ip": "185.25.183.1", "port": 27015, "asn": "AS32590 Valve", "v": True, "probe": {"DE": 136, "SG": 81, "TR": 168}},
            ],
            "EU": [
                {"id": "valve-sto", "loc": "استکلهم (Valve)", "ip": "146.66.155.1", "port": 27015, "asn": "AS32590 Valve", "v": True, "probe": {"DE": 16, "SG": 183, "TR": 24}},
                {"id": "valve-fra", "loc": "فرانکفورت (Valve)", "ip": "146.66.152.1", "port": 27015, "asn": "AS32590 Valve", "v": True, "probe": {"DE": 380, "SG": 178, "TR": 385}},
            ],
            "SEA": [
                {"id": "valve-sg-a", "loc": "سینگاپور (Valve)", "ip": "103.10.124.1", "port": 27015, "asn": "AS32590 Valve", "v": True, "probe": {"DE": 159, "SG": 1, "TR": 205}},
                {"id": "valve-sg-b", "loc": "سینگاپور (Valve)", "ip": "103.10.125.1", "port": 27015, "asn": "AS32590 Valve", "v": True, "probe": {"DE": 175, "SG": 1, "TR": 257}},
            ],
        },
    },
}

# ---------------------------------------------------------------- سرویس‌ها (ICMP بسته)
# عدد = زمان کل درخواست HTTPS (DNS+TCP+TLS+پاسخ) از پروب تهران (Globalping http) — نه پینگ.
SERVICES = {
    "note": "بازی‌هایی که سرور بازی‌شان ICMP را بلاک می‌کند با «پینگ» قابل سنجش نیستند. اینجا زمان پاسخ سرویس (HTTPS کامل) از پروب تهران می‌آید؛ این عدد شامل DNS+TCP+TLS است و با پینگ داخل بازی یکی نیست. برای پینگ داخل بازی، عدد خودِ بازی معتبر است.",
    "measured_at": V_AT,
    "rows": [
        {"game": "Roblox", "fa": "ربلاکس", "host": "www.roblox.com", "ir_https_ms": 389, "status": 200, "extra": [{"loc": "DE", "ms": 195}, {"loc": "TR", "ms": None}]},
        {"game": "Free Fire", "fa": "فری فایر (Garena)", "host": "www.garena.sg", "ir_https_ms": 1005, "status": 200, "extra": [{"loc": "DE", "ms": 653}, {"loc": "TR", "ms": 1176}]},
        {"game": "eFootball", "fa": "ای‌فوتبال (Konami)", "host": "www.konami.com", "ir_https_ms": 924, "status": 302, "extra": [{"loc": "DE", "ms": 395}, {"loc": "TR", "ms": 487}]},
        {"game": "Steam", "fa": "استیم (Valve)", "host": "store.steampowered.com", "ir_https_ms": 562, "status": 200, "extra": [{"loc": "DE", "ms": 312}, {"loc": "TR", "ms": 468}]},
        {"game": "Epic / Fortnite", "fa": "اپیک / فورتنایت", "host": "www.epicgames.com", "ir_https_ms": 151, "status": 403, "extra": [{"loc": "DE", "ms": 45}, {"loc": "TR", "ms": 36}]},
        {"game": "EA / Apex", "fa": "EA / ایپکس", "host": "accounts.ea.com", "ir_https_ms": 603, "status": 404, "extra": [{"loc": "DE", "ms": 354}, {"loc": "TR", "ms": 430}]},
        {"game": "Call of Duty", "fa": "کالاف دیوتی", "host": "www.callofduty.com", "ir_https_ms": None, "status": None, "extra": [{"loc": "DE", "ms": None}], "why": "پاسخی نیامد (۱۵ ثانیه تایم‌اوت از هر سه نقطه)"},
    ],
}


def main():
    doc = json.loads(P.read_text(encoding="utf-8"))
    doc.setdefault("regions_fa", {}).update({
        "SEA": "جنوب شرق آسیا (سینگاپور/جاکارتا)",
        "ME": "خاورمیانه (دبی/بحرین)",
        "OCE": "اقیانوسیه (سیدنی)",
        "EU": "اروپا", "NA": "آمریکای شمالی", "ASIA": "آسیا", "SA": "آمریکای جنوبی",
    })
    games = doc["games"]
    added = []
    for slug, g in NEW_GAMES.items():
        g2 = dict(g)
        g2["v_at"] = V_AT
        g2["probe_note"] = PROBE_NOTE
        g2.setdefault("name", slug)
        # پاک‌سازی: سرورهای تأییدنشده فقط اگر دلیل دارند بمانند
        for reg, arr in list(g2["regions"].items()):
            for s in arr:
                if not s.get("v") and not s.get("why"):
                    s["why"] = "تأیید نشده"
        games[slug] = g2
        added.append(slug)

    doc["services"] = SERVICES
    doc["verified_at"] = V_AT
    doc["verified_by"] = "Globalping (ICMP از DE/SG/TR) + Globalping HTTP از پروب تهران"
    doc["build_note"] = "بازتولید: python3 tools/build_games_catalog.py"

    P.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

    tot = sum(len(v) for g in games.values() for v in g.get("regions", {}).values())
    vtot = sum(1 for g in games.values() for v in g.get("regions", {}).values() for s in v if s.get("v"))
    print(f"games={len(games)}  servers={tot}  verified={vtot}  services={len(SERVICES['rows'])}")
    for slug in added:
        n = sum(len(v) for v in games[slug]["regions"].values())
        print(f"  + {slug}: {n} server")


if __name__ == "__main__":
    main()
