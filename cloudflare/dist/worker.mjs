/**
 * پینگ‌هاب (PingHub) — Cloudflare Worker
 * =============================================================================
 * یک Worker که هم‌زمان سه نقش دارد:
 *   ۱) سایت عمومی  → /            (تست DNS روی گوشی خود بازدیدکننده)
 *   ۲) مینی‌اپ تلگرام → /app       (با اعتبارسنجی initData)
 *   ۳) وب‌هوک بات تلگرام → /tg/webhook  (@Pinghab_bot)
 * و علاوه بر این:
 *   /api/me          → اطلاعات خط کاربر (ASN، اپراتور، لبهٔ کلادفلر)
 *   /api/edge        → سلامت سرورهای DNS از دید لبهٔ کلادفلر
 *   /api/save        → ذخیرهٔ نتیجه در KV + ساخت لینک اشتراک
 *   /r/<id>          → صفحهٔ اشتراک‌پذیر نتیجه
 *   /tg/setup?key=   → تنظیم مجدد وب‌هوک/دستورها/دکمهٔ منو
 *
 * متغیرهای محیطی (binding):
 *   DNSRADAR_KV (KV) · TG_TOKEN (secret) · TG_SECRET (secret) · ADMIN_KEY (secret)
 *
 * اندازه‌گیری «پینگ واقعی» عمداً در مرورگر کاربر انجام می‌شود (نه در سرور)،
 * چون فقط این‌طوری عدد مربوط به «خط خودِ کاربر» است.
 */

import { connect } from "cloudflare:sockets";

