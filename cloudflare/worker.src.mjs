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

const APP_HTML = __APP_HTML__;
const REPO = "Alisarani7021/pinghab";
const SITE = "https://pinghab.catclient-59gk2mui.workers.dev";

/* ------------------------------------------------------------------ ابزارها */

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, X-Admin-Key",
  "Access-Control-Max-Age": "86400",
};
const json = (obj, status = 200, extra = {}) =>
  new Response(JSON.stringify(obj), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
               ...CORS, ...extra },
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
  const out = { rcode: null, a: [], minTtl: null, ad: false, ede: null, flags: 0 };
  const dv = new DataView(buf.buffer ?? buf, buf.byteOffset ?? 0, buf.byteLength);
  if (buf.byteLength < 12) return out;
  out.flags = dv.getUint16(2);
  out.rcode = out.flags & 0xf;
  out.ad = (out.flags & 0x20) === 0x20;
  const qd = dv.getUint16(4), an = dv.getUint16(6), ar = dv.getUint16(10);
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
  // رکوردهای اضافی: OPT (نوع ۴۱) → استخراج EDE (Extended DNS Errors، گزینهٔ ۱۵)
  for (let r = 0; r < ar && i + 11 <= buf.byteLength; r++) {
    const l0 = buf[i];
    if (l0 === 0) i++;
    else if ((l0 & 0xc0) === 0xc0) i += 2;
    else { while (i < buf.byteLength && buf[i] !== 0) i += buf[i] + 1; i++; }
    if (i + 10 > buf.byteLength) break;
    const type = dv.getUint16(i), rdlen = dv.getUint16(i + 8);
    i += 10;
    if (type === 41 && rdlen >= 4) {
      let j = i, end = i + rdlen;
      while (j + 4 <= end) {
        const ocode = dv.getUint16(j), olen = dv.getUint16(j + 2);
        if (ocode === 15 && olen >= 2) {
          out.ede = { code: dv.getUint16(j + 4), text: new TextDecoder().decode(buf.slice(j + 6, j + 4 + olen)) };
        }
        j += 4 + olen;
      }
    }
    i += rdlen;
  }
  return out;
}

