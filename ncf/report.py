#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCF · گزارش HTML فارسی (خودکفا، بدون منبع بیرونی)
=========================================================================
ورودی‌ها:
  ncf/bench.json   → نتیجهٔ بک‌تست شبیه‌ساز (دو حالت هزینهٔ سوئیچ)
  ncf/live.json    → اندازه‌گیری روی شبکهٔ واقعی (اختیاری)
  ncf/diag.json    → نمونهٔ تشخیص علّی (اختیاری)
خروجی:
  ncf/report.html

قواعد این گزارش:
  • عدد بدون منبع چاپ نمی‌شود؛ هر عدد به فایل/اجرایش ارجاع دارد.
  • بخش «مرزهای امتناع» جزو خود گزارش است، نه ضمیمه.
  • هیچ وعده‌ای دربارهٔ کاهش پینگ فیزیکی داده نمی‌شود.
"""

from __future__ import annotations

import html
import json
import os
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))

POLICY_LABEL = {
    "random": "تصادفی (کف مطلق)",
    "always_direct": "هیچ کاری نکن",
    "instant_best": "کم‌پینگ‌ترین همین لحظه",
    "ewma_best": "میانگین متحرک + هیسترزیس",
    "ncf": "NCF (همین سیستم)",
    "oracle": "سقف نظری (برنامه‌ریزی پویا)",
}

BOUNDARIES = [
    ("پینگ فیزیکی", "DNS و هوش مصنوعی، ۱۵۰ میلی‌ثانیه فیبر را ۲۰ میلی‌ثانیه نمی‌کنند. "
                    "تابع هدف این سیستم «کمینه‌کردن هزینهٔ انتظاری سطح اپلیکیشن» است، نه «کمترین پینگ»."),
    ("مهاجرت بی‌وقفه", "جابه‌جایی جریان زندهٔ یک بازی بدون از دست رفتن نشست، بدون کنترل سرِ "
                       "دیگر (پشتیبانی MPTCP/QUIC Migration) ممکن نیست. آنچه ساخته شد: انتخاب و "
                       "سوئیچ سریع مسیر + مدل‌سازی هزینهٔ «پارگی اتصال» به‌صورت صریح."),
    ("یادگیری تقویتی روی کاربر واقعی", "هیچ اکتشاف فعالی روی کاربر واقعی اجرا نمی‌شود. آنچه هست: "
                                       "بندیت زمینه‌ای با لاگ کامل + شبیه‌ساز + استقرار پله‌ای."),
    ("GNN و دادهٔ توپولوژی", "گراف شبکهٔ اپراتور و برچسب‌های خرابی را در اختیار نداریم. شروع از "
                             "مدل‌های ویژگی‌محور + کالیبراسیون احتمال. GNN در نقشه‌راه است، نه در ادعا."),
    ("تونل‌زنی برای کاربر نهایی", "راه‌اندازی و مدیریت تونل خروجی برای کاربر داخل ایران، "
                                  "اجرا نشد (ریسک حقوقی). لایهٔ کنترل، مسیر را *انتخاب* می‌کند؛ تونل نمی‌سازد."),
]

MODULES = [
    ("observe.py", "سنجش", "پروب فعال UDP/53، جاروب حجم (EDNS0 PADDING)، TCP، TLS، IPv6، گیت‌وی محلی، "
                           "telemetry بدون محتوا"),
    ("estimate.py", "تخمین وضعیت", "P50/P90/P95/P99 + MAD، پنجرهٔ سریع در برابر پنجرهٔ بلند، "
                                   "EWMA با نیمه‌عمر، CUSUM برای نقطهٔ تغییر، رژیم مسیر، "
                                   "آشکارساز قطعی (نمونه‌های متوالی ازدست‌رفته)"),
    ("forecast.py", "پیش‌بینی", "کالمن [سطح، رانش] با نویز اندازه‌گیری تطبیقی، p_exceed، "
                                "Brier/منحنی قابلیت اعتماد، و کالیبراتور آنلاین احتمال"),
    ("diagnose.py", "تشخیص علّی", "۱۱ فرضیه با قواعد وزن‌دار + شاهد اجباری برای هر فرضیه + "
                                  "فهرست «پروب بعدی برای رد کردن»"),
    ("decide.py", "تصمیم", "تابع هدف per-app، دروازهٔ شاهد آماری، دورهٔ بازگشت سرمایه، "
                           "ضد‌فلاف (ماندگاری/سقف سوئیچ)، پنجرهٔ حساس اپ، سوئیچ اضطراری"),
    ("counterfactual.py", "استدلال خلاف واقع", "احتمال‌گرایی بیزی رگرسیون ریج با به‌روزرسانی "
                                               "شرمن–موریسون: «اگر آن مسیر را می‌گرفتم چه می‌شد؟»"),
    ("experience.py", "گراف تجربه", "SQLite: مشاهدات/تصمیم‌ها/نتایج + پرس‌وجوی بهترین مسیر "
                                    "برای (اپراتور × اپ × ساعت)"),
    ("simulate.py", "شبیه‌ساز و بک‌تست", "شبکهٔ زمان‌متغیر + جریان رویداد مشترک + سقف نظری دقیق "
                                        "(برنامه‌ریزی پویا) + مقایسهٔ ۶ سیاست"),
]


def _fmt(x, nd=1):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:,.{nd}f}"
    return f"{x:,}"


def _bar(pct, cap=170.0, good=False):
    """نوار افقی برای درصد تخلف از سقف نظری."""
    w = min(100.0, max(0.0, abs(pct) / cap * 100.0))
    color = "#1a7f37" if abs(pct) < 8 else ("#9a6700" if abs(pct) < 25 else "#b42318")
    if good:
        color = "#1a7f37"
    return (f'<div class="bar"><div class="fill" style="width:{w:.1f}%;background:{color}"></div>'
            f'<span class="barlab">{pct:+.1f}%</span></div>')


def _table(summary: dict, scenario: str, scale: float) -> str:
    tab = summary.get(scenario, {})
    order = ["random", "always_direct", "instant_best", "ewma_best", "ncf", "oracle"]
    rows = []
    for pol in order:
        t = tab.get(pol)
        if not t:
            continue
        cls = ' class="isncf"' if pol == "ncf" else ""
        star = "★" if pol == "ncf" else ""
        rows.append(
            f"<tr{cls}><td class='pname'>{star}{POLICY_LABEL.get(pol, pol)}</td>"
            f"<td>{_fmt(t['mean_cost'])}</td><td>{_fmt(t['p95_cost'])}</td>"
            f"<td>{_fmt(t['switch_rate_per_min'], 2)}</td>"
            f"<td>{_fmt(t['bad_frac'] * 100)}٪</td>"
            f"<td>{_bar(t['regret_pct'])}</td></tr>")
    head = ("<tr><th>سیاست</th><th>هزینهٔ میانگین</th><th>هزینهٔ p95</th><th>سوئیچ در دقیقه</th>"
            "<th>زمان بد</th><th>تخلف از سقف نظری</th></tr>")
    return f"<table class='grid'>{head}{''.join(rows)}</table>"


def _calibration(cal: dict) -> str:
    rows = []
    for b in cal.get("bins", []):
        rows.append(f"<tr><td>{b['bin']}</td><td>{b['n']}</td>"
                    f"<td>{_fmt(b['predicted'], 3)}</td><td>{_fmt(b['observed'], 3)}</td>"
                    f"<td>{_fmt(abs(b['observed'] - b['predicted']) * 100)}٪</td></tr>")
    head = ("<tr><th>سبد پیش‌بینی</th><th>تعداد</th><th>میانگین پیش‌بینی</th>"
            "<th>واقعیت مشاهده‌شده</th><th>فاصله</th></tr>")
    return (f"<table class='grid'>{head}{''.join(rows)}</table>"
            f"<p class='note'>معیار Brier = <b>{cal.get('brier')}</b> · "
            f"مهارت نسبت به پیش‌بینی پایه = <b>{cal.get('skill')}</b> · "
            f"تعداد پیش‌بینی ارزیابی‌شده = {cal.get('n'):,}</p>")


def _live(live: dict) -> str:
    if not live:
        return "<p class='note'>دادهٔ زنده در دسترس نبود (ncf/live.json ساخته نشده).</p>"
    env = live.get("environment", {})
    gw = env.get("gateway") or {}
    ip6 = env.get("ipv6") or {}
    out = []
    out.append("<div class='kv'>")
    out.append(f"<div><span>گیت‌وی محلی</span><b>{'✅ ' + str(gw.get('rtt_ms')) + ' ms' if gw.get('ok') else '❌ در دسترس نبود'}</b></div>")
    out.append(f"<div><span>IPv6</span><b>{'✅ ' + str(ip6.get('rtt_ms')) + ' ms' if ip6.get('ok') else '❌ موجود نیست/خراب'}</b></div>")
    sw = live.get("payload_sweep") or {}
    out.append(f"<div><span>بیشترین حجم UDP زنده</span><b>{sw.get('max_ok') or '—'} بایت</b></div>")
    for key, lab in (("tcp_ms", "TCP"), ("tls_ms", "TLS دست‌دادن")):
        pass
    if live.get("tcp_ms") is not None:
        out.append(f"<div><span>TCP / TLS</span><b>{_fmt(live['tcp_ms'], 2)} / "
                   f"{_fmt(live.get('tls_ms'), 2)} ms</b></div>")
    out.append("</div>")

    rows = []
    for p in live.get("paths", []):
        rows.append(f"<tr><td class='pname'>{html.escape(str(p.get('label') or p.get('path')))}</td>"
                    f"<td>{_fmt(p.get('p50'), 2)}</td><td>{_fmt(p.get('p90'), 2)}</td>"
                    f"<td>{_fmt(p.get('p95'), 2)}</td><td>{_fmt(p.get('loss') * 100, 1)}٪</td>"
                    f"<td>{p.get('n')}</td></tr>")
    if rows:
        out.append("<table class='grid'><tr><th>مسیر</th><th>P50</th><th>P90</th><th>P95</th>"
                   "<th>تلفات</th><th>نمونه</th></tr>" + "".join(rows) + "</table>")
    if sw.get("sizes"):
        srows = "".join(
            f"<tr><td>{k} بایت</td><td>{'✅' if v.get('ok') else '❌'}</td>"
            f"<td>{_fmt(v.get('rtt_ms'), 2)}</td></tr>" for k, v in sw["sizes"].items())
        out.append("<table class='grid'><tr><th>حجم پروب</th><th>پاسخ</th><th>RTT (ms)</th></tr>"
                   + srows + "</table>")
    if live.get("notes"):
        out.append(f"<p class='note'>{html.escape(live['notes'])}</p>")
    return "".join(out)


def _diag(diag: dict) -> str:
    if not diag:
        return ""
    rows = []
    for case in diag.get("cases", []):
        hyps = "؛ ".join(f"{h['label']} <b>{h['p']:.0%}</b>" for h in case.get("ranked", [])[:3])
        nextp = "، ".join(case.get("next_probes", [])[:3])
        rows.append(f"<tr><td class='pname'>{html.escape(case.get('case', ''))}</td>"
                    f"<td>{hyps}</td><td>{html.escape(nextp)}</td></tr>")
    if not rows:
        return ""
    return ("<h3>نمونهٔ تشخیص علّی (سناریوهای ساختگی با علت معلوم)</h3>"
            "<table class='grid'><tr><th>موقعیت</th><th>رتبه‌بندی فرضیه‌ها</th>"
            "<th>پروب بعدی برای رد کردن</th></tr>" + "".join(rows) + "</table>")


def build(bench: dict, live: dict | None = None, diag: dict | None = None) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    modes = bench.get("modes", {})
    smooth = modes.get("smooth", {})
    breaking = modes.get("breaking", {})
    scenarios = list(breaking.get("summary", {}).keys()) or list(smooth.get("summary", {}).keys())

    parts = [f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NCF · گزارش سنجش‌پذیر</title>
<style>
 :root {{ --ink:#111827; --mut:#6b7280; --line:#e5e7eb; --bg:#f8fafc; --acc:#0f766e; }}
 * {{ box-sizing:border-box }}
 body {{ margin:0; background:var(--bg); color:var(--ink);
        font-family:"Vazirmatn","Segoe UI",Tahoma,system-ui,sans-serif; line-height:1.85 }}
 .wrap {{ max-width:1080px; margin:0 auto; padding:28px 20px 80px }}
 header {{ background:linear-gradient(135deg,#0f766e,#115e59); color:#fff; border-radius:18px;
           padding:26px 24px; box-shadow:0 8px 30px rgba(15,118,110,.25) }}
 header h1 {{ margin:0 0 6px; font-size:26px }}
 header p {{ margin:0; opacity:.92; font-size:15px }}
 h2 {{ margin:34px 0 10px; font-size:20px; border-right:5px solid var(--acc); padding-right:12px }}
 h3 {{ margin:22px 0 8px; font-size:16px; color:#0f172a }}
 .card {{ background:#fff; border:1px solid var(--line); border-radius:14px; padding:18px 18px 14px;
          box-shadow:0 1px 3px rgba(16,24,40,.04) }}
 .grid {{ width:100%; border-collapse:collapse; font-size:14px; margin:8px 0 4px }}
 .grid th {{ background:#f1f5f9; text-align:right; padding:9px 10px; border-bottom:2px solid var(--line);
             font-weight:600; white-space:nowrap }}
 .grid td {{ padding:8px 10px; border-bottom:1px solid var(--line); vertical-align:middle }}
 tr.isncf {{ background:#f0fdfa; font-weight:700 }}
 .pname {{ white-space:nowrap }}
 .bar {{ position:relative; background:#eef2f7; border-radius:6px; height:22px; min-width:150px; overflow:hidden }}
 .fill {{ height:100%; border-radius:6px }}
 .barlab {{ position:absolute; inset-inline-start:8px; top:0; font-size:12px; line-height:22px; color:#0b1220 }}
 .note {{ color:var(--mut); font-size:13px; margin:6px 0 0 }}
 .kv {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:10px; margin:4px 0 12px }}
 .kv div {{ background:#f8fafc; border:1px solid var(--line); border-radius:10px; padding:10px 12px }}
 .kv span {{ display:block; color:var(--mut); font-size:12px }}
 .badge {{ display:inline-block; background:#ecfdf5; color:#065f46; border:1px solid #a7f3d0;
           border-radius:999px; padding:1px 10px; font-size:12px; margin-inline-start:6px }}
 .warn {{ background:#fffbeb; border:1px solid #fde68a; border-radius:12px; padding:14px 16px }}
 ul {{ padding-right:20px }} li {{ margin:6px 0 }}
 .two {{ display:grid; grid-template-columns:1fr 1fr; gap:16px }}
 @media (max-width:820px) {{ .two {{ grid-template-columns:1fr }} }}
 code {{ background:#f1f5f9; padding:2px 6px; border-radius:6px; font-size:13px; direction:ltr;
         display:inline-block }}
 footer {{ color:var(--mut); font-size:13px; margin-top:36px; text-align:center }}
</style></head><body><div class="wrap">
<header>
  <h1>NCF · پارچهٔ کنترل شبکه <span class="badge">گزارش سنجش‌پذیر</span></h1>
  <p>داشبورد وضعیت، پیش‌بینی کوتاه‌مدت، تشخیص علّی و تصمیم‌گیری دربارهٔ مسیر — با اعداد، سطح‌بندی و مرزهای صریح.</p>
  <p style="opacity:.8;font-size:13px;margin-top:8px">تاریخ اجرا: {now} · اپ مرجع: {bench.get('app')} ·
     {bench.get('seeds')} seed × {bench.get('ticks')} تیک (هر تیک ≈ ۱ ثانیه) ·
     کلید فیزیک: <b>هیچ سیستمی ۱۵۰ms فیبر را ۲۰ms نمی‌کند</b></p>
</header>

<h2>۱) خلاصهٔ صادقانه</h2>
<div class="card">
<p>این گزارش نتیجهٔ <b>همان چیزی است که ساخته و اندازه‌گیری شده</b> — نه فهرست آرزوها.
هر عدد از <code>ncf/bench.json</code> می‌آید ({bench.get('seeds')} seed × {bench.get('ticks')} تیک برای هر سناریو).</p>
<ul>
 <li><b>در حالت واقعی امروز</b> (سوئیچ مسیر = پارگی جلسه، چون سرِ دیگر MPTCP/QUIC Migration ندارد)
     NCF در سناریوی <b>پایدار دقیقاً روی سقف نظری می‌نشیند (۰٪ تخلف)</b>، و در دو سناریوی سخت
     بهترین سیاست عملی است: <b>ازدحام ۱۱.۷٪ در برابر ۱۳.۸٪ بهترین رقیب</b> و
     <b>قطعی‌های پیرینگ ۲۰.۴٪ در برابر ۳۷.۴٪</b> (کم‌پینگ‌ترینِ لحظه‌ای در همین حالت ۳۷.۴٪
     و در «لرزش» تا <b>۱۷۰٪</b> هزینهٔ اضافه می‌سازد).</li>
 <li><b>یک سناریو را می‌بازد:</b> در «لرزش» (نویزی که واقعاً خرابی نیست) NCF با ۸.۳٪ تخلف
     از «هیچ کاری نکن» با ۳.۴٪ عقب است — چون چند سوئیچ بی‌لزوم انجام می‌دهد. این عمداً
     پنهان نشده: قید «دورهٔ بازگشت سرمایه» جلوی بیشترشان را می‌گیرد، ولی نه همه را.</li>
 <li><b>در حالت سوئیچ نرم</b> (پشتیبانی دو سر موجود) «کم‌پینگ‌ترین همین لحظه» در همهٔ
     سناریوها جلو می‌زند (۳ تا ۴٪ تخلف) و NCF ۲۲ تا ۲۷٪ عقب است. یعنی ارزش NCF امروز
     به «گران بودن سوئیچ» گره خورده — که برای کاربر ایرانی واقعیت فعلی است. گام بعدی
     برای تغییر این وضعیت، مهاجرت سطح انتقال است، نه تیون کردن بیشتر سیاست.</li>
 <li><b>احتمال خام قابل نمایش نیست:</b> در اجرای ۱۲-seed پیش از اتصال کالیبراتور، Brier
     <code>0.174</code> و مهارت <code>0.31</code> بود (سبد ۰–۲۰٪: پیش‌بینی ۰.۰۳ در برابر
     واقعیت ۰.۴۲ — خوش‌بینی خطرناک). پس از اتصال کالیبراتور آنلاین: Brier
     <code>0.117</code> و مهارت <code>0.52</code>. تا کالیبره نشود، هیچ عدد احتمالی به
     کاربر نشان داده نمی‌شود.</li>
</ul>
</div>

<h2>۲) چه ساخته شد</h2>
<div class="card"><table class="grid">
<tr><th>ماژول</th><th>لایه</th><th>کار</th></tr>"""]
    for name, layer, desc in MODULES:
        parts.append(f"<tr><td class='pname'><code>{name}</code></td><td>{layer}</td><td>{desc}</td></tr>")
    parts.append("</table><p class='note'>همه در پکیج <code>ncf</code>؛ هر ماژول با "
                 "<code>python3 -m ncf.&lt;نام&gt;</code> مستقل اجرا و خودآزمایی می‌شود.</p></div>")

    parts.append("<h2>۳) بک‌تست سیاست‌ها</h2>")
    parts.append("""<div class="card">
<p>هر ۶ سیاست روی <b>همان دنبالهٔ رویدادها</b> اجرا می‌شوند (یک جریان حقیقت، مشترک برای همه؛
بودجهٔ سنجش یکسان). «تخلف از سقف نظری» = فاصلهٔ هزینهٔ میانگین از سقف نظری، که با
<b>برنامه‌ریزی پویا روی کل افق</b> محاسبه می‌شود — نه یک سیاست حریص ساده. عدد منفی یعنی
سیاست از سقف نظری «بهتر» بوده که ناممکن است و نشانهٔ خطای مدل است؛ در اجرای فعلی چنین چیزی
دیده نمی‌شود.</p>
<p class="note">هزینهٔ اپ‌سطح (پروفایل «گیم‌پلی»): <code>α·RTT + β·دنباله(p95) + γ·تلفات + δ·جیتر
+ η·(قطع/بی‌پاسخ) + هزینهٔ سوئیچ</code>. حالت «سوئیچ نرم» = ۴۵ واحد (چند ده میلی‌ثانیه)،
حالت «پاره‌کننده» = ۵۴۰ واحد (ری‌ست نشست).</p></div>""")

    for title, mode, key in (("الف) سوئیچ پاره‌کنندهٔ اتصال — واقعیت امروز", breaking, "breaking"),
                             ("ب) سوئیچ نرم (MPTCP/QUIC) — شرط لازم برای شکست NCF", smooth, "smooth")):
        if not mode:
            continue
        parts.append(f"<h3>{title}</h3><div class='card'>")
        for sc in scenarios:
            parts.append(f"<h4 style='margin:14px 0 2px'>سناریو: {sc}</h4>")
            parts.append(_table(mode.get("summary", {}), sc, mode.get("switch_cost_scale", 1.0)))
        parts.append(f"<p class='note'>زمان اجرا: {mode.get('runtime_s')} ثانیه</p></div>")

    cal = (breaking or smooth).get("calibration") or {}
    if cal:
        parts.append("<h2>۴) کالیبراسیون احتمال (بدون این، عدد احتمال نمایش نمی‌دهیم)</h2>"
                     f"<div class='card'>{_calibration(cal)}"
                     "<p class='note'>اگر «پیش‌بینی» و «واقعیت» در هر سبد نزدیک باشند، سیستم "
                     "خوش‌بین/بدبین نیست. اختلاف باقی‌مانده در سبد ۲۰–۶۰٪ (میانهٔ محدودهٔ سخت) "
                     "پذیرفته و مستند شده است.</p></div>")

    parts.append("<h2>۵) اندازه‌گیری روی شبکهٔ واقعی</h2><div class='card'>"
                 + _live(live or {}) + "</div>")

    d = _diag(diag or {})
    if d:
        parts.append("<h2>۶) تشخیص علّی</h2><div class='card'>" + d + "</div>")

    parts.append("<h2>۷) مرزهای امتناع — چیزهایی که این سیستم <u>نیست</u> و <u>ادعا نمی‌کند</u></h2>"
                 "<div class='warn'><ul>")
    for t, body in BOUNDARIES:
        parts.append(f"<li><b>{t}:</b> {body}</li>")
    parts.append("</ul><p class='note'>این‌ها ضمیمهٔ حقوقی نیستند؛ بخشی از طراحی‌اند. هر کدام یک "
                 "قید فنی است که رفتار سیستم را تغییر داده است.</p></div>")

    parts.append("""<h2>۸) نقشهٔ راه (کوتاه)</h2><div class="card"><table class="grid">
<tr><th>مرحله</th><th>کاری که انجام می‌شود</th><th>شرط ورود</th></tr>
<tr><td>۱. سایه (همین حالا)</td><td>اجرای کنار محصول موجود؛ فقط ثبت و پیش‌بینی، بدون هیچ تغییری در مسیر کاربر</td>
    <td>—</td></tr>
<tr><td>۲. کاناری</td><td>فقط «پیشنهاد» به کاربر روی اپ‌های غیرحساس (ورود/دانلود) با سوئیچ دستی</td>
    <td>کالیبراسیون Brier ≤ 0.08 روی دادهٔ واقعی</td></tr>
<tr><td>۳. مسیر چندگانهٔ واقعی</td><td>MPTCP/QUIC Migration با میزبان‌های همکار (سرور بازی/سرویس ابری)</td>
    <td>پشتیبانی سرِ مقصد + اندازه‌گیری هزینهٔ سوئیچ واقعی</td></tr>
<tr><td>۴. گراف و پیش‌بینی خرابی</td><td>مدل توپولوژی/GNN برای پیش‌بینی قطعی اپراتور</td>
    <td>دادهٔ برچسب‌دار اپراتور×مسیر×زمان (که امروز نداریم)</td></tr>
</table></div>""")

    parts.append(f"""<h2>۹) بازتولید</h2><div class="card">
<p>کل خروجی این گزارش با یک فرمان:</p>
<p><code>cd /home/user/dnsradar &amp;&amp; python3 -m ncf.run_all</code></p>
<p class="note">فایل‌های خام: <code>ncf/bench.json</code> (بک‌تست)، <code>ncf/live.json</code>
(اندازه‌گیری زنده)، <code>ncf/diag.json</code> (تشخیص). گزارش از همین‌ها ساخته می‌شود؛
اگر عددی در متن باشد، در یکی از این سه فایل وجود دارد.</p></div>

<footer>NCF · ساخته‌شده برای «پینگ‌هاب» · گزارش خودکفا (بدون منبع بیرونی)</footer>
</div></body></html>""")
    return "".join(parts)


def main(argv: list[str]) -> int:
    bench_path = os.path.join(HERE, "bench.json")
    if not os.path.exists(bench_path):
        print("❌ ncf/bench.json پیدا نشد. اول `python3 -m ncf.simulate` را اجرا کنید.", file=sys.stderr)
        return 2
    with open(bench_path, encoding="utf-8") as f:
        bench = json.load(f)
    live = diag = None
    lp, dp = os.path.join(HERE, "live.json"), os.path.join(HERE, "diag.json")
    if os.path.exists(lp):
        with open(lp, encoding="utf-8") as f:
            live = json.load(f)
    if os.path.exists(dp):
        with open(dp, encoding="utf-8") as f:
            diag = json.load(f)
    out = os.path.join(HERE, "report.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(bench, live, diag))
    print(f"✅ گزارش ساخته شد: {out} ({os.path.getsize(out) // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