const APP_HTML = "<!DOCTYPE html>\n<html lang=\"fa\" dir=\"rtl\">\n<head>\n<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n<title>پینگ‌هاب — کدام DNS برای اینترنت تو بهتر است؟</title>\n<meta property=\"og:title\" content=\"پینگ‌هاب | تست و انتخاب بهترین DNS\">\n<meta property=\"og:description\" content=\"تست زندهٔ DNS روی گوشی خودت + مقایسهٔ منطقه‌ای. رایگان و بدون فیلترشکن.\">\n<style>\n  :root{\n    --bg:#070c18; --card:#101b30; --card2:#0d1729; --line:#1d2c48; --tx:#e9effb; --mut:#8ba0c4;\n    --great:#12b981; --good:#4ade80; --ok:#a3e635; --meh:#f59e0b; --weak:#f97316; --dead:#ef4444;\n    --acc:#38bdf8; --violet:#8b5cf6; --pink:#e879f9;\n  }\n  *{box-sizing:border-box;-webkit-tap-highlight-color:transparent}\n  html,body{margin:0;padding:0}\n  body{background:radial-gradient(1100px 480px at 50% -140px,#12233f 0%,#070c18 62%);color:var(--tx);\n       font-family:Tahoma,Vazirmatn,\"Segoe UI\",system-ui,sans-serif;line-height:1.75;font-size:14.5px;\n       min-height:100vh;padding-bottom:30px}\n  .wrap{max-width:760px;margin:0 auto;padding:14px 12px 40px}\n  h1{font-size:20px;margin:0;letter-spacing:.2px}\n  h2{font-size:15.5px;margin:20px 0 8px;padding-right:8px;border-right:4px solid var(--acc)}\n  h3{font-size:14px;margin:14px 0 6px}\n  .sub{color:var(--mut);font-size:12.5px;line-height:1.6}\n  .mut{color:var(--mut)}\n  .head{background:linear-gradient(150deg,#122343,#0d1729);border:1px solid var(--line);border-radius:16px;padding:13px 14px}\n  .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}\n  .between{justify-content:space-between}\n  button{border:1px solid var(--line);background:#152340;color:var(--tx);border-radius:11px;padding:9px 13px;\n         font-size:13.5px;font-family:inherit;cursor:pointer;transition:.15s}\n  button:hover{background:#1b2c52;border-color:#2b4470}\n  button:active{transform:scale(.98)}\n  button.primary{background:linear-gradient(135deg,#0ea5e9,#2563eb);border:none;font-weight:700;font-size:15px;\n                 padding:11px 18px;box-shadow:0 10px 24px -12px #0ea5e9}\n  button.ghost{background:transparent}\n  button:disabled{opacity:.55;cursor:not-allowed}\n  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:11px 12px}\n  .kpi{flex:1;min-width:120px}\n  .kpi b{display:block;font-size:19px;font-variant-numeric:tabular-nums}\n  .kpi span{color:var(--mut);font-size:11.5px}\n  .badge{display:inline-block;font-size:10.5px;padding:1px 7px;border-radius:999px;border:1px solid var(--line);\n         margin-left:4px;background:#0e1a2e;color:#cbd5e1;white-space:nowrap}\n  .b-great{border-color:#1d7a5f;color:#7ff0c0}.b-good{border-color:#2d7a2d;color:#b6f2b6}\n  .b-ok{border-color:#5a7a1d;color:#e2f7a8}.b-meh{border-color:#b45309;color:#fcd34d}\n  .b-weak{border-color:#c2410c;color:#fdba74}.b-dead{border-color:#7f1d1d;color:#fca5a5;background:#2a1113}\n  .dot{width:8px;height:8px;border-radius:50%;background:var(--great);display:inline-block;\n       box-shadow:0 0 0 0 rgba(18,185,129,.7);animation:pulse 1.7s infinite}\n  @keyframes pulse{70%{box-shadow:0 0 0 9px rgba(18,185,129,0)}100%{box-shadow:0 0 0 0 rgba(18,185,129,0)}}\n  .pill{display:inline-flex;align-items:center;gap:6px;border:1px solid var(--line);background:#0f1c31;\n        border-radius:999px;padding:6px 11px;font-size:12px;cursor:pointer;transition:.15s;white-space:nowrap}\n  .pill:hover{border-color:#2b4470;background:#16264a}\n  .pill.on{background:linear-gradient(135deg,#123c5a,#0f2f46);border-color:#2a7fa8;color:#d8f1ff}\n  .pill .m{font-variant-numeric:tabular-nums;font-weight:700}\n  table{width:100%;border-collapse:separate;border-spacing:0 5px;font-size:12.8px}\n  th{color:var(--mut);font-size:11px;font-weight:600;text-align:right;padding:3px 6px;white-space:nowrap}\n  td{background:var(--card);padding:8px 6px;border-top:1px solid var(--line);border-bottom:1px solid var(--line);vertical-align:top}\n  td:first-child{border-right:1px solid var(--line);border-radius:0 11px 11px 0}\n  td:last-child{border-left:1px solid var(--line);border-radius:11px 0 0 11px}\n  .num{font-variant-numeric:tabular-nums;direction:ltr;text-align:center;white-space:nowrap}\n  .ping{font-size:16.5px;font-weight:700;font-variant-numeric:tabular-nums;direction:ltr}\n  .barwrap{position:relative;height:15px;background:#0d1729;border:1px solid var(--line);border-radius:6px;overflow:hidden;min-width:58px}\n  .bar{height:100%;transition:width .5s ease}\n  .barval{position:absolute;inset:0;text-align:center;font-size:10.5px;font-variant-numeric:tabular-nums}\n  .g-great{background:linear-gradient(90deg,#0d9488,#12b981)}.g-good{background:linear-gradient(90deg,#15803d,#4ade80)}\n  .g-ok{background:linear-gradient(90deg,#4d7c0f,#a3e635)}.g-meh{background:linear-gradient(90deg,#b45309,#f59e0b)}\n  .g-weak{background:linear-gradient(90deg,#c2410c,#f97316)}.g-dead{background:#3f1d1d}\n  .note{background:#0d1729;border:1px dashed var(--line);border-radius:13px;padding:11px 12px;color:#c3d3ee;font-size:12.5px}\n  .warn{border-color:#7c2d12;background:#1f1206}\n  .info{border-color:#1e40af;background:#0b1a33}\n  .good{border-color:#1d7a5f;background:#0b2a22}\n  code{direction:ltr;display:inline-block;background:#0d1729;padding:1px 6px;border-radius:6px;\n       font-family:ui-monospace,Consolas,monospace;font-size:12px}\n  .foot{color:var(--mut);font-size:11.5px;text-align:center;margin-top:24px;line-height:1.9}\n  a{color:var(--acc)}\n  .hide-s{display:table-cell}\n  @media(max-width:520px){.hide-s{display:none}}\n  .spark{display:block}\n  .idcard{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:7px;margin-top:9px}\n  .idcell{background:#0d1729;border:1px solid var(--line);border-radius:10px;padding:6px 9px}\n  .idcell span{display:block;color:var(--mut);font-size:10.5px}\n  .idcell b{font-size:12.8px}\n  .adv{background:linear-gradient(150deg,#0e2a22,#0d1729);border:1px solid #1d7a5f;border-radius:14px;padding:11px 13px}\n  .adv.bad{background:linear-gradient(150deg,#2a1414,#0d1729);border-color:#7f1d1d}\n  .tabs{display:flex;gap:6px;margin:10px 0 4px}\n  .tab{flex:1;text-align:center;border:1px solid var(--line);border-radius:11px;padding:7px 4px;font-size:12.5px;\n       cursor:pointer;background:#0f1c31}\n  .tab.on{background:linear-gradient(135deg,#123c5a,#0f2f46);border-color:#2a7fa8}\n  #toast{position:fixed;bottom:16px;right:50%;transform:translateX(50%);background:#0d9488;color:#04211a;\n         font-weight:700;padding:9px 16px;border-radius:12px;font-size:13px;opacity:0;pointer-events:none;\n         transition:.25s;z-index:99}\n  #toast.show{opacity:1;bottom:26px}\n  .inline{display:inline}\n</style>\n<script src=\"https://telegram.org/js/telegram-web-app.js\" onerror=\"window.__noTgSdk=1\"></script>\n</head>\n<body>\n<div class=\"wrap\">\n\n  <div class=\"head\">\n    <div class=\"row between\">\n      <div class=\"row\">\n        <h1>📡 پینگ‌هاب</h1>\n        <span class=\"badge b-great\" id=\"liveBadge\"><span class=\"dot\"></span> زنده</span>\n      </div>\n      <div class=\"row\">\n        <button class=\"ghost\" id=\"tgTheme\" title=\"تم\" style=\"display:none\">🌓</button>\n      </div>\n    </div>\n    <div class=\"sub\" style=\"margin-top:5px\">\n      تست <b>واقعی</b> روی گوشی خودت: پینگ، جیتر و افت بستهٔ هر DNS + مقایسهٔ <b>منطقه‌ای</b>.\n      هیچ VPN و هیچ فیلترشکنی لازم نیست.\n    </div>\n    <div class=\"idcard\" id=\"idcard\">\n      <div class=\"idcell\"><span>خط اینترنت تو</span><b id=\"isp\">در حال تشخیص…</b></div>\n      <div class=\"idcell\"><span>شبکه / ASN</span><b id=\"asn\">—</b></div>\n      <div class=\"idcell\"><span>موقعیت</span><b id=\"geo\">—</b></div>\n      <div class=\"idcell\"><span>نزدیک‌ترین لبهٔ کلادفلر</span><b id=\"colo\">—</b></div>\n    </div>\n  </div>\n\n  <div class=\"row\" style=\"margin-top:12px\">\n    <button class=\"primary\" id=\"run\">▶ تست کن (۲۰ ثانیه)</button>\n    <button id=\"auto\">🔁 تست زنده خودکار</button>\n    <button id=\"save\">💾 ذخیره و اشتراک</button>\n  </div>\n  <div class=\"sub\" id=\"status\" style=\"margin-top:7px\">آماده — دکمهٔ تست را بزن.</div>\n\n  <div class=\"row\" style=\"margin-top:12px\">\n    <div class=\"card kpi\"><b id=\"k-best\">—</b><span>بهترین انتخاب الان</span><div class=\"sub\" id=\"k-best-ip\">—</div></div>\n    <div class=\"card kpi\"><b id=\"k-quality\">—</b><span>قدرت آن سرور</span><div class=\"sub\">امتیاز ۰ تا ۱۰۰</div></div>\n    <div class=\"card kpi\"><b id=\"k-region\">—</b><span>سریع‌ترین منطقه</span><div class=\"sub\" id=\"k-region-name\">—</div></div>\n  </div>\n\n  <div class=\"adv\" id=\"advice\" style=\"margin-top:12px\">\n    <b>🎯 نتیجه اینجا می‌آید</b>\n    <div class=\"sub\">بعد از تست، بهترین DNS برای خط تو، با دلیل و نحوهٔ تنظیمش، همین‌جا نوشته می‌شود.</div>\n  </div>\n\n  <h2>🌐 نتیجهٔ سرورهای DNS</h2>\n  <div class=\"row\" id=\"regionPills\"></div>\n  <table>\n    <thead><tr>\n      <th>سرور</th><th>پینگ</th><th>قدرت</th><th class=\"hide-s\">روند</th><th class=\"hide-s\">جیتر</th><th class=\"hide-s\">افت</th>\n    </tr></thead>\n    <tbody id=\"rows\"><tr><td colspan=\"6\" class=\"sub\">هنوز تستی اجرا نشده.</td></tr></tbody>\n  </table>\n\n  <h2>🌍 تأخیر مسیر تا هر منطقه (تقریبی)</h2>\n  <div class=\"note\" style=\"margin-bottom:8px\">\n    این بخش نشان می‌دهد از <b>خط اینترنت تو</b> تا هر منطقه چند میلی‌ثانیه فاصله است.\n    مرورگر نمی‌تواند پینگ خام بزند، پس این اعداد شامل زمان گشایش اتصال امن (TLS) هستند و <b>تقریبی</b>اند —\n    اما نسبتشان به هم درست است: هر جا کمتر بود، سرورهای بازی همان منطقه برایت نزدیک‌ترند.\n  </div>\n  <table><tbody id=\"regionRows\"><tr><td class=\"sub\">در حال اندازه‌گیری…</td></tr></tbody></table>\n\n  <h2>🩺 سلامت سرورها از دید اینترنت (مرجع)</h2>\n  <div class=\"note\" style=\"margin-bottom:8px\">\n    این اعداد از <b>لبهٔ شبکهٔ کلادفلر</b> گرفته می‌شوند، نه از گوشی تو — برای همین فقط می‌گویند یک DNS\n    «سالم و در دسترس» است یا نه. (سرورهای ایرانی از بیرون ایران جواب نمی‌دهند؛ این طبیعی است.)\n  </div>\n  <div id=\"edgeBox\" class=\"card sub\">برای دیدن، دکمهٔ زیر را بزن.</div>\n  <div class=\"row\" style=\"margin-top:8px\"><button id=\"edgeBtn\">🩺 بررسی سلامت</button></div>\n\n  <h2>📘 راهنمای واقعی (بدون شایعه)</h2>\n  <div class=\"note\">\n    <b>۱) DNS پینگ داخل مچ بازی را کم نمی‌کند.</b> بازی بعد از پیدا کردن سرور، با IP بازی وصل می‌شود.\n    DNS این‌ها را بهتر می‌کند: ورود به بازی، رفع تحریم، سرعت دانلود آپدیت، خطاهای لابی.<br>\n    <b>۲) برای پینگ واقعی:</b> خروجی تونل نزدیک سرور بازی (دبی/بحرین → ترکیه/عراق)، پروتکل UDP/WireGuard،\n    MTU درست، وای‌فای ۵GHz، بستن اپ‌های پس‌زمینه، خنک بودن گوشی.<br>\n    <b>۳) افت بسته از پینگ مهم‌تر است.</b> اگر ستون «افت» بالا بود، آن DNS را استفاده نکن حتی اگر سریع باشد.<br>\n    <b>۴) DNS خصوصی اندروید:</b> تنظیمات › شبکه و اینترنت › DNS خصوصی › «نام میزبان ارائه‌دهنده» →\n    مثل <code>shecan.ir</code> یا <code>dns.google</code> یا <code>one.one.one.one</code><br>\n    <b>۵) امنیت:</b> از DNS ناشناس استفاده نکن؛ می‌تواند تو را به سایت جعلی ببرد.\n  </div>\n\n  <div class=\"foot\">\n    پینگ‌هاب · اندازه‌گیری محلی در مرورگر خودت · بدون ذخیره‌سازی داده‌های شخصی<br>\n    <span id=\"links\"></span>\n  </div>\n</div>\n<div id=\"toast\"></div>\n\n<script>\n\"use strict\";\n/* ============================ ابزارها ============================ */\nconst $ = id => document.getElementById(id);\nconst FA = s => String(s).replace(/[0-9]/g, d => \"۰۱۲۳۴۵۶۷۸۹\"[d]);\nconst fmt = (v,d=1) => (v===null||v===undefined||isNaN(v)) ? \"—\" : FA(Number(v).toFixed(d));\nconst COLORS = {great:\"#12b981\", good:\"#4ade80\", ok:\"#a3e635\", meh:\"#f59e0b\", weak:\"#f97316\", dead:\"#ef4444\"};\nconst TG = (window.Telegram && window.Telegram.WebApp) ? window.Telegram.WebApp : null;\nfunction toast(msg){ const t=$(\"toast\"); t.textContent=msg; t.classList.add(\"show\"); setTimeout(()=>t.classList.remove(\"show\"),2200); }\nfunction setupTelegram(){\n  if(!TG) return;\n  try{\n    TG.ready(); TG.expand();\n    if(TG.setHeaderColor) TG.setHeaderColor(\"#0b1120\");\n    if(TG.setBackgroundColor) TG.setBackgroundColor(\"#070c18\");\n    if(TG.colorScheme === \"light\") document.documentElement.style.filter = \"none\";\n  }catch(e){}\n}\nfunction getInitData(){\n  if(TG && TG.initData) return TG.initData;\n  const h = new URLSearchParams(location.hash.replace(/^#/, \"\"));\n  return (h.get(\"tgWebAppData\") || \"\").replace(/^tgWebAppData=/, \"\");\n}\nfunction tgUser(){\n  if(TG && TG.initDataUnsafe && TG.initDataUnsafe.user) return TG.initDataUnsafe.user;\n  try{\n    const d = new URLSearchParams(getInitData());\n    const u = d.get(\"user\"); return u ? JSON.parse(u) : null;\n  }catch(e){ return null; }\n}\n\n/* ============================ سرورهای DoH ============================ */\nconst RESOLVERS = [\n  {id:\"cloudflare\", name:\"کلودفلر\", url:\"https://cloudflare-dns.com/dns-query\", region:\"anycast\", dns:\"1.1.1.1 / 1.0.0.1\", tag:\"بدون سانسور، سریع\"},\n  {id:\"google\",     name:\"گوگل\",     url:\"https://dns.google/dns-query\",        region:\"anycast\", dns:\"8.8.8.8 / 8.8.4.4\", tag:\"پایدار\"},\n  {id:\"quad9\",      name:\"کوآد۹\",    url:\"https://dns.quad9.net/dns-query\",     region:\"anycast\", dns:\"9.9.9.9\", tag:\"ضد بدافزار، بدون لاگ\"},\n  {id:\"adguard\",    name:\"ادگارد\",   url:\"https://dns.adguard-dns.com/dns-query\",region:\"anycast\", dns:\"94.140.14.14\", tag:\"ضد تبلیغ\"},\n  {id:\"dnssb\",      name:\"DNS.SB\",   url:\"https://doh.dns.sb/dns-query\",        region:\"anycast\", dns:\"185.222.222.222\", tag:\"بدون لاگ\"},\n  {id:\"controld\",   name:\"ControlD\", url:\"https://freedns.controld.com/p0\",    region:\"anycast\", dns:\"76.76.2.0\", tag:\"سریع\"},\n  {id:\"dns0\",       name:\"DNS0.eu\",  url:\"https://dns0.eu/dns-query\",          region:\"anycast\", dns:\"193.110.81.0\", tag:\"اروپایی، بدون لاگ\"},\n  {id:\"nextdns\",    name:\"NextDNS\",  url:\"https://dns.nextdns.io\",             region:\"anycast\", dns:\"45.90.28.0\", tag:\"قابل شخصی‌سازی\"},\n  {id:\"mullvad\",    name:\"Mullvad\",  url:\"https://dns.mullvad.net/dns-query\",  region:\"anycast\", dns:\"194.242.2.2\", tag:\"حریم خصوصی\"},\n  {id:\"cffamily\",   name:\"کلودفلر خانواده\", url:\"https://family.cloudflare-dns.com/dns-query\", region:\"family\", dns:\"1.1.1.3\", tag:\"فیلتر بزرگسال\"},\n  {id:\"adguardfam\", name:\"ادگارد خانواده\", url:\"https://family.adguard-dns.com/dns-query\",     region:\"family\", dns:\"94.140.14.15\", tag:\"تبلیغ+بزرگسال\"},\n  {id:\"cleanbr\",    name:\"CleanBrowsing\",  url:\"https://doh.cleanbrowsing.org/doh/security-filter/\", region:\"family\", dns:\"185.228.168.9\", tag:\"امنیتی\"}\n];\nconst REGION_LABEL = {anycast:\"🌐 نزدیک‌ترین لبه\", family:\"🛡 خانواده\", iran:\"🇮🇷 ایران\"};\nconst REGION_NOTE  = {\n  anycast:\"این‌ها هرجای دنیا «لبهٔ» نزدیک به خودت را جواب می‌دهند؛ عددشان یعنی فاصله‌ات تا نزدیک‌ترین مرکز CDN.\",\n  family:\"نسخه‌های فیلترشده برای محتوای نامناسب (مناسب دستگاه بچه‌ها).\",\n  iran:\"سرویس‌های داخلی مخصوص رفع تحریم.\"\n};\n\n/* مقصدهای منطقه‌ای برای سنجش تقریبی مسیر */\nconst REGION_TARGETS = [\n  {region:\"ایران\",        flag:\"🇮🇷\", url:\"https://www.aparat.com/favicon.ico\"},\n  {region:\"ترکیه\",        flag:\"🇹🇷\", url:\"https://www.ttnet.com.tr/favicon.ico\"},\n  {region:\"امارات/خلیج\",  flag:\"🇦🇪\", url:\"https://www.etisalat.ae/favicon.ico\"},\n  {region:\"اروپا (آلمان)\",flag:\"🇩🇪\", url:\"https://www.hetzner.com/favicon.ico\"},\n  {region:\"آسیا (شرق)\",   flag:\"🌏\", url:\"https://www.twnic.tw/favicon.ico\"},\n  {region:\"آمریکا\",       flag:\"🇺🇸\", url:\"https://www.verisign.com/favicon.ico\"}\n];\n\n/* ============================ موتور DNS در مرورگر ============================ */\nfunction buildQuery(name, txid){\n  const labels = name.split(\".\").filter(Boolean);\n  let len = 17; labels.forEach(l => len += 1 + l.length);\n  const buf = new Uint8Array(len), dv = new DataView(buf.buffer);\n  dv.setUint16(0, txid); dv.setUint16(2, 0x0100); dv.setUint16(4, 1);\n  let o = 12;\n  for(const l of labels){ buf[o++] = l.length; for(const ch of l) buf[o++] = ch.charCodeAt(0); }\n  buf[o++] = 0; dv.setUint16(o, 1); dv.setUint16(o+2, 1);\n  return buf;\n}\nfunction parseDns(buf){\n  const out = {rcode:null, a:[], minTtl:null};\n  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);\n  if(buf.byteLength < 12) return out;\n  out.rcode = dv.getUint16(2) & 0xF;\n  const qd = dv.getUint16(4), an = dv.getUint16(6);\n  let i = 12;\n  const skipName = () => {\n    while(i < buf.byteLength){\n      const l = buf[i];\n      if(l === 0){ i++; return; }\n      if((l & 0xC0) === 0xC0){ i += 2; return; }\n      i += l + 1;\n    }\n  };\n  for(let q=0;q<qd;q++){ skipName(); i += 4; }\n  for(let r=0;r<an && i+10<=buf.byteLength;r++){\n    skipName();\n    const type = dv.getUint16(i), ttl = dv.getUint32(i+4), rdlen = dv.getUint16(i+8);\n    i += 10;\n    if(type === 1 && rdlen === 4){\n      out.a.push(`${buf[i]}.${buf[i+1]}.${buf[i+2]}.${buf[i+3]}`);\n      out.minTtl = out.minTtl === null ? ttl : Math.min(out.minTtl, ttl);\n    }\n    i += rdlen;\n  }\n  return out;\n}\nconst TEST_DOMAINS = [\"www.wikipedia.org\",\"www.google.com\",\"www.instagram.com\",\"www.youtube.com\",\"www.microsoft.com\"];\nasync function dohQuery(server, name, timeoutMs){\n  const ctrl = new AbortController();\n  const timer = setTimeout(()=>ctrl.abort(), timeoutMs);\n  const t0 = performance.now();\n  try{\n    const res = await fetch(server.url, {\n      method:\"POST\",\n      headers:{\"Content-Type\":\"application/dns-message\",\"Accept\":\"application/dns-message\"},\n      body: buildQuery(name, Math.floor(Math.random()*65535)),\n      signal: ctrl.signal, cache:\"no-store\", mode:\"cors\", redirect:\"follow\"\n    });\n    const ab = await res.arrayBuffer();\n    const ms = performance.now() - t0;\n    if(!res.ok) return {ok:false, ms, err:\"HTTP \"+res.status};\n    const dns = parseDns(new Uint8Array(ab));\n    if(dns.rcode !== 0 && dns.rcode !== 3) return {ok:false, ms, err:\"rcode \"+dns.rcode};\n    return {ok:true, ms, dns};\n  }catch(e){\n    return {ok:false, ms:null, err: e.name === \"AbortError\" ? \"تایم‌اوت\" : \"مسدود/شبکه\"};\n  }finally{ clearTimeout(timer); }\n}\nconst median = a => { if(!a.length) return null; const s=[...a].sort((x,y)=>x-y), m=s.length>>1;\n  return s.length%2 ? s[m] : (s[m-1]+s[m])/2; };\n\nfunction quality(st){\n  if(st.med === null) return {score:0, grade:\"قطع\", color:\"dead\"};\n  let s = 100;\n  s -= Math.min(55, st.med * 0.45);\n  if(st.jit !== null) s -= Math.min(20, st.jit * 1.2);\n  if(st.loss) s -= st.loss * 60;\n  const score = Math.max(0, Math.min(100, Math.round(s)));\n  const grade = score>=85?\"عالی\":score>=70?\"خیلی خوب\":score>=55?\"خوب\":score>=38?\"متوسط\":\"ضعیف\";\n  const color = score>=85?\"great\":score>=70?\"good\":score>=55?\"ok\":score>=38?\"meh\":\"weak\";\n  return {score, grade, color};\n}\nfunction sparkline(hist, color, w=92, h=22){\n  const vals = (hist||[]).filter(v => v !== null && v !== undefined);\n  if(vals.length < 2) return `<svg width=\"${w}\" height=\"${h}\"></svg>`;\n  const min = Math.min(...vals), max = Math.max(...vals), span = (max-min)||1;\n  const pts = vals.map((v,i)=>[2 + i/(vals.length-1)*(w-4), h-3-(1-(v-min)/span)*(h-7)]);\n  const line = pts.map(p=>p[0].toFixed(1)+\",\"+p[1].toFixed(1)).join(\" \");\n  return `<svg class=\"spark\" width=\"${w}\" height=\"${h}\">\n    <polygon points=\"2,${h-2} ${line} ${(w-2)},${h-2}\" fill=\"${color}\" opacity=\".15\"></polygon>\n    <polyline points=\"${line}\" fill=\"none\" stroke=\"${color}\" stroke-width=\"1.7\"></polyline>\n    <circle cx=\"${pts.at(-1)[0].toFixed(1)}\" cy=\"${pts.at(-1)[1].toFixed(1)}\" r=\"2.2\" fill=\"${color}\"></circle></svg>`;\n}\n\n/* ============================ وضعیت برنامه ============================ */\nconst state = {\n  results: new Map(),      // id -> {med,jit,loss,ok,total,history:[]}\n  regions: [],             // نتایج منطقه‌ای\n  me: null,\n  running: false,\n  auto: false,\n  filter: \"all\",\n  lastRun: null\n};\n\n/* ============================ تشخیص خط اینترنت ============================ */\nasync function detectMe(){\n  try{\n    const r = await fetch(\"api/me\", {cache:\"no-store\"});\n    const j = await r.json();\n    state.me = j;\n    const org = (j.asOrganization || \"\").trim();\n    const persian = mapISP(org, j.asn);\n    $(\"isp\").textContent = persian || (org || \"ناشناس\");\n    $(\"asn\").textContent  = j.asn ? (\"AS\" + j.asn) : \"—\";\n    $(\"geo\").textContent  = [j.city, j.country].filter(Boolean).join(\"، \") || \"—\";\n    $(\"colo\").textContent = j.colo ? (j.colo + \" (\" + (COLO[j.colo] || \"لبهٔ کلادفلر\") + \")\") : \"—\";\n  }catch(e){\n    $(\"isp\").textContent = \"در دسترس نیست\";\n  }\n}\nconst COLO = {DXB:\"دبی\", FRA:\"فرانکفورت\", IST:\"استانبول\", AMS:\"آمستردام\", LHR:\"لندن\", CDG:\"پاریس\",\n              BOM:\"بمبئی\", SIN:\"سنگاپور\", IAD:\"واشینگتن\", DME:\"مسکو\", WAW:\"ورشو\", ARN:\"استکهلم\", ZRH:\"زوریخ\"};\nfunction mapISP(org, asn){\n  const o = (org || \"\").toLowerCase();\n  if(/irancell|iran cell/.test(o)) return \"ایرانسل\";\n  if(/mobile communication|mcci|mci\\b|همراه/.test(o)) return \"همراه اول\";\n  if(/rightel/.test(o)) return \"رایتل\";\n  if(/telecommunication company of iran|tci\\b/.test(o)) return \"مخابرات (TCI)\";\n  if(/shatel/.test(o)) return \"شاتل\";\n  if(/asiatech/.test(o)) return \"آسیاتک\";\n  if(/pars ?online/.test(o)) return \"پارس‌آنلاین\";\n  if(/hiweb/.test(o)) return \"های‌وب\";\n  if(/respina/.test(o)) return \"رسپینا\";\n  if(/mobile telecommunication|mtn/.test(o)) return \"MTN/ایرانسل\";\n  return null;\n}\n\n/* ============================ اجرای تست ============================ */\nfunction setStatus(t){ $(\"status\").textContent = t; }\n\nasync function runOnce(silent){\n  if(state.running) return;\n  state.running = true;\n  $(\"run\").disabled = true;\n  setStatus(\"در حال تست \" + FA(RESOLVERS.length) + \" سرور DNS روی گوشی تو…\");\n\n  // نتایج منطقه‌ای (موازی با تست DNS)\n  measureRegions();\n\n  const results = [];\n  let done = 0;\n  const CONC = 3;\n  const queue = [...RESOLVERS];\n  async function worker(){\n    while(queue.length){\n      const srv = queue.shift();\n      const prev = state.results.get(srv.id) || {med:null, jit:null, loss:1, ok:0, total:0, history:[]};\n      const lats = [];\n      let tried = 0, losses = 0;\n      const warm = await dohQuery(srv, TEST_DOMAINS[0], 7000);   // گرم‌کردن اتصال TLS\n      if(!warm.ok) losses++;\n      tried++;\n      for(let i=0;i<5;i++){\n        const name = TEST_DOMAINS[Math.floor(Math.random()*TEST_DOMAINS.length)];\n        const r = await dohQuery(srv, name, 7000);\n        tried++;\n        if(r.ok) lats.push(r.ms); else losses++;\n        await new Promise(x=>setTimeout(x,35));\n      }\n      const med = median(lats);\n      const jit = lats.length ? lats.reduce((a,b)=>a+Math.abs(b-med),0)/lats.length : null;\n      const st = {\n        med, jit,\n        loss: tried ? losses/tried : 1,\n        ok: lats.length, total: tried,\n        history: [...(prev.history||[]), med].slice(-30)\n      };\n      state.results.set(srv.id, st);\n      results.push({srv, st});\n      done++;\n      setStatus(`تست شد: ${FA(done)} از ${FA(RESOLVERS.length)} — ${srv.name}…`);\n      renderTable();\n    }\n  }\n  await Promise.all(Array.from({length:CONC}, worker));\n\n  state.lastRun = {when: Date.now(), results: results.map(r=>({...r.srv, ...r.st}))};\n  renderAll(true);\n  $(\"run\").disabled = false;\n  state.running = false;\n  setStatus(silent ? \"به‌روزرسانی زنده انجام شد ✓\" : \"تست تمام شد ✓ — نتیجهٔ زیر را ببین و ذخیره کن.\");\n}\n\n/* سنجش تقریبی مسیر منطقه‌ای با no-cors */\nasync function measureRegions(){\n  const out = [];\n  for(const t of REGION_TARGETS){\n    const lats = [];\n    for(let i=0;i<3;i++){\n      const ctrl = new AbortController();\n      const timer = setTimeout(()=>ctrl.abort(), 6000);\n      const t0 = performance.now();\n      try{\n        await fetch(t.url + \"?cb=\" + Math.random(), {mode:\"no-cors\", cache:\"no-store\", signal:ctrl.signal});\n        lats.push(performance.now() - t0);\n      }catch(e){ /* ناموفق */ }\n      clearTimeout(timer);\n      await new Promise(x=>setTimeout(x,50));\n    }\n    out.push({...t, ms: median(lats), ok: lats.length});\n  }\n  state.regions = out;\n  renderRegions();\n}\n\n/* ============================ رندر ============================ */\nfunction renderAll(final){\n  const alive = [...state.results.entries()]\n    .map(([id, st]) => ({srv: RESOLVERS.find(r=>r.id===id), st}))\n    .filter(x => x.st.med !== null)\n    .sort((a,b) => a.st.med - b.st.med);\n\n  if(alive.length){\n    const best = alive[0], q = quality(best.st);\n    $(\"k-best\").innerHTML = fmt(best.st.med) + '<span class=\"sub\" style=\"font-size:11px\"> ms</span>';\n    $(\"k-best-ip\").innerHTML = best.srv.name + '<div class=\"sub\" style=\"direction:ltr\">' + best.srv.dns + '</div>';\n    $(\"k-quality\").innerHTML = FA(q.score) + '<span class=\"sub\" style=\"font-size:11px\">/۱۰۰</span>';\n  }\n  const fastestRegion = state.regions.filter(r=>r.ms!==null).sort((a,b)=>a.ms-b.ms)[0];\n  if(fastestRegion){\n    $(\"k-region\").innerHTML = fmt(fastestRegion.ms, 0) + '<span class=\"sub\" style=\"font-size:11px\"> ms</span>';\n    $(\"k-region-name\").textContent = fastestRegion.flag + \" \" + fastestRegion.region;\n  }\n  $(\"best-holder\")?.remove();\n  renderRegions(); renderTable(); renderPills(); if(final) renderAdvice(alive);\n}\n\nfunction renderPills(){\n  const keys = [\"all\", ...new Set([...state.results.keys()].map(id => (RESOLVERS.find(r=>r.id===id)||{}).region))];\n  const order = [\"all\",\"anycast\",\"family\"];\n  keys.sort((a,b)=>order.indexOf(a)-order.indexOf(b));\n  $(\"regionPills\").innerHTML = keys.map(k=>{\n    const label = k===\"all\" ? \"همه\" : (REGION_LABEL[k] || k);\n    const arr = k===\"all\" ? [...state.results.values()]\n      : [...state.results.entries()].filter(([id])=> (RESOLVERS.find(r=>r.id===id)||{}).region===k).map(([,v])=>v);\n    const good = arr.filter(s=>s.med!==null);\n    const bestMs = good.length ? Math.min(...good.map(s=>s.med)) : null;\n    return `<span class=\"pill ${state.filter===k?'on':''}\" data-k=\"${k}\" title=\"${REGION_NOTE[k]||''}\">\n      ${label} <span class=\"m\">${bestMs!==null?fmt(bestMs,0)+' ms':'—'}</span></span>`;\n  }).join(\"\");\n  $(\"regionPills\").querySelectorAll(\".pill\").forEach(p=>p.onclick=()=>{ state.filter=p.dataset.k; renderPills(); renderTable(); });\n}\n\nfunction renderTable(){\n  let list = [...state.results.entries()].map(([id, st]) => ({srv: RESOLVERS.find(r=>r.id===id), st}));\n  if(state.filter !== \"all\") list = list.filter(x => x.srv && x.srv.region === state.filter);\n  list.sort((a,b)=> (a.st.med===null)-(b.st.med===null) || (a.st.med??9e9)-(b.st.med??9e9));\n  if(!list.length){ $(\"rows\").innerHTML = `<tr><td colspan=\"6\" class=\"sub\">داده‌ای برای این فیلتر نیست.</td></tr>`; return; }\n  $(\"rows\").innerHTML = list.map(({srv, st})=>{\n    const q = quality(st), c = COLORS[q.color];\n    const dead = st.med === null;\n    return `<tr>\n      <td><b>${srv.name}</b><div class=\"sub\" style=\"direction:ltr\">${srv.dns}</div>\n          <div class=\"sub\">${srv.tag}</div></td>\n      <td class=\"num\"><span class=\"ping\" style=\"color:${c}\">${dead?\"—\":fmt(st.med)}</span>\n          <div><span class=\"badge b-${q.color}\">${q.grade}</span></div></td>\n      <td><div class=\"barwrap\"><div class=\"bar g-${q.color}\" style=\"width:${Math.max(3,q.score)}%\"></div>\n          <span class=\"barval\">${FA(q.score)}</span></div></td>\n      <td class=\"hide-s\">${sparkline(st.history, c)}</td>\n      <td class=\"num hide-s\">${fmt(st.jit)}</td>\n      <td class=\"num hide-s\" style=\"color:${st.loss>0.25?'#fca5a5':'inherit'}\">${FA(Math.round(st.loss*100))}٪</td>\n    </tr>`;\n  }).join(\"\");\n}\n\nfunction renderRegions(){\n  if(!state.regions.length){ $(\"regionRows\").innerHTML = `<tr><td class=\"sub\">در حال اندازه‌گیری…</td></tr>`; return; }\n  const max = Math.max(...state.regions.map(r=>r.ms||0), 1);\n  $(\"regionRows\").innerHTML = state.regions.map(r=>{\n    const dead = r.ms === null;\n    const pct = dead ? 0 : Math.max(4, 100 - (r.ms/max)*100);\n    const col = dead ? \"var(--dead)\" : r.ms<80?\"linear-gradient(90deg,#0d9488,#12b981)\"\n              : r.ms<160?\"linear-gradient(90deg,#4d7c0f,#a3e635)\":\"linear-gradient(90deg,#c2410c,#f97316)\";\n    return `<tr><td style=\"min-width:150px\">${r.flag} <b>${r.region}</b>\n        <div class=\"sub\">${dead?\"دسترسی نداشت\":\"تقریبی (شامل TLS)\"}</div></td>\n      <td class=\"num\" style=\"width:64px\"><span class=\"ping\" style=\"color:${dead?'#ef4444':'inherit'}\">${dead?\"—\":fmt(r.ms,0)}</span></td>\n      <td><div class=\"barwrap\"><div class=\"bar\" style=\"width:${pct}%;background:${col}\"></div>\n          <span class=\"barval\">${dead?\"\":FA(Math.round(r.ms))+\" ms\"}</span></div></td></tr>`;\n  }).join(\"\");\n}\n\nfunction renderAdvice(alive){\n  const box = $(\"advice\");\n  if(!alive.length){\n    box.className = \"adv\";\n    box.innerHTML = `<b>😕 هیچ سروری جواب نداد</b>\n      <div class=\"sub\" style=\"margin-top:6px\">اگر اینترنت داری ولی همه قطع‌اند، احتمالاً شبکه‌ات DoH را می‌بندد.\n      با این حال نتیجهٔ منطقه‌ای پایین صفحه هنوز معتبر است. برای تست کامل (UDP/53) نسخهٔ پایتون پینگ‌هاب را روی\n      کامپیوتر/ترموکس اجرا کن — لینک در پایین صفحه.</div>`;\n    return;\n  }\n  const best = alive[0], q = quality(best.st);\n  const famBest = alive.find(x=>x.srv.region===\"family\");\n  const fastestRegion = state.regions.filter(r=>r.ms!==null).sort((a,b)=>a.ms-b.ms)[0];\n  const isp = state.me ? (mapISP(state.me.asOrganization, state.me.asn) || state.me.asOrganization) : null;\n  const privateDns = best.srv.id === \"cloudflare\" ? \"one.one.one.one\"\n    : best.srv.id === \"google\" ? \"dns.google\"\n    : best.srv.id === \"adguard\" ? \"dns.adguard-dns.com\"\n    : best.srv.id === \"quad9\" ? \"dns.quad9.net\"\n    : best.srv.id === \"dnssb\" ? \"dns.sb\"\n    : best.srv.id === \"controld\" ? \"p2.freedns.controld.com\"\n    : best.srv.id === \"mullvad\" ? \"dns.mullvad.net\"\n    : best.srv.id === \"nextdns\" ? \"dns.nextdns.io\"\n    : best.srv.id === \"cffamily\" ? \"family.cloudflare-dns.com\"\n    : best.srv.id === \"adguardfam\" ? \"family.adguard-dns.com\"\n    : best.srv.id === \"cleanbr\" ? \"security-filter-dns.cleanbrowsing.org\"\n    : best.srv.dns.split(\" / \")[0];\n  box.className = \"adv\";\n  box.innerHTML = `<b>🎯 بهترین DNS برای خط تو الان: ${best.srv.name}</b>\n    <div class=\"row\" style=\"margin-top:8px\">\n      <span class=\"badge b-${q.color}\">${q.grade} · قدرت ${FA(q.score)}/۱۰۰</span>\n      <span class=\"badge\">پینگ ${fmt(best.st.med)} ms</span>\n      <span class=\"badge\">جیتر ${fmt(best.st.jit)} ms</span>\n      <span class=\"badge ${best.st.loss>0.1?'b-meh':'b-great'}\">افت ${FA(Math.round(best.st.loss*100))}٪</span>\n    </div>\n    <div style=\"margin-top:10px\">\n      <b>چطور تنظیمش کنم؟</b>\n      <div class=\"sub\">اندروید ۹+: تنظیمات › شبکه و اینترنت › <b>DNS خصوصی</b> › «نام میزبان ارائه‌دهندهٔ DNS» →\n      <code>${privateDns}</code></div>\n      <div class=\"sub\">آیفون: تنظیمات › وای‌فای › (i) › Configure DNS › Manual →\n      <code>${best.srv.dns.split(\" / \")[0]}</code></div>\n      <div class=\"row\" style=\"margin-top:6px\">\n        <button class=\"ghost\" id=\"copyDns\">📋 کپی ${privateDns}</button>\n      </div>\n    </div>\n    ${isp ? `<div class=\"sub\" style=\"margin-top:9px\">خط تو: <b>${isp}</b>${state.me.colo?` · نزدیک‌ترین لبه: ${state.me.colo}`:\"\"}</div>`:\"\"}\n    ${fastestRegion ? `<div class=\"sub\">نزدیک‌ترین منطقه به تو: <b>${fastestRegion.flag} ${fastestRegion.region}</b>\n        (${fmt(fastestRegion.ms,0)} ms) — سرور بازی را از همین منطقه انتخاب کن.</div>`:\"\"}\n    ${best.srv.id === \"cloudflare\" || best.srv.id === \"google\" ? `<div class=\"note warn\" style=\"margin-top:9px;font-size:12px\">\n       ⚠️ اگر داخل ایران هستی و این سرور در عمل کار نکرد، احتمالاً ISP آن را مخدوش می‌کند؛\n       در اپ اندروید/ویندوز می‌توانی DNS-over-HTTPS را روشن کنی، یا از DNS داخلی (شکن/رادار/الکترو) استفاده کنی.</div>`:\"\"}\n    ${famBest ? `<div class=\"sub\" style=\"margin-top:8px\">🛡 برای دستگاه بچه‌ها: <b>${famBest.srv.name}</b> (${fmt(famBest.st.med)} ms)</div>`:\"\"}\n    ${best.st.loss > 0.25 ? `<div class=\"note warn\" style=\"margin-top:9px\">⚠️ افت بستهٔ این سرور بالاست؛ اگر پینگ دیگری نزدیک همین بود، آن را انتخاب کن.</div>`:\"\"}`;\n  const btn = $(\"copyDns\");\n  if(btn) btn.onclick = () => { navigator.clipboard?.writeText(privateDns); toast(\"کپی شد: \" + privateDns); };\n}\n\n/* ============================ سلامت از لبهٔ کلادفلر ============================ */\nasync function edgeCheck(){\n  $(\"edgeBox\").innerHTML = \"در حال بررسی…\";\n  try{\n    const r = await fetch(\"api/edge\", {cache:\"no-store\"});\n    const j = await r.json();\n    $(\"edgeBox\").innerHTML = `<div class=\"sub\" style=\"margin-bottom:6px\">\n        از لبهٔ <code>${(j.from&&j.from.colo)||\"?\"}</code> — ${FA(j.results.length)} سرور بررسی شد</div>` +\n      j.results.map(x=>`<div class=\"row between\" style=\"border-top:1px solid var(--line);padding:4px 0\">\n        <span>${x.name} <span class=\"sub\" style=\"direction:ltr\">${x.dns||\"\"}</span></span>\n        <span class=\"num\">${x.ok ? `<b style=\"color:${x.ms<100?'var(--great)':'var(--meh)'}\">${FA(x.ms)} ms</b>`\n                                 : `<span class=\"badge b-dead\">پاسخ نداد</span>`}</span></div>`).join(\"\");\n  }catch(e){\n    $(\"edgeBox\").innerHTML = \"بررسی ناموفق بود: \" + e.message;\n  }\n}\n\n/* ============================ ذخیره و اشتراک ============================ */\nasync function saveResult(){\n  if(!state.lastRun){ toast(\"اول تست بگیر!\"); return; }\n  const payload = {\n    initData: getInitData(),\n    me: state.me,\n    results: state.lastRun.results.map(r=>({id:r.id, name:r.name, dns:r.dns, med:r.med, jit:r.jit,\n                                            loss:r.loss, quality: (r.med===null?0:quality(r).score)})),\n    regions: state.regions.map(r=>({region:r.region, flag:r.flag, ms:r.ms}))\n  };\n  toast(\"در حال ذخیره…\");\n  try{\n    const r = await fetch(\"api/save\", {method:\"POST\", headers:{\"Content-Type\":\"application/json\"},\n      body: JSON.stringify(payload)});\n    const j = await r.json();\n    if(!j.ok) throw new Error(j.error || \"خطا\");\n    if(TG && TG.openTelegramLink && j.tgShare){\n      TG.openTelegramLink(j.tgShare);\n    } else if(navigator.share){\n      await navigator.share({title:\"نتیجهٔ پینگ‌هاب من\", url:j.url});\n    } else {\n      await navigator.clipboard?.writeText(j.url);\n      toast(\"لینک کپی شد ✓\");\n    }\n    const linkRow = `<div class=\"note\" style=\"margin-top:10px\">🔗 لینک نتیجهٔ تو:\n      <a href=\"${j.url}\" target=\"_blank\" rel=\"noopener\">${j.url}</a>\n      <div class=\"row\" style=\"margin-top:6px\">\n        <button class=\"ghost\" onclick=\"navigator.clipboard.writeText('${j.url}');\">📋 کپی لینک</button>\n        <a href=\"${j.tgShare||'#'}\" target=\"_blank\" rel=\"noopener\"><button class=\"ghost\">📤 اشتراک در تلگرام</button></a>\n      </div></div>`;\n    $(\"advice\").insertAdjacentHTML(\"beforeend\", linkRow);\n  }catch(e){ toast(\"خطا: \" + e.message); }\n}\n\n/* ============================ راه‌اندازی ============================ */\nsetupTelegram();\nif(TG){ $(\"tgTheme\").style.display = \"inline-block\";\n        $(\"tgTheme\").onclick = () => TG.showPopup ? toast(\"توی تلگرام تم را عوض کن\") : null; }\ndetectMe();\n$(\"run\").onclick = () => runOnce(false);\n$(\"save\").onclick = saveResult;\n$(\"edgeBtn\").onclick = edgeCheck;\n$(\"auto\").onclick = () => {\n  state.auto = !state.auto;\n  $(\"auto\").textContent = state.auto ? \"⏸ توقف تست زنده\" : \"🔁 تست زنده خودکار\";\n  $(\"auto\").style.borderColor = state.auto ? \"var(--great)\" : \"\";\n  if(state.auto){\n    runOnce(false);\n    state.timer = setInterval(()=>{ if(!state.running) runOnce(true); }, 20000);\n  } else {\n    clearInterval(state.timer);\n    setStatus(\"تست خودکار خاموش شد.\");\n  }\n};\nconst repo = \"Alisarani7021/pinghab\";\n$(\"links\").innerHTML = `کد منبع: <a href=\"https://github.com/${repo}\" target=\"_blank\" rel=\"noopener\">github.com/${repo}</a>`;\n// در تلگرام: پاک‌کردن حالت لودینگ\nif(TG){ setTimeout(()=>{ try{TG.expand()}catch(e){} }, 300); }\n</script>\n</body>\n</html>\n";
const REPO = "Alisarani7021/pinghab";
const SITE = "https://pinghab.catclient-59gk2mui.workers.dev";