function dnsPacket(name, id = Math.floor(Math.random() * 65535), opts = {}) {
  const labels = name.split(".").filter(Boolean);
  const withOpt = opts.do !== false;               // پیش‌فرض: EDNS0 + پرچم DO (برای DNSSEC)
  let len = 17 + (withOpt ? 11 : 0);
  labels.forEach((l) => (len += 1 + l.length));
  const buf = new Uint8Array(len), dv = new DataView(buf.buffer);
  dv.setUint16(0, id); dv.setUint16(2, 0x0100); dv.setUint16(4, 1);
  dv.setUint16(10, withOpt ? 1 : 0);               // ARCOUNT
  let o = 12;
  for (const l of labels) { buf[o++] = l.length; for (const ch of l) buf[o++] = ch.charCodeAt(0); }
  buf[o++] = 0; dv.setUint16(o, 1); dv.setUint16(o + 2, 1); o += 4;
  if (withOpt) {                                    // OPT: name=0, type=41, class=1232, ttl=DO, rdlen=0
    buf[o++] = 0; dv.setUint16(o, 41); dv.setUint16(o + 2, 1232); dv.setUint32(o + 4, 0x00008000); dv.setUint16(o + 8, 0);
  }
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

const WORLD_CATALOG = __WORLD_CATALOG__;
/* ---------- داده‌های تازه (تزریق در زمان build) — هرکدام با منبع و مجوز ---------- */
const IR_GEO = __IR_PROVINCES__;        // ۳۱ استان + ۲۵۰ شهر
const IR_CARRIERS = __IR_CARRIERS__;    // PLMN/ASN اپراتورها (تأییدشده)
const GAMES = __GAMES_CATALOG__;        // سرورهای بازی (MIT — pingdiff)
const CF_IR = __CF_IR__;                // آی‌پی‌های کلادفلر دامنه‌های ایرانی (MIT — CF-Web)
const R_META = __RESOLVERS_META__;      // متادیتای رزولورها: DNSSEC/بدون‌لاگ/بدون‌فیلتر (ISC)
const SCAN_SUMMARY = __SCAN_SUMMARY__;  // نتیجهٔ اسکن خودمان (اثر رزولور → آی‌پی → RTT)
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


/* ------------------------------------------------------------------ ابزارهای تازه */

const djb2 = (str) => { let h = 5381; for (let i = 0; i < str.length; i++) h = ((h * 33) ^ str.charCodeAt(i)) >>> 0; return h.toString(36); };

function carrierList() {
  return [].concat(
    (IR_CARRIERS.mobile || []).map((c) => ({ ...c, t: "mobile" })),
    (IR_CARRIERS.mvno || []).map((c) => ({ ...c, t: "mvno" })),
    (IR_CARRIERS.fixed || []).map((c) => ({ ...c, t: "fixed" })));
}
/** اپراتور را از ASN (دقیق) و در صورت نبود، از نام سازمان (تقریبی) حدس می‌زند */
function carrierOf(asn, org) {
  const list = carrierList(), a = String(asn || "");
  let hit = list.find((c) => (c.asn || []).some((x) => String(x).replace(/^AS/i, "") === a));
  if (hit) return { id: hit.id, fa: hit.fa, en: hit.en || null, type: hit.t, match: "asn" };
  if (org) {
    const o = String(org).toLowerCase();
    hit = list.find((c) => (c.en && o.includes(String(c.en).toLowerCase().split(/[\s\/]/)[0])) || (c.fa && org.includes(c.fa)));
    if (hit) return { id: hit.id, fa: hit.fa, en: hit.en || null, type: hit.t, match: "org" };
  }
  return null;
}
/** نام شهر (از request.cf.city) را به استان نگاشت می‌کند — تقریبی */
function provinceByCityName(city) {
  if (!city) return null;
  const raw = String(city).trim();
  for (const p of IR_GEO.provinces) {
    if (p.fa === raw || p.capital === raw) return { id: p.id, fa: p.fa, capital: p.capital, exact: true };
    if ((p.cities || []).includes(raw)) return { id: p.id, fa: p.fa, capital: p.capital, exact: true };
  }
  for (const p of IR_GEO.provinces) if (raw.includes(p.capital) || p.capital.includes(raw)) return { id: p.id, fa: p.fa, capital: p.capital, exact: false };
  return null;
}
function nearestProvince(lat, lon) {
  let best = null, bd = 1e9;
  for (const p of IR_GEO.provinces) {
    const dLat = (lat - p.lat) * 111, dLon = (lon - p.lon) * 111 * Math.cos((lat * Math.PI) / 180);
    const d = Math.sqrt(dLat * dLat + dLon * dLon);
    if (d < bd) { bd = d; best = p; }
  }
  return best ? { id: best.id, fa: best.fa, capital: best.capital, km: Math.round(bd) } : null;
}

/** پروکسی Globalping با کش KV — سنجش از داخل ایران و هر کشور دیگر */
async function gpRun(env, payload, ttl = 900) {
  const key = "gp:" + djb2(JSON.stringify(payload));
  try { const c = await env.DNSRADAR_KV.get(key); if (c) return { ok: true, cached: true, ...JSON.parse(c) }; } catch {}
  let post;
  try {
    post = await fetch("https://api.globalping.io/v1/measurements", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  } catch (e) { return { ok: false, error: "globalping network: " + String(e?.name || e) }; }
  if (!post.ok) return { ok: false, error: "globalping " + post.status, detail: (await post.text()).slice(0, 200) };
  const j = await post.json().catch(() => null);
  if (!j?.id) return { ok: false, error: "پاسخ نامعتبر از Globalping" };
  let d = null;
  for (let i = 0; i < 9; i++) {
    await new Promise((r) => setTimeout(r, 1100));
    try {
      const r = await fetch("https://api.globalping.io/v1/measurements/" + j.id);
      if (!r.ok) break;
      d = await r.json();
      if (d.status === "finished") break;
    } catch { break; }
  }
  if (!d) return { ok: false, error: "نتیجه نگرفت (تایم‌اوت)" };
  const out = gpSimplify(d, j.id);
  try { await env.DNSRADAR_KV.put(key, JSON.stringify(out), { expirationTtl: ttl }); } catch {}
  return { ok: true, cached: false, ...out };
}
function gpSimplify(d, id) {
  const results = (d.results || []).map((res) => {
    const pr = res.probe || {}, r = res.result || {};
    const base = { city: pr.city || null, country: pr.country || null, asn: pr.asn || null, network: pr.network || null, tags: (pr.tags || []).slice(0, 2) };
    if (r.timings && !Array.isArray(r.timings)) return { ...base, kind: "dns", total: typeof r.timings.total === "number" ? r.timings.total : null,
      status: r.statusCodeName || null, answers: (r.answers || []).map((a) => a.value).slice(0, 4) };
    if (Array.isArray(r.timings)) { const st = r.stats || {};
      return { ...base, kind: "ping", min: st.min ?? null, avg: st.avg ?? null, max: st.max ?? null, loss: st.loss ?? null }; }
    if (Array.isArray(r.hops)) return { ...base, kind: "traceroute",
      hops: r.hops.slice(0, 14).map((h) => ({ ip: h.resolvedAddress || h.address || null, ms: (h.timings && h.timings.length) ? Math.round(h.timings[0]) : null })) };
    if (r.statusCode !== undefined || r.headers) return { ...base, kind: "http", status: r.statusCode ?? null, total: (r.timings || {}).total ?? null };
    return { ...base, kind: "?", raw: JSON.stringify(r).slice(0, 140) };
  });
  return { id, status: d.status || null, probe_count: results.length, results,
    measurement_url: "https://globalping.io?measurement=" + id, note: "سنجش از پروب‌های عمومی Globalping (دیتاسنتری، نه خط موبایل)." };
}

/** تولید فایل‌های تنظیمات/اسکریپت (ویندوز، لینوکس، روتر) از روی یافته‌های خودمان */
function genText(kind, q) {
  const ip = (q.get("ip") || "10.202.10.10,10.202.10.11").replace(/[^0-9a-fA-F:.,\s]/g, "").slice(0, 80);
  const iface = (q.get("iface") || "eth0").replace(/[^a-zA-Z0-9._-]/g, "").slice(0, 20);
  const rate = (q.get("rate") || "20mbit").replace(/[^0-9a-zA-Z]/g, "").slice(0, 12);
  const K = {
    "windows-game": `# پینگ‌هاب — کاهش تأخیر ویندوز برای بازی (TCP)
# منبع مکانیزم: orlp/ReducePing · ajnewlands/PingTune · Twanislas/PingFix (زنجیرهٔ ACK و Nagle)
# ⚠️ فقط روی بازی‌های TCP اثر دارد؛ برای بازی‌های UDP بی‌اثر است. اثر معمول ۱ تا ۱۰ میلی‌ثانیه.
# برای اجرا: PowerShell را با دسترسی Administrator باز کن، سپس:
#   Set-ExecutionPolicy -Scope Process Bypass -Force ; .\pinghab-windows-game.ps1
$ErrorActionPreference = "Stop"
Write-Host "پینگ‌هاب: اعمال تنظیمات تأخیر TCP ..." -ForegroundColor Cyan
# ۱) تأیید فوری بسته‌ها به‌جای انباشتن (TcpAckFrequency = ۱)
$base = "HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
Get-ChildItem $base | ForEach-Object {
  New-ItemProperty -Path $_.PSPath -Name TcpAckFrequency -Value 1 -PropertyType DWord -Force | Out-Null
  New-ItemProperty -Path $_.PSPath -Name TCPNoDelay     -Value 1 -PropertyType DWord -Force | Out-Null
  New-ItemProperty -Path $_.PSPath -Name TcpDelAckTicks -Value 0 -PropertyType DWord -Force | Out-Null
}
# ۲) پروفایل توان «حداکثر کارایی» (کاهش تأخیر پردازش کارت شبکه)
powercfg /setactive SCHEME_MIN
Write-Host "✅ انجام شد. برای اعمال کامل، ویندوز را ری‌استارت کن." -ForegroundColor Green
Write-Host "برگشت به حالت قبل: پینگ‌هاب → بخش خانه و مسیریاب → اسکریپت بازگردانی."
`,
    "windows-reset": `# پینگ‌هاب — بازگردانی تنظیمات ویندوز به حالت پیش‌فرض
$base = "HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\Interfaces"
Get-ChildItem $base | ForEach-Object {
  foreach ($n in "TcpAckFrequency","TCPNoDelay","TcpDelAckTicks") {
    Remove-ItemProperty -Path $_.PSPath -Name $n -ErrorAction SilentlyContinue
  }
}
powercfg /setactive SCHEME_BALANCED
Write-Host "✅ بازگردانی شد." -ForegroundColor Green
`,
    "linux-cake": `#!/bin/sh
# پینگ‌هاب — SQM/CAKE برای کاهش بافر‌بلاست (علت اصلی «پینگ ۲۰ → ۲۲۰» زیر بار)
# منبع مکانیزم: LibreQoE/LibreQoS · jeverley/dscpclassify · filip-lebiecki/bufferbloat-lab
# نرخ را با سرعت واقعی خطت عوض کن (مثلاً 50mbit برای اینترنت ۵۰ مگ). مؤثرترین راه کاهش جهش پینگ.
tc qdisc del dev ${iface} root 2>/dev/null
tc qdisc add dev ${iface} root cake bandwidth ${rate} besteffort dual-dsthost nat nowash
# اولویت‌دهی به بازی با DSCP (اختیاری، طبق dscpclassify):
# nft add rule inet filter forward ip dscp set ef udp dport 27015-27050
echo "CAKE روی ${iface} با نرخ ${rate} اعمال شد. تست: پینگ‌هاب → بخش خانه → آزمون بافر‌بلاست"
`,
    "router-openwrt": `# پینگ‌هاب — روتر OpenWrt: SQM + CAKE (متن راهنما؛ در LuCI هم می‌شود)
opkg update && opkg install sqm-scripts luci-app-sqm
uci set sqm.eth1.enabled='1'
uci set sqm.eth1.interface='${iface}'
uci set sqm.eth1.download='90000'   # ~۸۵٪ سرعت دانلود واقعی (Kbit/s)
uci set sqm.eth1.upload='18000'     # ~۸۵٪ سرعت آپلود واقعی
uci set sqm.eth1.qdisc='cake'
uci set sqm.eth1.script='piece_of_cake.qos'
uci commit sqm && /etc/init.d/sqm restart
# نکته: ۸۵٪ سرعت را بگذار تا صف‌ها هرگز پر نشوند — همین کار بافر‌بلاست را می‌خواباند.
`,
    "router-mikrotik": `# پینگ‌هاب — میکروتیک: صف CAKE (RouterOS 7.1+) روی اینترفیس WAN
/queue type add name=cake-up kind=cake cake-bandwidth=${rate}
/queue simple add name=pinghab-wan target=${iface} max-limit=90M/18M queue=cake-up/cake-up comment="pinghab SQM"
# برای اولویت بازی: /ip firewall mangle → DSCP ef روی پورت‌های بازی، بعد queue with priority.
`,
    "mtu": `# پینگ‌هاب — کشف درست MTU (تا بسته‌ها تکه‌تکه نشوند)
# یافتهٔ ما: در محیط سنجش، بسته‌های UDP بزرگ‌تر از ۵۱۲ بایت پاسخ نگرفتند → MSS را بزرگ نگذار.
# روش دقیق MTU روی ویندوز (Command Prompt):
#   ping -f -l 1472 1.1.1.1      → اگر «Packet needs to be fragmented» داد، عدد را کم کن تا جواب دهد (1472 = MTU ۱۵۰۰)
#   سپس MTU = عددی که جواب داد + ۲۸  → در تنظیمات کارت شبکه وارد کن (معمولاً ۱۴۹۲ برای PPPoE، ۱۵۰۰ برای فیبر)
# روی لینوکس:
#   ping -M do -s 1472 1.1.1.1
# روی روتر: MSS clamping روی PPPoE معمولاً همان کار را می‌کند.
`};
  const hot = {
    "resolver-info": `# پینگ‌هاب — راهنمای رزولورها (خلاصهٔ یافته‌ها)
- رزولور خوب = رزولوری که «آی‌پی نزدیک‌تر» بدهد، نه سریع‌ترین پاسخ.
- رزولور داخلی (رادار/۴۰۳/الکترو/شکن) فقط از خط داخل ایران سنجیدنی است (بازهٔ 10.x).
- DNSSEC را با /api/dnssec بسنج؛ EDE کار خطا را نشان می‌دهد.
${ip ? "- آی‌پی‌های پیشنهادی برای تست: " + ip : ""}
`};
  if (K[kind]) return { body: K[kind], name: `pinghab-${kind}.${kind.startsWith("windows") ? "ps1" : kind === "linux-cake" ? "sh" : "txt"}` };
  return { body: hot[kind] || `# پینگ‌هاب\nنوع نامعتبر. انواع: ${Object.keys(K).join(", ")}, resolver-info\n`, name: "pinghab.txt" };
}

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

  if (msg.location) {
    const pr = nearestProvince(msg.location.latitude, msg.location.longitude);
    await env.DNSRADAR_KV.put(`geo:${chatId}`, JSON.stringify({ province: pr?.fa || null, lat: msg.location.latitude,
      lon: msg.location.longitude, ts: Date.now() }), { expirationTtl: 60 * 60 * 24 * 365 });
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true,
      text: pr ? `📍 ثبت شد: <b>${esc(pr.fa)}</b> (نزدیک‌ترین مرکز استان، ~${pr.km} کیلومتر).\nاپراتورت را هم بگو: <code>/city ${esc(pr.fa)} ایرانسل</code>` : "📍 موقعیت ثبت شد.",
      reply_markup: mainKeyboard() });
    return;
  }

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
  if (cmd === "/dnslist" || cmd === "/list") {
    const cc = (arg || "").toUpperCase().slice(0, 2) || "IR";
    const c = (WORLD_CATALOG.countries || {})[cc];
    const groups = (WORLD_CATALOG.curated_groups || []).filter((g) => g.cc === (c ? cc : "GL"));
    const lines = [`🌍 <b>DNS پیشنهادی</b> ${c ? `— ${c.name_fa}` : "— جهانی"}`];
    if (c) {
      lines.push(`<i>${c.count} رزولور عمومی از این کشور در کاتالوگ ما ثبت است (v4=${c.v4}، v6=${c.v6}).</i>`);
    }
    for (const g of groups.slice(0, 3)) {
      lines.push("");
      for (const e of g.entries.slice(0, 8)) {
        const ips = [...(e.v4 || []), ...(e.v6 || [])].slice(0, 3).join(" · ");
        lines.push(`<b>${e.name}</b>\n<code>${ips}</code>`);
      }
    }
    lines.push("");
    lines.push("⚠️ این‌ها «کاندید»‌اند نه توصیه: بهترین DNS هر خط را باید روی گوشی خودت تست کنی.");
    lines.push("کشور دیگر: <code>/dnslist DE</code> — یا دکمهٔ اپ را بزن.");
    await tg(env, "sendMessage", { chat_id: chatId, text: lines.join("\n"), parse_mode: "HTML",
      reply_markup: mainKeyboard(), disable_web_page_preview: true });
    return;
  }
  if (cmd === "/impact") {
    const name = (arg || "cdn.cloudflare.steamstatic.com").slice(0, 80);
    await tg(env, "sendChatAction", { chat_id: chatId, action: "typing" });
    const one = async (r) => {
      const ctrl = new AbortController();
      const t = setTimeout(() => ctrl.abort(), 5000);
      try {
        const res = await fetch(r.url, {
          method: "POST",
          headers: { "Content-Type": "application/dns-message", "Accept": "application/dns-message" },
          body: dnsPacket(name), signal: ctrl.signal,
        });
        const p2 = parseDns(new Uint8Array(await res.arrayBuffer()));
        return { label: r.name, ips: p2.a.slice(0, 2) };
      } catch (e) { return { label: r.name, ips: [] }; }
      finally { clearTimeout(t); }
    };
    const rs = await Promise.all(EDGE_RESOLVERS.slice(0, 8).map(one));
    const uniq = new Set(rs.flatMap((r) => r.ips));
    const lines = [`🎯 <b>سنجش اثر</b> — <code>${name}</code>`,
                   `<i>هر رزولور چه آی‌پی می‌دهد؟ آی‌پی متفاوت = PoP متفاوت.</i>`, ""];
    for (const r of rs) lines.push(`${r.label}: <code>${r.ips.join(" · ") || "—"}</code>`);
    lines.push("");
    lines.push(uniq.size > 1
      ? `✅ ${uniq.size} آی‌پی متمایز پیدا شد — یعنی انتخاب DNS واقعاً مسیر را عوض می‌کند.`
      : "همه یک آی‌پی دادند.");
    lines.push("تأخیر تا هر PoP را از گوشی خودت در اپ بسنج.");
    await tg(env, "sendMessage", { chat_id: chatId, text: lines.join("\n"), parse_mode: "HTML",
      reply_markup: mainKeyboard(), disable_web_page_preview: true });
    return;
  }

  if (cmd === "/geo") {
    let saved = null;
    try { const raw = await env.DNSRADAR_KV.get(`geo:${chatId}`); if (raw) saved = JSON.parse(raw); } catch {}
    const me = await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true,
      text: ["📍 <b>جای من</b>",
        saved ? `ثبت‌شده: <b>${esc(saved.province || saved.city || "—")}</b>` : "هنوز چیزی ثبت نشده.",
        "", "دو راه:", "۱) دکمهٔ «ارسال موقعیت» را بزن (پایین، یک‌بار)", "۲) بنویس: <code>/city مشهد همراه اول</code>",
        "", "<i>چرا می‌پرسیم؟ چون مسیر شبکه در ایران به استان و اپراتور بستگی دارد؛ آمار را برای همین گروه‌بندی می‌کنیم. هیچ‌چیز هویتی ذخیره نمی‌شود.</i>"].join("\n"),
      reply_markup: { keyboard: [[{ text: "📍 ارسال موقعیت من", request_location: true }]], resize_keyboard: true, one_time_keyboard: true } });
    return;
  }
  if (cmd === "/city") {
    if (!arg) { await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", text: "نمونه:\n<code>/city تهران ایرانسل</code>\n<code>/city مشهد همراه اول</code>" }); return; }
    const parts = arg.split(/\s+/);
    const found = provinceByCityName(parts[0]);
    const car = parts.slice(1).join(" ");
    const doc = { province: found ? found.fa : (parts[0] || null), city: parts[0] || null, carrier: car || null,
      lat: found?.lat ?? null, lon: found?.lon ?? null, ts: Date.now(), manual: true };
    await env.DNSRADAR_KV.put(`geo:${chatId}`, JSON.stringify(doc), { expirationTtl: 60 * 60 * 24 * 365 });
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", reply_markup: mainKeyboard(),
      text: `✅ ثبت شد: <b>${esc(doc.city || "—")}</b>${doc.province && doc.province !== doc.city ? ` (استان ${esc(doc.province)})` : ""}${doc.carrier ? ` · <b>${esc(doc.carrier)}</b>` : ""}\n\nحالا در اپ، نتیجه‌ها را بی‌نام برای همین گروه ثبت کن.` });
    return;
  }
  if (cmd === "/watch") {
    const parts = arg.split(/\s+/);
    const target = (parts[0] || "").slice(0, 80);
    const thr = Math.max(20, Math.min(2000, parseInt(parts[1] || "120", 10) || 120));
    if (!/^[a-z0-9.\-]+$/i.test(target)) {
      await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", text: "نمونه:\n<code>/watch discord.com 120</code>\n<code>/watch cdn.cloudflare.steamstatic.com 90</code>" });
      return;
    }
    await env.DNSRADAR_KV.put(`w:${chatId}:${target}`, JSON.stringify({ chat: chatId, target, thr, ts: Date.now(), last: null }));
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: mainKeyboard(),
      text: `🔔 پایش فعال شد: <code>${esc(target)}</code>\nاگر از لبهٔ ما بیش از <b>${thr} ms</b> طول بکشد یا پاسخ نده، خبر می‌دهم. (هر ۱۵ دقیقه)\n\n/i/watching را بزن تا لیست را ببینی.` });
    return;
  }
  if (cmd === "/unwatch") {
    const t = arg.trim();
    if (!t) {
      const l = await env.DNSRADAR_KV.list({ prefix: `w:${chatId}:` });
      for (const k of l.keys) await env.DNSRADAR_KV.delete(k.name);
      await tg(env, "sendMessage", { chat_id: chatId, text: "🧹 همهٔ پایش‌های تو حذف شد.", reply_markup: mainKeyboard() });
      return;
    }
    await env.DNSRADAR_KV.delete(`w:${chatId}:${t}`);
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", text: `حذف شد: <code>${esc(t)}</code>`, reply_markup: mainKeyboard() });
    return;
  }
  if (cmd === "/watching") {
    const l = await env.DNSRADAR_KV.list({ prefix: `w:${chatId}:` });
    const lines = ["🔔 <b>پایش‌های فعال</b>"];
    for (const k of l.keys) {
      const raw = await env.DNSRADAR_KV.get(k.name); if (!raw) continue;
      const w = JSON.parse(raw);
      lines.push(`• <code>${esc(w.target)}</code> — حد ${w.thr} ms${w.last != null ? ` · آخرین: ${w.last} ms` : ""}`);
    }
    if (l.keys.length === 0) lines.push("چیزی فعال نیست. <code>/watch discord.com 120</code>");
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: mainKeyboard(), text: lines.join("\n") });
    return;
  }
  if (cmd === "/stats") {
    const prov = arg.trim().split(/\s+/)[0] || "";
    const prefix = prov ? `st:${prov}:` : "st:";
    const l = await env.DNSRADAR_KV.list({ prefix, limit: 400 });
    const rows = [];
    for (const k of l.keys) {
      const raw = await env.DNSRADAR_KV.get(k.name); if (!raw) continue;
      const parts = k.name.split(":"); const v = JSON.parse(raw);
      rows.push({ p: parts[1], c: parts[2], r: parts.slice(3).join(":"), n: v.n, avg: v.avg });
    }
    rows.sort((a, b) => (a.avg ?? 1e9) - (b.avg ?? 1e9));
    const lines = [`📊 <b>آمار بی‌نام کاربران</b>${prov ? ` — ${esc(prov)}` : ""}`];
    if (!rows.length) lines.push("هنوز نمونه‌ای ثبت نشده. اولین نفر باش — در اپ، بخش «📍 خط من».");
    rows.slice(0, 10).forEach((x) => lines.push(`• ${esc(x.r)} — <b>${x.avg} ms</b> · ${x.p}/${x.c} · n=${x.n}`));
    lines.push("", "<i>عدد تجمیعی است؛ برای عدد خط خودت، اپ را باز کن.</i>");
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: mainKeyboard(), text: lines.join("\n") });
    return;
  }
  if (cmd === "/games") {
    const slug = arg.trim().split(/\s+/)[0];
    if (!slug) {
      const lines = ["🎮 <b>کاتالوگ سرورهای بازی</b> (۹ بازی · ۱۴۱ سرور)"];
      for (const [k, g] of Object.entries(GAMES.games)) lines.push(`• <code>/games ${k}</code> — ${esc(g.name_fa)}`);
      lines.push("", "<i>دادهٔ سرورها از پروژهٔ MIT «pingdiff».</i>");
      await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", reply_markup: mainKeyboard(), text: lines.join("\n") });
      return;
    }
    const g = GAMES.games[slug];
    if (!g) { await tg(env, "sendMessage", { chat_id: chatId, text: "این بازی نیست. /games را بزن." }); return; }
    const lines = [`🎮 <b>${esc(g.name_fa)}</b> — ${esc(g.name)}`];
    for (const [reg, arr] of Object.entries(g.regions)) {
      const top = arr[0];
      lines.push(`<b>${esc(GAMES.regions_fa?.[reg] || reg)}</b>: ${arr.length} سرور · نمونه <code>${esc(top.ip)}:${top.port}</code>`);
    }
    lines.push("", "برای تست پینگ از ایران: <code>/gp ping " + esc(g.regions.EU?.[0]?.ip || "1.1.1.1") + "</code>");
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: mainKeyboard(), text: lines.join("\n") });
    return;
  }
  if (cmd === "/resolvers") {
    const need = arg.trim().split(/[,\s]+/).filter((x) => ["dnssec", "nolog", "nofilter"].includes(x));
    let items = R_META.resolvers.filter((r) => need.every((f) => (r.f || []).includes(f)));
    items = items.filter((r) => r.d || r.a);
    const lines = [`🧪 <b>رزولورها</b>${need.length ? " — " + need.join(" + ") : ""} (${items.length} از ${R_META.count})`];
    items.slice(0, 8).forEach((r) => lines.push(`• <b>${esc(r.n)}</b>\n<code>${esc(r.a || "")}${r.d ? " · " + esc(r.d) : ""}</code>\n<i>${(r.f || []).join(" · ") || "—"}</i>`));
    lines.push("", "فیلترها: <code>/resolvers dnssec nolog nofilter</code>");
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: mainKeyboard(), text: lines.join("\n") });
    return;
  }
  if (cmd === "/cfip") {
    const lines = [`🔥 <b>آی‌پی‌های کلادفلر دامنه‌های ایرانی</b> (${CF_IR.domains_total} دامنه · ${CF_IR.unique_ips} آی‌پی یکتا)`];
    CF_IR.ips.slice(0, 8).forEach((x) => lines.push(`<code>${esc(x.ip)}</code> — ${x.domains} دامنه · ${esc((x.sample || [])[0] || "")}`));
    lines.push("", "برای سنجش از ایران: " + `${SITE}/api/cfip-test?n=3` , "<i>منبع: MIT — CF-Web</i>");
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: mainKeyboard(), text: lines.join("\n") });
    return;
  }
  if (cmd === "/tune") {
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: mainKeyboard(),
      text: ["🛠 <b>اسکریپت‌های آماده</b>",
        `• ویندوز (بازی): ${SITE}/api/gen?kind=windows-game`,
        `• بازگردانی ویندوز: ${SITE}/api/gen?kind=windows-reset`,
        `• لینوکس CAKE: ${SITE}/api/gen?kind=linux-cake&iface=eth0&rate=20mbit`,
        `• روتر OpenWrt: ${SITE}/api/gen?kind=router-openwrt&iface=eth1`,
        `• میکروتیک: ${SITE}/api/gen?kind=router-mikrotik&rate=20mbit`,
        `• کشف MTU: ${SITE}/api/gen?kind=mtu`,
        "", "<i>خودِ اسکریپت‌ها را ما می‌سازیم (مکانیزم از پروژه‌های باز). روی بازی‌های TCP اثر ۱ تا ۱۰ ms؛ روی UDP بی‌اثر.</i>"].join("\n") });
    return;
  }
  if (cmd === "/gp") {
    const [t, ...rest] = arg.split(/\s+/);
    const target = rest.join(" ") || "1.1.1.1";
    const type = ["ping", "dns", "traceroute", "http"].includes(t) ? t : "ping";
    await tg(env, "sendChatAction", { chat_id: chatId, action: "typing" });
    const out = await gpRun(env, type === "dns"
      ? { type, target, limit: 2, locations: [{ country: "IR" }], measurementOptions: { query: { type: "A" }, protocol: "UDP", port: 53 } }
      : { type, target, limit: 2, locations: [{ country: "IR" }] }, 600);
    const lines = [`🌐 <b>${esc(type)}</b> → <code>${esc(target)}</code> از داخل ایران`];
    if (!out.ok) lines.push("❌ " + esc(out.error || "خطا"));
    else for (const r of (out.results || [])) {
      if (r.kind === "ping") lines.push(`• ${esc(r.city || "?")} · ${esc(String(r.network || "").slice(0, 22))} — <b>${r.avg ?? "?"} ms</b> (loss ${r.loss ?? "?"}%)`);
      else if (r.kind === "dns") lines.push(`• ${esc(r.city || "?")} — ${r.total ?? "?"} ms · <span dir="ltr">${esc((r.answers || []).join(", ").slice(0, 60))}</span>`);
      else if (r.kind === "traceroute") lines.push(`• ${esc(r.city || "?")} — ${(r.hops || []).length} hop`);
      else lines.push(`• ${esc(r.city || "?")} — ${esc(r.kind)} ${r.status ?? ""} ${r.total ?? ""} ms`);
    }
    lines.push("", "<i>پروب‌های Globalping در ایران دیتاسنتری‌اند؛ خط موبایل تو نیست.</i>");
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: mainKeyboard(), text: lines.join("\n") });
    return;
  }
  if (cmd === "/help") {
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true,
      text: `📖 <b>دستورها</b>\n\n/start — شروع و باز کردن اپ\n/app — باز کردن مینی‌اپ تست\n` +
            `/guide — راهنمای واقعی کم کردن پینگ\n/dns 1.1.1.1 — بررسی یک DNS مشخص (از دید اینترنت)\n` +
            `/health — سلامت سرورهای DNS\n/site — لینک سایت و کد منبع\n\n` +
            `/dnslist IR — لیست DNS یک کشور (نمونه: /dnslist DE)\n` +
            `/impact دامنه — رایانش PoP: /impact cdn.cloudflare.steamstatic.com\n\n` +
            `📍 <b>جای من</b>\n/geo — ثبت استان/شهر (دکمهٔ موقعیت یا متن)\n/city مشهد همراه اول\n\n` +
            `🎮 <b>بازی</b>\n/games — کاتالوگ ۹ بازی و ۱۴۱ سرور · /games cs2\n/gp ping 1.1.1.1 — سنجش از پروب‌های داخل ایران\n\n` +
            `🔔 <b>پایش و آمار</b>\n/watch discord.com 120 — هشدار وقتی خراب شد\n/watching · /unwatch\n/stats [استان] — آمار بی‌نام کاربران\n\n` +
            `🧪 <b>ابزار</b>\n/resolvers dnssec nolog — رزولورهای تأییدشده\n/cfip — آی‌پی‌های تمیز کلادفلر\n/tune — اسکریپت ویندوز/روتر/MTU\n\n` +
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

async function checkWatchers(env) {
  let list;
  try { list = await env.DNSRADAR_KV.list({ prefix: "w:", limit: 500 }); } catch { return; }
  for (const k of list.keys) {
    const raw = await env.DNSRADAR_KV.get(k.name);
    if (!raw) continue;
    let w; try { w = JSON.parse(raw); } catch { continue; }
    if (!w?.target || !w?.chat) continue;
    const r = EDGE_RESOLVERS[0];
    const t0 = Date.now();
    let ms = null, ok = false, rcode = null;
    try {
      const ctrl = new AbortController(); const t = setTimeout(() => ctrl.abort(), 5000);
      const res = await fetch(r.url, { method: "POST",
        headers: { "Content-Type": "application/dns-message", "Accept": "application/dns-message" },
        body: dnsPacket(w.target, undefined, { do: true }), signal: ctrl.signal });
      const p2 = parseDns(new Uint8Array(await res.arrayBuffer()));
      clearTimeout(t);
      ms = Date.now() - t0; rcode = p2.rcode; ok = (p2.rcode === 0 || p2.rcode === 3);
    } catch { ok = false; ms = null; }
    const breach = !ok || (ms !== null && ms > (w.thr || 120));
    const key = ms === null ? "down" : String(Math.round(ms / 25));
    if (breach && w.lastBreachKey !== key) {
      w.lastBreachKey = key; w.last = ms; w.lastCheck = Date.now();
      try { await env.DNSRADAR_KV.put(k.name, JSON.stringify(w)); } catch {}
      try {
        await tg(env, "sendMessage", { chat_id: w.chat, parse_mode: "HTML", disable_web_page_preview: true,
          text: `⚠️ <b>هشدار پایش</b>\n<code>${esc(w.target)}</code>\n` +
            (ok ? `تأخیر از لبه: <b>${ms} ms</b> (حد تو: ${w.thr} ms)` : "پاسخ نداد یا خطای DNS") +
            "\n\n<i>این عدد از لبهٔ ماست؛ برای خط خودت اپ را باز کن.</i>" });
      } catch {}
    } else if (!breach) {
      w.last = ms; w.lastCheck = Date.now(); w.lastBreachKey = null;
      try { await env.DNSRADAR_KV.put(k.name, JSON.stringify(w)); } catch {}
    }
  }
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(checkWatchers(env));
  },
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

      /* --- فهرست DNS جهان (کاتالوگ WorldScan) --- */
      if (p === "/api/dnslist") {
        const cc = (url.searchParams.get("cc") || "").trim().toUpperCase();
        const n = Math.min(60, Math.max(1, parseInt(url.searchParams.get("n") || "25", 10) || 25));
        const v6only = url.searchParams.get("v6") === "1";
        if (url.searchParams.get("meta") === "1") {
          return json({
            generated_at: WORLD_CATALOG.generated_at, source: WORLD_CATALOG.source,
            totals: WORLD_CATALOG.totals, curated: WORLD_CATALOG.curated_counts,
            countries: Object.entries(WORLD_CATALOG.countries || {}).map(([k, v]) => ({
              cc: k, name: v.name_fa, count: v.count, v4: v.v4, v6: v.v6,
            })),
          });
        }
        const out = { cc: cc || null, source: "public-dns.info + curated", groups: [], servers: [] };
        const groupsAll = WORLD_CATALOG.curated_groups || [];
        const hasCountry = cc && groupsAll.some((g) => g.cc === cc);
        for (const g of groupsAll) {
          if (cc) { if (g.cc !== (hasCountry ? cc : "GL")) continue; }
          else if (g.cc !== "GL") continue;
          for (const e of g.entries) {
            const ips = v6only ? (e.v6 || []) : [...(e.v4 || []), ...(e.v6 || [])];
            if (!ips.length) continue;
            out.groups.push({
              name: e.name, group: g.id, country: g.cc, ips, doh: e.doh || null,
              dot: e.dot || null, note: e.note || "",
            });
          }
        }
        const c = (WORLD_CATALOG.countries || {})[cc];
        if (c) {
          out.country = { cc, name: c.name_fa, count: c.count, v4: c.v4, v6: c.v6 };
          out.servers = (c.top || [])
            .filter((s) => (v6only ? s.v === 6 : true))
            .slice(0, n)
            .map((s) => ({ ip: s.ip, v: s.v, as: s.as, city: s.city, dnssec: s.dnssec, reliability: s.rel }));
          out.servers.sort((a, b) => (b.reliability || 0) - (a.reliability || 0));
        }
        return json(out);
      }

      /* --- سنجش اثر از لبهٔ کلادفلر: رزولور → آی‌پی → کدام PoP --- */
      if (p === "/api/impact") {
        const name = (url.searchParams.get("name") || "cdn.cloudflare.steamstatic.com").trim().slice(0, 80);
        if (!/^[a-z0-9.\-]+$/i.test(name)) return json({ ok: false, error: "نام دامنهٔ نامعتبر" }, 400);
        const list = EDGE_RESOLVERS.slice(0, 10);
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
            const p2 = parseDns(new Uint8Array(ab));
            return { resolver: r.id, label: r.name, dns_ip: r.dns, ms: Date.now() - t0,
                     rcode: p2.rcode, ips: p2.a.slice(0, 3), ttl: p2.minTtl };
          } catch (e) {
            return { resolver: r.id, label: r.name, dns_ip: r.dns, ms: null, rcode: null, ips: [],
                     err: e.name };
          } finally { clearTimeout(t); }
        };
        const results = await Promise.all(list.map(one));
        const uniq = new Set(results.flatMap((r) => r.ips));
        const answered = results.filter((r) => r.ips.length);
        return json({
          name, from: { colo: request.cf?.colo || null, country: request.cf?.country || null },
          answered: answered.length, total: results.length,
          distinct_ips: uniq.size, distinct_pops_hint: uniq.size > 1,
          results,
          note: uniq.size > 1
            ? "رزولورهای مختلف آی‌پی‌های متفاوتی دادند = PoPهای متفاوت. تأخیر تا هر PoP را از دستگاه خودت بسنج (این endpoint فقط PoP را نشان می‌دهد، نه پینگ دستگاه تو)."
            : "همهٔ رزولورها یک آی‌پی دادند.",
        });
      }


      /* --- 📍 خط من: تشخیص اپراتور/شهر از خودِ درخواست (بدون API بیرونی) --- */
      if (p === "/api/geo") {
        const cf = request.cf || {};
        return json({ ok: true, ip: request.headers.get("CF-Connecting-IP") || null,
          asn: cf.asn || null, org: cf.asOrganization || null, country: cf.country || null,
          city: cf.city || null, region: cf.region || null, lat: cf.latitude || null, lon: cf.longitude || null,
          colo: cf.colo || null, tcpRtt: (cf.clientTcpRtt ?? null), timezone: cf.timezone || null,
          carrier: carrierOf(cf.asn, cf.asOrganization), province: provinceByCityName(cf.city),
          note: "اپراتور از ASN تشخیص داده می‌شود (دقیق). شهر از IP تقریبی است — اگر غلط بود خودت انتخاب کن." });
      }

      /* --- فهرست استان/شهر + اپراتورها --- */
      if (p === "/api/ir") {
        return json({ ok: true, note: IR_GEO.note, source: IR_CARRIERS.note,
          provinces: IR_GEO.provinces.map((x) => ({ id: x.id, fa: x.fa, capital: x.capital, cities: x.cities })),
          carriers: IR_CARRIERS });
      }

      /* --- ثبت بی‌نام نتیجه (برای آمار استانی/اپراتوری) --- */
      if (p === "/api/report" && method === "POST") {
        const b = await request.json().catch(() => null);
        if (!b) return json({ ok: false, error: "بدنهٔ نامعتبر" }, 400);
        const prov = String(b.province || "?").slice(0, 24) || "?";
        const carrier = String(b.carrier || "?").slice(0, 24) || "?";
        const res = String(b.resolver || "?").slice(0, 40) || "?";
        const ms = Math.max(0, Math.min(20000, Number(b.ms) || 0));
        const key = `st:${prov}:${carrier}:${res}`;
        let cur = { n: 0, ok: 0, sum: 0, min: null, max: null };
        try { const raw = await env.DNSRADAR_KV.get(key); if (raw) cur = JSON.parse(raw); } catch {}
        cur.n++; cur.ok += b.ok === false ? 0 : 1; cur.sum += ms;
        cur.min = cur.min === null ? ms : Math.min(cur.min, ms);
        cur.max = cur.max === null ? ms : Math.max(cur.max, ms);
        cur.avg = Math.round((cur.sum / cur.n) * 10) / 10; cur.ts = Date.now();
        await env.DNSRADAR_KV.put(key, JSON.stringify(cur));
        return json({ ok: true, key, cur, note: "بی‌نام ذخیره شد: فقط استان/اپراتور/رزولور/عدد." });
      }

      /* --- آمار استانی/اپراتوری (آنچه کاربران دیگر ثبت کرده‌اند) --- */
      if (p === "/api/stats") {
        const prov = (url.searchParams.get("province") || "").trim().slice(0, 24);
        const car = (url.searchParams.get("carrier") || "").trim().slice(0, 24);
        const prefix = (prov || car) ? `st:${prov}:${car}` : "st:";
        const list = await env.DNSRADAR_KV.list({ prefix, limit: 500 });
        const rows = [];
        for (const k of list.keys) {
          const raw = await env.DNSRADAR_KV.get(k.name);
          if (!raw) continue;
          const parts = k.name.split(":");
          try { rows.push({ province: parts[1], carrier: parts[2], resolver: parts.slice(3).join(":"), ...JSON.parse(raw) }); } catch {}
        }
        rows.sort((x, y) => (x.avg ?? 1e9) - (y.avg ?? 1e9));
        return json({ ok: true, province: prov || null, carrier: car || null, count: rows.length, rows: rows.slice(0, 60),
          note: "آمار تجمیعی کاربران — تعداد نمونه (n) را ببین؛ نمونهٔ کم = اعتبار کم." });
      }

      /* --- جدول رده‌بندی استانی/اپراتوری --- */
      if (p === "/api/leaderboard") {
        const list = await env.DNSRADAR_KV.list({ prefix: "st:", limit: 800 });
        const agg = new Map();
        for (const k of list.keys) {
          const raw = await env.DNSRADAR_KV.get(k.name);
          if (!raw) continue;
          const parts = k.name.split(":"); const v = JSON.parse(raw);
          const id = parts[1] + "|" + parts[2];
          const a = agg.get(id) || { province: parts[1], carrier: parts[2], n: 0, sum: 0, resolvers: new Set() };
          a.n += v.n || 0; a.sum += (v.avg || 0) * (v.n || 0); a.resolvers.add(parts.slice(3).join(":"));
          agg.set(id, a);
        }
        const rows = [...agg.values()].map((a) => ({ province: a.province, carrier: a.carrier, n: a.n,
          avg: a.n ? Math.round((a.sum / a.n) * 10) / 10 : null, resolvers: a.resolvers.size }))
          .filter((x) => x.n >= 2).sort((x, y) => x.avg - y.avg).slice(0, 50);
        return json({ ok: true, count: rows.length, rows, note: "فقط گروه‌هایی با ۲ نمونه یا بیشتر." });
      }

      /* --- متادیتای رزولورها (DNSSEC / بدون‌لاگ / بدون‌فیلتر + DoH) --- */
      if (p === "/api/resolvers") {
        const qs = (url.searchParams.get("q") || "").toLowerCase().trim();
        const need = (url.searchParams.get("flags") || "").split(",").map((x) => x.trim()).filter(Boolean);
        const dohOnly = url.searchParams.get("doh") === "1";
        const lim = Math.min(200, Math.max(1, parseInt(url.searchParams.get("n") || "40", 10) || 40));
        let items = R_META.resolvers;
        if (qs) items = items.filter((r) => (r.n || "").includes(qs) || (r.a || "").includes(qs) || (r.d || "").toLowerCase().includes(qs));
        if (need.length) items = items.filter((r) => need.every((f) => (r.f || []).includes(f)));
        if (dohOnly) items = items.filter((r) => !!r.d);
        return json({ ok: true, total: R_META.count, matched: items.length, flags: need, items: items.slice(0, lim), source: R_META.source });
      }

      /* --- کاتالوگ بازی‌ها + سرورها (MIT — pingdiff) --- */
      if (p === "/api/games") {
        const slug = (url.searchParams.get("game") || "").trim();
        const reg = (url.searchParams.get("region") || "").trim().toUpperCase();
        if (!slug) {
          return json({ ok: true, count: Object.keys(GAMES.games).length, source: GAMES.source,
            regions_fa: GAMES.regions_fa,
            games: Object.entries(GAMES.games).map(([k, g]) => ({ slug: k, fa: g.name_fa, name: g.name,
              regions: Object.keys(g.regions), servers: Object.values(g.regions).reduce((a, b) => a + b.length, 0) })) });
        }
        const g = GAMES.games[slug];
        if (!g) return json({ ok: false, error: "بازی پیدا نشد", available: Object.keys(GAMES.games) }, 404);
        const regions = reg ? { [reg]: g.regions[reg] || [] } : g.regions;
        return json({ ok: true, slug, fa: g.name_fa, name: g.name, regions_fa: GAMES.regions_fa, regions, source: GAMES.source });
      }

      /* --- آی‌پی‌های کلادفلر دامنه‌های ایرانی (MIT — CF-Web) --- */
      if (p === "/api/cfip") {
        const qs = (url.searchParams.get("q") || "").toLowerCase().trim();
        const take = Math.min(40, Math.max(1, parseInt(url.searchParams.get("n") || "16", 10) || 16));
        let ips = CF_IR.ips;
        if (qs) ips = ips.filter((x) => x.ip.includes(qs) || (x.sample || []).some((s) => s.includes(qs)));
        return json({ ok: true, total_domains: CF_IR.domains_total, unique_ips: CF_IR.unique_ips,
          matched: ips.length, ips: ips.slice(0, take), source: CF_IR.source });
      }
      /* --- سنجش آی‌پی‌های تمیز از پروب‌های ایران --- */
      if (p === "/api/cfip-test") {
        const n = Math.min(3, Math.max(1, parseInt(url.searchParams.get("n") || "3", 10) || 3));
        const cc = (url.searchParams.get("cc") || "IR").toUpperCase().slice(0, 2);
        const cands = CF_IR.ips.slice(0, n);
        const outs = await Promise.all(cands.map(async (c) => {
          const r = await gpRun(env, { type: "ping", target: c.ip, limit: 1, locations: [{ country: cc }] }, 3600);
          const first = (r.results || [])[0];
          return { ip: c.ip, domains: (c.sample || []).slice(0, 2), avg: first ? first.avg : null,
                   loss: first ? first.loss : null, network: first ? first.network : null,
                   cached: !!r.cached, err: r.error || null };
        }));
        outs.sort((a, b) => (a.avg == null ? 1e9 : a.avg) - (b.avg == null ? 1e9 : b.avg));
        return json({ ok: true, cc, results: outs, note: "پینگ از پروب‌های داخل ایران (دیتاسنتری، نه خط موبایل)." });
      }

      /* --- پروکسی Globalping: سنجش از داخل ایران و هر کشور دیگر --- */
      if (p === "/api/gp") {
        const type = (url.searchParams.get("type") || "ping").toLowerCase();
        const target = (url.searchParams.get("target") || "1.1.1.1").trim().slice(0, 80);
        const cc = (url.searchParams.get("cc") || "IR").toUpperCase().slice(0, 2);
        const limit = Math.min(4, Math.max(1, parseInt(url.searchParams.get("limit") || "2", 10) || 2));
        const resolver = (url.searchParams.get("resolver") || "").trim().slice(0, 60);
        if (!/^[a-z0-9.\-:_\[\]]+$/i.test(target)) return json({ ok: false, error: "target نامعتبر" }, 400);
        if (!["ping", "traceroute", "dns", "http"].includes(type)) return json({ ok: false, error: "type نامعتبر", allowed: ["ping", "traceroute", "dns", "http"] }, 400);
        const payload = { type, target, limit, locations: [{ country: cc }] };
        if (type === "dns") { payload.measurementOptions = { query: { type: "A" }, protocol: "UDP", port: 53 }; if (resolver) payload.measurementOptions.resolver = resolver; }
        else if (type === "traceroute") payload.measurementOptions = { protocol: "ICMP", port: 80 };
        else if (type === "http") payload.measurementOptions = { protocol: "HTTPS", request: { path: "/" } };
        const out = await gpRun(env, payload, 600);
        return json(out.ok ? out : { ok: false, error: out.error, detail: out.detail }, out.ok ? 200 : 502);
      }

      /* --- DNSSEC + EDE از دید لبه (پرچم DO در EDNS0) --- */
      if (p === "/api/dnssec") {
        const name = (url.searchParams.get("name") || "cloudflare.com").trim().slice(0, 80);
        const rid = (url.searchParams.get("resolver") || "cloudflare").trim();
        const r = EDGE_RESOLVERS.find((x) => x.id === rid) || EDGE_RESOLVERS[0];
        if (!/^[a-z0-9.\-]+$/i.test(name)) return json({ ok: false, error: "نام نامعتبر" }, 400);
        const ctrl = new AbortController(); const t = setTimeout(() => ctrl.abort(), 5000);
        try {
          const res = await fetch(r.url, { method: "POST",
            headers: { "Content-Type": "application/dns-message", "Accept": "application/dns-message" },
            body: dnsPacket(name, undefined, { do: true }), signal: ctrl.signal });
          const p2 = parseDns(new Uint8Array(await res.arrayBuffer()));
          return json({ ok: true, name, resolver: r.id, label: r.name, ad: p2.ad, ede: p2.ede, rcode: p2.rcode,
            ips: p2.a.slice(0, 3), minTtl: p2.minTtl,
            verdict: p2.ad ? "امضای DNSSEC معتبر تأیید شد ✅" : "بدون تأیید DNSSEC (یا دامنه DNSSEC ندارد) — نه الزاماً خطر" });
        } catch (e) { return json({ ok: false, error: String(e?.name || e) }, 502); }
        finally { clearTimeout(t); }
      }

      /* --- پینگ سبک برای آزمون بافر‌بلاست (RTT خالص) --- */
      if (p === "/api/ping") return json({ ok: true, t: Date.now() });

      /* --- بار مصنوعی برای آزمون بافر‌بلاست (حداکثر ۲ مگابایت) --- */
      if (p === "/api/load") {
        const want = Math.min(2_000_000, Math.max(16 * 1024, parseInt(url.searchParams.get("bytes") || "524288", 10) || 524288));
        const chunk = new Uint8Array(64 * 1024);
        for (let i = 0; i < chunk.length; i++) chunk[i] = (i * 1103515245 + 12345) & 255;
        let sent = 0;
        const rs = new ReadableStream({ pull(c) {
          if (sent >= want) { c.close(); return; }
          const take = Math.min(chunk.length, want - sent);
          c.enqueue(chunk.slice(0, take)); sent += take;
        } });
        return new Response(rs, { headers: { "Content-Type": "application/octet-stream",
          "Cache-Control": "no-store", "Access-Control-Allow-Origin": "*" } });
      }

      /* --- تولید اسکریپت/تنظیمات (ویندوز، لینوکس، روتر، MTU) --- */
      if (p === "/api/gen") {
        const g = genText((url.searchParams.get("kind") || "windows-game").trim(), url.searchParams);
        return new Response(g.body, { headers: { "Content-Type": "text/plain; charset=utf-8",
          "Content-Disposition": `attachment; filename="${g.name}"`, "Cache-Control": "no-store", ...CORS } });
      }

      /* --- نتیجهٔ اسکن خودمان (اثر رزولور → آی‌پی → RTT) --- */
      if (p === "/api/scan") return json({ ok: true, ...SCAN_SUMMARY });

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
            { command: "dnslist", description: "لیست DNS یک کشور: /dnslist IR" },
            { command: "impact", description: "سنجش PoP برای یک دامنه: /impact <domain>" },
            { command: "geo", description: "ثبت جای من (استان/شهر)" },
            { command: "city", description: "ثبت شهر و اپراتور: /city مشهد همراه اول" },
            { command: "gp", description: "سنجش از ایران: /gp ping 1.1.1.1" },
            { command: "games", description: "کاتالوگ سرورهای بازی" },
            { command: "watch", description: "پایش خرابی: /watch discord.com 120" },
            { command: "watching", description: "لیست پایش‌های فعال" },
            { command: "stats", description: "آمار بی‌نام کاربران" },
            { command: "resolvers", description: "رزولورها با فیلتر DNSSEC/بدون‌لاگ" },
            { command: "cfip", description: "آی‌پی‌های تمیز کلادفلر (MIT — CF-Web)" },
            { command: "tune", description: "اسکریپت ویندوز/روتر/MTU" },
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
