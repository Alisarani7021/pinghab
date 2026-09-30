#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ابزار کاتالوگ DNS جهانی
=========================================================================
دو لایهٔ داده می‌سازد:

  ۱) catalog.json  — تمام رزولورهای عمومی جهان از public-dns.info
                     (۶۲٬۷۹۰ سرور، ۱۹۳ کشور) با نام فارسی کشورها.
  ۲) curated.json  — لایهٔ «چندتایی مطمئن»: anycast های جهانی + رزولورهای ایرانی
                     با IPv4/IPv6/DoH/DoT، و **منبع هر رکورد** یادداشت شده.

صداقت داده:
  • منبع لایهٔ ۱ اسکن اینترنتی است، نه ادعای کیفیت. هر رزولور عمومیِ باز
    می‌تواند لاگ‌بردار، ناپایدار یا دست‌کاری‌شده باشد. تا زمانی که
    `worldscan.py` آن را در «سنجش اثر» تأیید نکند، فقط «کاندید» است.
  • لایهٔ ۲ تا وقتی سنجیده نشود `verified: false` است.

اجرا:
    python3 tools/dns_catalog.py            # ساخت هر دو فایل
    python3 tools/dns_catalog.py --query IR # فقط نگاه کردن به یک کشور
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data", "dns_world")
RAW = os.path.join(DATA, "raw", "nameservers.csv")
SOURCE_URL = "https://public-dns.info/nameservers.csv"
SOURCE_NOTE = ("public-dns.info — اسکن پیوستهٔ رزولورهای عمومی باز (IPv4/IPv6). "
               "این‌ها «برترین DNS برای بازی» نیستند؛ کاندید خام برای سنجش‌اند.")

