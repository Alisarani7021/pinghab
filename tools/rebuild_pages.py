#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rebuild_pages.py — بازسازی قطعی cloudflare/app.html و web/dns-radar.html

خط تولید (همیشه یکسان):
  ۱) checkout پایه از کامیت 75cd418 (پایهٔ ۲.۰ — طرح ظاهری کاربر)
  ۲) وصله‌های پایه: مدیریت عدد BGP، جدول رزولور کشوری، مسابقهٔ DoH دستگاه+لبه،
     پنل بازی‌ها v2، لایهٔ طراحی v3 + هیرو
  ۳) درج بلوک tools2 (پنل‌های p8..p12)
  ۴) درج بلوک tools3 (پنل‌های p13..p19) با همان منطق inline_tools3.py
  ۵) وارسی: ۱۹ پنل، اندازه‌ها، نبود نشانگر تکراری
اجرا: python3 tools/rebuild_pages.py
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = "75cd418"
PAGES = [ROOT / "cloudflare" / "app.html", ROOT / "web" / "dns-radar.html"]


def sh(*args):
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print("FAILED:", " ".join(args), r.stdout[-500:], r.stderr[-500:])
        sys.exit(1)
    return r.stdout


# ------------------------------------------------------------------ ۱) checkout پایه
sh("git", "checkout", BASE_COMMIT, "--", "cloudflare/app.html", "web/dns-radar.html")
print("base checked out from", BASE_COMMIT)

# لایهٔ چیدمان v2 (دور ۷): فقط پنل فعال دیده شود + فشرده‌سازی برای جا شدن در قالب اپ
LAYOUT_CSS = r"""
<style id="ph-layout7">
@font-face{font-family:VazirmatnX;src:url("fonts/Vazirmatn-Regular.woff2") format("woff2");font-weight:400;font-display:swap}
@font-face{font-family:VazirmatnX;src:url("fonts/Vazirmatn-Bold.woff2") format("woff2");font-weight:700;font-display:swap}
body,button,input,select,textarea{font-family:VazirmatnX,Vazirmatn,Tahoma,system-ui,sans-serif}
/* پوستهٔ قدیمی/بخش‌های بیرون پنل نباید در همهٔ صفحات تکرار شوند */
.wrap > *:not(.ph-panel){display:none !important}
.wrap{padding:10px 10px 84px !important;max-width:820px !important}
body{padding-top:52px !important;padding-bottom:0 !important}
h2{font-size:14px !important;margin:12px 0 6px !important}
.head,.adv,.card,.ph-card,.wwrow,.wwbox,.ph-box,.note{border-radius:var(--mr) !important;padding:10px 12px !important;margin:6px 0 !important}
.ph-card > b{font-size:13.5px !important;line-height:1.6}
.sub{font-size:12px !important;line-height:1.65 !important}
table{font-size:12px !important}
th{padding:3px 4px !important} td{padding:6px 4px !important}
.ph-grid2{gap:6px !important}
.wwbtn,button{padding:7px 11px !important;font-size:12.5px !important}
.ph-startbtn{min-height:48px !important}
.ph-ip{font-size:24px !important}
h1{font-size:19px !important}
.mn-db{padding:0 8px calc(14px + env(safe-area-inset-bottom,0px)) !important}
.mn-it{padding:8px 10px !important;font-size:13.5px !important}
.mn-g>button{padding:9px 6px 4px !important}
.mn-g .ls>div{max-height:none}
.mn-dr aside{width:min(88vw,340px) !important}
/* ---- دور ۹: جا شدن در قالب اپ — هیچ‌چیز از عرض صفحه بیرون نزند ---- */
html,body{overflow-x:hidden;overflow-x:clip}
.wrap,.ph-panel{min-width:0 !important;max-width:100% !important}
.ph-panel{overflow-x:hidden;overflow-x:clip}
.ph-tblwrap{overflow-x:auto;max-width:100%}
.ph-tblwrap table{margin:0;width:100%;min-width:0} /* باریک=بی‌اسکرول؛ پهن=خودکار پهن و اسکرول */
.ph-tblwrap th,.ph-tblwrap td{white-space:nowrap}
.ph-tblwrap td.wrap,.ph-tblwrap th.wrap{white-space:normal;min-width:120px}
.mono,.ph-mono,code{overflow-wrap:anywhere;word-break:break-word}
table.ph-facts{width:100%;border-collapse:collapse}
table.ph-facts td{vertical-align:top;overflow-wrap:anywhere;word-break:break-word}
@media (max-width:560px){
table.ph-facts,table.ph-facts tbody,table.ph-facts tr,table.ph-facts td{display:block;width:100% !important}
table.ph-facts tr{border-bottom:1px solid var(--line);padding:7px 2px}
table.ph-facts tr:last-child{border-bottom:0}
table.ph-facts td{border:0 !important;padding:2px 0 !important}
table.ph-facts td:first-child{font-weight:800;color:var(--mut);font-size:11.5px}
}
</style>
"""

