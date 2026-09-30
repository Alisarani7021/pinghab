#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorldScan · گزارش HTML فارسی (خودکفا)
=========================================================================
  python3 tools/worldreport.py [--scan data/dns_world/scan-*.json]

خروجی: data/dns_world/worldscan-report.html
"""

from __future__ import annotations

import argparse
import glob
import html
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data", "dns_world")


def _f(x, nd=2, dash="—"):
    try:
        return f"{float(x):,.{nd}f}"
    except (TypeError, ValueError):
        return dash


def load(path: str | None) -> tuple[dict, dict, dict]:
    scan_path = path or sorted(glob.glob(os.path.join(DATA, "scan-*.json")))[-1]
    scan = json.load(open(scan_path, encoding="utf-8"))
    cat = json.load(open(os.path.join(DATA, "catalog.json"), encoding="utf-8"))
    cur = json.load(open(os.path.join(DATA, "curated.json"), encoding="utf-8"))
    scan["_path"] = os.path.basename(scan_path)
    return scan, cat, cur


def build(scan: dict, cat: dict, cur: dict) -> str:
    res = scan["results"]
    live = sorted([r for r in res if r.get("ok") and r.get("rtt_p50") is not None],
                  key=lambda r: r["rtt_p50"])
    hij = [r for r in live if r.get("hijack")]
    div = [r for r in live if r.get("divergent")]
    imp = [r for r in live if r.get("impact")]
    totals = cat["totals"]
    args = scan.get("args", {})

    # --- خلاصهٔ سنجش اثر: بیشترین اختلاف بین رزولورها برای یک دامنه
    impact_summary = []
    if imp:
        doms = set()
        for r in imp:
            doms |= set(r["impact"].keys())
        for dom in sorted(doms):
            rows = [(r, r["impact"][dom]) for r in imp if dom in r["impact"]]
            vals = [x[1]["total_ms"] for x in rows if x[1].get("total_ms")]
            ips = {x[1]["ip"] for x in rows}
            if len(vals) > 1:
                impact_summary.append({
                    "domain": dom, "label": rows[0][1].get("label", ""),
                    "n": len(rows), "ips": len(ips),
                    "best": min(vals), "worst": max(vals),
                    "spread": round(max(vals) - min(vals), 1),
                    "rows": sorted(rows, key=lambda x: x[1]["total_ms"] or 9e9)[:8],
                })
        impact_summary.sort(key=lambda d: -d["spread"])

    parts = [f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>WorldScan · اسکنر DNS جهانی با سنجش اثر</title>
<style>
 :root {{ --ink:#0b1220; --mut:#64748b; --line:#e2e8f0; --bg:#f6f8fb; --acc:#1d4ed8; --ok:#15803d; --warn:#b45309; --bad:#b91c1c; }}
 * {{ box-sizing:border-box }}
 body {{ margin:0; background:var(--bg); color:var(--ink); font-family:"Vazirmatn","Segoe UI",Tahoma,system-ui,sans-serif; line-height:1.8 }}
 .wrap {{ max-width:1180px; margin:0 auto; padding:26px 18px 70px }}
 header {{ background:linear-gradient(135deg,#1d4ed8,#0f172a); color:#fff; border-radius:18px; padding:26px 24px;
           box-shadow:0 10px 30px rgba(29,78,216,.25) }}
 header h1 {{ margin:0 0 6px; font-size:25px }}
 header p {{ margin:0; opacity:.93; font-size:15px }}
 h2 {{ margin:32px 0 10px; font-size:19px; border-right:5px solid var(--acc); padding-right:11px }}
 h3 {{ margin:18px 0 6px; font-size:15px }}
 .card {{ background:#fff; border:1px solid var(--line); border-radius:14px; padding:16px 16px 12px; box-shadow:0 1px 3px rgba(16,24,40,.05) }}
 .grid {{ width:100%; border-collapse:collapse; font-size:13.5px; margin:8px 0 4px }}
 .grid th {{ background:#eef2f7; text-align:right; padding:8px 9px; border-bottom:2px solid var(--line); white-space:nowrap }}
 .grid td {{ padding:7px 9px; border-bottom:1px solid var(--line) }}
 .mono {{ direction:ltr; font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12.5px }}
 .kv {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:10px; margin:4px 0 10px }}
 .kv div {{ background:#f8fafc; border:1px solid var(--line); border-radius:10px; padding:10px 12px }}
 .kv span {{ display:block; color:var(--mut); font-size:12px }}
 .kv b {{ font-size:17px }}
 .big {{ background:#eff6ff; border:1px solid #bfdbfe; border-radius:12px; padding:12px 14px; margin:10px 0 }}
 .warn {{ background:#fffbeb; border:1px solid #fde68a; border-radius:12px; padding:12px 14px }}
 .bad {{ background:#fef2f2; border:1px solid #fecaca; border-radius:12px; padding:12px 14px }}
 .pill {{ display:inline-block; border-radius:999px; padding:1px 9px; font-size:11.5px; border:1px solid }}
 .p-ok {{ background:#ecfdf5; color:#065f46; border-color:#a7f3d0 }}
 .p-warn {{ background:#fffbeb; color:#92400e; border-color:#fde68a }}
 .p-bad {{ background:#fef2f2; color:#991b1b; border-color:#fecaca }}
 .p-info {{ background:#eff6ff; color:#1e40af; border-color:#bfdbfe }}
 code {{ background:#eef2f7; padding:2px 6px; border-radius:6px; direction:ltr; display:inline-block; font-size:12.5px }}
 ul {{ padding-right:20px }} li {{ margin:5px 0 }}
 footer {{ color:var(--mut); font-size:12.5px; margin-top:34px; text-align:center }}
</style></head><body><div class="wrap">
<header>
  <h1>WorldScan · اسکنر DNS جهانی <span class="pill p-info">با سنجش اثر</span></h1>
  <p>کاتالوگ {totals['servers']:,} رزولور از {totals['countries']} کشور، سنجش فعال، تشخیص سانسور،
     و متریک جدید: «کدام آی‌پی را می‌دهد و تأخیر تا همان آی‌پی چقدر است».</p>
  <p style="opacity:.85;font-size:13px;margin-top:8px">اجرا: {scan.get('generated_at','')} ·
     {scan.get('responded',0)} پاسخ از {scan.get('candidates',0)} کاندید ·
     {scan.get('duration_s','?')} ثانیه · vantage: ماشین ابری (نه ایران)</p>
</header>

<h2>۱) چرا «سنجش اثر»؟</h2>
<div class="card">
<p>حقیقت فیزیکی: <b>هیچ DNS ای پینگ فیبر را کم نمی‌کند.</b> اما سه چیز را واقعاً تغییر می‌دهد:</p>
<ul>
 <li><b>کدام PoP را می‌گیری.</b> رزولورهای مختلف برای یک دامنهٔ بازی آی‌پی متفاوتی برمی‌گردانند.
     در همین اسکن، <code>{impact_summary[0]['domain'] if impact_summary else '—'}</code> بین
     رزولورها {impact_summary[0]['ips'] if impact_summary else '—'} آی‌پی متفاوت داشت و
     اختلاف تأخیر تا مقصد <b>{impact_summary[0]['spread'] if impact_summary else '—'} میلی‌ثانیه</b> بود —
     این عدد را DNS به‌وجود می‌آورد، نه فیبر.</li>
 <li><b>زمان خودِ resolution.</b> چند میلی‌ثانیه تا صدها میلی‌ثانیه (خصوصاً در مسیر سرد).</li>
 <li><b>سانسور/دست‌کاری.</b> اگر پاسخ <code>NXDOMAIN</code>/<code>REFUSED</code> یا آی‌پی
     سینک‌هول باشد، بازی همان‌جا تمام می‌شود.</li>
</ul>
<p>ابزارهای موجود (<code>dnseval</code>، <code>dnsping</code>، <code>dns-benchmark-tool</code>)
فقط مورد دوم را می‌سنجند. این ابزار هر سه را می‌سنجد و رزولور را بر اساس <b>مجموع
(resolution + تأخیر تا آی‌پیِ دریافتی)</b> رتبه می‌دهد.</p>
</div>

<h2>۲) خلاصهٔ اجرا</h2>
<div class="card">
<div class="kv">
  <div><span>کاندید اسکن‌شده</span><b>{scan.get('candidates',0)}</b></div>
  <div><span>پاسخ‌داده</span><b>{scan.get('responded',0)}</b></div>
  <div><span>PoP متفاوت (اطلاعاتی)</span><b>{len(div)}</b></div>
  <div><span>رد صریح / سینک‌هول</span><b>{len(hij)}</b></div>
  <div><span>کاتالوگ جهانی</span><b>{totals['countries']} کشور</b></div>
  <div><span>IPv6 در کاتالوگ</span><b>{totals['v6']}</b></div>
</div>
<p class="note" style="color:var(--mut);font-size:12.5px">
محدودیت‌های همین vantage: {html.escape(str(args.get('_vantage_note','IPv6 این ماشین مسیر ندارد؛ رزولورهای داخل ایران از بیرون قابل‌سنجش نیستند (آی‌پی‌های 10.x فقط داخل شبکهٔ اپراتور زنده‌اند).')))}</p>
</div>

<h2>۳) سریع‌ترین رزولورها (مسیر گرم، {args.get('count','?')} کوئری)</h2>
<div class="card"><table class="grid">
<tr><th>#</th><th>آی‌پی</th><th>منبع</th><th>کشور</th><th>RTT میانگین</th><th>p95</th>
    <th>پرش</th><th>تلفات</th><th>EDNS0</th><th>DNSSEC</th><th>وضعیت</th></tr>"""]
    for i, r in enumerate(live[:45], 1):
        flags = []
        if r.get("hijack"):
            flags.append('<span class="pill p-bad">رد صریح</span>')
        if r.get("divergent"):
            flags.append('<span class="pill p-info">PoP متفاوت</span>')
        if (r.get("loss") or 0) > 0.2:
            flags.append('<span class="pill p-warn">تلفات بالا</span>')
        parts.append(
            f"<tr><td>{i}</td><td class='mono'>{html.escape(r['ip'])}</td>"
            f"<td>{'منتخب' if r.get('source') == 'curated' else 'کاتالوگ'}</td>"
            f"<td>{html.escape(r.get('cc') or '')}</td><td>{_f(r.get('rtt_p50'))}</td>"
            f"<td>{_f(r.get('rtt_p95'))}</td><td>{_f(r.get('jitter'))}</td>"
            f"<td>{_f((r.get('loss') or 0) * 100, 0)}٪</td>"
            f"<td>{'✅' if r.get('edns') else '—'}</td><td>{'✅' if r.get('dnssec_ad') else '—'}</td>"
            f"<td>{' '.join(flags) or '<span class=\"pill p-ok\">سالم</span>'}</td></tr>")
    parts.append("</table><p style='color:var(--mut);font-size:12.5px'>"
                 "«پرش» = تغییر متوالی RTT (میانگین |Δ|). برای بازی، پرش مهم‌تر از میانگین است: "
                 "پینگ ۶۰ms ثابت از پینگ ۴۰ms پرنوسان بهتر بازی می‌شود.</p></div>")

    if impact_summary:
        parts.append("<h2>۴) سنجش اثر — قلب این ابزار</h2><div class='card'>"
                     "<p>برای هر دامنه: هر رزولور چه آی‌پی می‌دهد، و از <b>همین ماشین</b> تا آن آی‌پی "
                     "چند میلی‌ثانیه است. مجموع = زمان resolution + تأخیر تا مقصد.</p>")
        for d in impact_summary[:6]:
            parts.append(f"<h3>{html.escape(d['domain'])} <span class='pill p-info'>{html.escape(d['label'])}</span></h3>"
                         f"<div class='big'>اختلاف بین بهترین و بدترین رزولور: <b>{_f(d['spread'],1)} میلی‌ثانیه</b> "
                         f"({d['ips']} آی‌پی متفاوت از {d['n']} رزولور)</div>"
                         "<table class='grid'><tr><th>رزولور</th><th>آی‌پیِ پاسخ</th><th>زمان DNS</th>"
                         "<th>تا مقصد</th><th>مجموع</th></tr>")
            for r, im in d["rows"]:
                parts.append(f"<tr><td class='mono'>{html.escape(r['ip'])}</td>"
                             f"<td class='mono'>{html.escape(str(im['ip']))}</td>"
                             f"<td>{_f(im['dns_ms'],1)}</td><td>{_f(im['conn_ms'],2)}</td>"
                             f"<td><b>{_f(im['total_ms'],1)}</b></td></tr>")
            parts.append("</table>")
        parts.append("</div>")

    parts.append("<h2>۵) رزولورهای ایران</h2><div class='card'>"
                 "<div class='warn'><b>نکتهٔ حیاتی:</b> رزولورهای رادار و ۴۰۳ روی بازهٔ "
                 "<code>10.0.0.0/8</code> هستند — یعنی <b>فقط داخل شبکهٔ اپراتور</b> زنده‌اند و از "
                 "بیرون (و از این ماشین ابری) قابل‌سنجش نیستند. رزولورهای شکن/الکترو/بگزار هم از "
                 "خارج ایران پاسخ نمی‌دهند. پس برای این‌ها باید همین اسکنر را <b>از خود ایران</b> اجرا کرد؛ "
                 "اعداد زیر «کاندید»‌اند نه «تأییدشده».</div>"
                 "<table class='grid'><tr><th>سرویس</th><th>IPv4</th><th>IPv6</th><th>DoH</th><th>یادداشت</th></tr>")
    for e in [e for g in cur["groups"] if g["id"] == "iran" for e in g["entries"]]:
        parts.append(f"<tr><td>{html.escape(e['name'])}</td>"
                     f"<td class='mono'>{html.escape(', '.join(e.get('v4') or []))}</td>"
                     f"<td class='mono'>{html.escape(', '.join(e.get('v6') or [])) or '—'}</td>"
                     f"<td class='mono' style='font-size:11.5px'>{html.escape(str(e.get('doh') or '—'))}</td>"
                     f"<td>{html.escape(e.get('note') or '')}</td></tr>")
    parts.append("</table>")
    ir_cat = cat["countries"].get("IR", {})
    if ir_cat:
        parts.append(f"<h3>رزولورهای ایرانی که در اسکن اینترنتی پیدا شده‌اند ({ir_cat['count']} مورد)</h3>"
                     "<table class='grid'><tr><th>آی‌پی</th><th>سازمان</th><th>اعتبار</th><th>DNSSEC</th></tr>")
        for s in ir_cat["top"][:12]:
            parts.append(f"<tr><td class='mono'>{html.escape(s['ip'])}</td><td>{html.escape(s['as'][:46])}</td>"
                         f"<td>{_f(s['rel'],2)}</td><td>{'✅' if s['dnssec'] else '—'}</td></tr>")
        parts.append("</table>")
    parts.append("</div>")

    if hij:
        parts.append("<h2>۶) رد صریح (نیازمند بازرسی دستی)</h2><div class='bad'>"
                     "<p>این رزولورها برای دامنه‌های مرجع، <code>NXDOMAIN</code>/<code>REFUSED</code> "
                     "دادند (با تلاش دوباره). <b>دو علت ممکن:</b> سیاست مسدودسازی، یا ACL/محدودیت نرخ "
                     "روی vantage ما. پس «سانسور» قطعی نیست؛ فهرست برای بازرسی است.</p><ul>")
        for r in hij[:12]:
            parts.append(f"<li><span class='mono'>{html.escape(r['ip'])}</span> — "
                         f"{html.escape(' | '.join(r.get('hijack_detail') or [])[:160])}</li>")
        parts.append("</ul></div>")

    parts.append(f"""<h2>۷) روش، اخلاق و محدودیت‌ها</h2><div class="card">
<ul>
 <li><b>روش:</b> پروب واقعی UDP/53 با EDNS0 (payload 1232)، {args.get('count','?')} کوئری برای هر رزولور،
     نرخ محدودشده ({args.get('rate','?')} کوئری/ثانیه) تا باری روی سرویس‌دهنده تحمیل نشود.</li>
 <li><b>مسیر گرم/سرد:</b> رتبه‌بندی روی مسیر گرم است (چیزی که کاربر ۹۰٪ مواقع می‌بیند)؛
     مسیر سرد (NXDOMAIN با بازگشت کامل) جدا اندازه‌گیری می‌شود.</li>
 <li><b>کاتالوگ:</b> منبع <code>public-dns.info</code> — همین لحظه {totals['servers']:,} رزولور از
     {totals['countries']} کشور. این‌ها «کاندید»اند، نه توصیه. رزولور عمومی باز می‌تواند
     لاگ‌بردار، ناپایدار یا دست‌کاری‌شده باشد.</li>
 <li><b>vantage:</b> این اجرا از یک ماشین ابری بیرون ایران است؛ اعداد مطلق برای کاربر ایرانی
     قابل‌ترجمه نیستند. اما <b>روش و رتبه‌بندی</b> همان است که از داخل ایران اجرا می‌شود.</li>
 <li><b>آنچه ادعا نمی‌شود:</b> هیچ رزولوری «پینگ بازی را N میلی‌ثانیه کم می‌کند» — فقط می‌توان
     گفت کدام رزولور از این مسیر سریع‌تر جواب می‌دهد و کدام PoP را می‌دهد.</li>
</ul>
<p class="note">تکرار: <code>python3 tools/worldscan.py --curated --countries IR --limit-per-country 24 --v6</code></p>
<p class="note">فایل خام: <code>{html.escape(scan.get('_path',''))}</code> · CSV کنارش در
   <code>data/dns_world/</code></p>
</div>

<footer>WorldScan · بخشی از «پینگ‌هاب» · دادهٔ کاتالوگ: public-dns.info ·
گزارش خودکفا، بدون منبع بیرونی</footer>
</div></body></html>""")
    return "".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan")
    args = ap.parse_args()
    files = sorted(glob.glob(os.path.join(DATA, "scan-*.json")))
    if not files and not args.scan:
        print("❌ هیچ scan-*.json پیدا نشد. اول worldscan.py را اجرا کنید.")
        return 2
    scan, cat, cur = load(args.scan)
    out = os.path.join(DATA, "worldscan-report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(scan, cat, cur))
    print(f"✅ گزارش ساخته شد: {out} ({os.path.getsize(out)//1024} KB) از {scan['_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