# ---------------------------------------------------------------------------- نگاشت کد کشور → نام فارسی
FA_NAMES = {
    "AF": "افغانستان", "AL": "آلبانی", "DZ": "الجزایر", "AS": "ساموآی آمریکا", "AD": "آندورا",
    "AO": "آنگولا", "AQ": "جنوبگان", "AG": "آنتیگوا و باربودا", "AR": "آرژانتین", "AM": "ارمنستان",
    "AW": "آروبا", "AU": "استرالیا", "AT": "اتریش", "AZ": "جمهوری آذربایجان", "BS": "باهاما",
    "BH": "بحرین", "BD": "بنگلادش", "BB": "باربادوس", "BY": "بلاروس", "BE": "بلژیک",
    "BZ": "بلیز", "BJ": "بنین", "BM": "برمودا", "BT": "بوتان", "BO": "بولیوی",
    "BA": "بوسنی و هرزگوین", "BW": "بوتسوانا", "BR": "برزیل", "BN": "برونئی", "BG": "بلغارستان",
    "BF": "بورکینافاسو", "BI": "بوروندی", "KH": "کامبوج", "CM": "کامرون", "CA": "کانادا",
    "CV": "کیپ‌ورد", "KY": "جزایر کیمن", "TD": "چاد", "CL": "شیلی", "CN": "چین",
    "CO": "کلمبیا", "CG": "کنگو", "CD": "کنگو (دموکراتیک)", "CR": "کاستاریکا", "HR": "کرواسی",
    "CU": "کوبا", "CY": "قبرس", "CZ": "چک", "CI": "ساحل عاج", "DK": "دانمارک",
    "DO": "جمهوری دومینیکن", "EC": "اکوادور", "EG": "مصر", "SV": "السالوادور", "GQ": "گینهٔ استوایی",
    "EE": "استونی", "ET": "اتیوپی", "FI": "فنلاند", "FR": "فرانسه", "GF": "گویان فرانسه",
    "PF": "پولی‌نزی فرانسه", "GA": "گابن", "GE": "گرجستان", "DE": "آلمان", "GH": "غنا",
    "GI": "جبل‌طارق", "GR": "یونان", "GL": "گرینلند", "GP": "گوادلوپ", "GU": "گوام",
    "GT": "گواتمالا", "GG": "گرنزی", "GN": "گینه", "HN": "هندوراس", "HK": "هنگ‌کنگ",
    "HU": "مجارستان", "IS": "ایسلند", "IN": "هند", "ID": "اندونزی", "IR": "ایران",
    "IQ": "عراق", "IE": "ایرلند", "IM": "جزیرهٔ من", "IL": "اسرائیل", "IT": "ایتالیا",
    "JM": "جامائیکا", "JP": "ژاپن", "JE": "جرزی", "JO": "اردن", "KZ": "قزاقستان",
    "KE": "کنیا", "KR": "کرهٔ جنوبی", "KW": "کویت", "KG": "قرقیزستان", "LA": "لائوس",
    "LV": "لتونی", "LB": "لبنان", "LR": "لیبریا", "LY": "لیبی", "LI": "لیختن‌اشتاین",
    "LT": "لیتوانی", "LU": "لوکزامبورگ", "MO": "ماکائو", "MK": "مقدونیه", "MG": "ماداگاسکار",
    "MW": "مالاوی", "MY": "مالزی", "MV": "مالدیو", "ML": "مالی", "MT": "مالت",
    "MH": "جزایر مارشال", "MQ": "مارتینیک", "MR": "موریتانی", "MU": "موریس", "YT": "مایوت",
    "MX": "مکزیک", "MD": "مولداوی", "MC": "موناکو", "MN": "مغولستان", "ME": "مونته‌نگرو",
    "MA": "مراکش", "MZ": "موزامبیک", "MM": "میانمار", "NA": "نامیبیا", "NP": "نپال",
    "NL": "هلند", "NC": "کالدونیای جدید", "NZ": "نیوزیلند", "NI": "نیکاراگوئه", "NE": "نیجر",
    "NG": "نیجریه", "OM": "عمان", "PK": "پاکستان", "PS": "فلسطین", "PA": "پاناما",
    "PG": "پاپوآ گینهٔ نو", "PY": "پاراگوئه", "PE": "پرو", "PH": "فیلیپین", "PL": "لهستان",
    "PT": "پرتغال", "PR": "پورتوریکو", "QA": "قطر", "RO": "رومانی", "RU": "روسیه",
    "RW": "رواندا", "SA": "عربستان", "SN": "سنگال", "RS": "صربستان", "SC": "سیشل",
    "SL": "سیرالئون", "SG": "سنگاپور", "SK": "اسلواکی", "SI": "اسلوونی", "SB": "جزایر سلیمان",
    "SO": "سومالی", "ZA": "آفریقای جنوبی", "ES": "اسپانیا", "LK": "سری‌لانکا", "SD": "سودان",
    "SR": "سورینام", "SZ": "اسواتینی", "SE": "سوئد", "CH": "سوئیس", "SY": "سوریه",
    "TW": "تایوان", "TJ": "تاجیکستان", "TZ": "تانزانیا", "TH": "تایلند", "TL": "تیمور شرقی",
    "TG": "توگو", "TT": "ترینیداد و توباگو", "TN": "تونس", "TR": "ترکیه", "TM": "ترکمنستان",
    "UG": "اوگاندا", "UA": "اوکراین", "AE": "امارات", "GB": "بریتانیا", "US": "آمریکا",
    "UY": "اروگوئه", "UZ": "ازبکستان", "VE": "ونزوئلا", "VN": "ویتنام", "VI": "جزایر ویرجین",
    "XK": "کوزوو", "YE": "یمن", "ZM": "زامبیا", "ZW": "زیمبابوه", "AX": "جزایر آلند",
    "BQ": "بونیر", "CW": "کوراسائو", "SX": "سینت مارتن", "SS": "سودان جنوبی", "EH": "صحرای غربی",
    "FO": "جزایر فارو", "FK": "جزایر فالکلند", "MR_": "موریتانی", "NC_": "کالدونیای جدید",
}