# ------------------------------------------------------------------ ۲) CSS طراحی v3
DESIGN_CSS = r"""
<style id="ph-design-v3">
/* ================= پینگ‌هاب — لایهٔ طراحی v3 (روی متغیرهای هر ۱۱ تم) ================= */
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{
  font-family:Vazirmatn,system-ui,-apple-system,"Segoe UI",Roboto,"Noto Sans Arabic",sans-serif;
  background:var(--bg);
  background:
    radial-gradient(1100px 520px at 88% -8%, color-mix(in srgb,var(--acc) 13%, transparent), transparent 62%),
    radial-gradient(760px 420px at 4% 2%, color-mix(in srgb,var(--acc) 7%, transparent), transparent 58%),
    var(--bg);
  background-attachment:fixed;
  color:var(--tx);
  line-height:1.75;
  -webkit-text-size-adjust:100%;
  font-feature-settings:"ss01","ss02";
}
::selection{background:color-mix(in srgb,var(--acc) 40%, transparent)}
h1,h2,h3,b,strong{font-weight:800;letter-spacing:-.01em}
h2{font-size:clamp(19px,4.6vw,26px);margin:18px 0 6px;display:flex;align-items:center;gap:8px}
h2::after{content:"";flex:1;height:2px;border-radius:2px;
  background:linear-gradient(90deg,color-mix(in srgb,var(--acc) 55%, transparent),transparent)}
a{color:var(--acc);text-decoration:none}
a:hover{text-decoration:underline}
.mono,.ph-mono,code{font-family:ui-monospace,SFMono-Regular,"JetBrains Mono",Menlo,monospace;
  font-variant-numeric:tabular-nums;font-size:.92em;direction:ltr;unicode-bidi:isolate}
.num,.ph-kv b{font-variant-numeric:tabular-nums}

/* ---- هیرو ---- */
.ph-hero{position:relative;overflow:hidden;margin:14px 0 4px;padding:20px 18px 16px;
  border:1px solid var(--line);border-radius:calc(var(--r) + 6px);
  background:var(--card);
  background:linear-gradient(135deg,color-mix(in srgb,var(--acc) 20%, var(--card)),var(--card) 62%);
  box-shadow:var(--sh), 0 18px 44px -28px color-mix(in srgb,var(--acc) 60%, transparent)}
.ph-hero::before{content:"";position:absolute;inset:auto -30% -70% 40%;height:180px;
  background:radial-gradient(closest-side,color-mix(in srgb,var(--acc) 30%, transparent),transparent);pointer-events:none}
.ph-hero h1{margin:0;font-size:clamp(24px,7vw,38px);line-height:1.15;display:flex;align-items:center;gap:10px}
.ph-hero .ph-hero-sub{margin-top:6px;color:var(--mut);font-size:clamp(12.5px,3.4vw,15px);max-width:62ch}
.ph-hero .ph-hero-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px;position:relative;z-index:1}
.ph-hero .ph-chip{border:1px solid var(--line);background:var(--card);background:color-mix(in srgb,var(--tx) 5%, transparent);
  color:var(--tx);border-radius:999px;padding:9px 14px;font-size:13.5px;font-weight:700;cursor:pointer;
  transition:transform .15s ease, border-color .15s ease, background .15s ease}
.ph-hero .ph-chip:hover{transform:translateY(-1px);border-color:var(--acc);
  background:color-mix(in srgb,var(--acc) 16%, transparent)}
.ph-hero .ph-hero-note{margin-top:12px;font-size:12.5px;color:var(--mut);position:relative;z-index:1}

/* ---- تب‌ها: چسبان + نواری ---- */
.ph-tabs{position:sticky;top:0;z-index:30;display:flex;gap:7px;overflow-x:auto;flex-wrap:nowrap;
  padding:9px 6px;margin:12px -6px 14px;background:var(--bg);background:color-mix(in srgb,var(--bg) 86%, transparent);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
  border-bottom:1px solid var(--line);scrollbar-width:none;scroll-snap-type:x proximity}
.ph-tabs::-webkit-scrollbar{display:none}
.ph-tab{flex:0 0 auto;padding:9px 14px;border-radius:var(--rb,999px);border:1px solid var(--line);
  background:var(--card);background:color-mix(in srgb,var(--card) 92%, transparent);color:var(--mut);font:inherit;font-size:13px;
  font-weight:700;cursor:pointer;white-space:nowrap;scroll-snap-align:center;
  transition:color .15s ease, background .15s ease, border-color .15s ease, transform .15s ease}
.ph-tab:hover{color:var(--tx);border-color:color-mix(in srgb,var(--acc) 50%, var(--line))}
.ph-tab.on{background:var(--acc);color:var(--on);border-color:var(--acc);
  box-shadow:0 8px 22px -12px color-mix(in srgb,var(--acc) 75%, transparent);transform:translateY(-1px)}

/* ---- پنل‌ها و کارت‌ها ---- */
.ph-panel{animation:phFade .25s ease}
@keyframes phFade{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
.ph-card{position:relative;margin:12px 0;padding:16px 15px;border:1px solid var(--line);
  border-radius:calc(var(--r) + 4px);background:var(--card);box-shadow:var(--sh);
  transition:border-color .18s ease, transform .18s ease}
.ph-card:hover{border-color:color-mix(in srgb,var(--acc) 34%, var(--line))}
.ph-card>b:first-child,.ph-card>div>b:first-child{display:inline-flex;align-items:center;gap:7px;font-size:15.5px}
.ph-box{border:1px dashed color-mix(in srgb,var(--acc) 45%, var(--line));
  background:color-mix(in srgb,var(--acc) 7%, transparent);border-radius:calc(var(--r) + 2px);padding:12px 13px}
.sub{color:var(--mut);font-size:13px;line-height:1.85}
.ph-lbl{display:block;margin-bottom:5px;font-size:12.5px;font-weight:700;color:var(--mut)}
.row{display:flex;align-items:center;gap:8px}
.ph-grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:10px}
.ph-kv{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}

/* ---- فرم‌ها ---- */
.wwin,input[type=text],input[type=search],input[type=number],input:not([type]),select,textarea{
  width:100%;min-height:46px;padding:10px 12px;border-radius:var(--r);border:1px solid var(--line);
  background:var(--card);background:color-mix(in srgb,var(--tx) 4%, transparent);color:var(--tx);font:inherit;font-size:14.5px;
  transition:border-color .15s ease, box-shadow .15s ease, background .15s ease}
.wwin:focus,input:focus,select:focus,textarea:focus{outline:none;border-color:var(--acc);
  box-shadow:0 0 0 3px color-mix(in srgb,var(--acc) 22%, transparent)}
input[style*="direction:ltr"],.wwin[style*="direction:ltr"],#ph-dom,#ph3-race-name,#ph3-flt-host,#ph2-path-target{
  font-family:ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.01em}

/* ---- دکمه‌ها ---- */
.wwbtn{min-height:44px;padding:10px 15px;border-radius:var(--rb,10px);border:1px solid var(--line);
  background:var(--card);background:color-mix(in srgb,var(--tx) 6%, transparent);color:var(--tx);font:inherit;font-size:13.5px;
  font-weight:700;cursor:pointer;transition:transform .14s ease, background .14s ease, border-color .14s ease;
  display:inline-flex;align-items:center;justify-content:center;gap:6px}
.wwbtn:hover{transform:translateY(-1px);border-color:color-mix(in srgb,var(--acc) 55%, var(--line));
  background:color-mix(in srgb,var(--acc) 12%, transparent)}
.wwbtn:active{transform:translateY(0) scale(.985)}
.wwbtn.wwprimary{background:var(--acc);color:var(--on);border-color:var(--acc);
  box-shadow:0 10px 26px -14px color-mix(in srgb,var(--acc) 80%, transparent)}
.wwbtn.wwprimary:hover{filter:brightness(1.06)}
.wwbtn.wwcopy{min-height:34px;padding:5px 11px;font-size:12.5px;border-radius:999px}

/* ---- جدول‌ها ---- */
table{width:100%;border-collapse:separate;border-spacing:0;margin:10px 0;font-size:13.5px;
  overflow:hidden;border:1px solid var(--line);border-radius:calc(var(--r) + 2px)}
th,td{padding:9px 11px;text-align:right;border-bottom:1px solid color-mix(in srgb,var(--line) 80%, transparent)}
th{background:var(--card);background:color-mix(in srgb,var(--tx) 6%, transparent);color:var(--mut);font-size:12.5px;font-weight:800;
  position:sticky;top:0;backdrop-filter:blur(6px)}
tbody tr:nth-child(even) td{background:color-mix(in srgb,var(--tx) 2.6%, transparent)}
tbody tr:hover td{background:color-mix(in srgb,var(--acc) 8%, transparent)}
tr:last-child td{border-bottom:none}
.ph-tblwrap{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:10px 0}
.ph-tblwrap table{margin:0;min-width:520px}

/* ---- نشان‌ها ---- */
.ph-badge,.badge,.pill{display:inline-flex;align-items:center;gap:5px;padding:3px 9px;border-radius:999px;
  border:1px solid var(--line);font-size:11.5px;font-weight:800;
  background:var(--card);background:color-mix(in srgb,var(--tx) 5%, transparent)}
.ph-good,.ph-warn,.ph-bad{display:inline-flex;align-items:center;gap:5px;padding:2px 9px;border-radius:999px;font-weight:800}
.ph-good{color:#0f7a55;background:rgba(16,168,116,.18);border:1px solid rgba(16,168,116,.42)}
.ph-warn{color:#8a5a00;background:rgba(224,138,0,.18);border:1px solid rgba(224,138,0,.42)}
.ph-bad{color:#a1231f;background:rgba(229,57,53,.16);border:1px solid rgba(229,57,53,.42)}
[data-t=renault] .ph-good,[data-t=apple] .ph-good,[data-t=claude] .ph-good,[data-t=lovable] .ph-good{color:#046b48}
.ph-chip-ok{background:color-mix(in srgb,#10a874 20%, transparent);border-color:color-mix(in srgb,#10a874 45%, transparent)}
.ph-chip-no{background:color-mix(in srgb,#e53935 16%, transparent);border-color:color-mix(in srgb,#e53935 40%, transparent)}

/* ---- اسکرول‌بار ---- */
*{scrollbar-width:thin;scrollbar-color:color-mix(in srgb,var(--acc) 45%, var(--line)) transparent}
*::-webkit-scrollbar{width:9px;height:9px}
*::-webkit-scrollbar-thumb{background:color-mix(in srgb,var(--acc) 40%, var(--line));border-radius:99px}
*::-webkit-scrollbar-track{background:transparent}

/* ---- موبایل ---- */
@media (max-width:640px){
  .ph-card{padding:14px 12px;border-radius:calc(var(--r) + 2px)}
  .row{flex-wrap:wrap}
  .wwbtn{flex:1 1 auto}
  .ph-tabs{margin:10px -4px 12px}
  th,td{padding:8px 9px;font-size:12.5px}
  .ph-hero{padding:16px 14px}
  body{line-height:1.7}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style>
"""