/* ------------------------------------------------------------------ ابزارها */

const json = (obj, status = 200, extra = {}) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...extra },
  });

const html = (body, status = 200) =>
  new Response(body, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "public, max-age=120" },
  });

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const shortId = () => {
  const alphabet = "abcdefghjkmnpqrstuvwxyz23456789";
  let s = "";
  const rnd = crypto.getRandomValues(new Uint8Array(7));
  for (const b of rnd) s += alphabet[b % alphabet.length];
  return s;
};

async function hmac(keyBytes, msgBytes) {
  const key = await crypto.subtle.importKey("raw", keyBytes, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, msgBytes);
  return new Uint8Array(sig);
}
const enc = new TextEncoder();
const hex = (buf) => [...buf].map((b) => b.toString(16).padStart(2, "0")).join("");

/** اعتبارسنجی initData مینی‌اپ تلگرام (HMAC-SHA256 طبق مستندات رسمی) */
async function verifyInitData(initData, botToken) {
  if (!initData) return { ok: false, user: null, err: "بدون initData" };
  const params = new URLSearchParams(initData);
  const hash = params.get("hash");
  if (!hash) return { ok: false, user: null, err: "hash ندارد" };
  params.delete("hash");
  const dataCheck = [...params.entries()]
    .map(([k, v]) => `${k}=${v}`)
    .sort()
    .join("\n");
  const secret = await hmac(enc.encode("WebAppData"), enc.encode(botToken));
  const sig = hex(await hmac(secret, enc.encode(dataCheck)));
  if (sig !== hash) return { ok: false, user: null, err: "امضا نامعتبر" };
  let user = null;
  try { user = JSON.parse(params.get("user") || "null"); } catch {}
  return { ok: true, user, authDate: params.get("auth_date") };
}