# ---------------------------------------------------------------------------- لایهٔ منتخب (curated)
# هر رکورد: منبع + وضعیت تأیید. IPv4/IPv6/DoH/DoT جایی که سرویس اعلام کرده است.
CURATED = {
    "note": ("لایهٔ منتخب: anycast های جهانی و رزولورهای ایرانی. "
             "«verified» یعنی با worldscan.py روی همین ماشین سنجیده شده؛ "
             "رزولورهای داخل ایران از بیرون قابل‌سنجش نیستند و باید از خود ایران اجرا شوند."),
    "groups": [
        {
            "id": "global-anycast", "label": "anycast های جهانی (از هر نقطهٔ دنیا نزدیک‌ترین PoP پاسخ می‌دهد)",
            "source": "اعلام رسمی سرویس‌ها",
            "entries": [
                {"name": "Cloudflare", "v4": ["1.1.1.1", "1.0.0.1"],
                 "v6": ["2606:4700:4700::1111", "2606:4700:4700::1001"],
                 "doh": "https://cloudflare-dns.com/dns-query", "dot": "one.one.one.one",
                 "note": "بدون فیلتر (نسخهٔ ۱.۱.۱.۲/۳ فیلتردار)", "verified": None},
                {"name": "Google Public DNS", "v4": ["8.8.8.8", "8.8.4.4"],
                 "v6": ["2001:4860:4860::8888", "2001:4860:4860::8844"],
                 "doh": "https://dns.google/dns-query", "dot": "dns.google",
                 "note": "بدون فیلتر", "verified": None},
                {"name": "Quad9", "v4": ["9.9.9.9", "149.112.112.112"],
                 "v6": ["2620:fe::fe", "2620:fe::9"],
                 "doh": "https://dns.quad9.net/dns-query", "dot": "dns.quad9.net",
                 "note": "فیلتر بدافزار (نسخهٔ ۹.۹.۹.۱۰ بدون فیلتر)", "verified": None},
                {"name": "OpenDNS", "v4": ["208.67.222.222", "208.67.220.220"],
                 "v6": ["2620:119:35::35", "2620:119:53::53"], "doh": None, "dot": None,
                 "note": "Cisco", "verified": None},
                {"name": "AdGuard DNS", "v4": ["94.140.14.14", "94.140.15.15"],
                 "v6": ["2a10:50c0::ad1:ff", "2a10:50c0::ad2:ff"],
                 "doh": "https://dns.adguard-dns.com/dns-query", "dot": "dns.adguard-dns.com",
                 "note": "مسدودسازی تبلیغ/ردیاب", "verified": None},
                {"name": "Control D", "v4": ["76.76.2.0", "76.76.10.0"],
                 "v6": ["2606:1a40::", "2606:1a40:1::"], "doh": None, "dot": None,
                 "note": "anycast گسترده", "verified": None},
                {"name": "DNS0.eu", "v4": ["193.110.81.0", "185.253.5.0"],
                 "v6": ["2a0f:fc80::", "2a0f:fc81::"], "doh": "https://dns0.eu/", "dot": None,
                 "note": "اروپایی، بدون لاگ", "verified": None},
                {"name": "Mullvad", "v4": ["194.242.2.2", "194.242.2.3"],
                 "v6": ["2a07:e340::2", "2a07:e340::3"],
                 "doh": "https://dns.mullvad.net/dns-query", "dot": None,
                 "note": "بدون لاگ", "verified": None},
                {"name": "dns.sb", "v4": ["185.222.222.222", "45.11.45.11"],
                 "v6": ["2a09::", "2a11::"], "doh": "https://doh.sb/dns-query", "dot": "dot.sb",
                 "note": "بدون لاگ", "verified": None},
                {"name": "UncensoredDNS", "v4": ["91.239.100.100", "89.233.43.71"],
                 "v6": ["2001:67c:28a4::", "2c0f:f930:0:4::10"], "doh": None, "dot": "anycast.censurfridns.dk",
                 "note": "دانمارک، بدون سانسور", "verified": None},
                {"name": "NextDNS (anycast)", "v4": ["45.90.28.0", "45.90.30.0"], "v6": [],
                 "doh": "https://dns.nextdns.io/", "dot": None,
                 "note": "لینک اختصاصی لازم است", "verified": None},
                {"name": "Verisign Public DNS", "v4": ["64.6.64.6", "64.6.65.6"],
                 "v6": ["2620:74:1b::1:1", "2620:74:1c::2:2"], "doh": None, "dot": None,
                 "note": "بدون فیلتر", "verified": None},
                {"name": "Hurricane Electric", "v4": ["74.82.42.42"], "v6": ["2001:470:20::2"],
                 "doh": None, "dot": None, "note": "IPv6-first", "verified": None},
                {"name": "Comodo Secure", "v4": ["8.26.56.26", "8.20.247.20"], "v6": [],
                 "doh": None, "dot": None, "note": "فیلتر بدافزار", "verified": None},
                {"name": "Yandex DNS", "v4": ["77.88.8.8", "77.88.8.1"],
                 "v6": ["2a02:6b8::feed:0ff", "2a02:6b8:0:1::feed:0ff"], "doh": None, "dot": None,
                 "note": "روسیه، نزدیک به ایران", "verified": None},
                {"name": "Yandex Safe", "v4": ["77.88.8.7", "77.88.8.88"], "v6": [],
                 "doh": None, "dot": None, "note": "نسخهٔ خانوادگی/امن", "verified": None},
                {"name": "DNS.WATCH", "v4": ["84.200.69.80", "84.200.70.40"],
                 "v6": ["2001:1608:10:25::1c04:b12f", "2001:1608:10:25::9249:d69b"], "doh": None,
                 "dot": "dns.watch", "note": "آلمان، بدون فیلتر", "verified": None},
                {"name": "CIRA Canadian Shield", "v4": ["149.112.121.10", "149.112.122.10"],
                 "v6": ["2620:10A:80BB::10", "2620:10A:80BC::10"], "doh": None, "dot": None,
                 "note": "کانادا", "verified": None},
                {"name": "Level3 / CenturyLink", "v4": ["4.2.2.1", "4.2.2.2"], "v6": [],
                 "doh": None, "dot": None, "note": "قدیمی ولی پرترافیک", "verified": None},
                {"name": "Freenom World", "v4": ["80.80.80.80", "81.81.81.81"], "v6": [],
                 "doh": None, "dot": None, "note": "هلند", "verified": None},
            ],
        },
        {
            "id": "iran", "label": "رزولورهای داخل ایران (برای کاربر ایرانی از همه نزدیک‌ترند)",
            "source": "اسناد عمومی سرویس‌دهنده‌ها + فهرست‌های جامعهٔ کاربری",
            "entries": [
                {"name": "رادار (Radar)", "v4": ["10.202.10.10", "10.202.10.11"], "v6": [],
                 "doh": "https://10.202.10.10/dns-query", "dot": None, "sni": "radar.game",
                 "note": "بازی‌محور؛ روی ایرانسل در تست‌های جامعه خوب بود", "verified": None},
                {"name": "الکترو (Electro)", "v4": ["78.157.42.100", "78.157.42.101"], "v6": [],
                 "doh": "https://37.152.182.112/dns-query", "dot": None, "sni": "electrotm.org",
                 "note": "DoH با IP و SNI مجزا", "verified": None},
                {"name": "شکن (Shecan)", "v4": ["178.22.122.100", "185.51.200.2"], "v6": [],
                 "doh": "https://178.22.122.100/dns-query", "dot": None, "sni": "shecan.ir",
                 "note": "قدیمی‌ترین؛ برای برخی بازی‌ها افت کرده", "verified": None},
                {"name": "بگزار (Begzar)", "v4": ["185.55.226.26", "185.55.225.25"], "v6": [],
                 "doh": None, "dot": None, "note": "", "verified": None},
                {"name": "۴۰۳ (403)", "v4": ["10.202.10.202", "10.202.10.102"], "v6": [],
                 "doh": "https://10.202.10.202/dns-query", "dot": None, "sni": "403.online",
                 "note": "رسمی", "verified": None},
                {"name": "Vanilla", "v4": ["10.139.177.21", "10.139.177.22"], "v6": [],
                 "doh": None, "dot": None, "note": "", "verified": None},
                {"name": "Zeus", "v4": ["37.32.5.60", "37.32.5.61"], "v6": [], "doh": None, "dot": None,
                 "note": "", "verified": None},
                {"name": "Shelter", "v4": ["94.103.125.157", "94.103.125.158"], "v6": [], "doh": None,
                 "dot": None, "note": "", "verified": None},
                {"name": "شاتل (Shatel)", "v4": ["85.15.1.14", "85.15.1.15"], "v6": [], "doh": None,
                 "dot": None, "note": "resolver اپراتور", "verified": None},
                {"name": "سرورایران (ServerIR)", "v4": ["194.104.158.48", "194.104.158.78"], "v6": [],
                 "doh": None, "dot": None, "note": "", "verified": None},
                {"name": "پارس‌آنلاین", "v4": ["46.224.1.221", "46.224.1.220"], "v6": [], "doh": None,
                 "dot": None, "note": "resolver اپراتور", "verified": None},
                {"name": "هاست‌ایران", "v4": ["172.29.2.100", "172.29.0.100"], "v6": [], "doh": None,
                 "dot": None, "note": "", "verified": None},
                {"name": "GreenTeam", "v4": ["81.218.119.11", "209.88.198.133"], "v6": [], "doh": None,
                 "dot": None, "note": "", "verified": None},
            ],
        },
    ],
}