# ------------------------------------------------------------------ هیرو + بهبود تب‌ها
HERO_JS = r"""
<script>
/* ================= هیرو و بهبود تجربهٔ تب‌ها (لایهٔ v3) ================= */
(function(){
  function q(i){ return document.getElementById(i); }
  function jump(target){
    var b = document.querySelector('.ph-tab[data-target="'+target+'"]');
    if (b) b.click();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  try{
    var tabs = q("ph-tabs");
    var host = tabs ? (tabs.closest("div") || document.body) : document.body;
    var hero = document.createElement("div");
    hero.className = "ph-hero";
    hero.innerHTML =
      '<h1>📡 پینگ‌هاب <span class="ph-badge mono">۲.۲</span></h1>' +
      '<div class="ph-hero-sub">کدام DNS و کدام مسیر، برای <b>خط خودت</b> بهتر است؟ این‌جا عدد واقعی سنجیده می‌شود — ' +
      'از گوشی تو، از شبکه‌های ایران، و از پروب‌های دیتاسنتری تهران. هر عدد، منبع و محدودیتش را کنارش می‌نویسیم.</div>' +
      '<div class="ph-hero-chips">' +
        '<button class="ph-chip" data-j="ph-p1">🚀 تست خط من</button>' +
        '<button class="ph-chip" data-j="ph-p3">🧭 بهترین DNS</button>' +
        '<button class="ph-chip" data-j="ph-p2">🎮 سرورهای بازی</button>' +
        '<button class="ph-chip" data-j="ph-p13">🕵️ کالبدشکافی فیلترینگ</button>' +
        '<button class="ph-chip" data-j="ph-p15">🏁 مسابقهٔ رزولور</button>' +
      '</div>' +
      '<div class="ph-hero-note">قانون ما: <b>کاندید، نه توصیه</b> · «DNS پینگ داخل مچ بازی را کم نمی‌کند» (فیزیک) · ' +
      'هر جا سنجش ممکن نباشد، «سنجش‌پذیر نیست» می‌نویسیم و عدد نمی‌سازیم.</div>';
    if (tabs && tabs.parentNode) tabs.parentNode.insertBefore(hero, tabs);
    hero.querySelectorAll("[data-j]").forEach(function(b){
      b.onclick = function(){ jump(b.getAttribute("data-j")); };
    });
    // تب فعال همیشه در دید بماند
    document.addEventListener("click", function(e){
      var t = e.target.closest && e.target.closest(".ph-tab");
      if (t && t.parentNode) t.parentNode.scrollTo({ left: Math.max(0, t.offsetLeft - 20), behavior: "smooth" });
    }, true);
  }catch(e){}
})();
</script>
"""

# ------------------------------------------------------------------ وصله‌های پایه


NAV_CSS = r"""
<style id="ph-nav-css">
/* ============ پوستهٔ اپ: نوار بالا + منوی پایین ۴ تایی + منوی همبرگری ============ */
#ph-tabs,.ph-hero{display:none !important}
body{padding-top:58px !important;padding-bottom:88px !important}
.ph-appbar{position:fixed;top:0;right:0;left:0;z-index:60;height:56px;display:flex;align-items:center;gap:10px;
  padding:0 12px;background:color-mix(in srgb,var(--bg) 92%, transparent);backdrop-filter:blur(14px);
  -webkit-backdrop-filter:blur(14px);border-bottom:1px solid var(--line)}
.ph-appbar b{font-size:15.5px;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ph-abtn{min-width:42px;min-height:42px;display:inline-flex;align-items:center;justify-content:center;
  border:1px solid var(--line);border-radius:12px;background:var(--card);color:var(--tx);font-size:19px;cursor:pointer;text-decoration:none}
.ph-abtn:active{transform:scale(.96)}
.ph-nav{position:fixed;bottom:0;right:0;left:0;z-index:60;display:grid;grid-template-columns:repeat(4,1fr);gap:2px;
  padding:6px 6px calc(6px + env(safe-area-inset-bottom,0px));background:color-mix(in srgb,var(--bg) 94%, transparent);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);border-top:1px solid var(--line)}
.ph-nav button{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:6px 4px;border:0;
  background:transparent;color:var(--mut);font:inherit;font-size:11px;font-weight:700;cursor:pointer;border-radius:12px;min-height:52px}
.ph-nav button i{font-style:normal;font-size:19px;line-height:1}
.ph-nav button.on{color:var(--acc);background:color-mix(in srgb,var(--acc) 14%, transparent)}
.ph-drawer{position:fixed;inset:0;z-index:70;display:none}
.ph-drawer.on{display:block}
.ph-drawer-bg{position:absolute;inset:0;background:rgba(0,0,0,.55)}
.ph-drawer aside{position:absolute;top:0;bottom:0;right:0;width:min(86vw,340px);background:var(--card);
  border-left:1px solid var(--line);padding:14px 14px calc(14px + env(safe-area-inset-bottom,0px));overflow-y:auto}
.ph-drawer h4{margin:14px 0 6px;font-size:12.5px;color:var(--mut)}
.ph-ditem{display:flex;align-items:center;gap:10px;padding:11px 10px;border-radius:12px;border:1px solid transparent;
  cursor:pointer;font-size:14px}
.ph-ditem:hover{background:color-mix(in srgb,var(--acc) 10%, transparent);border-color:color-mix(in srgb,var(--acc) 30%, var(--line))}
.ph-ditem.on{background:color-mix(in srgb,var(--acc) 16%, transparent);border-color:var(--acc)}
.ph-ditem i{font-style:normal;font-size:17px;width:22px;text-align:center}
.ph-dhead{display:flex;align-items:center;gap:8px;margin-bottom:6px}
.ph-dhead b{font-size:17px;flex:1}
/* کارت اصلی DNS (سبک دی‌ان‌اس‌چنجر) */
.ph-dnsmain{border-color:color-mix(in srgb,var(--acc) 42%, var(--line))}
.ph-dnsbar{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.ph-dnsbar b{font-size:19px}
.ph-state{padding:4px 12px;border-radius:999px;font-size:12.5px;font-weight:800;border:1px solid var(--line)}
.ph-state.on{background:rgba(16,168,116,.18);color:#12b981;border-color:rgba(16,168,116,.5)}
.ph-state.off{background:color-mix(in srgb,var(--tx) 6%, transparent);color:var(--mut)}
.ph-dnssrv{text-align:right}
.ph-ip{font-size:26px;font-weight:800;letter-spacing:.5px;line-height:1.35;word-break:break-all}
.ph-ip2{font-size:19px;font-weight:700;letter-spacing:.4px;word-break:break-all;color:var(--mut)}
.ph-startbtn{width:100%;margin-top:14px;min-height:54px;font-size:17px;letter-spacing:.3px}
.ph-livemetrics{margin-top:4px}
.ph-metric{display:flex;flex-direction:column;gap:2px;padding:9px 10px;border:1px solid var(--line);border-radius:12px;
  background:color-mix(in srgb,var(--tx) 3%, transparent)}
.ph-metric span{font-size:11.5px;color:var(--mut)}
.ph-metric b{font-size:16px;font-variant-numeric:tabular-nums}
.ph-resrow{display:flex;align-items:center;gap:10px;padding:10px 8px;border-bottom:1px solid color-mix(in srgb,var(--line) 70%, transparent);cursor:pointer}
.ph-resrow.on{background:color-mix(in srgb,var(--acc) 12%, transparent);border-radius:10px}
.ph-resrow .ph-pickmark{font-size:11.5px;color:var(--acc);border:1px solid color-mix(in srgb,var(--acc) 45%, var(--line));
  border-radius:999px;padding:3px 10px;white-space:nowrap}
.ph-resrow.on .ph-pickmark::before{content:"✓ "}
</style>
"""