/* ------------------------------------------------------------------ پیام‌رسان تلگرام */

async function tg(env, method, payload) {
  const r = await fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/${method}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  try { return await r.json(); } catch { return { ok: false }; }
}

const BTN = (text, extra) => ({ text, ...extra });
const webAppBtn = (text) => BTN(text, { web_app: { url: `${SITE}/app` } });

function mainKeyboard() {
  return {
    inline_keyboard: [
      [BTN("🚀 باز کردن پینگ‌هاب (تست زنده)", { web_app: { url: `${SITE}/app` } })],
      [BTN("📘 راهنمای کم کردن پینگ", { callback_data: "guide" }),
       BTN("🩺 سلامت DNSها", { callback_data: "health" })],
      [BTN("🌐 سایت", { url: SITE }), BTN("💻 کد منبع", { url: `https://github.com/${REPO}` })],
    ],
  };
}

const WELCOME = `👋 سلام! من <b>پینگ‌هاب</b> هستم.

کاری که می‌کنم: روی <b>گوشی خودت</b> به ده‌ها سرور DNS وصل می‌شوم،
<b>پینگ، جیتر و افت بسته</b>شان را اندازه می‌گیرم و می‌گویم کدام برای <b>خط اینترنت تو</b> بهتر است —
و این‌که شبکه‌ات به کدام <b>منطقه</b> (ایران، ترکیه، اروپا، آمریکا…) نزدیک‌تر است.

<b>دکمهٔ زیر را بزن 👇</b> (هیچ VPN و فیلترشکنی لازم نیست)`;