def build_catalog(top_n: int = 40) -> dict:
    rows = list(csv.DictReader(open(RAW, encoding="utf-8", errors="replace")))
    countries: dict[str, dict] = {}
    for r in rows:
        ip = (r.get("ip_address") or "").strip()
        cc = (r.get("country_code") or "").strip()
        if not ip or not cc:
            continue
        c = countries.setdefault(cc, {"count": 0, "v4": 0, "v6": 0, "servers": []})
        c["count"] += 1
        is6 = ":" in ip
        c["v4" if not is6 else "v6"] += 1
        try:
            rel = float(r.get("reliability") or 0)
        except ValueError:
            rel = 0.0
        c["servers"].append({
            "ip": ip, "rel": round(rel, 3),
            "as": (r.get("as_org") or "").strip(), "asn": (r.get("as_number") or "").strip(),
            "city": (r.get("city") or "").strip(),
            "dnssec": (r.get("dnssec") or "").strip().lower() == "true",
            "sw": (r.get("version") or "").strip()[:40],
            "v": 6 if is6 else 4,
        })

    out_countries = {}
    for cc, c in countries.items():
        servers = sorted(c["servers"], key=lambda s: (-s["rel"], s["v"]))
        out_countries[cc] = {
            "name_fa": FA_NAMES.get(cc, cc),
            "count": c["count"], "v4": c["v4"], "v6": c["v6"],
            "top": servers[:top_n],
        }
    catalog = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source_url": SOURCE_URL,
        "source_note": SOURCE_NOTE,
        "totals": {
            "servers": len(rows), "countries": len(out_countries),
            "v4": sum(c["v4"] for c in countries.values()),
            "v6": sum(c["v6"] for c in countries.values()),
        },
        "warning": ("فهرست کاندید است، نه فهرست توصیه. رزولور عمومی باز می‌تواند "
                    "دست‌کاری‌شده یا ناپایدار باشد؛ تأیید فقط با سنجش اثر."),
        "countries": dict(sorted(out_countries.items(), key=lambda kv: -kv[1]["count"])),
    }
    return catalog


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", help="کد کشور برای نمایش سریع (مثل IR یا DE)")
    ap.add_argument("--top", type=int, default=40, help="تعداد سرور ذخیره‌شده برای هر کشور")
    args = ap.parse_args()

    if not os.path.exists(RAW):
        print(f"❌ فایل خام پیدا نشد: {RAW}\n   دانلود: curl -o {RAW} {SOURCE_URL}")
        return 2

    os.makedirs(DATA, exist_ok=True)
    cat = build_catalog(top_n=args.top)
    with open(os.path.join(DATA, "catalog.json"), "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False, separators=(",", ":"))

    curated = dict(CURATED)
    curated["generated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    curated["counts"] = {
        "groups": len(curated["groups"]),
        "entries": sum(len(g["entries"]) for g in curated["groups"]),
        "v4": sum(len(e.get("v4") or []) for g in curated["groups"] for e in g["entries"]),
        "v6": sum(len(e.get("v6") or []) for g in curated["groups"] for e in g["entries"]),
    }
    with open(os.path.join(DATA, "curated.json"), "w", encoding="utf-8") as f:
        json.dump(curated, f, ensure_ascii=False, indent=1)

    t = cat["totals"]
    print(f"✅ catalog.json : {t['servers']:,} سرور · {t['countries']} کشور · "
          f"IPv4 {t['v4']:,} · IPv6 {t['v6']}")
    print(f"✅ curated.json : {curated['counts']['entries']} سرویس · "
          f"IPv4 {curated['counts']['v4']} · IPv6 {curated['counts']['v6']}")

    if args.query:
        cc = args.query.upper()
        c = cat["countries"].get(cc)
        if not c:
            print(f"❌ کشور {cc} در کاتالوگ نیست")
            return 1
        print(f"\n▸ {cc} — {c['name_fa']} | {c['count']} سرور (v4={c['v4']}, v6={c['v6']})")
        for s in c["top"][:10]:
            print(f"   {s['ip']:40s} v{s['v']} rel={s['rel']:<5} dnssec={'✅' if s['dnssec'] else '—'} "
                  f"{s['as'][:40]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