# بخش‌ها و گروه‌های منو (تک‌منبع تولید HTML ایستا)
NAV_SECTIONS = [
    ("ph-p20", "🚀", "حالت DNS", "اصلی"),
    ("ph-p1", "📈", "خط من", "اصلی"),
    ("ph-p2", "🎮", "سرور بازی‌ها", "اصلی"),
    ("ph-p3", "🧭", "کاتالوگ رزولورها", "سنجش و رزولور"),
    ("ph-p4", "🌍", "ایران و جهان", "سنجش و رزولور"),
    ("ph-p5", "✨", "آی‌پی تمیز", "سنجش و رزولور"),
    ("ph-p9", "🔍", "واقعیت خط", "سنجش و رزولور"),
    ("ph-p15", "⚡", "رزولوشن و مسابقه", "سنجش و رزولور"),
    ("ph-p21", "🎯", "اسکنر IP و DNS", "سنجش و رزولور"),
    ("ph-p10", "🌡️", "ایران امروز", "سنجش و رزولور"),
    ("ph-p8", "🛰️", "مسیر من", "شبکه و مسیر"),
    ("ph-p6", "🏠", "خانه و شبکه", "شبکه و مسیر"),
    ("ph-p7", "📊", "اسکن و آمار", "شبکه و مسیر"),
    ("ph-p13", "🕵️", "کالبدشکافی فیلترینگ", "شبکه و مسیر"),
    ("ph-p14", "🌊", "موج و UDP", "شبکه و مسیر"),
    ("ph-p11", "🎯", "آمادهٔ رنکد", "ویژهٔ بازی"),
    ("ph-p12", "🤝", "تیمی و اشتراک", "ویژهٔ بازی"),
    ("ph-p19", "📱", "آزمون دستگاه و ویجت", "ابزار و اپ"),
    ("ph-p16", "📡", "نقطهٔ کور (آفلاین)", "ابزار و اپ"),
    ("ph-p17", "🧪", "صف و سیاست اپراتور", "ابزار و اپ"),
    ("ph-p18", "🛠️", "نسخهٔ مقاوم", "ابزار و اپ"),
]
NAV_GROUPS = ["اصلی", "سنجش و رزولور", "شبکه و مسیر", "ویژهٔ بازی", "ابزار و اپ"]

APK_URL = "https://github.com/Alisarani7021/pinghab/releases/download/apk-latest/pinghab-latest.apk"


def _nav_html():
    items = []
    for g in NAV_GROUPS:
        rows = [x for x in NAV_SECTIONS if x[3] == g]
        if not rows:
            continue
        items.append(f'<h4>{g}</h4>')
        for sid, ic, fa, _g in rows:
            items.append(f'<div class="ph-ditem" data-item="{sid}"><i>{ic}</i><span>{fa}</span></div>')
    items.append('<h4>درباره</h4>')
    items.append(f'<a class="ph-ditem" href="{APK_URL}" style="text-decoration:none;color:inherit"><i>⬇️</i><span>دانلود / به‌روزرسانی APK</span></a>')
    items.append('<a class="ph-ditem" href="/docs" target="_blank" style="text-decoration:none;color:inherit"><i>📘</i><span>مستندات API و دادهٔ باز</span></a>')
    items.append('<div class="sub">قانون ما: کاندید، نه توصیه · DNS پینگ داخل مچ بازی را کم نمی‌کند.</div>')
    return (
        '<div class="ph-appbar" id="ph-appbar">'
        '<button class="ph-abtn" id="ph-burger" aria-label="منو">☰</button>'
        '<b id="ph-appbar-title">🚀 حالت DNS</b>'
        f'<a class="ph-abtn" id="ph-appbar-apk" href="{APK_URL}" title="دانلود/به‌روزرسانی APK">⬇️</a>'
        '</div>'
        '<div class="ph-nav" id="ph-nav">'
        '<button data-nav="ph-p20"><i>🚀</i><span>DNS</span></button>'
        '<button data-nav="ph-p1"><i>📈</i><span>خط من</span></button>'
        '<button data-nav="ph-p2"><i>🎮</i><span>بازی</span></button>'
        '<button data-nav="__drawer__"><i>☰</i><span>بیشتر</span></button>'
        '</div>'
        '<div class="ph-drawer" id="ph-drawer"><div class="ph-drawer-bg" data-close="1"></div><aside>'
        '<div class="ph-dhead"><b>📡 پینگ‌هاب</b><span class="ph-badge mono">۲.۸</span>'
        '<button class="wwbtn" data-close="1" style="min-height:36px">✕</button></div>'
        + "".join(items) +
        '</aside></div>'
    )


NAV_HTML = '<div id="ph-nav-root">' + _nav_html() + '</div>'

# لایهٔ طراحی کاربر (round-6): پوستهٔ mn — نوار بالا/پایین + کشوی آکاردئونی + آیکون‌های SVG
# فایل عیناً همان چیزی است که کاربر تحویل داد (web/ui-layer-mn.html) — دست‌کاری نشود.
MN_LAYER = (ROOT / "web" / "ui-layer-mn.html").read_text(encoding="utf-8").strip() + "\n"

NAV_JS = r"""
<script id="ph-nav-script">
(function(){
  if (window.__phNavReady) return; window.__phNavReady = true;
  function $(s, r){ return (r || document).querySelector(s); }
  function $$(s, r){ return [].slice.call((r || document).querySelectorAll(s)); }
  var nav = $("#ph-nav"), dr = $("#ph-drawer"), ttl = $("#ph-appbar-title");
  var MAIN = ["ph-p20", "ph-p1", "ph-p2"];
  function openDrawer(){ if (dr) { dr.classList.add("on"); syncDrawer(); } }
  function closeDrawer(){ if (dr) dr.classList.remove("on"); }
  function current(){ var on = $(".ph-panel.on"); return on ? on.id : "ph-p20"; }
  function titleOf(id){ var it = $('.ph-ditem[data-item="' + id + '"]'); return it ? it.textContent.trim() : "پینگ‌هاب"; }
  function syncDrawer(id){
    id = id || current();
    $$(".ph-ditem[data-item]", dr).forEach(function(x){ x.className = "ph-ditem" + (x.getAttribute("data-item") === id ? " on" : ""); });
    if (nav) $$("button", nav).forEach(function(b){ b.className = (b.getAttribute("data-nav") === id) ? "on" : ""; });
    if (ttl){ var it = $('.ph-ditem[data-item="' + id + '"]'); ttl.innerHTML = it ? it.innerHTML.replace(/<i>|<\/i>/g, "") : "پینگ‌هاب"; }
  }
  function show(id, silent){
    var tab = document.querySelector('.ph-tab[data-target="' + id + '"]');
    if (tab) tab.click();
    /* همیشه تک‌پنلی: بعضی هندلرهای تب قدیمی فقط گروه خودشان را خاموش می‌کنند */
    $$(".ph-panel").forEach(function(pn){ pn.className = "ph-panel" + (pn.id === id ? " on" : ""); });
    syncDrawer(id);
    if (!silent) window.scrollTo({ top: 0, behavior: "smooth" });
  }
  window.phShow = show;
  if (nav) $$("button", nav).forEach(function(b){
    b.onclick = function(){
      var t = b.getAttribute("data-nav");
      if (t === "__drawer__") openDrawer(); else show(t);
    };
  });
  $$("[data-close]", dr).forEach(function(x){ x.onclick = closeDrawer; });
  $$(".ph-ditem[data-item]", dr).forEach(function(x){
    x.onclick = function(){ show(x.getAttribute("data-item")); closeDrawer(); };
  });
  var burger = $("#ph-burger"); if (burger) burger.onclick = openDrawer;
  document.addEventListener("keydown", function(e){ if (e.key === "Escape") closeDrawer(); });
  window.phOpenDrawer = openDrawer;
  /* صفحهٔ خانه = حالت DNS (آیتم اول منوی پایین) */
  var _h = (location.hash || "").replace("#", "");
  setTimeout(function(){ show(_h ? _h : "ph-p20", true); }, 150);
})();
</script>
"""