const GUIDE = `📘 <b>راهنمای واقعیِ پینگ — بدون شایعه</b>

<b>۱) حقیقت مهم:</b> عوض کردن DNS <b>پینگ داخل مچ بازی را کم نمی‌کند</b>. بازی بعد از پیدا کردن سرور با IP بازی وصل می‌شود.
DNS این‌ها را بهتر می‌کند: ✅ ورود به بازی و رفع تحریم ✅ دانلود آپدیت و باز شدن لانچر ✅ خطاهای لابی.

<b>۲) برای پینگ واقعی، به ترتیب اهمیت:</b>
• <b>محل خروجی تونل</b>: برای سرورهای خاورمیانه (دبی/بحرین) خروجی ترکیه/عراق/امارات ≈ ۶۰–۹۰ms؛ آلمان/هلند ≈ ۱۲۰–۱۵۰ms.
• <b>پروتکل</b>: WireGuard/UDP بله، OpenVPN روی TCP نه.
• <b>افت بسته</b> از پینگ مهم‌تر است.
• <b>رِیجن درون بازی</b>: Middle East / Asia را بزن، نه Europe.
• وای‌فای ۵GHz، بستن اپ‌های پس‌زمینه، خنک بودن گوشی، ری‌استارت مودم.

<b>۳) افسانه‌ها:</b> «DNS پینگ را ۵۰٪ کم می‌کند» ❌ · «پاک‌کردن کش DNS پینگ را نصف می‌کند» ❌

<b>۴) امنیت:</b> از DNS ناشناس استفاده نکن؛ می‌تواند تو را به سایت جعلی ببرد.

از دکمهٔ «🚀 باز کردن پینگ‌هاب» استفاده کن تا بهترین DNS <b>برای خط خودت</b> را زنده ببینی.`;