FIT9_JS = r"""
<script id="ph-fit9">
/* دور ۹ — تور ایمنی چیدمان: هر جدولی که بیرون .ph-tblwrap رندر شود، خودکار داخل اسکرول‌پیچ
   قرار می‌گیرد تا هیچ‌وقت صفحه (و منوی پایین) از عرض گوشی بیرون نزند. ph-facts مستثناست. */
(function(){
  if (window.__phFit9) return; window.__phFit9 = true;
  function wrap(t){
    if (!t || t.nodeType !== 1) return;
    if (t.closest(".ph-tblwrap") || t.classList.contains("ph-facts") || t.closest("#ph-nav-root")) return;
    var d = document.createElement("div"); d.className = "ph-tblwrap";
    t.parentNode.insertBefore(d, t); d.appendChild(t);
  }
  function sweep(root){
    if (!root || !root.querySelectorAll) return;
    var ts = root.querySelectorAll("table");
    for (var i = 0; i < ts.length; i++) wrap(ts[i]);
  }
  function boot(){
    sweep(document);
    try{
      var mo = new MutationObserver(function(muts){
        for (var i = 0; i < muts.length; i++){
          var nodes = muts[i].addedNodes;
          for (var j = 0; j < nodes.length; j++){
            var n = nodes[j];
            if (!n || n.nodeType !== 1) continue;
            if (n.tagName === "TABLE") wrap(n); else sweep(n);
          }
        }
      });
      mo.observe(document.documentElement, { childList: true, subtree: true });
    }catch(e){}
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
</script>
"""

def patch_bgp(src):
    old = 'var vals = ser.serie_0.values.map(function(v){ return typeof v === "number" ? v : (v && v.value) || 0; });'
    new = ('var vals = ser.serie_0.values.map(function(v){ var n = (typeof v === "number") ? v : Number(v && v.value !== undefined ? v.value : v);'
           ' return isFinite(n) ? n : 0; });')
    if old in src:
        src = src.replace(old, new, 1)
        old2 = '''            '<br>کمترین ' + fa(Math.min.apply(null, vals)) + ' · بیشترین ' + fa(Math.max.apply(null, vals)) + '</div>';'''
        new2 = ("""            '<br>کمترین ' + fa(Math.min.apply(null, vals)) + ' · بیشترین ' + fa(Math.max.apply(null, vals)) +
            ' · مجموع ' + fa(vals.reduce(function(a,b){return a+b;},0)) + '</div>';""")
        assert old2 in src
        src = src.replace(old2, new2, 1)
        return src, True
    return src, False


def patch_doh(src):
    """مسابقهٔ DoH: آدرس‌های درست + تفکیک خطا + نسخهٔ لبه که همیشه عدد واقعی می‌دهد."""
    start = src.find('  /* ---------- سنجش از دستگاه (DoH JSON) + p95/jitter ---------- */')
    end = src.find('  q("ph-report").onclick = async function(){')
    if start == -1 or end == -1 or 'ph-doh-v2' in src:
        return src, False
    new_block = r'''  /* ---------- سنجش از دستگاه (DoH) — نسخهٔ ۲ (ph-doh-v2) ---------- */
  /* ریشهٔ خطای «همه ناموفق»: آدرس‌های غلط (adguard/nextdns)، نبود CORS، و بسته‌بودن DoH روی برخی اپراتورها.
     راه‌حل: (۱) آدرس‌های درست، (۲) آزمون «دسترسی» بدون نیاز به CORS، (۳) نسخهٔ لبه که همیشه عدد واقعی می‌دهد. */
  var DOH = [
    { id:"cloudflare", name:"کلودفلر", url:"https://cloudflare-dns.com/dns-query" },
    { id:"google", name:"گوگل", url:"https://dns.google/dns-query" },
    { id:"adguard", name:"ادگارد", url:"https://dns.adguard-dns.com/resolve" },
    { id:"quad9", name:"کوآد۹", url:"https://dns.quad9.net:5053/dns-query" },
    { id:"dns0", name:"DNS0.eu", url:"https://dns0.eu/dns-query" },
    { id:"dnssb", name:"DNS.SB", url:"https://doh.sb/dns-query" }
  ];
  async function probeOne(r, name){
    var ctrl = new AbortController(); var to = setTimeout(function(){ ctrl.abort(); }, 4500);
    var t0 = performance.now();
    try{
      var u = r.url + (r.url.indexOf("?") >= 0 ? "&" : "?") + "name=" + encodeURIComponent(name) + "&type=A";
      var res = await fetch(u, { headers:{ accept:"application/dns-json" }, signal: ctrl.signal, cache:"no-store" });
      var ms = performance.now() - t0;
      var ips = [];
      try{ var j = await res.json(); ips = (j.Answer||[]).filter(function(a){ return a.type === 1; }).map(function(a){ return a.data; }); }catch(e){}
      return { id:r.id, name:r.name, ms:ms, ips:ips, ok:!!res.ok && ips.length>0 };
    }catch(e){
      var why = (e && e.name === "AbortError") ? "timeout" : "دسترسی/CORS";
      return { id:r.id, name:r.name, ms:performance.now()-t0, ips:[], ok:false, why:why };
    }
    finally{ clearTimeout(to); }
  }
  /* آزمون «فقط دسترسی»: با no-cors بدنه خوانده نمی‌شود ولی اگر TLS برقرار شود، خط بسته نیست. */
  async function reachOne(r){
    var ctrl = new AbortController(); var to = setTimeout(function(){ ctrl.abort(); }, 4000);
    var t0 = performance.now();
    try{
      await fetch(r.url, { mode:"no-cors", cache:"no-store", signal: ctrl.signal });
      return { id:r.id, reach:true, ms:Math.round(performance.now()-t0) };
    }catch(e){
      return { id:r.id, reach:false, ms:Math.round(performance.now()-t0),
        why:(e && e.name === "AbortError") ? "پاسخی نیامد (۴ث)" : "اتصال برقرار نشد" };
    }
    finally{ clearTimeout(to); }
  }
  var LAST = [];
  q("ph-run").onclick = async function(){
    var name = (q("ph-dom").value||"").trim().replace(/[^a-z0-9.\-]/gi, "") || "cdn.cloudflare.steamstatic.com";
    var out = q("ph-out"); out.innerHTML = "در حال سنجش (۶ رزولور × ۳ بار) + آزمون دسترسی…";
    var rows = [], reachRows = {};
    for (var i=0;i<DOH.length;i++){
      var rs = [], re = null;
      re = await reachOne(DOH[i]);
      reachRows[DOH[i].id] = re;
      for (var k=0;k<3;k++){ rs.push(await probeOne(DOH[i], name)); }
      var good = rs.filter(function(x){ return x.ok && x.ips.length; });
      var ms = good.map(function(x){ return x.ms; });
      var failWhy = !good.length ? ((rs[0] && rs[0].why) || "بی‌پاسخ") : null;
      rows.push({ id:DOH[i].id, name:DOH[i].name, ok:good.length>0, n:good.length,
        p50: pct(ms,50), p95: pct(ms,95), jit: ms.length>1 ? Math.round((Math.max.apply(null,ms)-Math.min.apply(null,ms))) : null,
        ips: good.length ? good[0].ips : [], reach: re, why: failWhy });
    }
    LAST = rows;
    var okRows = rows.filter(function(x){ return x.ok; }).sort(function(a,b){ return a.p50-b.p50; });
    var reachOk = rows.filter(function(x){ return x.reach && x.reach.reach; }).length;
    var html = '<div class="sub" style="margin-top:8px">از خط خودت: <b>' + fa(reachOk) + ' از ' + fa(rows.length) +
      '</b> رزولور قابل دسترسی بود · پاسخ سالم از <b>' + fa(okRows.length) + '</b> رزولور.</div>';
    html += '<div class="ph-tblwrap"><table><tr><th>DNS</th><th>دسترسی از خط تو</th><th>میانه</th><th>p95</th><th>نوسان</th><th>آی‌پی برگشتی</th></tr>';
    rows.forEach(function(r2){
      var reachTxt = r2.reach && r2.reach.reach
        ? '<span class="ph-badge ph-chip-ok">✅ بله (' + fa(r2.reach.ms) + 'ms)</span>'
        : '<span class="ph-badge ph-chip-no">⛔ ' + esc((r2.reach && r2.reach.why) || "بسته") + '</span>';
      html += '<tr><td>' + esc(r2.name) + (r2.ok ? "" : ' <span class="ph-bad">بی‌پاسخ</span>') + "</td>"
        + "<td>" + reachTxt + "</td>"
        + "<td>" + (r2.p50==null?"—":fa(r2.p50.toFixed(0))+"ms") + "</td>"
        + "<td>" + (r2.p95==null?"—":fa(r2.p95.toFixed(0))+"ms") + "</td>"
        + "<td>" + (r2.jit==null?"—":fa(r2.jit)+"ms") + "</td>"
        + '<td class="ph-mono">' + esc((r2.ips||[]).slice(0,2).join(" · ")||"—") + "</td></tr>";
    });
    html += "</table></div>";
    if (okRows.length){
      var b = okRows[0], w = okRows[okRows.length-1], gap = (w.p50 - b.p50);
      html += '<div class="ph-card"><b>خلاصه از خط تو:</b> بهترین <b>' + esc(b.name) + "</b> با میانهٔ <b>" + fa(b.p50.toFixed(0)) + "ms</b>"
        + (okRows.length>1 ? " · اختلاف تا بدترین (" + esc(w.name) + "): <b>" + fa(gap.toFixed(0)) + "ms</b>" : "") + "</div>";
    } else {
      html += '<div class="ph-warn">هیچ رزولوری از این خط پاسخ JSON نداد. دو حالت دارد: یا اپراتور DoH را بسته، یا مرورگر به‌خاطر CORS اجازهٔ خواندن بدنه را نمی‌دهد. جدول پایین (سنجش از لبهٔ شبکه) در هر دو حالت عدد واقعی می‌دهد.</div>';
    }
    html += '<div class="sub">▲ این عدد «سرعت رسیدن پاسخ DNS» است، نه پینگ بازی. اثر واقعی روی مسیر بازی از <b>آی‌پی برگشتی</b> می‌آید. در مرورگر نمی‌توانیم DNS سیستم را عوض کنیم؛ در اپ اندروید هم بدون روت فقط راهنمای تغییر دستی می‌دهیم.</div>';
    out.innerHTML = html;

    /* --- نسخهٔ لبه: از سرور ما، مستقل از فیلتر اپراتور --- */
    out.innerHTML += '<div class="ph-card" id="ph-edge-race"><b>🏁 مسابقهٔ رزولور از لبهٔ شبکه</b><div class="sub">در حال سنجش…</div></div>';
    try{
      var d = await jget("/api/dohrace?host=" + encodeURIComponent(name));
      var eh = '<div class="ph-card" id="ph-edge-race"><b>🏁 مسابقهٔ رزولور از لبهٔ شبکه</b><div class="sub">' +
        'این مسابقه از سرور ما اجرا می‌شود، پس اگر اپراتور DoH را بسته باشد هم عدد واقعی می‌بینی (مرجع، نه خط تو).</div>' +
        '<div class="ph-tblwrap"><table><tr><th>رزولور</th><th>زمان</th><th>کد</th><th>آی‌پی</th></tr>';
      (d.rows||[]).forEach(function(x){
        eh += "<tr><td>" + esc(x.name) + "</td><td>" + (x.ok? fa(x.ms)+"ms" : '<span class="ph-bad">'+esc(x.err||"—")+"</span>") +
          "</td><td>" + (x.rcode==null?"—":fa(x.rcode)) + '</td><td class="ph-mono">' + esc((x.ips||[]).join(" · ")||"—") + "</td></tr>";
      });
      eh += "</table></div>";
      if (d.best) eh += '<div class="sub">پاسخ‌دهنده: <b>' + fa(d.answered) + " از " + fa(d.tried) + "</b> · تندترین: <b>" + esc(d.best.name) +
        "</b> (" + fa(d.best.ms) + "ms) · آی‌پی‌های اولین پاسخ متمایز: <b>" + fa(d.distinct_first_ips||0) + "</b> (تفاوت = PoP متفاوت)</div>";
      eh += "</div>";
      var box = q("ph-edge-race"); if (box) box.outerHTML = eh;
    }catch(e){
      var box2 = q("ph-edge-race"); if (box2) box2.innerHTML = '<b>🏁 مسابقهٔ لبه</b><div class="ph-warn">دسترسی نبود: ' + esc(e.message) + "</div>";
    }
  };
'''
    src = src[:start] + new_block + src[end:]
    return src, True