/* ------------------------------------------------------------------ کوئری DNS روی TCP/53 از لبه */

function parseDns(buf) {
  const out = { rcode: null, a: [], minTtl: null };
  const dv = new DataView(buf.buffer ?? buf, buf.byteOffset ?? 0, buf.byteLength);
  if (buf.byteLength < 12) return out;
  out.rcode = dv.getUint16(2) & 0xf;
  const qd = dv.getUint16(4), an = dv.getUint16(6);
  let i = 12;
  const skip = () => {
    while (i < buf.byteLength) {
      const l = buf[i];
      if (l === 0) { i++; return; }
      if ((l & 0xc0) === 0xc0) { i += 2; return; }
      i += l + 1;
    }
  };
  for (let q = 0; q < qd; q++) { skip(); i += 4; }
  for (let r = 0; r < an && i + 10 <= buf.byteLength; r++) {
    skip();
    const type = dv.getUint16(i), ttl = dv.getUint32(i + 4), rdlen = dv.getUint16(i + 8);
    i += 10;
    if (type === 1 && rdlen === 4) {
      out.a.push(`${buf[i]}.${buf[i + 1]}.${buf[i + 2]}.${buf[i + 3]}`);
      out.minTtl = out.minTtl === null ? ttl : Math.min(out.minTtl, ttl);
    }
    i += rdlen;
  }
  return out;
}

function dnsPacket(name, id = Math.floor(Math.random() * 65535)) {
  const labels = name.split(".").filter(Boolean);
  let len = 17;
  labels.forEach((l) => (len += 1 + l.length));
  const buf = new Uint8Array(len), dv = new DataView(buf.buffer);
  dv.setUint16(0, id); dv.setUint16(2, 0x0100); dv.setUint16(4, 1);
  let o = 12;
  for (const l of labels) { buf[o++] = l.length; for (const ch of l) buf[o++] = ch.charCodeAt(0); }
  buf[o++] = 0; dv.setUint16(o, 1); dv.setUint16(o + 2, 1);
  return buf;
}

/** کوئری واقعی DNS روی TCP از لبهٔ کلادفلر (برای دستور /dns در بات) */
async function tcpDnsQuery(ip, name = "www.wikipedia.org", timeoutMs = 4000) {
  const id = Math.floor(Math.random() * 65535);
  const pkt = dnsPacket(name, id);
  const framed = new Uint8Array(pkt.length + 2);
  framed[0] = (pkt.length >> 8) & 0xff; framed[1] = pkt.length & 0xff; framed.set(pkt, 2);
  const t0 = Date.now();
  let sock;
  try {
    sock = connect({ hostname: ip, port: 53 });
    const writer = sock.writable.getWriter();
    const timeout = new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), timeoutMs));
    await Promise.race([writer.write(framed), timeout]);
    const reader = sock.readable.getReader();
    const { value } = await Promise.race([reader.read(), timeout]);
    const ms = Date.now() - t0;
    writer.releaseLock?.(); reader.releaseLock?.();
    if (!value || value.length < 4) return { ok: false, err: "پاسخ کوتاه" };
    const len = (value[0] << 8) | value[1];
    const body = value.slice(2, 2 + len);
    const parsed = parseDns(body);
    return { ok: true, ms, ...parsed };
  } catch (e) {
    const m = String(e?.message || e);
    return { ok: false, err: /cancel|timed? ?out/i.test(m) ? "پاسخی نداد (تایم‌اوت)" : m };
  } finally {
    try { await sock?.close(); } catch {}
  }
}

/* ------------------------------------------------------------------ بررسی لبه‌ای DoH */

const EDGE_RESOLVERS = [
  { id: "cloudflare", name: "کلودفلر", url: "https://cloudflare-dns.com/dns-query", dns: "1.1.1.1" },
  { id: "google", name: "گوگل", url: "https://dns.google/dns-query", dns: "8.8.8.8" },
  { id: "quad9", name: "کوآد۹", url: "https://dns.quad9.net/dns-query", dns: "9.9.9.9" },
  { id: "adguard", name: "ادگارد", url: "https://dns.adguard-dns.com/dns-query", dns: "94.140.14.14" },
  { id: "dnssb", name: "DNS.SB", url: "https://doh.dns.sb/dns-query", dns: "185.222.222.222" },
  { id: "controld", name: "ControlD", url: "https://freedns.controld.com/p0", dns: "76.76.2.0" },
  { id: "dns0", name: "DNS0.eu", url: "https://dns0.eu/dns-query", dns: "193.110.81.0" },
  { id: "shecan", name: "شکن (ایران)", url: "https://free.shecan.ir/dns-query", dns: "178.22.122.100" },
  { id: "electro", name: "الکترو (ایران)", url: "https://dns.electrotm.org/dns-query", dns: "78.157.42.100" },
  { id: "radar", name: "رادار گیم (ایران)", url: "https://10.202.10.10/dns-query", dns: "10.202.10.10" },
  { id: "403", name: "۴۰۳ (ایران)", url: "https://10.202.10.202/dns-query", dns: "10.202.10.202" },
];

async function edgeCheckDoh(list = EDGE_RESOLVERS, name = "www.wikipedia.org") {
  const one = async (r) => {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 5000);
    const t0 = Date.now();
    try {
      const res = await fetch(r.url, {
        method: "POST",
        headers: { "Content-Type": "application/dns-message", "Accept": "application/dns-message" },
        body: dnsPacket(name),
        signal: ctrl.signal,
      });
      const ab = await res.arrayBuffer();
      const ms = Date.now() - t0;
      const p = parseDns(new Uint8Array(ab));
      return { id: r.id, name: r.name, dns: r.dns, ok: res.ok && (p.rcode === 0 || p.rcode === 3), ms };
    } catch (e) {
      return { id: r.id, name: r.name, dns: r.dns, ok: false, ms: null, err: e.name };
    } finally { clearTimeout(t); }
  };
  const results = await Promise.all(list.map(one));
  return results;
}