def patch_impact_fallback(src):
    """سنجش اثر PoP: اگر کشور DoH معرفی‌شده نداشت، از ۶ رزولور جهانی استفاده کن — با برچسب صریح."""
    old = '    if(!targets.length){ out.textContent = "آدرس DoH پیدا نشد."; return; }'
    new = """    if(!targets.length){
      targets = (typeof DOH !== "undefined" ? DOH : []).map(function(x){ return { name: x.name, doh: x.url }; });
      out.innerHTML = '<div class="sub">برای این کشور رزولور DoH معرفی‌شده ثبت نشده (لیست آن کشور، سرورهای بومی همان کشور است)؛ این سنجش با ۶ رزولور جهانی انجام می‌شود و «آی‌پی برگشتی» مقایسه می‌شود — نه اینکه لیست کشورها را تکرار کنیم.</div>';
    }
    if(!targets.length){ out.textContent = "هیچ رزولور DoH در دسترس نبود."; return; }"""
    if old not in src:
        return src, False
    return src.replace(old, new, 1), True


def patch_games(src):
    if 'ph-games-v2' in src:
        return src, False
    # ۱) متن و مارک‌آپ پنل (هر دو صفحه رشتهٔ کمی متفاوت دارند ⇒ regex)
    new_head = ('''      <b>سرورهای بازی — بهترین رجین برای تو</b> <!-- ph-games-v2 -->
      <div class="sub">۱۳ بازی · ۱۶۸ سرور. سرورهای <b>پابجی موبایل</b> و <b>موبایل لجندز</b> با پینگ واقعی از سه نقطهٔ دید سنجیده و تأیید شده‌اند (✅)؛
        برای هر سرور، منبع و تاریخ تأیید ثبت است. جست‌وجو کن، رجین را ببین، بعد «پینگ زنده از ایران» را بگیر.</div>''')
    src, n1 = re.subn(r'<b>[^<]*سرورهای بازی — بهترین رجین برای تو</b>\s*\n\s*<div class="sub">۹ بازی · ۱۴۱ سرور[^<]*</div>',
                      new_head, src, count=1)
    assert n1 == 1, "games head anchor"

    new_btns = '''      <div class="row" style="flex-wrap:wrap;gap:8px;margin-top:8px">
        <input id="ph-gsearch" class="wwin" placeholder="جست‌وجو: pubg، لجند، valorant…" style="flex:1;min-width:180px">
      </div>
      <div class="row" style="flex-wrap:wrap;gap:8px;margin-top:8px">
        <button class="wwbtn wwprimary" id="ph-gload">نمایش سرورها</button>
        <button class="wwbtn" id="ph-gping">📡 پینگ زنده از ایران</button>
        <button class="wwbtn" id="ph-gsvc">🧩 سرویس‌هایی که ICMP بسته‌اند</button>
      </div>'''
    src, n2 = re.subn(r'<div class="row"[^>]*>\s*<button class="wwbtn wwprimary" id="ph-gload">نمایش سرورها</button>\s*'
                      r'<button class="wwbtn" id="ph-gping">[^<]*</button>\s*</div>',
                      new_btns, src, count=1)
    assert n2 == 1, "games buttons anchor"

    # ۲) منطق
    start = src.find('  /* ---------- بازی ---------- */')
    end = src.find('  /* ---------- رزولورها ---------- */')
    assert start != -1 and end != -1, "games js anchors"
    new_js = r'''  /* ---------- بازی (نسخهٔ ۲: تأییدشده + پینگ زنده + سرویس‌ها) ---------- */
  var GAMES = null;
  function gameRowBadges(s){
    var b = '';
    if (s.v) b += ' <span class="ph-badge ph-chip-ok">✅ تأییدشده</span>';
    else b += ' <span class="ph-badge">کاندید</span>';
    return b;
  }
  function renderProbe(s){
    if (!s.probe) return "—";
    var parts = [];
    ["DE","SG","TR"].forEach(function(k){ if (s.probe[k] != null) parts.push(k + " " + fa(Math.round(s.probe[k])) + "ms"); });
    return parts.length ? parts.join(" · ") : "—";
  }
  async function loadGames(){
    var qq = (q("ph-gsearch") && q("ph-gsearch").value || "").trim();
    try{ GAMES = await jget("/api/games" + (qq ? "?q=" + encodeURIComponent(qq) : "")); }catch(e){ return; }
    if (!GAMES || !GAMES.games) return;
    q("ph-game").innerHTML = GAMES.games.map(function(g){
      return '<option value="'+esc(g.slug)+'">'+esc(g.fa)+' — '+fa(g.servers)+' سرور'+(g.verified?" · "+fa(g.verified)+" تأییدشده":"")+'</option>'; }).join("");
    loadRegion();
    q("ph-gout").innerHTML = '<div class="sub">' + fa(GAMES.count) + " بازی · " + fa(GAMES.total_servers) + " سرور · تأییدشده با پینگ واقعی: <b>" +
      fa(GAMES.verified_servers) + "</b> سرور · تاریخ تأیید: " + esc(GAMES.verified_at||"—") + "</div>";
  }
  async function loadRegion(){
    var slug = q("ph-game").value; if(!slug) return;
    try{
      var d = await jget("/api/games?game=" + encodeURIComponent(slug));
      q("ph-region").innerHTML = Object.keys(d.regions).map(function(r){
        var cnt = d.regions[r].length;
        return '<option value="'+esc(r)+'">'+esc(d.regions_fa[r]||r)+" ("+fa(cnt)+")</option>"; }).join("");
      if (d.note) q("ph-gout").innerHTML = '<div class="ph-box"><b>' + esc(d.fa) + (d.publisher ? " — " + esc(d.publisher) : "") + '</b><div class="sub">' +
        esc(d.note) + (d.src ? '<br>منبع: <span class="mono">' + esc(d.src) + '</span>' : '') + '</div>' +
        ((d.unmeasurable||[]).length ? '<div class="sub">⚠️ سنجش‌پذیر نیست: ' + d.unmeasurable.map(function(u){ return esc(u.loc) + " (" + esc(u.why) + ")"; }).join(" · ") + '</div>' : '') +
        '</div>';
    }catch(e){}
  }
  if (q("ph-game")) q("ph-game").onchange = loadRegion;
  if (q("ph-gsearch")) q("ph-gsearch").oninput = function(){ loadGames(); };
  q("ph-gload").onclick = async function(){
    var slug = q("ph-game").value, reg = q("ph-region").value;
    var out = q("ph-gout"); out.innerHTML = "…";
    try{
      var d = await jget("/api/games?game=" + encodeURIComponent(slug) + "&region=" + encodeURIComponent(reg));
      var arr = d.regions[reg] || [];
      var html = '<div class="sub">' + fa(arr.length) + " سرور در رجین " + esc(d.regions_fa[reg]||reg) + " · پینگ‌های ستون «سنجش ما» میانگین ICMP از DE/SG/TR است (نه خط تو).</div>";
      html += '<div class="ph-tblwrap"><table><tr><th>سرور</th><th>آی‌پی:پورت</th><th>ASN</th><th>وضعیت</th><th>سنجش ما</th><th></th></tr>';
      arr.forEach(function(s){
        html += "<tr><td>" + esc(s.loc||s.id) + '</td><td class="ph-mono">' + esc(s.ip+":"+s.port) + "</td>"
          + '<td class="ph-mono">' + esc(s.asn||"—") + "</td>"
          + "<td>" + gameRowBadges(s) + (s.why ? '<div class="sub">' + esc(s.why) + '</div>' : "") + "</td>"
          + '<td class="ph-mono">' + renderProbe(s) + "</td>"
          + '<td><button class="wwbtn wwcopy" data-c="' + esc(s.ip+":"+s.port) + '">کپی</button></td></tr>';
      });
      html += "</table></div>";
      out.innerHTML = html;
      Array.prototype.forEach.call(out.querySelectorAll("[data-c]"), function(b){ b.onclick = function(){ copy(b, b.getAttribute("data-c")); }; });
    }catch(e){ out.textContent = "خطا: " + e.message; }
  };
  q("ph-gping").onclick = async function(){
    var slug = q("ph-game").value, reg = q("ph-region").value;
    var out = q("ph-gout");
    try{
      var d = await jget("/api/games?game=" + encodeURIComponent(slug) + "&region=" + encodeURIComponent(reg));
      var arr = (d.regions[reg]||[]).slice(0,3);
      if (!arr.length) return;
      out.innerHTML = '<div class="sub">در حال پینگ زندهٔ ' + fa(arr.length) + " سرور از پروب‌های ایران (Globalping)…</div>";
      var r = await jget("/api/gameping?ips=" + encodeURIComponent(arr.map(function(s){ return s.ip; }).join(",")) + "&cc=IR");
      var html = '<div class="ph-card"><b>📡 پینگ زندهٔ سرور بازی از داخل ایران</b>';
      (r.results||[]).forEach(function(res){
        var meta = arr.filter(function(s){ return s.ip === res.ip; })[0] || {};
        html += '<div class="ph-box" style="margin-top:8px"><b>' + esc(meta.loc||res.ip) + '</b> <span class="ph-mono">' + esc(res.ip) + '</span>';
        if (!res.rows || !res.rows.length){ html += '<div class="ph-warn">پاسخی نیامد — این سرور ICMP را می‌بندد یا مسیر بسته است. عدد نمی‌سازیم.</div>'; }
        else {
          html += '<div class="ph-tblwrap"><table style="margin-top:6px"><tr><th>شبکهٔ پروب</th><th>میانگین</th><th>نوسان</th><th>افت</th><th>اعتبار</th></tr>';
          res.rows.forEach(function(x){
            var trust = (x.sanity && x.sanity.trusted) ? '<span class="ph-badge ph-chip-ok">معتبر</span>'
              : '<span class="ph-badge ph-chip-no">نانشنه</span> <span class="sub">' + esc((x.sanity && x.sanity.flags || []).join(" · ")) + '</span>';
            html += "<tr><td>" + esc(x.network||"—") + "</td><td>" + (x.avg==null?"—":fa(Math.round(x.avg))+"ms") + "</td>"
              + "<td>" + (x.jitter==null?"—":fa(Math.round(x.jitter))+"ms") + "</td><td>" + (x.loss==null?"—":fa(x.loss)+"٪") + "</td><td>" + trust + "</td></tr>";
          });
          html += "</table></div>";
          if (res.summary) html += '<div class="sub">میانهٔ شبکه‌های معتبر: <b>' + (res.summary.median_ms==null?"—":fa(res.summary.median_ms)+"ms") +
            '</b> · پروب‌های نانشنه/بسته: ' + fa((res.summary.quantized||0)+(res.summary.icmp_filtered||0)) + '</div>';
        }
        html += "</div>";
      });
      html += '<div class="sub">' + esc(r.note||"") + '</div></div>';
      out.innerHTML = html;
    }catch(e){ out.textContent = "خطا: " + e.message; }
  };
  q("ph-gsvc").onclick = async function(){
    var out = q("ph-gout");
    try{
      var d = GAMES || await jget("/api/games");
      var sv = d.services;
      if (!sv || !sv.rows) { out.innerHTML = '<div class="ph-warn">دادهٔ سرویس‌ها نبود.</div>'; return; }
      var html = '<div class="ph-card"><b>🧩 بازی‌هایی که سرورشان ICMP را می‌بندد</b><div class="sub">' + esc(sv.note) + '</div>';
      html += '<div class="ph-tblwrap"><table><tr><th>بازی</th><th>هاست</th><th>زمان پاسخ HTTPS از ایران</th><th>از DE</th><th>از TR</th></tr>';
      sv.rows.forEach(function(x){
        var ex = {}; (x.extra||[]).forEach(function(e){ ex[e.loc] = e.ms; });
        html += "<tr><td>" + esc(x.fa||x.game) + '</td><td class="ph-mono">' + esc(x.host) + "</td><td>" +
          (x.ir_https_ms==null ? '<span class="ph-bad">بی‌پاسخ</span>' : "<b>" + fa(x.ir_https_ms) + "ms</b>") + "</td><td class=\"ph-mono\">" +
          (ex.DE==null?"—":fa(ex.DE)+"ms") + "</td><td class=\"ph-mono\">" + (ex.TR==null?"—":fa(ex.TR)+"ms") + "</td></tr>";
      });
      html += "</table></div><div class='sub'>تاریخ سنجش: " + esc(sv.measured_at||"—") + "</div></div>";
      out.innerHTML = html;
    }catch(e){ out.textContent = "خطا: " + e.message; }
  };

'''
    src = src[:start] + new_js + src[end:]
    return src, True