/* ------------------------------------------------------------------ صفحهٔ اشتراک نتیجه */

function sharePage(doc) {
  const rows = (doc.results || []).filter((r) => r.med !== null)
    .sort((a, b) => a.med - b.med).map((r, i) => {
      const q = r.quality || 0;
      const color = q >= 85 ? "#12b981" : q >= 70 ? "#4ade80" : q >= 55 ? "#a3e635" : q >= 38 ? "#f59e0b" : "#f97316";
      return `<tr>
        <td class="num">${i + 1}</td>
        <td><b>${esc(r.name)}</b><div class="sub" dir="ltr">${esc(r.dns || "")}</div></td>
        <td class="num"><b style="color:${color};font-size:16px">${r.med.toFixed(1)}</b> <span class="sub">ms</span></td>
        <td><div class="barwrap"><div class="bar" style="width:${Math.max(3, q)}%;background:${color}"></div>
            <span class="barval">${q}</span></div></td>
        <td class="num sub">${r.jit === null ? "—" : r.jit.toFixed(1)}</td>
        <td class="num sub">${Math.round((r.loss || 0) * 100)}٪</td></tr>`;
    }).join("");
  const best = (doc.results || []).filter((r) => r.med !== null).sort((a, b) => a.med - b.med)[0];
  const regions = (doc.regions || []).filter((r) => r.ms !== null).sort((a, b) => a.ms - b.ms)
    .map((r) => `<span class="badge">${esc(r.flag || "")} ${esc(r.region)} ${Math.round(r.ms)} ms</span>`).join("");
  const org = doc.me?.asOrganization || "";
  const when = doc.when ? new Date(doc.when).toLocaleString("fa-IR") : "";
  return `<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>نتیجهٔ پینگ‌هاب — بهترین DNS</title>
<meta property="og:title" content="نتیجهٔ تست DNS من در پینگ‌هاب">
<meta property="og:description" content="${best ? esc(`بهترین DNS: ${best.name} با ${best.med.toFixed(1)} میلی‌ثانیه — ${org}`) : "تست DNS"}">
<meta property="og:url" content="${SITE}/r/${esc(doc.id || "")}">
<style>
 body{margin:0;background:#070c18;color:#e9effb;font-family:Tahoma,Vazirmatn,system-ui,sans-serif;line-height:1.8}
 .wrap{max-width:680px;margin:0 auto;padding:18px 14px 50px}
 .card{background:linear-gradient(150deg,#122343,#0d1729);border:1px solid #1d2c48;border-radius:16px;padding:14px}
 h1{font-size:19px;margin:0 0 4px} h2{font-size:15px;margin:22px 0 8px;border-right:4px solid #38bdf8;padding-right:8px}
 .sub{color:#8ba0c4;font-size:12.5px}
 .badge{display:inline-block;font-size:11.5px;padding:3px 9px;border-radius:999px;border:1px solid #1d2c48;
        background:#0e1a2e;margin:2px}
 table{width:100%;border-collapse:separate;border-spacing:0 5px;font-size:13px}
 th{color:#8ba0c4;font-size:11.5px;text-align:right;padding:3px 6px}
 td{background:#101b30;padding:8px 6px;border-top:1px solid #1d2c48;border-bottom:1px solid #1d2c48}
 td:first-child{border-right:1px solid #1d2c48;border-radius:0 11px 11px 0}
 td:last-child{border-left:1px solid #1d2c48;border-radius:11px 0 0 11px}
 .num{text-align:center;direction:ltr;font-variant-numeric:tabular-nums}
 .barwrap{position:relative;height:15px;background:#0d1729;border:1px solid #1d2c48;border-radius:6px;overflow:hidden}
 .bar{height:100%} .barval{position:absolute;inset:0;text-align:center;font-size:10.5px}
 button{background:linear-gradient(135deg,#0ea5e9,#2563eb);border:0;color:#fff;font-weight:700;border-radius:12px;
        padding:11px 18px;font-family:inherit;font-size:15px;cursor:pointer;width:100%;margin-top:12px}
 a{color:#38bdf8}
</style></head><body><div class="wrap">
 <div class="card">
   <h1>📡 نتیجهٔ تست پینگ‌هاب</h1>
   <div class="sub">${esc(when)} ${org ? "· خط اینترنت: <b>" + esc(org) + "</b>" : ""}
     ${doc.me?.colo ? "· لبهٔ کلادفلر: " + esc(doc.me.colo) : ""}</div>
   ${best ? `<div class="card" style="margin-top:12px;background:#0e2a22;border-color:#1d7a5f">
      <div>🎯 <b>بهترین DNS این خط: ${esc(best.name)}</b></div>
      <div class="sub">پینگ ${best.med.toFixed(1)} ms · کیفیت ${best.quality}/۱۰۰ · آدرس:
        <code dir="ltr">${esc(best.dns || "")}</code></div></div>` : ""}
 </div>
 <h2>🌐 رتبه‌بندی سرورهای DNS</h2>
 <table><thead><tr><th>#</th><th>سرور</th><th>پینگ</th><th>قدرت</th><th>جیتر</th><th>افت</th></tr></thead>
 <tbody>${rows || `<tr><td colspan="6" class="sub">داده‌ای نیست</td></tr>`}</tbody></table>
 ${regions ? `<h2>🌍 فاصله تا مناطق</h2><div>${regions}</div>` : ""}
 <h2>خودت هم تست کن</h2>
 <div class="sub">این تست روی گوشی خودِ کاربر انجام می‌شود؛ چون هر خط اینترنت بهترین DNS خودش را دارد.</div>
 <a href="${SITE}/app"><button>🚀 باز کردن پینگ‌هاب</button></a>
 <div class="sub" style="text-align:center;margin-top:18px">
   ⚠️ یادت باشد: DNS پینگ داخل مچ بازی را کم نمی‌کند؛ ورود، رفع تحریم و دانلود آپدیت را بهتر می‌کند.
 </div>
</div></body></html>`;
}

/* ------------------------------------------------------------------ بات تلگرام */

async function botHandleUpdate(env, update) {
  const msg = update.message || update.edited_message;
  const cq = update.callback_query;
  const chatId = msg?.chat?.id ?? cq?.message?.chat?.id;
  if (!chatId) return;

  // ذخیرهٔ کاربر
  if (msg?.from) {
    try {
      await env.DNSRADAR_KV.put(`user:${msg.from.id}`, JSON.stringify({
        id: msg.from.id, username: msg.from.username, name: msg.from.first_name,
        lang: msg.from.language_code, ts: Date.now(),
      }), { expirationTtl: 60 * 60 * 24 * 180 });
    } catch {}
  }

  if (cq) {
    await tg(env, "answerCallbackQuery", { callback_query_id: cq.id });
    if (cq.data === "guide") {
      await tg(env, "sendMessage", { chat_id: chatId, text: GUIDE, parse_mode: "HTML",
        reply_markup: mainKeyboard(), disable_web_page_preview: true });
    } else if (cq.data === "health") {
      await tg(env, "sendChatAction", { chat_id: chatId, action: "typing" });
      const list = EDGE_RESOLVERS.slice(0, 8);
      const res = await edgeCheckDoh(list);
      const lines = res.map((r) => r.ok
        ? `✅ <b>${esc(r.name)}</b> — ${r.ms} ms <span dir="ltr">(${esc(r.dns)})</span>`
        : `❌ <b>${esc(r.name)}</b> — پاسخ نداد <span dir="ltr">(${esc(r.dns)})</span>`);
      await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true,
        text: `🩺 <b>سلامت سرورهای DNS از دید اینترنت</b>\n<i>(سنجیده‌شده از لبهٔ شبکهٔ کلادفلر)</i>\n\n${lines.join("\n")}\n\n` +
              `⚠️ سرورهای ایرانی از بیرون ایران جواب نمی‌دهند؛ این طبیعی است. برای دیدن پینگ <b>خط خودت</b>، اپ را باز کن.`,
        reply_markup: { inline_keyboard: [[BTN("🚀 تست روی گوشی خودم", { web_app: { url: `${SITE}/app` } })]] } });
    }
    return;
  }

  const text = (msg.text || "").trim();
  const [cmdRaw, ...rest] = text.split(/\s+/);
  const cmd = (cmdRaw || "").split("@")[0].toLowerCase();
  const arg = rest.join(" ").trim();

  if (msg.web_app_data) {
    await tg(env, "sendMessage", { chat_id: chatId,
      text: "نتیجه‌ات را دیدم ✅ دکمهٔ «ذخیره و اشتراک» در اپ، لینک نتیجه‌ات را می‌سازد که می‌توانی در گروه بفرستی." });
    return;
  }

  if (!cmd || cmd === "/start") {
    await tg(env, "sendMessage", { chat_id: chatId, text: WELCOME, parse_mode: "HTML",
      reply_markup: mainKeyboard(), disable_web_page_preview: true });
    return;
  }
  if (cmd === "/help") {
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true,
      text: `📖 <b>دستورها</b>\n\n/start — شروع و باز کردن اپ\n/app — باز کردن مینی‌اپ تست\n` +
            `/guide — راهنمای واقعی کم کردن پینگ\n/dns 1.1.1.1 — بررسی یک DNS مشخص (از دید اینترنت)\n` +
            `/health — سلامت سرورهای DNS\n/site — لینک سایت و کد منبع\n\n` +
            `💡 نتیجهٔ تست <b>روی گوشی خودت</b> است؛ چون هر خط اینترنت بهترین DNS خودش را دارد.`,
      reply_markup: mainKeyboard() });
    return;
  }
  if (cmd === "/app" || cmd === "/test" || cmd === "/scan") {
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true,
      text: "🚀 اپ را باز کن — تست روی <b>گوشی خودت</b> انجام می‌شود و ۲۰ ثانیه طول می‌کشد:",
      reply_markup: { inline_keyboard: [[BTN("🚀 باز کردن پینگ‌هاب", { web_app: { url: `${SITE}/app` } })]] } });
    return;
  }
  if (cmd === "/guide") {
    await tg(env, "sendMessage", { chat_id: chatId, text: GUIDE, parse_mode: "HTML",
      reply_markup: mainKeyboard(), disable_web_page_preview: true });
    return;
  }
  if (cmd === "/health") {
    await tg(env, "sendChatAction", { chat_id: chatId, action: "typing" });
    const res = await edgeCheckDoh(EDGE_RESOLVERS.slice(0, 8));
    const lines = res.map((r) => r.ok ? `✅ ${esc(r.name)} — ${r.ms} ms` : `❌ ${esc(r.name)} — قطع`);
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true,
      text: `🩺 <b>سلامت DNSها (از دید اینترنت)</b>\n\n${lines.join("\n")}` });
    return;
  }
  if (cmd === "/dns") {
    const ip = arg.split(/\s+/)[0];
    if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) {
      await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML",
        text: "نمونه:\n<code>/dns 1.1.1.1</code>\n<code>/dns 10.202.10.10</code>" });
      return;
    }
    await tg(env, "sendChatAction", { chat_id: chatId, action: "typing" });
    const r = await tcpDnsQuery(ip, "www.wikipedia.org");
    const txt = r.ok
      ? `🔎 <b>${esc(ip)}</b> پاسخ داد ✅\nتأخیر (از لبهٔ کلادفلر): <b>${r.ms} ms</b>\n` +
        `آی‌پی‌های برگشتی: <span dir="ltr">${esc((r.a || []).slice(0, 3).join(", ") || "—")}</span>\n` +
        `کد پاسخ: ${r.rcode} (۰ = موفق)\n\n<i>توجه: این عدد از سرور ماست، نه از خط تو.</i>\n` +
        `برای پینگ واقعی خط خودت، اپ را باز کن 👇`
      : `❌ <b>${esc(ip)}</b> از دید اینترنت پاسخ نداد (${esc(r.err)}).\n` +
        `<i>اگر DNS ایرانی است، طبیعی است — از بیرون ایران بسته‌اند.</i>`;
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true,
      text: txt, reply_markup: { inline_keyboard: [[BTN("🚀 تست روی گوشی خودم", { web_app: { url: `${SITE}/app` } })]] } });
    return;
  }
  if (cmd === "/site") {
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: false,
      text: `🌐 سایت: ${SITE}\n💻 کد منبع: https://github.com/${REPO}` });
    return;
  }
  await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true,
    text: "دستور را نفهمیدم 🤔\n/help را بزن تا لیست دستورها را ببینی.", reply_markup: mainKeyboard() });
}