# ------------------------------------------------------------------ ۳) درج بلوک‌ها
def patch_preflight_page(src):
    """آزمون آمادگی: از فایل مشترک tools/patch_preflight.py استفاده می‌کند (تک‌منبع)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pp", ROOT / "tools" / "patch_preflight.py")
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    tmp = ROOT / "cloudflare" / "_tmp_page.html"
    tmp.write_text(src, encoding="utf-8")
    ok = mod.patch(tmp)
    return tmp.read_text(encoding="utf-8"), ok


def patch_round9(src):
    """دور ۹: جدول‌ها داخل اسکرول‌پیچ + «خط من» و «واقعیت خط» به سطرهای خوانا."""
    reps = [
        ('+ "<table><tr><th>نام</th><th>آدرس</th><th>DoH</th><th>پرچم‌ها</th><th>کپی</th></tr>";',
         '+ \'<div class="ph-tblwrap"><table><tr><th>نام</th><th>آدرس</th><th>DoH</th><th>پرچم‌ها</th><th>کپی</th></tr>\';'),
        ('+ "<td>" + esc((r.f||[]).join(" · ")||"—") + "</td>"',
         '+ \'<td class="wrap">\' + esc((r.f||[]).join(" · ")||"—") + "</td>"'),
        ('+ \'<td><button class="wwbtn wwcopy" data-c="\' + esc(r.a||r.d||"") + \'">کپی</button></td></tr>\';\n      });\n      html += "</table>";',
         '+ \'<td><button class="wwbtn wwcopy" data-c="\' + esc(r.a||r.d||"") + \'">کپی</button></td></tr>\';\n      });\n      html += "</table></div>";'),
        ('html += "<table><tr><th>پروب</th><th>شبکه (ASN)</th><th>نتیجه</th></tr>";',
         'html += \'<div class="ph-tblwrap"><table><tr><th>پروب</th><th>شبکه (ASN)</th><th>نتیجه</th></tr>\';'),
        ('+ ")</td><td>" + v + "</td></tr>";\n        });\n        html += "</table>";\n      } else {',
         '+ ")</td><td>" + v + "</td></tr>";\n        });\n        html += "</table></div>";\n      } else {'),
        ('html += "<table><tr><th>پروب</th><th>زمان</th><th>کد</th><th>پاسخ</th></tr>";',
         'html += \'<div class="ph-tblwrap"><table><tr><th>پروب</th><th>زمان</th><th>کد</th><th>پاسخ</th></tr>\';'),
        ('+ \'</td><td class="ph-mono">\' + esc((r.answers||[]).join(", ").slice(0,60)||"—") + "</td></tr>";\n        });\n        html += "</table>";\n      }',
         '+ \'</td><td class="ph-mono">\' + esc((r.answers||[]).join(", ").slice(0,60)||"—") + "</td></tr>";\n        });\n        html += "</table></div>";\n      }'),
        ('<div class="ph-card" style="margin-top:8px"><table style="width:100%;font-size:13px;border-collapse:collapse">',
         '<div class="ph-card" style="margin-top:8px"><table class="ph-facts" style="width:100%;font-size:13px;border-collapse:collapse">'),
    ]
    for old, new in reps:
        assert src.count(old) == 1, old[:60]
        src = src.replace(old, new, 1)
    a = src.find('ME = await jget("/api/geo");')
    b = src.find('q("ph-me-out").innerHTML = html;')
    assert a != -1 and b != -1 and a < b, "me-out anchors"
    mid = src[a:b]
    assert "ph-kv" in mid and "نزدیک‌ترین استان" in mid, "me-out shape"
    new_me = ('ME = await jget("/api/geo");\n'
        '      var meRows = [["ASN", \'<b class="ph-mono">\' + esc(ME.asn||"—") + "</b>"],\n'
        '        ["سازمان", "<b>" + esc(ME.org||"—") + "</b>"],\n'
        '        ["شهرِ IP", "<b>" + esc(ME.city||"—") + "</b>"],\n'
        '        ["استانِ IP", esc(ME.region||"—")],\n'
        '        ["لبهٔ کلادفلر", \'<b class="ph-mono">\' + esc(ME.colo||"—") + "</b>"],\n'
        '        ["RTT خط تو تا لبه", "<b>" + (ME.tcpRtt==null?"—":fa(ME.tcpRtt)+" ms") + "</b>"]];\n'
        '      if (ME.carrier) meRows.push(["📶 اپراتور", "<b>" + esc(ME.carrier.fa) + \'</b> <span class="ph-badge">\' + esc(ME.carrier.type) + " · از " + esc(ME.carrier.match) + "</span>"]);\n'
        '      else meRows.push(["📶 اپراتور", "خودکار تشخیص داده نشد — خودت انتخاب کن."]);\n'
        '      if (ME.province) meRows.push(["📍 نزدیک‌ترین استان", "<b>" + esc(ME.province.fa) + "</b>" + (ME.province.exact ? "" : " <span class=\'ph-badge\'>تقریبی</span>")]);\n'
        '      var html = \'<table class="ph-facts" style="margin-top:6px">\' + meRows.map(function(rr){ return "<tr><td>" + rr[0] + "</td><td>" + rr[1] + "</td></tr>"; }).join("") + "</table>";\n      ')
    src = src[:a] + new_me + src[b:]
    return src, True


def inline_tools3(src):
    block = (ROOT / "web" / "tools3-block.html").read_text(encoding="utf-8")
    parts = block.split("<!--PH3-SCRIPT-->")
    assert len(parts) == 2, "PH3-SCRIPT marker missing"
    markup, script = parts[0].rstrip() + "\n", parts[1].strip() + "\n"
    anchor1 = '<script>\n/* =========== ⚡ پینگ‌هاب ۲.۰'
    anchor2 = '''  if (location.protocol !== "file:" && !/appassets\\.androidplatform\\.net$/.test(location.hostname) && "serviceWorker" in navigator){
    navigator.serviceWorker.register("/sw.js").catch(function(){});
  }
})();
</script>
'''
    assert anchor1 in src, "anchor1"
    assert anchor2 in src, "anchor2"
    src = src.replace(anchor1, markup + anchor1, 1)
    src = src.replace(anchor2, anchor2 + "\n" + script, 1)
    return src


# ------------------------------------------------------------------ اجرا
report = []
for page in PAGES:
    src = (ROOT / "cloudflare" / "_tmp_page.html").read_text(encoding="utf-8") if False else page.read_text(encoding="utf-8")
    src = src.replace("</head>", DESIGN_CSS + "</head>", 1)
    src = src.replace("</head>", NAV_CSS + "</head>", 1)
    src = src.replace("</head>", LAYOUT_CSS + "</head>", 1)
    src = src.replace("</body>\n</html>", HERO_JS + "</body>\n</html>", 1)
    src = src.replace("</body>\n</html>", NAV_HTML + NAV_JS + FIT9_JS + MN_LAYER + "</body>\n</html>", 1)
    src, b1 = patch_bgp(src)
    src, b2 = patch_doh(src)
    src, b3 = patch_games(src)
    src, b3b = patch_impact_fallback(src)
    src, b4 = patch_preflight_page(src)
    src, b5 = patch_round9(src)
    src = inline_tools3(src)
    page.write_text(src, encoding="utf-8")
    n_panels = len(set(re.findall(r'id="ph-p(\d+)"', src)))
    report.append(f"{page.name}: {len(src):,} bytes · panels={n_panels} · bgp={b1} doh={b2} games={b3} pf={b4} fit9={b5}")

for r in report:
    print(r)