/* ------------------------------------------------------------------ سرور اصلی */

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const p = url.pathname;
    const method = request.method;

    try {
      /* --- صفحات --- */
      if (p === "/" || p === "/app" || p === "/index.html") return html(APP_HTML);
      if (p === "/healthz") return json({ ok: true, ts: Date.now(), version: "1.0" });

      /* --- اطلاعات خط کاربر --- */
      if (p === "/api/me") {
        const cf = request.cf || {};
        return json({
          ip: request.headers.get("CF-Connecting-IP"),
          asn: cf.asn || null,
          asOrganization: cf.asOrganization || null,
          country: cf.country || null,
          city: cf.city || null,
          region: cf.region || null,
          colo: cf.colo || null,
          timezone: cf.timezone || null,
          httpProtocol: cf.httpProtocol || null,
        });
      }

      /* --- بررسی لبه‌ای --- */
      if (p === "/api/edge") {
        const custom = url.searchParams.get("resolvers");
        let list = EDGE_RESOLVERS;
        if (custom) {
          const ids = custom.split(",").map((s) => s.trim());
          list = EDGE_RESOLVERS.filter((r) => ids.includes(r.id));
          if (!list.length) list = EDGE_RESOLVERS;
        }
        const results = await edgeCheckDoh(list.slice(0, 12));
        return json({ from: { colo: request.cf?.colo || null, asn: request.cf?.asn || null }, results });
      }

      /* --- بررسی زندهٔ یک DNS مشخص (TCP/53 از لبهٔ کلادفلر) --- */
      if (p === "/api/dns") {
        const ip = (url.searchParams.get("ip") || "").trim();
        const name = (url.searchParams.get("name") || "www.wikipedia.org").trim().slice(0, 60);
        if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) {
          return json({ ok: false, error: "آی‌پی نامعتبر — نمونه: /api/dns?ip=1.1.1.1" }, 400);
        }
        const r = await tcpDnsQuery(ip, /^[a-z0-9.\-]+$/i.test(name) ? name : "www.wikipedia.org");
        return json({ ok: r.ok, ip, name, from: { colo: request.cf?.colo || null }, ...r });
      }

      /* --- ذخیرهٔ نتیجه و ساخت لینک اشتراک --- */
      if (p === "/api/save" && method === "POST") {
        const body = await request.json().catch(() => null);
        if (!body || !Array.isArray(body.results)) return json({ ok: false, error: "دادهٔ نامعتبر" }, 400);
        const v = await verifyInitData(body.initData || "", env.TG_TOKEN);
        const id = shortId();
        const doc = {
          id, when: Date.now(),
          user: v.ok && v.user ? { id: v.user.id, name: v.user.first_name, username: v.user.username } : null,
          me: body.me || null,
          results: body.results.slice(0, 20).map((r) => ({
            id: String(r.id || "").slice(0, 24), name: String(r.name || "").slice(0, 40),
            dns: String(r.dns || "").slice(0, 40),
            med: typeof r.med === "number" ? Math.round(r.med * 10) / 10 : null,
            jit: typeof r.jit === "number" ? Math.round(r.jit * 10) / 10 : null,
            loss: typeof r.loss === "number" ? Math.max(0, Math.min(1, r.loss)) : null,
            quality: typeof r.quality === "number" ? Math.round(r.quality) : null,
          })),
          regions: (body.regions || []).slice(0, 8).map((r) => ({
            region: String(r.region || "").slice(0, 24), flag: String(r.flag || "").slice(0, 6),
            ms: typeof r.ms === "number" ? Math.round(r.ms) : null,
          })),
        };
        await env.DNSRADAR_KV.put(`r:${id}`, JSON.stringify(doc), { expirationTtl: 60 * 60 * 24 * 90 });
        const shareUrl = `${url.origin}/r/${id}`;
        const tgShare = `https://t.me/share/url?url=${encodeURIComponent(shareUrl)}` +
          `&text=${encodeURIComponent("نتیجهٔ تست DNS من در پینگ‌هاب:")}`;
        // اگر کاربر از داخل تلگرام آمده، لینک را در چتش هم بفرست
        if (v.ok && v.user?.id) {
          ctx.waitUntil(tg(env, "sendMessage", {
            chat_id: v.user.id, parse_mode: "HTML", disable_web_page_preview: false,
            text: `✅ نتیجهٔ تست تو ذخیره شد:\n${shareUrl}\n\n<i>می‌توانی همین لینک را در گروه بفرستی تا بقیه هم تست بگیرند.</i>`,
            reply_markup: { inline_keyboard: [[webAppBtn("🔁 تست دوباره")]] },
          }));
        }
        return json({ ok: true, id, url: shareUrl, tgShare, verified: v.ok });
      }

      /* --- صفحهٔ نتیجه --- */
      if (p.startsWith("/r/")) {
        const id = p.slice(3).replace(/[^a-z0-9]/g, "").slice(0, 12);
        const raw = await env.DNSRADAR_KV.get(`r:${id}`);
        if (!raw) return html(`<!DOCTYPE html><html lang="fa" dir="rtl"><body style="background:#070c18;color:#e9effb;
          font-family:Tahoma;text-align:center;padding:60px 20px">
          <h2>نتیجه پیدا نشد یا منقضی شده 🕐</h2>
          <p style="color:#8ba0c4">نتیجه‌ها ۹۰ روز نگه داشته می‌شوند.</p>
          <a href="${SITE}/app" style="color:#38bdf8">خودت تست بگیر →</a></body></html>`, 404);
        return html(sharePage(JSON.parse(raw)));
      }

      /* --- وب‌هوک تلگرام --- */
      if (p === "/tg/webhook" && method === "POST") {
        const secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token");
        if (!env.TG_SECRET || secret !== env.TG_SECRET) return json({ ok: false, error: "forbidden" }, 403);
        const update = await request.json().catch(() => null);
        if (update) ctx.waitUntil(botHandleUpdate(env, update));
        return json({ ok: true });
      }

      /* --- تنظیم مجدد بات (محافظت‌شده) --- */
      if (p === "/tg/setup") {
        if (url.searchParams.get("key") !== env.ADMIN_KEY) return json({ ok: false }, 403);
        const hook = await tg(env, "setWebhook", {
          url: `${url.origin}/tg/webhook`, secret_token: env.TG_SECRET,
          allowed_updates: ["message", "callback_query", "edited_message"],
          drop_pending_updates: false,
        });
        const cmds = await tg(env, "setMyCommands", {
          commands: [
            { command: "start", description: "شروع و باز کردن پینگ‌هاب" },
            { command: "app", description: "تست زندهٔ DNS روی گوشی خودم" },
            { command: "guide", description: "راهنمای واقعی کم کردن پینگ" },
            { command: "health", description: "سلامت سرورهای DNS" },
            { command: "dns", description: "بررسی یک DNS مشخص: /dns 1.1.1.1" },
            { command: "site", description: "لینک سایت و کد منبع" },
          ],
        });
        const menu = await tg(env, "setChatMenuButton", {
          menu_button: { type: "web_app", text: "پینگ‌هاب", web_app: { url: `${url.origin}/app` } },
        });
        return json({ ok: true, hook, cmds, menu, site: url.origin });
      }

      return json({ ok: false, error: "not found" }, 404);
    } catch (e) {
      return json({ ok: false, error: String(e?.message || e) }, 500);
    }
  },
};
