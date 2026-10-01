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
  "Access-Control-Expose-Headers": "Date, Server-Timing",
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

/* ------------------------------------------------------------------ مسیر (AS-Path) و رادار */

/* جدول کوچک نقاط تبادل ترافیک (IXP). لینک‌های peering در RIPEstat ثبت نمی‌شوند، پس این‌ها را
   دستی نگه می‌داریم و در خروجی هم صادقانه «IXP» می‌نویسیم. */
const IX_TABLE = {
  "80.81.192": "DE-CIX Frankfurt", "80.81.193": "DE-CIX Frankfurt", "80.81.194": "DE-CIX Frankfurt",
  "80.81.195": "DE-CIX Frankfurt", "80.81.196": "DE-CIX Frankfurt",
  "195.66.224": "LINX London", "195.66.225": "LINX London", "195.66.226": "LINX London",
  "80.249.208": "AMS-IX Amsterdam", "80.249.209": "AMS-IX Amsterdam", "80.249.210": "AMS-IX Amsterdam",
  "198.32.160": "Equinix Ashburn", "198.32.176": "Equinix San Jose", "198.32.118": "Equinix Amsterdam",
  "185.1.8": "MIX Milan", "193.178.185": "France-IX Paris", "94.31.32": "Netnod Stockholm",
  "91.239.96": "DE-CIX Frankfurt",
};
/* بازه‌هایی که از داخل ایران دیده می‌شوند ولی ثبت عمومی (RIPE) ندارند — صادقانه همین را می‌نویسیم */
const IR_INTERNAL = { "185.228.239": "شبکهٔ داخلی (ثبت عمومی ندارد)", "185.228.238": "شبکهٔ داخلی (ثبت عمومی ندارد)",
  "185.228.237": "شبکهٔ داخلی (ثبت عمومی ندارد)" };
const isPrivate = (ip) => /^10\./.test(ip) || /^192\.168\./.test(ip) || /^172\.(1[6-9]|2\d|3[01])\./.test(ip) || /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(ip);
const ixOf = (ip) => { const k = ip.split(".").slice(0, 3).join("."); return IX_TABLE[k] || null; };
const irInternalOf = (ip) => { const k = ip.split(".").slice(0, 3).join("."); return IR_INTERNAL[k] || null; };

/** نام شبکهٔ هر آی‌پی با RIPEstat (بدون کلید) — با کش ۳۰ روزه */
async function asnOf(env, ip) {
  if (isPrivate(ip)) return { asn: null, holder: "شبکهٔ داخلی (خصوصی)", kind: "private" };
  const ix = ixOf(ip);
  const key = "asn:" + ip;
  try { const c = await kvGet(env,key); if (c) return JSON.parse(c); } catch {}
  const intl = irInternalOf(ip);
  let out = { asn: null, holder: intl || null, kind: ix ? "ix" : (intl ? "internal" : "unknown") };
  try {
    const r = await fetch("https://stat.ripe.net/data/prefix-overview/data.json?resource=" + ip);
    if (r.ok) {
      const j = await r.json();
      const a = ((j.data || {}).asns || [])[0] || {};
      out = { asn: a.asn || null, holder: a.holder || null, kind: ix ? "ix" : "transit" };
    }
  } catch {}
  if (out.kind !== "ix") {
    if (/cloudflare/i.test(out.holder || "")) out.kind = "cloud";
    else if (/google|akamai|amazon|microsoft|fastly|meta|facebook|apple/i.test(out.holder || "")) out.kind = "cloud";
  }
  try { await kvPut(env,key, JSON.stringify(out), { expirationTtl: 60 * 60 * 24 * 30 }); } catch {}
  return out;
}

/** رادار کلادفلر: قطعی‌ها، هجک‌های BGP، ترافیک ایران، روند ASN اپراتور */
async function radarGet(env, path) {
  const token = env.CF_API_TOKEN;
  if (!token) return { ok: false, error: "توکن Radar روی سرور تنظیم نشده" };
  const key = "rd:" + djb2(path);
  try { const c = await kvGet(env,key); if (c) return { ok: true, cached: true, ...JSON.parse(c) }; } catch {}
  try {
    const r = await fetch("https://api.cloudflare.com/client/v4/radar/" + path, { headers: { Authorization: "Bearer " + token } });
    const j = await r.json().catch(() => null);
    if (!r.ok || !j || j.success === false) return { ok: false, error: "radar " + r.status + " " + String((j && j.errors && j.errors[0] && j.errors[0].message) || "") };
    const out = { result: j.result };
    try { await kvPut(env,key, JSON.stringify(out), { expirationTtl: 900 }); } catch {}
    return { ok: true, cached: false, ...out };
  } catch (e) { return { ok: false, error: "radar fetch: " + String(e?.name || e) }; }
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
const GAME_PROFILES = __GAME_PROFILES__; // آستانه و وزن هر بازی (تجربی — در متن هم همین را می‌نویسیم)
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
/* ---------- KV امن (دور ۹): تمام‌شدن سهمیهٔ روزانهٔ KV نباید هیچ درخواستی را ۵۰۰ کند ----------
   هر خواندن/نوشتن داخل try/catch است؛ روی خطا null/false برمی‌گردد و مسیر بدون کش ادامه می‌یابد.
   کش حافظه‌ای ۱۲۰ ثانیه‌ای هم تعداد نوشتن‌های واقعی را کم می‌کند (کلیدهای شمارنده مستثنا). */
const MEMCACHE = new Map();
function memGet(key) {
  const e = MEMCACHE.get(key);
  if (!e) return undefined;
  if (Date.now() - e.at > e.ttl * 1000) { MEMCACHE.delete(key); return undefined; }
  return e.val;
}
function memSet(key, val, ttl) {
  try {
    if (MEMCACHE.size > 800) MEMCACHE.delete(MEMCACHE.keys().next().value);
    MEMCACHE.set(key, { at: Date.now(), ttl: ttl || 300, val });
  } catch {}
}
// شمارنده‌ها (خواندن-تغییر-نوشتن) نباید از حافظه خوانده شوند تا آمار دقیق بماند
const KV_NOMEM = (k) => typeof k === "string" && (k.startsWith("chb:") || k.startsWith("st:") || k.startsWith("hr:") || k.startsWith("d:2"));
async function kvGet(env, key, type) {
  if (!KV_NOMEM(key)) {
    const m = memGet("g:" + key);
    if (m !== undefined) {
      if (type === "json") { try { return typeof m === "string" ? JSON.parse(m) : m; } catch { return null; } }
      return m;
    }
  }
  try {
    const v = await env.DNSRADAR_KV.get(key, type || "text");
    if (v !== null && v !== undefined && !KV_NOMEM(key)) {
      try { memSet("g:" + key, typeof v === "string" ? v : JSON.stringify(v), 120); } catch {}
    }
    return v;
  } catch { return null; }
}
async function kvPut(env, key, val, opts) {
  if (!KV_NOMEM(key)) {
    try {
      if (memGet("g:" + key) === val) return true; // مقدار تکراری: نوشتن واقعی لازم نیست
      const ttl = (opts && opts.expirationTtl) || 300;
      memSet("g:" + key, val, Math.min(ttl, 600));
    } catch {}
  }
  try { await env.DNSRADAR_KV.put(key, val, opts || {}); return true; }
  catch { return false; }
}
async function kvDel(env, key) {
  try { MEMCACHE.delete("g:" + key); } catch {}
  try { await env.DNSRADAR_KV.delete(key); return true; } catch { return false; }
}
async function kvList(env, opts) {
  try { return await env.DNSRADAR_KV.list(opts || {}); }
  catch { return { keys: [], list_complete: true, cursor: undefined }; }
}

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
  const key = "gp:v3:" + djb2(JSON.stringify(payload));   // v2: ساختار hops اصلاح شد
  try { const c = await kvGet(env,key); if (c) return { ok: true, cached: true, ...JSON.parse(c) }; } catch {}
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
  try { await kvPut(env,key, JSON.stringify(out), { expirationTtl: ttl }); } catch {}
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
    if (Array.isArray(r.hops)) { const hh = (h) => {
        const t = (h.timings || [])[0];
        const v = t == null ? null : (typeof t === "number" ? t : (t.rtt ?? null));
        return v == null ? null : Math.round(v * 10) / 10;
      };
      return { ...base, kind: "traceroute",
        hops: r.hops.slice(0, 18).map((h) => ({ ip: h.resolvedAddress || h.address || null, ms: hh(h) })) }; }
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


/* ------------------------------------------------------------------ صفحه‌های سروشده (وضعیت/گزارش/مستندات) */

const PAGE_CSS = `
:root{--bg:#000;--card:#0e0e0e;--line:#2c2c2c;--tx:#fff;--mut:#9a9a9a;--acc:#ffc000;--ok:#34b04a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--tx);font:400 14.5px/1.9 Vazirmatn,Tahoma,system-ui,sans-serif;padding:18px}
.wrap{max-width:900px;margin:0 auto}
h1{font-size:20px;margin:6px 0 2px} h2{font-size:16px;margin:22px 0 6px;color:var(--acc)}
.card{background:var(--card);border:1px solid var(--line);padding:12px 14px;margin:10px 0}
.mut{color:var(--mut);font-size:13px}
table{width:100%;border-collapse:collapse;font-size:13px;margin-top:6px}
th,td{padding:5px 4px;border-bottom:1px solid var(--line);text-align:right}
.mono{font-family:ui-monospace,Consolas,monospace;direction:ltr}
a{color:var(--acc)} .pill{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:2px 9px;font-size:12px;margin:2px}
.ok{color:var(--ok)} .bad{color:#e53935}
`;

function shell(title, body) {
  return `<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>${esc(title)} — پینگ‌هاب</title>
<style>${PAGE_CSS}</style></head><body><div class="wrap">
<h1>⚡ ${esc(title)}</h1>
<div class="mut">سنجش از خط خودت، نه وعده. <a href="/app">اپ</a> · <a href="/status">وضعیت</a> ·
<a href="/report">گزارش</a> · <a href="/docs">مستندات API</a></div>
${body}
<div class="mut" style="margin-top:22px">پینگ‌هاب — بدون VPN، بدون فیلترشکن، بدون وعدهٔ کاهش پینگ در مچ.</div>
</div></body></html>`;
}

function statusPage(rows, outages, edge) {
  const stats = rows.length
    ? `<table><tr><th>استان / اپراتور</th><th>رزولور</th><th>میانگین</th><th>n</th></tr>` +
      rows.map((r) => `<tr><td>${esc(r.province)} / ${esc(r.carrier)}</td><td class="mono">${esc(r.resolver)}</td><td>${r.avg ?? "—"} ms</td><td>${r.n}</td></tr>`).join("") + `</table>`
    : `<div class="mut">هنوز نمونهٔ بی‌نامی ثبت نشده — اولین نفر باش: در اپ بخش «📍 خط من» → «ثبت بی‌نام».</div>`;
  const edges = `<table><tr><th>DNS</th><th>وضعیت از دید لبه</th><th>ms</th></tr>` +
    edge.map((e) => `<tr><td>${esc(e.name)}</td><td class="${e.ok ? "ok" : "bad"}">${e.ok ? "پاسخ می‌دهد" : "پاسخ نداد"}</td><td>${e.ms ?? "—"}</td></tr>`).join("") + `</table>`;
  const out = outages.length
    ? outages.map((a) => `<div class="card"><b>${esc(a.scope || "رخداد")}</b> ${a.startDate ? `<span class="mut mono">${esc(String(a.startDate).slice(0, 16))}</span>` : ""}
        <div class="mut">${esc((a.description || a.eventType || "").slice(0, 220))}</div>
        ${(a.asns || []).length ? `<div class="mut">ASN: ${(a.asns || []).slice(0, 8).map((x) => `<span class="pill mono">${esc(String(x))}</span>`).join("")}</div>` : ""}</div>`).join("")
    : `<div class="mut">رخدادِ قطعیِ اعلامی در ۲۴ ساعت گذشته ثبت نشده.</div>`;
  return shell("وضعیت شبکه و دادهٔ ما", `
    <h2>🚦 وضعیت سرورهای DNS از دید اینترنت</h2><div class="card">${edges}
      <div class="mut">این عدد از لبهٔ کلادفلر است، نه خط تو. سرورهای ایرانی از بیرون پاسخ نمی‌دهند (طبیعی است).</div></div>
    <h2>🌡️ رخدادهای اعلامی (۲۴ ساعت، رادار کلادفلر)</h2><div class="card">${out}</div>
    <h2>📊 آمار بی‌نام کاربران (بهترین‌ها)</h2><div class="card">${stats}
      <div class="mut">فقط استان/اپراتور/رزولور/عدد ذخیره می‌شود. دادهٔ خام: <a href="/api/export">JSON</a> ·
      <a href="/api/export?format=csv">CSV</a></div></div>
    <div class="mut">صفحهٔ وضعیت هر ۶۰ ثانیه خودش را تازه می‌کند… <span class="mono">${new Date().toISOString().slice(0, 16)}Z</span></div>
    <script>setTimeout(function(){location.reload()},60000)</script>`);
}

function reportPage(rows, meta) {
  const body = rows.length
    ? `<table><tr><th>استان</th><th>میانگین (ms)</th><th>نمونه</th><th>اپراتورهای دیده‌شده</th></tr>` +
      rows.map((r) => `<tr><td>${esc(r.province)}</td><td>${r.avg ?? "—"}</td><td>${r.n}</td><td>${r.carriers}</td></tr>`).join("") + `</table>`
    : `<div class="mut">داده‌ای برای گزارش نیست؛ با ثبت بی‌نام در اپ، ماه بعد این گزارش ساخته می‌شود.</div>`;
  const best = rows[0], worst = rows[rows.length - 1];
  return shell("گزارش بهداشت اینترنت (خودساخته، صادقانه)", `
    <div class="card"><b>چه چیزی اینجاست؟</b>
      <div class="mut">این گزارش از نمونه‌های بی‌نام خود کاربران ساخته می‌شود: ${meta.keyCount} گروه (استان/اپراتور/رزولور)
      و ${meta.samples} نمونه. هیچ عددی حدس زده نشده و هیچ ادعایی دربارهٔ «بهترین DNS ایران» نمی‌کنیم —
      چون بهترین، بسته به خط، ساعت و مسیر فرق می‌کند.</div>
      ${best && best.avg != null ? `<div class="mut">میانگین کمترین: <b>${esc(best.province)}</b> (${best.avg} ms) ·
      بیشترین: <b>${esc(worst ? worst.province : "")}</b> (${worst && worst.avg != null ? worst.avg : "—"} ms)
      <span class="pill">ترتیب بر اساس میانگین است، نه قضاوت کیفیت</span></div>` : ""}</div>
    <h2>استان‌ها</h2><div class="card">${body}</div>
    <h2>دادهٔ باز</h2><div class="card">
      <div class="mut">می‌توانی همین داده را بردار و خودت تحلیل کنی:
        <a href="/api/export">JSON</a> · <a href="/api/export?format=csv">CSV</a> — با ذکر منبع «پینگ‌هاب».</div>
      <div class="mut">برای مقایسه، مرجع رسمی: گزارش‌های رگولاتوری (RTT و زمان پاسخ DNS هر اپراتور) —
        که در آن‌ها هر سه اپراتور بالاتر از حد مجاز خودشان هستند.</div></div>
    <h2>آنچه این گزارش نیست</h2><div class="card"><div class="mut">
      ❌ رتبه‌بندی «بهترین DNS» برای همهٔ ایران — معنا ندارد.<br>
      ❌ ادعای کاهش پینگ در مچ بازی — DNS پینگ داخل مچ را کم نمی‌کند.<br>
      ✅ تصویری از آنچه کاربران واقعاً اندازه گرفته‌اند، با تعداد نمونه در کنار هر عدد.</div></div>`);
}

function docsPage() {
  const rows = [
    ["GET", "/api/geo", "تشخیص خط کاربر: ASN، اپراتور، شهر، لبهٔ کلادفلر"],
    ["GET", "/api/ir", "۳۱ استان · ۲۵۰ شهر · ۲۴ اپراتور با PLMN/ASN"],
    ["GET", "/api/dnslist?cc=IR", "کاتالوگ ۱۹۳ کشور (۶۲٬۷۹۰ رزولور) + گروه‌های منتخب"],
    ["GET", "/api/impact?name=…", "اثر PoP: هر رزولور چه آی‌پی می‌دهد"],
    ["GET", "/api/path?target=1.1.1.1&cc=IR", "🛰️ مسیر گام‌به‌گام از داخل ایران + ASN/IX هر گام"],
    ["GET", "/api/gp?type=ping|dns|traceroute|http&target=…&cc=IR", "سنجش از پروب‌های جهانی (کش ۱۰ دقیقه)"],
    ["GET", "/api/dnssec?name=…", "DNSSEC (پرچم AD) + کد خطای EDE"],
    ["GET", "/api/resolvers?flags=dnssec,nolog&doh=1", "۷۷۲ رزولور با پرچم‌ها و آدرس DoH (ISC)"],
    ["GET", "/api/games?q=pubg", "کاتالوگ ۱۳ بازی · ۱۶۸ سرور (تأییدشده با پینگ واقعی + منبع)"],
    ["GET", "/api/gameping?ips=8.8.8.8", "پینگ زندهٔ سرور بازی از پروب‌های ایران"],
    ["GET", "/api/dohrace?host=…", "🏁 مسابقهٔ DoH از لبهٔ شبکه (همیشه عدد واقعی)"],
    ["GET", "/api/changer", "🚀 لیست رزولورها برای حالت DNS روی گوشی (DoT/DoH + بومی)"],
    ["GET", "/api/whoami", "📶 کشور/شهر/ASN/PoP همین درخواست (لبهٔ کلادفلر)"],
    ["GET", "/api/profile?game=cs2", "🎯 آستانه‌های تجربی هر بازی"],
    ["GET", "/api/cfip · /api/cfip-test", "آی‌پی تمیز کلادفلر ایرانی (MIT) + سنجش از ایران"],
    ["GET", "/api/radar?asn=44244", "🌡️ قطعی‌ها، هجک‌های BGP و ترافیک ایران (رادار)"],
    ["GET", "/api/golden?province=تهران&carrier=ایرانسل", "🕐 ساعت طلایی (میانگین ساعتی)"],
    ["GET", "/api/trend?days=30", "📈 روند روزانه"],
    ["GET", "/api/stats · /api/leaderboard", "آمار بی‌نام استانی/اپراتوری"],
    ["POST", "/api/report", "ثبت بی‌نام یک نمونه {province,carrier,resolver,ms,ok}"],
    ["POST", "/api/team", "🤝 حالت تیمی: create | join"],
    ["GET", "/api/export?format=json|csv", "📤 دادهٔ باز (بی‌نام)"],
    ["GET", "/api/scan", "نتیجهٔ اسکن ما: اثر رزولور → آی‌پی → تأخیر"],
    ["GET", "/api/gen?kind=windows-game", "🛠 تولید اسکریپت (ویندوز/CAKE/روتر/MTU)"],
    ["GET", "/api/ping · /api/load", "RTT + بار مصنوعی (آزمون بافر‌بلاست)"],
    ["GET", "/api/filter?host=…", "🕵️ کالبدشکافی فیلترینگ: چالهٔ DNS؟ IP مسدود؟ لایهٔ TLS؟ (شاهد خام + اطمینان)"],
    ["GET", "/api/vantage?host=…&near=1", "📍 دسترسی از ۶ شهر ایران + ۳ گرهٔ همسایه (TCP/HTTPS)"],
    ["GET", "/api/wave?host=…&packets=14&cc=IR", "🌊 آزمون موج: جیتر، افت، بافت‌نگار از پروب‌های ایران"],
    ["GET", "/api/asn?ip=…", "ASN هر آی‌پی (Team Cymru، پشتیبان RIPEstat)"],
    ["GET", "/api/scanner?ips=1.1.1.1,8.8.8.8&mode=ping|dns&from=ir|world", "🎯 اسکنر IP/DNS (IPv4+IPv6+رنج): پینگ/رزولوشن از پروب‌ها + کشور و ASN"],
    ["GET", "/api/ix?asn=44244", "IX های یک ASN (PeeringDB)"],
    ["GET", "/api/ioda?cc=IR&hours=24", "🛑 قطعی‌ها از IODA (جورجیا تک)"],
    ["GET", "/api/edns", "🧭 TCP/53 از ایران + سلامت مسیر DNS (DNS Flag Day 2020)"],
    ["POST/GET", "/api/rtc?code=…", "🎙 سیگنالینگ دو-دستگاهی برای آزمون UDP (اتاق ۱۵ دقیقه‌ای)"],
  ];
  return shell("مستندات API و دادهٔ باز", `
    <div class="card"><b>قواعد استفاده</b>
      <div class="mut">همهٔ خروجی‌ها JSON و CORS-آزادند. دادهٔ جمعی «بی‌نام» است: فقط استان/اپراتور/رزولور/عدد —
      هیچ IP، شناسه یا نامی ذخیره نمی‌شود. استفادهٔ آزاد با ذکر منبع «پینگ‌هاب».</div></div>
    <h2>مسیرها</h2><div class="card"><table><tr><th>روش</th><th>مسیر</th><th>توضیح</th></tr>
      ${rows.map((r) => `<tr><td class="mono">${r[0]}</td><td class="mono">${esc(r[1])}</td><td>${esc(r[2])}</td></tr>`).join("")}
    </table></div>
    <h2>صفحه‌ها</h2><div class="card">
      <span class="pill"><a href="/app">/app — سایت و مینی‌اپ</a></span>
      <span class="pill"><a href="/status">/status — وضعیت عمومی</a></span>
      <span class="pill"><a href="/report">/report — گزارش ماهانه</a></span>
      <span class="pill"><a href="/api/export?format=csv">/api/export — CSV</a></span></div>
    <h2>صداقت مهندسی</h2><div class="card"><div class="mut">
      • پروب‌های ایران در Globalping <b>دیتاسنتری</b>اند، نه خط موبایل.<br>
      • بازهٔ <span class="mono">10.0.0.0/8</span> (رادار/۴۰۳) فقط از خط خودِ کاربر قابل سنجش است.<br>
      • لینک‌های peering (IXP) در RIPEstat ثبت نمی‌شوند؛ برچسب IX از جدول محلی ماست و همان‌جا شفاف نوشته شده.<br>
      • «DNS پینگ داخل مچ بازی را کم نمی‌کند» — این را در همهٔ بخش‌ها می‌نویسیم.</div></div>`);
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
      await kvPut(env,`user:${msg.from.id}`, JSON.stringify({
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
    await kvPut(env,`geo:${chatId}`, JSON.stringify({ province: pr?.fa || null, lat: msg.location.latitude,
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
    try { const raw = await kvGet(env,`geo:${chatId}`); if (raw) saved = JSON.parse(raw); } catch {}
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
    await kvPut(env,`geo:${chatId}`, JSON.stringify(doc), { expirationTtl: 60 * 60 * 24 * 365 });
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", reply_markup: mainKeyboard(),
      text: `✅ ثبت شد: <b>${esc(doc.city || "—")}</b>${doc.province && doc.province !== doc.city ? ` (استان ${esc(doc.province)})` : ""}${doc.carrier ? ` · <b>${esc(doc.carrier)}</b>` : ""}\n\nحالا در اپ، نتیجه‌ها را بی‌نام برای همین گروه ثبت کن.` });
    return;
  }
  if (cmd === "/watch") {
    const parts = arg.split(/\s+/);
    const target = (parts[0] || "").slice(0, 80);
    // فرمت: /watch <domain> [ms] [jitter=ms] [loss=%] [ساعت=a-b]
    const numArg = (pref, def) => { const p = parts.find((x) => x.toLowerCase().startsWith(pref)); if (!p) return def; const n = parseInt(p.split("=")[1], 10); return Number.isFinite(n) ? n : def; };
    const thr = Math.max(20, Math.min(2000, numArg("ms=", parseInt(parts[1] || "120", 10) || 120)));
    const maxJitter = Math.max(0, Math.min(5000, numArg("jitter=", 0)));
    const maxLoss = Math.max(0, Math.min(100, numArg("loss=", 50)));
    let hours = null;
    const hp = parts.find((x) => x.startsWith("ساعت=") || x.startsWith("hours="));
    if (hp) { const m = hp.split("=")[1].split("-").map((n) => parseInt(n, 10)); if (m.length === 2 && m.every((x) => x >= 0 && x <= 23)) hours = m; }
    if (!/^[a-z0-9.\-]+$/i.test(target)) {
      await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true,
        text: ["نمونه‌ها:", "<code>/watch discord.com 120</code>", "<code>/watch discord.com ms=90 jitter=20 loss=10</code>",
               "<code>/watch cdn.cloudflare.steamstatic.com ms=80 ساعت=18-24</code>", "", "شرط‌ها ترکیبی‌اند (هر کدام اول برسد، هشدار)."].join("\n") });
      return;
    }
    const doc = { chat: chatId, target, thr, maxJitter: maxJitter || 1e9, maxLoss, hours, ts: Date.now(), last: null };
    await kvPut(env,`w:${chatId}:${target}`, JSON.stringify(doc));
    const cond = [`میانه > ${thr}ms`];
    if (maxJitter) cond.push(`نوسان > ${maxJitter}ms`);
    if (maxLoss < 50) cond.push(`افت > ${maxLoss}٪`);
    if (hours) cond.push(`ساعت ${hours[0]}–${hours[1]} به وقت ایران`);
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: mainKeyboard(),
      text: `🔔 پایش فعال شد: <code>${esc(target)}</code>\nشرط‌ها: ${cond.join(" · ")}\nاگر بد شد، حداکثر هر ۳۰ دقیقه یک‌بار خبر می‌دهم. /watching` });
    return;
  }
  if (cmd === "/unwatch") {
    const t = arg.trim();
    if (!t) {
      const l = await kvList(env,{ prefix: `w:${chatId}:` });
      for (const k of l.keys) await kvDel(env,k.name);
      await tg(env, "sendMessage", { chat_id: chatId, text: "🧹 همهٔ پایش‌های تو حذف شد.", reply_markup: mainKeyboard() });
      return;
    }
    await kvDel(env,`w:${chatId}:${t}`);
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", text: `حذف شد: <code>${esc(t)}</code>`, reply_markup: mainKeyboard() });
    return;
  }
  if (cmd === "/watching") {
    const l = await kvList(env,{ prefix: `w:${chatId}:` });
    const lines = ["🔔 <b>پایش‌های فعال</b>"];
    for (const k of l.keys) {
      const raw = await kvGet(env,k.name); if (!raw) continue;
      let w; try { w = JSON.parse(raw); } catch { continue; }
      const extras = [];
      if (w.maxJitter && w.maxJitter < 1e8) extras.push(`نوسان≤${w.maxJitter}ms`);
      if (w.maxLoss != null && w.maxLoss < 50) extras.push(`افت≤${w.maxLoss}٪`);
      if (w.hours) extras.push(`ساعت ${w.hours[0]}–${w.hours[1]}`);
      lines.push(`• <code>${esc(w.target)}</code> — حد ${w.thr} ms${extras.length ? ` · ${extras.join(" · ")}` : ""}` +
        (w.last != null ? ` · آخرین: ${w.last} ms${w.loss != null ? ` (افت ${w.loss}٪)` : ""}` : ""));
    }
    if (l.keys.length === 0) lines.push("چیزی فعال نیست. <code>/watch discord.com 120</code>");
    await tg(env, "sendMessage", { chat_id: chatId, parse_mode: "HTML", disable_web_page_preview: true, reply_markup: mainKeyboard(), text: lines.join("\n") });
    return;
  }
  if (cmd === "/stats") {
    const prov = arg.trim().split(/\s+/)[0] || "";
    const prefix = prov ? `st:${prov}:` : "st:";
    const l = await kvList(env,{ prefix, limit: 400 });
    const rows = [];
    for (const k of l.keys) {
      const raw = await kvGet(env,k.name); if (!raw) continue;
      const parts = k.name.split(":"); let v; try { v = JSON.parse(raw); } catch { continue; }
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
  try { list = await kvList(env,{ prefix: "w:", limit: 500 }); } catch { return; }
  const r = EDGE_RESOLVERS[0];
  for (const k of list.keys) {
    const raw = await kvGet(env,k.name);
    if (!raw) continue;
    let w; try { w = JSON.parse(raw); } catch { continue; }
    if (!w?.target || !w?.chat) continue;
    // ساعت مجاز (به وقت ایران) — اگر تعیین شده و بیرون بازه باشیم، بررسی نمی‌کنیم
    const irHour = new Date(Date.now() + 3.5 * 3600 * 1000).getUTCHours();
    if (Array.isArray(w.hours) && w.hours.length === 2) {
      const [a, b2] = w.hours;
      const inRange = a <= b2 ? (irHour >= a && irHour < b2) : (irHour >= a || irHour < b2);
      if (!inRange) continue;
    }
    // سه نمونهٔ سریع برای میانه/نوسان/افت
    const samples = [];
    for (let i = 0; i < 3; i++) {
      const t0 = Date.now();
      try {
        const ctrl = new AbortController(); const t = setTimeout(() => ctrl.abort(), 4000);
        const res = await fetch(r.url, { method: "POST",
          headers: { "Content-Type": "application/dns-message", "Accept": "application/dns-message" },
          body: dnsPacket(w.target, undefined, { do: true }), signal: ctrl.signal });
        const p2 = parseDns(new Uint8Array(await res.arrayBuffer()));
        clearTimeout(t);
        samples.push({ ms: Date.now() - t0, ok: p2.rcode === 0 || p2.rcode === 3 });
      } catch { samples.push({ ms: null, ok: false }); }
    }
    const good = samples.filter((x) => x.ok && x.ms != null).map((x) => x.ms).sort((a, b2) => a - b2);
    const ms = good.length ? Math.round(good[Math.floor(good.length / 2)]) : null;
    const jitter = good.length > 1 ? Math.max(...good) - Math.min(...good) : 0;
    const loss = Math.round(((samples.length - samples.filter((x) => x.ok).length) / samples.length) * 100);
    const reasons = [];
    if (loss > (w.maxLoss ?? 50)) reasons.push(`افت ${loss}٪`);
    if (ms != null && ms > (w.thr || 120)) reasons.push(`میانه ${ms}ms > حد ${w.thr || 120}ms`);
    if (ms != null && jitter > (w.maxJitter || 1e9)) reasons.push(`نوسان ${jitter}ms > حد ${w.maxJitter}ms`);
    if (ms == null && loss > 0) reasons.push("پاسخ نگرفت");
    const breach = reasons.length > 0;
    const cooldown = 30 * 60 * 1000;
    w.last = ms; w.jitter = jitter; w.loss = loss; w.lastCheck = Date.now();
    if (breach && (!w.lastAlert || Date.now() - w.lastAlert > cooldown)) {
      w.lastAlert = Date.now();
      try {
        await tg(env, "sendMessage", { chat_id: w.chat, parse_mode: "HTML", disable_web_page_preview: true,
          text: `⚠️ <b>هشدار پایش</b>\n<code>${esc(w.target)}</code>\n` +
            `دلیل: ${reasons.join(" · ")}\nمیانه ${ms ?? "—"}ms · نوسان ${jitter}ms · افت ${loss}٪\n\n` +
            "<i>از لبهٔ ما اندازه‌گیری شد؛ برای خط خودت اپ را باز کن.</i>" });
      } catch {}
    }
    try { await kvPut(env,k.name, JSON.stringify(w)); } catch {}
  }
}

/* ================================================================
   Phase E — کالبدشکافی فیلترینگ + مهندسیِ نتِ بد  (نسخهٔ ۲، موتور Globalping)
   شاهدهای زنده (۲۰۲۶-۱۰-۰۱ دستی تأیید شد):
     • Globalping از پروب‌های ایران: dns (رزولور خود شبکه) / dns با رزولور و پروتکل TCP
       / ping با timings حقیقی / http با status و timings
       — نمونهٔ واقعی: twitter.com از یک شبکهٔ تهران 10.10.34.36 (چالهٔ سانسور) و از شبکهٔ
         دیگر 162.159.140.229؛ و کوئری به 8.8.8.8 هم از یک شبکه چاله برگرداند = دزدی DNS.
     • check-host.net: check-dns/check-tcp/check-http از ۸ گره شهری ایران — وقتی در دسترس
       باشد (از برخی آی‌پی‌های خروجی ورکر سقف می‌خورد) به‌عنوان شاهد مکمل.
     • Team Cymru (DNS) · PeeringDB · IODA · M-Lab locate · DoH مستقل (گوگل/کلادفلر/ادگارد)
   قاعده: هر عدد با شاهد، هر حکم با درجهٔ اطمینان، نبودِ شاهد صریح اعلام می‌شود.
   ================================================================ */

const CH_BASE = "https://check-host.net";
const CH_UA = { "Accept": "application/json", "User-Agent": "Pinghab/2.1 (+https://github.com/Alisarani7021/pinghab)" };
const GP_UA = { "Content-Type": "application/json", "User-Agent": "Pinghab/2.1 (+https://github.com/Alisarani7021/pinghab)" };

const CH_IR = [
  { node: "ir1", city: "تهران",  asn: "AS47430" },  { node: "ir2", city: "اصفهان", asn: "AS209279" },
  { node: "ir3", city: "شیراز",  asn: "AS213953" }, { node: "ir4", city: "شیراز",  asn: "AS212077" },
  { node: "ir5", city: "تهران",  asn: "AS214431" }, { node: "ir6", city: "قم",     asn: "AS206596" },
  { node: "ir7", city: "تهران",  asn: "AS213727" }, { node: "ir8", city: "تهران",  asn: "AS214361" },
];
const CH_NEAR = [
  { node: "tr1", city: "استانبول",  cc: "TR" }, { node: "de4", city: "فرانکفورت", cc: "DE" },
  { node: "nl1", city: "آمستردام",  cc: "NL" },
];

const isSinkhole = (ip) => {
  const s = String(ip || "");
  return /^10\.10\.34\./.test(s) || /^10\./.test(s) || /^127\./.test(s) || /^0\./.test(s) ||
         /^192\.168\./.test(s) || /^169\.254\./.test(s) || /10:10:34/i.test(s) || /^::1?$/.test(s);
};
const isV6Sink = (ip) => /2001:4188:2:600:10:10:34:/i.test(String(ip || "")) || /10:10:34/i.test(String(ip || ""));

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/* ------------------------- Globalping (موتور اصلی) ------------------------- */
async function gpSubmit(payload) {
  try {
    const r = await fetch("https://api.globalping.io/v1/measurements", { method: "POST", headers: GP_UA, body: JSON.stringify(payload), signal: AbortSignal.timeout(15000) });
    if (!r.ok) return { err: "gp_" + r.status };
    const j = await r.json();
    return j && j.id ? { id: j.id } : { err: "gp_no_id" };
  } catch { return { err: "gp_net" }; }
}
async function gpFetch(id) {
  try {
    const r = await fetch(`https://api.globalping.io/v1/measurements/${id}`, { headers: { "User-Agent": GP_UA["User-Agent"] }, signal: AbortSignal.timeout(15000) });
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}
async function gpProbe(env, payload, ttl = 900) {
  const key = "wv:" + djb2(JSON.stringify(payload));
  const hit = await kvGet(env,key, "json");
  if (hit) return hit;
  const s = await gpSubmit(payload);
  if (s.err) return { ok: false, error: s.err };
  for (let i = 0; i < 9; i++) {
    await sleep(2200);
    const d = await gpFetch(s.id);
    if (d && d.status === "finished") {
      await kvPut(env,key, JSON.stringify(d), { expirationTtl: ttl });
      return d;
    }
    if (d && d.status === "failed") return { ok: false, error: "gp_failed" };
  }
  return { ok: false, error: "gp_timeout" };
}

function gpDnsRows(d) {
  return ((d && d.results) || []).map((r) => {
    const res = r.result || {};
    const ans = res.answers || [];
    const a = ans.filter((x) => x.type === "A").map((x) => x.value);
    const aaaa = ans.filter((x) => x.type === "AAAA").map((x) => x.value);
    return {
      city: (r.probe || {}).city, network: (r.probe || {}).network, asn: (r.probe || {}).asn,
      resolver: res.resolver || null,
      a, aaaa,
      ok: res.status === "finished", err: res.status === "finished" ? null : (res.status || "بی‌پاسخ"),
      ttl: ans.length ? ans[0].ttl : null,
    };
  });
}
function gpHttpRows(d) {
  return ((d && d.results) || []).map((r) => {
    const res = r.result || {}; const t = res.timings || {};
    return { city: (r.probe || {}).city, network: (r.probe || {}).network, asn: (r.probe || {}).asn,
      ok: res.status === "finished" && res.statusCode != null,
      status: res.status, status_code: res.statusCode || null,
      total_ms: t.total != null ? Math.round(t.total) : null,
      tls_ms: t.tls != null ? Math.round(t.tls) : null,
      resolved: res.resolvedAddress || null };
  });
}

/* ------------------------- check-host (شاهد مکمل) ------------------------- */
async function chAvailable(env) {
  try { return !(await kvGet(env,"ch:off")); } catch { return true; }
}
async function chMarkOff(env) {
  try { await kvPut(env,"ch:off", String(Date.now()), { expirationTtl: 3600 }); } catch {}
}

async function chBudget(env, n) {
  if (!env || !env.DNSRADAR_KV) return true;
  try {
    const k = "chb:" + new Date(Date.now() + 3.5 * 3600 * 1000).toISOString().slice(0, 13);
    const cur = parseInt((await kvGet(env,k)) || "0", 10) || 0;
    if (cur + n > 120) return false;
    await kvPut(env,k, String(cur + n), { expirationTtl: 7200 });
    return true;
  } catch { return true; }
}
async function chStart(env, kind, target, nodes) {
  const q = nodes.map((n) => `node=${encodeURIComponent(n)}.node.check-host.net`).join("&");
  const url = `${CH_BASE}/check-${kind}?${q}&host=${encodeURIComponent(target)}`;
  try {
    const r = await fetch(url, { headers: CH_UA, signal: AbortSignal.timeout(9000) });
    if (!r.ok) return null;
    const j = await r.json();
    if (!j || j.error || !j.request_id) return null;
    return j.request_id;
  } catch { return null; }
}
async function chResult(id) {
  try {
    const r = await fetch(`${CH_BASE}/check-result/${id}`, { headers: CH_UA, signal: AbortSignal.timeout(8000) });
    if (!r.ok) return null;
    return await r.json();
  } catch { return null; }
}
const chDone = (j) => { const vs = Object.values(j || {}); return vs.length > 0 && vs.every((v) => v !== null && v !== undefined); };
async function chCollect(ids, tries = 3, gap = 1800) {
  const out = {};
  const keys = Object.keys(ids).filter((k) => ids[k]);
  for (let round = 0; round < tries; round++) {
    let all = true;
    for (const k of keys) {
      if (out[k] && chDone(out[k])) continue;
      const j = await chResult(ids[k]);
      if (j) { out[k] = j; if (!chDone(j)) all = false; } else all = false;
    }
    if (all) break;
    if (round < tries - 1) await sleep(gap);
  }
  return out;
}
function chNode(v) {
  if (!v || !Array.isArray(v) || !v.length) return { ok: false, err: "بی‌پاسخ" };
  const f = v[0];
  if (typeof f === "string") return { ok: false, err: f.slice(0, 40) };
  if (f && typeof f === "object") {
    if (f.error) return { ok: false, err: String(f.error).slice(0, 40) };
    return { ok: true, t: f.time != null ? Math.round(f.time * 1000) : null, data: f };
  }
  return { ok: false, err: "نامعلوم" };
}
function chDnsRows(res) {
  return CH_IR.filter((n) => res[n.node + ".node.check-host.net"] !== undefined).map((n) => {
    const raw = res[n.node + ".node.check-host.net"];
    const one = Array.isArray(raw) ? raw[0] : raw;
    let ips = [], v6 = [], ttl = null, err = null;
    if (typeof one === "string") err = one.slice(0, 40);
    else if (one && typeof one === "object") { ips = one.A || []; v6 = one.AAAA || []; ttl = one.TTL != null ? one.TTL : null; }
    else err = "بی‌پاسخ";
    return { city: n.city, asn: n.asn, a: ips, aaaa: v6, ttl, err };
  });
}
function chTcpRows(res, nodes) {
  return (nodes || []).filter((n) => res[n.node + ".node.check-host.net"] !== undefined).map((n) => {
    const r = chNode(res[n.node + ".node.check-host.net"]);
    return { city: n.city, ok: r.ok, ms: r.t, err: r.err || null };
  });
}

/* ==================== /api/filter — چرا فیلتر است؟ ==================== */
async function filterProbe(env, host) {
  const key = "flt:v2:" + host.toLowerCase();
  const hit = await kvGet(env,key, "json");
  if (hit && Date.now() - (hit.at || 0) < 20 * 60 * 1000) return { ...hit, cache: "hit" };
  const chOpen = await chAvailable(env);
  const budget = chOpen && (await chBudget(env, 6));

  /* ۱) رزولوشن بی‌طرف از سه DoH مستقل */
  const NEUTRAL = [
    { id: "google", name: "گوگل", url: "https://dns.google/resolve" },
    { id: "cloudflare", name: "کلادفلر", url: "https://cloudflare-dns.com/dns-query" },
    { id: "adguard", name: "ادگارد", url: "https://dns.adguard-dns.com/resolve" },
  ];
  const neutralP = (async () => {
    const out = [];
    for (const r of NEUTRAL) {
      const t0 = Date.now();
      try {
        const res = await fetch(`${r.url}?name=${encodeURIComponent(host)}&type=A`,
          { headers: { accept: "application/dns-json" }, signal: AbortSignal.timeout(6000) });
        const j = await res.json();
        out.push({ id: r.id, name: r.name, ms: Date.now() - t0, status: j.Status,
          ips: (j.Answer || []).filter((a) => a.type === 1).map((a) => a.data) });
      } catch { out.push({ id: r.id, name: r.name, ms: null, status: null, ips: [], err: "unreachable" }); }
    }
    return out;
  })();

  /* ۲) سه سنجش موازی از پروب‌های ایران */
  const pDns = gpProbe(env, { type: "dns", target: host, locations: [{ country: "IR" }], limit: 5 }, 900);
  const pHttp = gpProbe(env, { type: "http", target: host, locations: [{ country: "IR" }], limit: 4 }, 900);
  const pTcp = gpProbe(env, { type: "dns", target: host, locations: [{ country: "IR" }], limit: 3,
    measurementOptions: { resolver: "8.8.8.8", protocol: "TCP", port: 53 } }, 900);

  /* ۳) شاهد مکمل شهر‌به‌شهر (اگر درگاه در دسترس باشد) */
  let chPromise = Promise.resolve(null);
  if (budget) {
    chPromise = (async () => {
      const nodes5 = ["ir1", "ir2", "ir3", "ir6", "ir8"];
      const nodes3 = ["ir1", "ir3", "ir6"];
      const ids = {};
      ids.dns = await chStart(env, "dns", host, nodes5);
      ids.http = await chStart(env, "http", "https://" + host, nodes5);
      ids.ctl = await chStart(env, "tcp", "1.1.1.1:443", nodes3);
      const res = await chCollect(ids, 3, 1800);
      const anyDns = CH_IR.some((n) => res.dns && res.dns[n.node + ".node.check-host.net"] !== undefined);
      const anyTcp = CH_IR.some((n) => res.ctl && res.ctl[n.node + ".node.check-host.net"] !== undefined);
      if (!anyDns && !anyTcp) { await chMarkOff(env); return { available: false, retry_in_min: 60,
        note: "check-host از مسیر این ورکر سقف/مسدود بود؛ یک ساعت دیگر خودکار دوباره امتحان می‌شود." }; }
      return {
        available: true,
        dns: chDnsRows(res.dns || {}),
        http: nodes5.map((nd) => { const m = CH_IR.find((x) => x.node === nd);
          const r = chNode((res.http || {})[nd + ".node.check-host.net"]); return { city: m.city, ok: r.ok, ms: r.t, err: r.err || null }; }),
        control: chTcpRows(res.ctl || {}, nodes3.map((n) => CH_IR.find((x) => x.node === n))),
      };
    })();
  }

  const [neutral, dDns, dHttp, dTcp, ch] = await Promise.all([neutralP, pDns, pHttp, pTcp, chPromise]);

  const neutralIps = [...new Set(neutral.flatMap((n) => n.ips))];
  const irRows = dDns && dDns.results ? gpDnsRows(dDns) : [];
  const irIps = [...new Set(irRows.flatMap((r) => r.a))];
  const irV6 = [...new Set(irRows.flatMap((r) => r.aaaa))];
  const tcpRows = dTcp && dTcp.results ? gpDnsRows(dTcp) : [];
  const httpRows = dHttp && dHttp.results ? gpHttpRows(dHttp) : [];

  const sinkLocal = [...irIps, ...irV6].filter((ip) => isSinkhole(ip) || isV6Sink(ip));
  const sinkViaPublic = [...new Set(tcpRows.flatMap((r) => r.a.concat(r.aaaa)))].filter((ip) => isSinkhole(ip) || isV6Sink(ip));
  const hijack = sinkViaPublic.length > 0;
  const split = irIps.length > 1 || (sinkLocal.length > 0 && irIps.some((ip) => !isSinkhole(ip)));
  const mismatch = irIps.length > 0 && neutralIps.length > 0 && !irIps.some((ip) => neutralIps.includes(ip)) && !sinkLocal.length;
  const httpOk = httpRows.filter((r) => r.ok).length;
  const httpTot = httpRows.length;
  const chAvail = !!(ch && ch.available);
  const chControlOk = chAvail ? (ch.control || []).some((c) => c.ok) : null;
  const chHttpOk = chAvail ? (ch.http || []).filter((x) => x.ok).length : null;

  let verdict;
  if (hijack) {
    verdict = { code: "dns_hijack", fa: "شبکهٔ تو کوئری DNS را می‌دزدد",
      layer: "لایهٔ DNS (دزدی شفاف)", conf: 0.95,
      what: "حتی وقتی مستقیم از یک رزولور عمومی (۸.۸.۸.۸) و روی TCP پرسیدیم، پاسخِ چالهٔ سانسور برگشت. یعنی شبکه کوئری را در میانه راه می‌قاپد و به تو دروغ می‌گوید — نه رزولور محلی مقصر است، نه انتخاب رزولور.",
      fix: "در این حالت «DNS بهتر عوض‌کردن» روی این خط جواب نمی‌دهد؛ چون خودِ مسیر کوئری دست‌کاری می‌شود. راه مؤثر، بردن کوئری در بستری است که قابل‌قاپیدن نیست (DoH/DoT رمزنگاری‌شده) یا مسیر دیگر.",
      notfix: "ست‌کردن 1.1.1.1 روی گوشی — همان‌طور که دیده می‌شود، جواب نمی‌دهد." };
  } else if (sinkLocal.length) {
    verdict = { code: "dns_sinkhole", fa: "رزولورهای این شبکه چالهٔ سانسور را تحویل می‌دهند",
      layer: "لایهٔ DNS", conf: 0.95,
      what: "پروبی که با رزولور خودِ شبکه پرسید، به‌جای آی‌پی واقعی، آی‌پی معلوم چالهٔ سانسور ایران (" + sinkLocal.slice(0, 2).join(", ") + ") را گرفت.",
      fix: "این لایه با رزولوشن رمزنگاری‌شده (DoH/DoT) یا رزولور سالم حل می‌شود — به شرطی که مسیر کوئری دزدیده نشود (آزمون ۸.۸.۸.۸ بالا همین را می‌سنجد).",
      notfix: "تونل/VPN برای این لایه لازم نیست؛ مشکل فقط نام است، نه مسیر بستهٔ داده." };
  } else if (mismatch || split) {
    verdict = { code: "dns_split", fa: "پاسخ داخل ایران و بیرون فرق دارد",
      layer: "لایهٔ DNS (احتمالی)", conf: 0.7,
      what: "شبکه‌های ایرانی برای این نام پاسخ متفاوتی از رزولورهای بی‌طرف می‌دهند. بخشی از این تفاوت می‌تواند اثر PoP/CDN باشد و بخشی تفکیک عمدی — از یک نمونه حکم قطعی نمی‌سازیم.",
      fix: "با دو دامنهٔ دیگر هم امتحان کن؛ اگر الگو تکرار شد، DoH/DoT این لایه را دور می‌زند.",
      notfix: "حکم قطعی از یک نمونه نگیر." };
  } else if (httpTot >= 2 && httpOk === 0) {
    verdict = { code: "reach_blocked", fa: "از داخل ایران به سرویس نمی‌رسد",
      layer: "لایهٔ دسترسی (آی‌پی/SNI)", conf: 0.75,
      what: "پروبی‌های ایرانی نتوانستند اتصال HTTPS را کامل کنند (حتی وقتی نام‌شان درست حل شد). الگو: مسدودسازی در سطح مقصد/نام، نه صرفاً DNS.",
      fix: "این لایه با تغییر DNS حل نمی‌شود. ابزارهای مستقلِ عبور از فیلتر همین لایه را هدف می‌گیرند؛ پینگ‌هاب طبق خط قرمز خودش تونل نمی‌سازد و فقط تشخیص می‌دهد.",
      notfix: "«DNS بهتری پیدا کنم» — بی‌اثر است." };
  } else if (httpOk >= 2) {
    verdict = { code: "reachable", fa: "از پروب‌های ایرانی باز است",
      layer: "هیچ لایهٔ مسدودی دیده نشد", conf: 0.7,
      what: "هم رزولوشن سالم بود، هم اتصال‌ها برقرار شدند. اگر روی خط خودت مشکل داری، احتمالاً مسئلهٔ خط/اپراتور است نه مقصد.",
      fix: "«🧪 صف و سیاست اپراتور» و «🌊 آزمون موج» را روی همین خط خودت بزن.",
      notfix: "پروب‌ها دیتاسنتری‌اند؛ خط موبایل می‌تواند سخت‌گیرتر باشد." };
  } else {
    verdict = { code: "unknown", fa: "نتیجهٔ قطعی نشد", layer: "نامعلوم", conf: 0.3,
      what: "شاهد کافی برنگشت (پروب‌های ایران پاسخ ندادند یا منبع سقف خورد).",
      fix: "یک دقیقه بعد دوباره بزن.", notfix: "از دادهٔ ناقص حکم نمی‌سازیم." };
  }

  /* «چرا پاسخ نداد»: پروبی که جواب نمی‌دهد نشانهٔ شبکهٔ بد نیست — خیلی از گیت‌وی‌ها
     پرسش ICMP/DNS از بیرون را می‌بندند. هر ردیف ناموفق دلیل صریح می‌گیرد. */
  const WHY_NO_REPLY = "پاسخی نیامد — احتمالاً فیلتر ICMP/پورت در سمت هدف است یا پروب دیتاسنتری اجازهٔ پرسش از بیرون را ندارد (نه اینکه «شبکه خراب» باشد).";
  const markRows = (rows) => rows.map((r) => ({ ...r, why: r.ok ? null : (r.err || "بی‌پاسخ"), why_fa: r.ok ? null : WHY_NO_REPLY }));
  const rowsAll = irRows.concat(tcpRows).concat(httpRows);
  const probeHealth = {
    total: rowsAll.length, answered: rowsAll.filter((r) => r.ok).length, failed: rowsAll.filter((r) => !r.ok).length,
    note: "پروب‌های ایران دیتاسنتری‌اند؛ «پاسخ نداد» با «کند/خراب» یکی نیست — دلیلش کنار هر ردیف نوشته شده است.",
  };
  const out = {
    ok: true, host, at: Date.now(), cache: "miss",
    neutral, neutral_ips: neutralIps,
    ir_dns: markRows(irRows), ir_via_public: markRows(tcpRows), ir_http: markRows(httpRows),
    probe_health: probeHealth,
    sinkhole_ips: [...new Set(sinkLocal.concat(sinkViaPublic))],
    hijack,
    checkhost: chAvail ? ch : { available: false, retry_in_min: chOpen ? 60 : 60,
      note: chOpen ? "دادهٔ شهری برنگشت؛ یک ساعت دیگر خودکار دوباره تلاش می‌شود." : "در وضعیت انتظار است (سقف منبع)؛ یک ساعت دیگر خودکار برمی‌گردد." },
    verdict,
    sources: {
      globalping_dns: dDns && dDns.results ? "ok" : ((dDns && dDns.error) || "unavailable"),
      globalping_http: dHttp && dHttp.results ? "ok" : ((dHttp && dHttp.error) || "unavailable"),
      globalping_dns_tcp: dTcp && dTcp.results ? "ok" : ((dTcp && dTcp.error) || "unavailable"),
      checkhost: chAvail ? "ok" : "unavailable",
      neutral_doh: neutral.filter((x) => x.ips && x.ips.length).length ? "ok" : "partial",
    },
    limits: [
      "پروب‌های ایران در Globalping شبکهٔ دیتاسنتری‌اند، نه خط موبایل تو — سخت‌گیری خط موبایل معمولاً بیشتر است.",
      "«قاپیدن DNS» ممکن است بسته به شبکه فرق کند؛ چند شبکه در یک اندازه‌گیری دیده می‌شود ولی خط تو می‌تواند متفاوت باشد.",
      "هر حکم با درجهٔ اطمینان و شاهد خام منتشر می‌شود؛ «نشانه» را «اثبات» نمی‌نامیم.",
    ],
  };
  await kvPut(env,key, JSON.stringify(out), { expirationTtl: 6 * 3600 });
  return out;
}

/* ==================== /api/vantage — نقطه‌به‌نقطه از شبکه‌های ایران ==================== */
async function vantageProbe(env, host, near) {
  const key = "vnt:v2:" + host.toLowerCase() + (near ? ":n" : "");
  const hit = await kvGet(env,key, "json");
  if (hit && Date.now() - (hit.at || 0) < 15 * 60 * 1000) return { ...hit, cache: "hit" };

  const pPing = gpProbe(env, { type: "ping", target: host, locations: [{ country: "IR" }], limit: 6,
    measurementOptions: { packets: 5 } }, 900);
  const pHttp = gpProbe(env, { type: "http", target: host.replace(/^https?:\/\//, ""), locations: [{ country: "IR" }], limit: 6 }, 900);
  let pNear = Promise.resolve(null);
  if (near) pNear = gpProbe(env, { type: "ping", target: host, locations: [{ country: "TR" }, { country: "DE" }, { country: "NL" }], limit: 3,
    measurementOptions: { packets: 5 } }, 900);

  const [dPing, dHttp, dNear] = await Promise.all([pPing, pHttp, pNear]);
  const rows = [];
  const hMap = {};
  gpHttpRows(dHttp).forEach((h) => { hMap[(h.city || "") + "|" + (h.network || "")] = h; });
  ((dPing && dPing.results) || []).forEach((r) => {
    const st = waveStats((r.result && r.result.timings) || []);
    const stats = (r.result && r.result.stats) || {};
    const key2 = ((r.probe || {}).city || "") + "|" + ((r.probe || {}).network || "");
    const h = hMap[key2] || {};
    const sLoss = stats.loss != null ? stats.loss : (st ? Math.max(0, Math.round((1 - st.n / 5) * 1000) / 10) : 100);
    rows.push({
      city: (r.probe || {}).city, network: (r.probe || {}).network, asn: (r.probe || {}).asn,
      avg: st ? st.avg : null, min: st ? st.min : null, max: st ? st.max : null, jitter: st ? st.jitter : null,
      loss: sLoss, sanity: probeSanity(st, sLoss, 5),
      http_ok: !!h.ok, http_ms: h.total_ms != null ? h.total_ms : null,
    });
  });
  // هر شبکهٔ HTTP که پینگ نداد را هم اضافه کن
  gpHttpRows(dHttp).forEach((h) => {
    if (!rows.some((x) => x.city === h.city && x.network === h.network))
      rows.push({ city: h.city, network: h.network, asn: h.asn, avg: null, min: null, max: null, jitter: null, loss: null,
        http_ok: !!h.ok, http_ms: h.total_ms != null ? h.total_ms : null });
  });
  const nearRows = (((dNear || {}).results) || []).map((r) => {
    const st = waveStats((r.result && r.result.timings) || []);
    return { city: (r.probe || {}).city, network: (r.probe || {}).network, cc: (r.probe || {}).country,
      avg: st ? st.avg : null, ok: (r.result || {}).status === "finished" };
  });
  const live = rows.filter((r) => r.avg != null && (!r.sanity || r.sanity.trusted)).sort((a, b) => a.avg - b.avg);
  const suspect = rows.filter((r) => r.sanity && !r.sanity.trusted);
  const out = {
    ok: true, host, at: Date.now(), cache: "miss", rows,
    near: nearRows.slice(0, 8),
    summary: {
      networks: rows.length,
      reachable: rows.filter((r) => r.http_ok).length,
      best: live[0] ? { city: live[0].city, network: live[0].network, avg: live[0].avg } : null,
      worst: live.length ? { city: live[live.length - 1].city, network: live[live.length - 1].network, avg: live[live.length - 1].avg } : null,
      spread_ms: live.length ? Math.round(live[live.length - 1].avg - live[0].avg) : null,
      trusted: live.length, excluded: suspect.length,
      excluded_rows: suspect.map((r) => ({ network: r.network, city: r.city, avg: r.avg, why: (r.sanity.flags || []).map((x) => SANITY_FA[x]) })),
      credible: live.length >= 2,
    },
    note: "پینگ و HTTPS از شبکه‌های دیتاسنتری ایران؛ «تفاوت بهترین و بدترین شبکه» دقیقاً همان چیزی است که انتخاب رزولور/مسیر را معنادار می‌کند.",
    sources: ["Globalping"],
  };
  await kvPut(env,key, JSON.stringify(out), { expirationTtl: 3600 });
  return out;
}

/* --- سنجش سلامت پروب: پروب «نانشنه» را از عدد معتبر جدا می‌کند ---
   نمونهٔ واقعی: پروب Batterflyai از تهران روی discord.com عدد ثابت ۱۹۹٫۹ داد؛
   همان پروب روی cdn.cloudflare.steamstatic.com هم دقیقاً ۱۹۹٫۹ داد ⇒ عدد، اثر شبکه نیست. */
function probeSanity(st, loss, expected) {
  const raws = (st && Array.isArray(st.raw) ? st.raw : []).filter((x) => typeof x === "number");
  const flags = [];
  let spread = null, sd = null;
  if (raws.length >= 8) {
    spread = Math.max(...raws) - Math.min(...raws);
    sd = st && st.sd != null ? st.sd : null;
    const avg = st && st.avg != null ? st.avg : raws.reduce((a, b) => a + b, 0) / raws.length;
    if (avg >= 120 && spread <= 2 && (sd == null || sd < 0.6)) flags.push("quantized_clock");
  }
  if (loss === 100 || (st && st.n === 0)) flags.push("icmp_filtered");
  else if (st && st.n != null && expected && st.n < expected * 0.5) flags.push("lossy");
  const bad = flags.includes("quantized_clock") || flags.includes("icmp_filtered");
  return { flags, spread, sd, n: (st && st.n != null ? st.n : raws.length), trusted: !bad };
}
const SANITY_FA = {
  quantized_clock: "ساعت/ICMP این پروب کوانتش‌شده — عدد ثابت است و اثر شبکه را نشان نمی‌دهد",
  icmp_filtered: "این پروب به ICMP جواب نمی‌دهد (فیلتر/بلاک در شبکهٔ پروب)",
  lossy: "بخشی از بسته‌ها گم شد",
};
function sanitySummary(rows) {
  const valid = rows.filter((r) => r.sanity && r.sanity.trusted && r.avg != null);
  const q = rows.filter((r) => r.sanity && r.sanity.flags.includes("quantized_clock"));
  const f = rows.filter((r) => r.sanity && r.sanity.flags.includes("icmp_filtered"));
  const avgs = valid.map((r) => r.avg).sort((a, b) => a - b);
  const jits = valid.map((r) => (r.jitter != null ? r.jitter : null)).filter((x) => x != null);
  const sds = valid.map((r) => (r.sanity && r.sanity.sd != null ? r.sanity.sd : null)).filter((x) => x != null);
  const losses = rows.map((r) => (r.loss != null ? r.loss : null)).filter((x) => x != null);
  const samples = valid.reduce((a, r) => a + ((r.sanity && r.sanity.n) || 0), 0);
  const medOf = (arr) => (arr.length ? arr.slice().sort((a, b) => a - b)[Math.floor(arr.length / 2)] : null);
  return {
    valid: valid.length, quantized: q.length, icmp_filtered: f.length,
    min_ms: avgs.length ? Math.round(avgs[0]) : null,
    median_ms: avgs.length ? Math.round(avgs[Math.floor(avgs.length / 2)]) : null,
    max_ms: avgs.length ? Math.round(avgs[avgs.length - 1]) : null,
    avg_ms: avgs.length ? Math.round(avgs.reduce((a, b) => a + b, 0) / avgs.length * 10) / 10 : null,
    jitter_ms: jits.length ? Math.round(medOf(jits) * 10) / 10 : null,
    sd_ms: sds.length ? Math.round(medOf(sds) * 10) / 10 : null,
    loss_pct: losses.length ? Math.round(losses.reduce((a, b) => a + b, 0) / losses.length * 10) / 10 : null,
    samples,
    credible: valid.length >= 2,
    excluded: q.concat(f).map((r) => ({ network: r.network, city: r.city, flags: r.sanity.flags, reasons: r.sanity.flags.map((x) => SANITY_FA[x]) })),
  };
}

/* ==================== /api/wave — آزمون موج ==================== */
function waveStats(timings) {
  const t = (timings || []).map((x) => (typeof x === "number" ? x : x && x.rtt)).filter((x) => x != null);
  if (!t.length) return null;
  const min = Math.min(...t), max = Math.max(...t);
  const avg = t.reduce((a, b) => a + b, 0) / t.length;
  const sd = Math.sqrt(t.reduce((a, b) => a + (b - avg) * (b - avg), 0) / t.length);
  let jsum = 0;
  for (let i = 1; i < t.length; i++) jsum += Math.abs(t[i] - t[i - 1]);
  const jit = t.length > 1 ? jsum / (t.length - 1) : 0;
  const hist = [];
  const lo = Math.floor(min), hi = Math.ceil(max), step = Math.max(1, (hi - lo) / 8);
  for (let b = 0; b < 8; b++) {
    const a = lo + b * step, z = a + step;
    hist.push({ from: Math.round(a * 10) / 10, to: Math.round(z * 10) / 10,
      n: t.filter((x) => x >= a && (b === 7 ? x <= z : x < z)).length });
  }
  return { n: t.length, min: Math.round(min * 10) / 10, max: Math.round(max * 10) / 10,
    avg: Math.round(avg * 10) / 10, sd: Math.round(sd * 10) / 10, jitter: Math.round(jit * 10) / 10, hist, raw: t };
}
async function waveProbe(env, host, packets, cc) {
  const n = Math.min(30, Math.max(5, packets || 14));
  const d = await gpProbe(env, { type: "ping", target: host, locations: [{ country: (cc || "IR").toUpperCase() }],
    limit: 6, measurementOptions: { packets: n } }, 600);
  if (!d || !d.results) return { ok: false, error: (d && d.error) || "gp_empty" };
  const probes = d.results.map((r) => {
    const st = waveStats((r.result && r.result.timings) || []);
    const stats = (r.result && r.result.stats) || {};
    const loss = stats.loss != null ? stats.loss : (st ? Math.max(0, Math.round((1 - st.n / n) * 1000) / 10) : 100);
    return { city: (r.probe || {}).city, network: (r.probe || {}).network, asn: (r.probe || {}).asn, tags: (r.probe || {}).tags || [],
      ok: !!(r.result && r.result.status === "finished"), loss,
      avg: st ? st.avg : null,
      sanity: probeSanity(st, loss, n),
      stats: st, resolved: (r.result && r.result.resolvedAddress) || null };
  });
  const summary = sanitySummary(probes);
  // چند هدف را هم‌زمان می‌سنجیم تا پروب «عدد ثابت روی هر هدف» لو برود: کنترلِ 1.1.1.1
  let control = null, controlRows = [];
  try {
    const d2 = await gpProbe(env, { type: "ping", target: "1.1.1.1", locations: [{ country: (cc || "IR").toUpperCase() }],
      limit: 6, measurementOptions: { packets: Math.min(8, n) } }, 600);
    const map = {};
    ((d2 && d2.results) || []).forEach((r) => {
      const st = waveStats((r.result && r.result.timings) || []);
      const stats2 = (r.result && r.result.stats) || {};
      const loss2 = stats2.loss != null ? stats2.loss : (st ? 0 : 100);
      map[((r.probe || {}).network || "") + "|" + ((r.probe || {}).city || "")] = st ? st.avg : null;
      controlRows.push({ city: (r.probe || {}).city, network: (r.probe || {}).network, avg: st ? st.avg : null,
        sanity: probeSanity(st, loss2, Math.min(8, n)) });
    });
    control = map;
    probes.forEach((p) => {
      const c = map[(p.network || "") + "|" + (p.city || "")];
      if (c != null && p.avg != null && Math.abs(c - p.avg) < 1.5 && p.avg >= 120) {
        if (!p.sanity.flags.includes("quantized_clock")) p.sanity.flags.push("quantized_clock");
        p.sanity.trusted = false;
        p.sanity.control_avg = c;
      }
    });
  } catch { /* کنترل اختیاری است */ }
  const sum2 = sanitySummary(probes);
  const csum = sanitySummary(controlRows);
  /* «هدف مشکل دارد یا شبکه؟» — مقایسهٔ صادقانهٔ هدف با کنترل */
  let verdict = null;
  if (sum2.valid >= 2 && csum.valid >= 2) verdict = "ok";
  else if (sum2.valid < 2 && csum.valid >= 2) verdict = "target_blocked";
  else if (sum2.valid < 2 && csum.valid < 2) verdict = "probes_weak";
  const VERDICT_FA = {
    ok: "هدف و کنترل هر دو از پروب‌های ایران عدد معتبر دادند.",
    target_blocked: "همین پروب‌ها روی کنترل (1.1.1.1) عدد معتبر دادند، ولی روی این هدف نه ⇒ مسئله «هدف» است: این سرور از شبکه‌های ایران به ICMP جواب نمی‌دهد (سیاست فیلتر/بلاک یا CDN بدون ICMP).",
    probes_weak: "هیچ‌کدام از پروب‌های ایران در این اجرا عدد معتبر ندادند (نه هدف و نه کنترل). یعنی خود مسیر/پروب‌های دیتاسنتری مسئله دارند — دوباره بزن.",
  };
  return { ok: true, target: host, packets: n, cc: (cc || "IR").toUpperCase(), at: Date.now(), probes,
    summary: sum2, control_target: "1.1.1.1", control: control || null,
    control_summary: csum, verdict, verdict_fa: verdict ? VERDICT_FA[verdict] : null,
    note: "پروب‌های دیتاسنتری ایران؛ جیتر = میانگین |اختلاف دو نمونهٔ پشت‌سرهم|. پروبی که عدد ثابت روی «هدف و کنترل» بدهد، از جمع‌بندی کنار گذاشته می‌شود و صریح علامت می‌خورد.",
    sources: ["Globalping"] };
}

/* ph6-scan-v1 */
/* ==================== /api/scanner — اسکنر IP و DNS (IPv4 + IPv6 + رنج) ====================
   ورودی: ips (حداکثر ۸ هدف در هر فراخوانی؛ IP یا دامنه)، mode=ping|dns|both، from=ir|world،
          cc، packets (۳..۸)، q (نام کوئری DNS).
   قاعدهٔ ثابت پروژه: هر عدد از پروب واقعی می‌آید، هر حکم با درجهٔ اطمینان، و اگر چیزی سنجش‌پذیر
   نبود «نانشنه» می‌گوییم و عدد نمی‌سازیم. «کاندید، نه توصیه». */
const SC_MAX_IPS = 8;

function ipKind(x) {
  if (/^\d{1,3}(\.\d{1,3}){3}$/.test(x)) return "v4";
  if (x.includes(":") && /^[0-9a-fA-F:]{2,45}$/.test(x)) return "v6";
  if (/^[a-z0-9][a-z0-9.-]{1,60}\.[a-z]{2,}$/i.test(x)) return "host";
  return null;
}
function ccNameFa(cc) {
  try {
    const c = (WORLD_CATALOG.countries || {})[String(cc || "").toUpperCase()];
    return c ? (c.name_fa || c.name || null) : null;
  } catch { return null; }
}
function v6Zone(ip) {
  let s = String(ip);
  if (s.includes("::")) {
    const parts = s.split("::");
    const h = parts[0] ? parts[0].split(":") : [];
    const t = parts[1] ? parts[1].split(":") : [];
    const mid = new Array(Math.max(0, 8 - h.length - t.length)).fill("0");
    s = h.concat(mid, t).join(":");
  }
  const g = s.split(":").map((x) => (x || "0").padStart(4, "0").slice(-4));
  if (g.length !== 8 || g.join("").length !== 32) return null;
  return g.join("").split("").reverse().join(".") + ".origin6.asn.cymru.com";
}
async function asnInfoAny(env, ip) {
  if (!String(ip).includes(":")) return await asnInfo(env, ip);
  const key = "an6:" + ip;
  const hit = await kvGet(env,key, "json");
  if (hit) return { ...hit, cache: "hit" };
  let out = { ip, source: null };
  const zone = v6Zone(ip);
  if (zone) {
    const txt = await dohTxt(zone).catch(() => null);
    if (txt) {
      const p = txt.split("|").map((x) => x.trim());
      let holder = null;
      const t2 = await dohTxt(`AS${p[0]}.asn.cymru.com`).catch(() => null);
      if (t2) holder = t2.split("|").map((x) => x.trim())[4] || null;
      out = { ip, asn: parseInt(p[0], 10) || null, holder, prefix: p[1] || null, cc: p[2] || null,
        source: "Team Cymru (DNS، v6)" };
    } else out.source = "این آی‌پی v6 ثبت عمومی در Team Cymru ندارد";
  }
  await kvPut(env,key, JSON.stringify(out), { expirationTtl: 7 * 86400 });
  return out;
}
async function scanResolveHost(host) {
  try {
    const r = await fetch(`https://dns.google/resolve?name=${encodeURIComponent(host)}&type=A`,
      { headers: { accept: "application/dns-json" }, signal: AbortSignal.timeout(6000) });
    if (!r.ok) return { ok: false, error: "doh_" + r.status };
    const j = await r.json();
    const ip = (((j && j.Answer) || []).find((a) => a.type === 1) || {}).data || null;
    return ip ? { ok: true, ip } : { ok: false, error: "no_a_record" };
  } catch { return { ok: false, error: "doh_net" }; }
}
function scanVerdict(median, loss) {
  if (median == null) return { code: "na", fa: "نانشنه", tone: "bad" };
  if (loss != null && loss >= 60) return { code: "lossy", fa: "افت بالا", tone: "bad" };
  if (loss != null && loss >= 25) return { code: "jittery", fa: "نوسانی", tone: "warn" };
  if (median <= 60) return { code: "great", fa: "عالی", tone: "good" };
  if (median <= 120) return { code: "ok", fa: "خوب", tone: "good" };
  if (median <= 240) return { code: "meh", fa: "قابل قبول", tone: "warn" };
  return { code: "slow", fa: "ضعیف", tone: "bad" };
}
function dnsVerdict(ms) {
  if (ms == null) return { code: "na", fa: "بی‌پاسخ", tone: "bad" };
  if (ms <= 80) return { code: "great", fa: "عالی", tone: "good" };
  if (ms <= 180) return { code: "ok", fa: "خوب", tone: "good" };
  if (ms <= 400) return { code: "meh", fa: "قابل قبول", tone: "warn" };
  return { code: "slow", fa: "کند", tone: "bad" };
}
async function scannerOne(env, target, mode, cc, from, packets, qname) {
  const kind = ipKind(target);
  if (!kind) return { target, ok: false, error: "هدف نامعتبر — نه IPv4، نه IPv6، نه دامنه" };
  let ip = target, hostNote = null;
  if (kind === "host") {
    const rz = await scanResolveHost(target);
    if (!rz.ok) return { target, ok: false, error: "دامنه حل نشد (" + rz.error + ")" };
    ip = rz.ip; hostNote = "دامنه به " + rz.ip + " حل شد (dns.google)";
  }
  const isV6 = ip.includes(":");
  const locations = from === "world"
    ? [{ continent: "EU" }, { continent: "AS" }, { continent: "NA" }]
    : [{ country: cc }];
  const limit = from === "world" ? 1 : 3;
  const out = { target, ip, version: isV6 ? "v6" : "v4", host_note: hostNote, mode,
    v6_note: isV6 ? "کمتر پروب داخل ایران IPv6 دارد؛ عدد v6 را با احتیاط بخوان." : null,
    probes: [], summary: null, dns: null, verdict: null, ok: true, error: null, country: null, asn: null };
  if (mode === "ping" || mode === "both") {
    const d = await gpProbe(env, { type: "ping", target: ip, locations, limit,
      measurementOptions: { packets } }, 600);
    if (d && d.results) {
      out.probes = d.results.map((r) => {
        const st = waveStats((r.result && r.result.timings) || []);
        const stats = (r.result && r.result.stats) || {};
        const loss = stats.loss != null ? stats.loss : (st ? Math.max(0, Math.round((1 - st.n / packets) * 1000) / 10) : 100);
        const sc = probeSanity(st, loss, packets);
        return { city: (r.probe || {}).city || null, network: (r.probe || {}).network || null,
          asn: (r.probe || {}).asn || null, avg: st ? st.avg : null, min: st ? st.min : null,
          max: st ? st.max : null, jitter: st ? st.jitter : null, loss, n: st ? st.n : 0,
          sanity: sc, reasons: (sc.flags || []).map((f) => SANITY_FA[f]).filter(Boolean) };
      });
      out.summary = sanitySummary(out.probes);
    } else out.error = (d && d.error) || "gp_empty";
  }
  if (mode === "dns" || mode === "both") {
    const name = qname || "www.wikipedia.org";
    const d2 = await gpProbe(env, { type: "dns", target: name, locations, limit,
      measurementOptions: { query: { type: "A" }, resolver: ip, protocol: "UDP", port: 53 } }, 600);
    if (d2 && d2.results) {
      const rows = d2.results.map((r) => {
        const res = r.result || {}; const t = res.timings || {};
        const ms = t.total != null ? Math.round(t.total * 10) / 10 : null;
        const okFlag = res.status === "finished" && !res.error && ms != null;
        return { city: (r.probe || {}).city || null, network: (r.probe || {}).network || null,
          asn: (r.probe || {}).asn || null, ms: okFlag ? ms : null, ok: okFlag,
          answers: (res.answers || []).length, status: res.error || res.status || "بی‌پاسخ" };
      });
      const good = rows.filter((x) => x.ok).map((x) => x.ms).sort((a, b) => a - b);
      const med = good.length ? good[Math.floor(good.length / 2)] : null;
      out.dns = { rows, ok_count: good.length, total: rows.length, median_ms: med,
        min_ms: good.length ? good[0] : null, verdict: dnsVerdict(med) };
    } else if (!out.error) out.error = (d2 && d2.error) || "gp_empty";
  }
  if (mode === "ping" || mode === "both") {
    const med = out.summary && out.summary.credible ? out.summary.median_ms : null;
    const lossAvg = out.probes.length
      ? Math.round(out.probes.reduce((a, r) => a + (r.loss || 0), 0) / out.probes.length) : null;
    /* صداقت: اگر عدد داریم ولی پروب معتبر کم است، «نانشنه» نمی‌گوییم — «نامطمئن» می‌گوییم. */
    out.verdict = (out.summary && out.summary.valid > 0 && !out.summary.credible)
      ? { code: "thin", fa: "پروب کم — نامطمئن", tone: "warn" }
      : scanVerdict(med, lossAvg);
    out.loss_avg = lossAvg;
  } else {
    out.verdict = out.dns ? out.dns.verdict : dnsVerdict(null);
  }
  try {
    const a = await asnInfoAny(env, ip);
    out.asn = { asn: a.asn || null, holder: a.holder || null, prefix: a.prefix || null, source: a.source || null };
    out.country = { cc: a.cc || null, fa: a.cc ? ccNameFa(a.cc) : null };
  } catch { out.asn = { asn: null, holder: null, prefix: null, source: "در دسترس نبود" }; }
  return out;
}
async function scannerRun(env, url) {
  const ipsRaw = (url.searchParams.get("ips") || "").split(/[,\s]+/).map((x) => x.trim()).filter(Boolean);
  const modeIn = (url.searchParams.get("mode") || "ping").toLowerCase();
  const mode = modeIn === "dns" ? "dns" : modeIn === "both" ? "both" : "ping";
  const from = (url.searchParams.get("from") || "ir").toLowerCase() === "world" ? "world" : "ir";
  const cc = (url.searchParams.get("cc") || "IR").toUpperCase().slice(0, 2);
  const packets = Math.min(8, Math.max(3, parseInt(url.searchParams.get("packets") || "4", 10) || 4));
  const qname = (url.searchParams.get("q") || "www.wikipedia.org").slice(0, 60);
  const ips = ipsRaw.slice(0, SC_MAX_IPS);
  if (!ips.length) return { ok: false, error: "هیچ هدفی داده نشده — پارامتر ips را بفرست", max_per_call: SC_MAX_IPS };
  const results = await Promise.all(ips.map((x) => scannerOne(env, x, mode, cc, from, packets, qname)
    .catch((e) => ({ target: x, ok: false, error: String((e && e.message) || e) }))));
  const byCc = {};
  for (const r of results) {
    const c = (r.country && r.country.cc) || "??";
    byCc[c] = byCc[c] || { cc: c, fa: (r.country && r.country.fa) || null, n: 0, medians: [] };
    byCc[c].n++;
    const m = mode === "dns" ? (r.dns && r.dns.median_ms) : (r.summary && r.summary.median_ms);
    if (m != null) byCc[c].medians.push(m);
  }
  const countries = Object.values(byCc).map((x) => ({
    cc: x.cc, fa: x.fa, n: x.n,
    median_ms: x.medians.length ? Math.round(x.medians.reduce((a, b) => a + b, 0) / x.medians.length) : null,
    best_ms: x.medians.length ? Math.min.apply(null, x.medians) : null,
  })).sort((a, b) => (a.median_ms == null ? 1e9 : a.median_ms) - (b.median_ms == null ? 1e9 : b.median_ms));
  return { ok: true, at: Date.now(), mode, from, cc, packets, qname,
    returned: results.length, requested: ipsRaw.length, max_per_call: SC_MAX_IPS,
    results, countries,
    note: from === "world"
      ? "سنجش از پروب‌های سه قاره (اروپا/آسیا/آمریکا) — برای مقایسهٔ جهانی. عدد «از داخل ایران» را جدا بگیر."
      : "پروب‌های داخل ایران دیتاسنتری‌اند، نه خط موبایل. اگر میزبان ICMP را ببندد «نانشنه» می‌گوییم و عدد نمی‌سازیم.",
    honesty: ["کاندید، نه توصیه — عدد واقعی خط خودت را با «📱 از این گوشی» بسنج.",
      "DNS پینگ داخل مچ بازی را کم نمی‌کند؛ زمان نام‌یابی/اتصال را بهتر می‌کند."],
    sources: ["Globalping (سنجش)", "Team Cymru (ASN/کشور)", "dns.google (حل دامنه)"] };
}

/* ==================== /api/asn — Team Cymru (+ پشتیبان) ==================== */
async function dohTxt(name) {
  try {
    const r = await fetch(`https://dns.google/resolve?name=${encodeURIComponent(name)}&type=TXT`,
      { headers: { accept: "application/dns-json" }, signal: AbortSignal.timeout(5000) });
    if (!r.ok) return null;
    const j = await r.json();
    const a = ((j && j.Answer) || []).find((x) => x.type === 16);
    return a ? String(a.data).replace(/"/g, "") : null;
  } catch { return null; }
}
async function asnInfo(env, ip) {
  const key = "an:" + ip;
  const hit = await kvGet(env,key, "json");
  if (hit) return { ...hit, cache: "hit" };
  let out = { ip, source: null };
  const txt = await dohTxt(ip.split(".").reverse().join(".") + ".origin.asn.cymru.com");
  if (txt) {
    const p = txt.split("|").map((s) => s.trim());
    let holder = null;
    const t2 = await dohTxt(`AS${p[0]}.asn.cymru.com`);
    if (t2) holder = t2.split("|").map((s) => s.trim())[4] || null;
    out = { ip, asn: parseInt(p[0], 10) || null, holder, prefix: p[1] || null, cc: p[2] || null,
      registry: p[3] || null, since: p[4] || null, source: "Team Cymru (DNS)" };
  } else {
    const alt = await asnOf(env, ip).catch(() => null);
    if (alt && alt.asn) out = { ip, asn: alt.asn, holder: alt.holder || null, prefix: alt.prefix || null, cc: null, source: "RIPEstat (پشتیبان)" };
  }
  if (!out.asn) out.source = "ثبت عمومی ندارد";
  await kvPut(env,key, JSON.stringify(out), { expirationTtl: 30 * 86400 });
  return out;
}

/* ==================== /api/ix — PeeringDB ==================== */
function irCarrierByAsn(asn) {
  const num = parseInt(asn, 10);
  for (const grp of ["mobile", "mvno", "fixed"]) {
    for (const c of (IR_CARRIERS[grp] || [])) {
      if ((c.asn || []).some((a) => parseInt(String(a).replace(/^AS/i, ""), 10) === num))
        return { group: grp, id: c.id, fa: c.fa, en: c.en, plmn: c.plmn || [] };
    }
  }
  return null;
}

async function ixInfo(env, asn) {
  const key = "ixd:v2:" + asn;
  const hit = await kvGet(env,key, "json");
  if (hit) return { ...hit, cache: "hit" };
  try {
    const r = await fetch(`https://www.peeringdb.com/api/netixlan?asn=${asn}`, {
      headers: { Accept: "application/json", "User-Agent": CH_UA["User-Agent"] }, signal: AbortSignal.timeout(9000) });
    if (!r.ok) return { ok: false, asn, error: "pdb_" + r.status,
      note: "PeeringDB به درخواست‌های بی‌سرشناس/ابر سقف پاسخ نمی‌دهد؛ از این منبع فقط به‌عنوان مکمل استفاده می‌کنیم." };
    const j = await r.json();
    const rows = (j.data || []).map((x) => ({ name: x.name, speed_mbps: x.speed, ipv4: x.ipaddr4 || null }));
    const cy = await dohTxt(`AS${asn}.asn.cymru.com`).catch(() => null);
    const holder = cy ? (cy.split("|").map((x) => x.trim())[4] || null) : null;
    const iran = irCarrierByAsn(asn);
    const out = { ok: true, asn, holder, iran, count: rows.length,
      rows: rows.sort((a, b) => (b.speed_mbps || 0) - (a.speed_mbps || 0)).slice(0, 30),
      at: Date.now(), sources: ["PeeringDB", "Team Cymru", "جدول محلی اپراتورهای ایران"],
      note: rows.length ? "" :
        (iran ? `این ASN متعلق به «${iran.fa}» است${iran.plmn.length ? " (PLMN " + iran.plmn.join("، ") + ")" : ""} و رکورد peering عمومی در PeeringDB ندارد؛ برای این اپراتورها جدول محلی + مسیرهای اندازه‌گیری‌شدهٔ خودمان (/api/path) منبع اصلی است.`
              : "این ASN رکورد peering عمومی در PeeringDB ندارد — یعنی داده از این‌جا نمی‌آید، نه این‌که peering ندارد.") };
    await kvPut(env,key, JSON.stringify(out), { expirationTtl: 7 * 86400 });
    return out;
  } catch { return { ok: false, asn, error: "pdb_net" }; }
}

/* ==================== /api/ioda ==================== */
async function iodaGet(env, cc, hours) {
  const key = "io:" + cc + ":" + hours;
  const hit = await kvGet(env,key, "json");
  if (hit && Date.now() - (hit.at || 0) < 15 * 60 * 1000) return { ...hit, cache: "hit" };
  const until = Math.floor(Date.now() / 1000), from = until - Math.min(168, Math.max(1, hours || 24)) * 3600;
  try {
    const r = await fetch(`https://api.ioda.inetintel.cc.gatech.edu/v2/outages/summary?entityType=country&entityCode=${encodeURIComponent(cc)}&from=${from}&until=${until}&limit=6`,
      { headers: { Accept: "application/json" }, signal: AbortSignal.timeout(12000) });
    if (!r.ok) return { ok: false, error: "ioda_" + r.status };
    const j = await r.json();
    const rows = (j.data || []).map((e) => ({ entity: (e.entity && (e.entity.name || e.entity.code)) || "?",
      scores: Object.fromEntries(Object.entries(e.scores || {}).map(([k, v]) => [k, Math.round(v * 1000) / 1000])) }));
    const out = { ok: true, cc, hours: hours || 24, rows, at: Date.now(), source: "IODA — Georgia Tech",
      note: "سیگنال‌های BGP و میانهٔ پینگ /۲۴ — مکمل رادار کلادفلر." };
    await kvPut(env,key, JSON.stringify(out), { expirationTtl: 3600 });
    return out;
  } catch { return { ok: false, error: "ioda_net" }; }
}

/* ==================== /api/edns — TCP/53 از داخل ایران ==================== */
async function ednsProbe(env) {
  const key = "edns:v2";
  const hit = await kvGet(env,key, "json");
  if (hit && Date.now() - (hit.at || 0) < 30 * 60 * 1000) return { ...hit, cache: "hit" };
  const pTcp = gpProbe(env, { type: "dns", target: "cloudflare.com", locations: [{ country: "IR" }], limit: 4,
    measurementOptions: { resolver: "8.8.8.8", protocol: "TCP", port: 53 } }, 1800);
  const pUdp = gpProbe(env, { type: "dns", target: "cloudflare.com", locations: [{ country: "IR" }], limit: 4,
    measurementOptions: { resolver: "8.8.8.8", protocol: "UDP", port: 53 } }, 1800);
  const [dTcp, dUdp] = await Promise.all([pTcp, pUdp]);
  const rowsTcp = gpDnsRows(dTcp), rowsUdp = gpDnsRows(dUdp);
  const okTcp = rowsTcp.filter((r) => r.ok).length, okUdp = rowsUdp.filter((r) => r.ok).length;
  const nTcp = rowsTcp.length || 0, nUdp = rowsUdp.length || 0;
  const hijacked = [...rowsTcp, ...rowsUdp].some((r) => r.a.some(isSinkhole));
  const t0 = Date.now(); let dohMs = null;
  try {
    const r = await fetch("https://cloudflare-dns.com/dns-query?name=cloudflare.com&type=DNSKEY",
      { headers: { accept: "application/dns-json" }, signal: AbortSignal.timeout(6000) });
    await r.json(); dohMs = Date.now() - t0;
  } catch {}
  let verdict;
  if (hijacked) verdict = { code: "dns_hijack", fa: "دزدی DNS دیده شد", conf: 0.9,
    text: "پاسخ‌های برگشتی از پروب‌های ایران، آی‌پی چالهٔ سانسور را داشتند — یعنی کوئری در مسیر قاپیده می‌شود. «تغییر رزولور» روی این شبکه‌ها اثری ندارد؛ DoH رمزنگاری‌شده راه مؤثر است." };
  else if (nTcp >= 2 && okTcp === 0 && okUdp > 0) verdict = { code: "tcp53_blocked", fa: "TCP/53 از این شبکه‌ها بسته است", conf: 0.8,
    text: "کوئری UDP جواب می‌دهد ولی TCP نه. پاسخ‌های بزرگ DNSSEC (که UDP جا نمی‌دهد) روی این شبکه‌ها شانس کمتری دارند؛ DoH روی ۴۴۳ انتخاب سالم‌تری است." };
  else if (okTcp >= 1) verdict = { code: "tcp53_ok", fa: "TCP/53 از این شبکه‌ها باز است", conf: 0.75,
    text: "پس پشتیبانِ پاسخ‌های بزرگ از داخل ایران کار می‌کند؛ شکست DNSSEC فقط اگر UDP تکه‌تکه شود رخ می‌دهد." };
  else verdict = { code: "unknown", fa: "نتیجهٔ DNS روشن نشد", conf: 0.3,
    text: "پروبی‌های ایران در دسترس نبودند یا نتیجه ندادند؛ بعداً دوباره امتحان کن." };
  const out = { ok: true, at: Date.now(), cache: "miss", tcp: rowsTcp, udp: rowsUdp, verdict, doh_ms: dohMs,
    note: "۱۲۳۲ = ۱۲۸۰ (حداقل MTU آی‌پی‌وی‌۶) − ۴۸ بایت هدر — توصیهٔ DNS Flag Day 2020. آزمون با رزولور ۸.۸.۸.۸ از داخل ایران انجام می‌شود.",
    sources: ["Globalping", "DNS Flag Day 2020"] };
  await kvPut(env,key, JSON.stringify(out), { expirationTtl: 3600 });
  return out;
}

/* ==================== /api/rtc — سیگنالینگ اتاق دو-دستگاهی ==================== */
async function rtcHandle(env, request, url) {
  const code = (url.searchParams.get("code") || "").replace(/[^A-Za-z0-9]/g, "").slice(0, 8).toUpperCase();
  if (code.length < 4) return json({ ok: false, error: "کد اتاق ۴ تا ۸ کاراکتر" }, 400);
  if (request.method === "POST") {
    const b = await request.json().catch(() => ({}));
    const role = String(b.role || "").slice(0, 10).toLowerCase();
    if (!["offer", "answer", "cand-o", "cand-a", "bye"].includes(role)) return json({ ok: false, error: "role نامعتبر" }, 400);
    const data = JSON.stringify(b.data ?? null);
    if (data.length > 12000) return json({ ok: false, error: "حجم زیاد" }, 413);
    await kvPut(env,`rtc:${code}:${role}`, data, { expirationTtl: 900 });
    return json({ ok: true, code, role, ttl: 900 });
  }
  const role = String(url.searchParams.get("role") || "").slice(0, 10).toLowerCase();
  const raw = await kvGet(env,`rtc:${code}:${role}`);
  let data = null; try { data = raw ? JSON.parse(raw) : null; } catch {}
  return json({ ok: true, code, role, data, note: "اتاق ۱۵ دقیقه عمر دارد؛ داده فقط بین دو دستگاه خودتان رد و بدل می‌شود." });
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


/* ==================== «حالت DNS روی گوشی» (ph-changer-v1) ====================
   لیست تمیزی که اپ اندروید می‌خواند: anycast جهانی + بومی ایران + رزولورهای کشوری.
   هر ردیف: آی‌پی نسخهٔ ۴/۶ + میزبان DoT (اگر رسماً اعلام شده) + DoH + منبع/وضعیت.
   «کاندید، نه توصیه»: عدد نهایی روی خط خود کاربر سنجیده می‌شود. */
const CHANGER_DOT = {
  "Cloudflare": "one.one.one.one",
  "Google Public DNS": "dns.google",
  "Quad9": "dns.quad9.net",
  "AdGuard DNS": "dns.adguard-dns.com",
  "dns.sb": "dot.sb",
  "DNS0.eu": "dns0.eu",
  "Mullvad": "dns.mullvad.net",
  "OpenDNS": "dns.opendns.com",
  "Control D": "p0.freedns.controld.com",
  "UncensoredDNS": "anycast.censurfridns.dk",
  "DNS.WATCH": "dns.watch",
};
const CHANGER_FA = {
  "Cloudflare": "کلودفلر", "Google Public DNS": "گوگل", "Quad9": "کوآد۹", "AdGuard DNS": "ادگارد",
  "OpenDNS": "اوپن‌دی‌ان‌اس", "Control D": "کنترل‌دی", "DNS0.eu": "دی‌ان‌اس‌زیرو", "Mullvad": "مولود",
  "dns.sb": "دی‌ان‌اس‌اس‌بی", "UncensoredDNS": "بدون‌سانسور", "NextDNS (anycast)": "نکست‌دی‌ان‌اس",
  "Verisign Public DNS": "وریساین", "Hurricane Electric": "هاریکین", "Comodo Secure": "کومودو",
  "Yandex DNS": "یاندکس", "Yandex Safe": "یاندکس‌امن", "DNS.WATCH": "دی‌ان‌اس‌واچ",
  "CIRA Canadian Shield": "سپر کانادایی", "Level3 / CenturyLink": "لول‌۳", "Freenom World": "فرینوم",
};
function changerList() {
  const out = [];
  const seen = new Set();
  const push = (e, kind, cc) => {
    const ips = (e.v4 || []).filter(Boolean);
    const v6 = (e.v6 || []).filter(Boolean);
    if (!ips.length && !v6.length) return;
    const key = (e.name || "") + "|" + (ips[0] || v6[0]);
    if (seen.has(key)) return;
    seen.add(key);
    out.push({
      id: djb2(key), name: e.name, fa: CHANGER_FA[e.name] || e.name, kind, cc: cc || null,
      ips: ips.slice(0, 2), ipv6: v6.slice(0, 1),
      doh: e.doh || null,
      dot: CHANGER_DOT[e.name] || null,
      sni: e.sni || null,
      note: e.note || "",
      verified: e.verified === true,
    });
  };
  for (const g of (WORLD_CATALOG.curated_groups || [])) {
    const kind = g.id === "iran" ? "iran" : "global";
    const cc = g.id === "iran" ? "IR" : null;
    if (g.id !== "iran" && g.id !== "global-anycast") continue;
    for (const e of g.entries) push(e, kind, cc);
  }
  for (const n of (NATIONAL_DNS || [])) push({ name: n.name, v4: n.v4, v6: n.v6, doh: n.doh, dot: n.dot, note: n.note, verified: n.verified }, "national", n.cc);
  return out;
}

/* --- رزولورهای بومی شناخته‌شدهٔ چند کشور (کاندید/تأییدشده — هرگز جای anycast جهانی) --- */
const NATIONAL_DNS = [
  { cc: "DE", name: "dnsforge.de (آلمان)", v4: ["176.9.93.198", "176.9.1.102"], doh: "https://dnsforge.de/dns-query", note: "کاندید — با سنجش ما تأیید نشده", verified: false },
  { cc: "DE", name: "Digitalcourage (آلمان)", v4: ["5.9.164.112", "46.182.19.48"], doh: null, dot: "dns3.digitalcourage.de", note: "کاندید", verified: false },
  { cc: "FR", name: "FDN (فرانسه)", v4: ["80.67.169.12", "80.67.169.40"], doh: null, note: "کاندید", verified: false },
  { cc: "FR", name: "DNS0.eu (اروپا)", v4: ["193.110.81.0", "185.253.5.0"], v6: ["2a0f:fc80::", "2a0f:fc81::"], doh: "https://dns0.eu/dns-query", note: "کاندید", verified: false },
  { cc: "RU", name: "Yandex DNS (روسیه)", v4: ["77.88.8.8", "77.88.8.1"], doh: null, note: "کاندید", verified: false },
  { cc: "CN", name: "AliDNS (چین)", v4: ["223.5.5.5", "223.6.6.6"], doh: "https://dns.alidns.com/dns-query", note: "کاندید", verified: false },
  { cc: "CN", name: "DNSPod/DoH.pub (چین)", v4: ["119.29.29.29", "119.28.28.28"], doh: "https://doh.pub/dns-query", note: "کاندید", verified: false },
  { cc: "KR", name: "KT (کره)", v4: ["168.126.63.1", "168.126.63.2"], note: "کاندید", verified: false },
  { cc: "KR", name: "SK Broadband (کره)", v4: ["210.220.163.82", "219.250.36.130"], note: "کاندید", verified: false },
  { cc: "TR", name: "Türk Telekom (ترکیه)", v4: ["195.175.39.39", "195.175.39.40"], note: "کاندید", verified: false },
  { cc: "NL", name: "DNS0.eu (هلند/اروپا)", v4: ["193.110.81.0", "185.253.5.0"], doh: "https://dns0.eu/dns-query", note: "کاندید", verified: false },
];

/* ==================== /api/dohrace — مسابقهٔ DoH از لبه ==================== */
const RACE_RESOLVERS = [
  { id: "cloudflare", name: "کلودفلر", url: "https://cloudflare-dns.com/dns-query" },
  { id: "google", name: "گوگل", url: "https://dns.google/dns-query" },
  { id: "quad9", name: "کوآد۹", url: "https://dns.quad9.net/dns-query" },
  { id: "adguard", name: "ادگارد", url: "https://dns.adguard-dns.com/dns-query" },
  { id: "dnssb", name: "DNS.SB", url: "https://doh.dns.sb/dns-query" },
  { id: "controld", name: "ControlD", url: "https://freedns.controld.com/p0" },
  { id: "dns0", name: "DNS0.eu", url: "https://dns0.eu/dns-query" },
  { id: "opendns", name: "OpenDNS", url: "https://doh.opendns.com/dns-query" },
  { id: "mullvad", name: "Mullvad", url: "https://dns.mullvad.net/dns-query" },
];
async function dohRace(env, name) {
  const key = "dr:" + djb2(name);
  const hit = await kvGet(env,key, "json");
  if (hit && Date.now() - (hit.at || 0) < 10 * 60 * 1000) return { ...hit, cache: "hit" };
  const one = async (r) => {
    const ctrl = new AbortController();
    const to = setTimeout(() => ctrl.abort(), 3000);
    const t0 = Date.now();
    try {
      const res = await fetch(r.url, { method: "POST",
        headers: { "Content-Type": "application/dns-message", Accept: "application/dns-message" },
        body: dnsPacket(name), signal: ctrl.signal });
      const buf = new Uint8Array(await res.arrayBuffer());
      const p2 = parseDns(buf);
      clearTimeout(to);
      return { id: r.id, name: r.name, ok: true, ms: Date.now() - t0, ips: p2.a.slice(0, 4), rcode: p2.rcode };
    } catch (e) {
      clearTimeout(to);
      return { id: r.id, name: r.name, ok: false, ms: Date.now() - t0, err: (e && e.name) === "AbortError" ? "timeout>3s" : "خطای اتصال" };
    }
  };
  const rows3 = await Promise.all(RACE_RESOLVERS.map(one));
  const good = rows3.filter((x) => x.ok).sort((a, b) => a.ms - b.ms);
  const distinct = [...new Set(good.map((g) => (g.ips || [])[0]).filter(Boolean))];
  const out = { ok: true, host: name, at: Date.now(), cache: "miss", rows: rows3,
    best: good[0] ? { name: good[0].name, ms: good[0].ms, ips: good[0].ips } : null,
    answered: good.length, tried: rows3.length,
    distinct_first_ips: distinct.length,
    note: "این مسابقه از «لبهٔ شبکهٔ کلادفلر» اجرا می‌شود، نه از خط تو — برای اینکه همیشه عدد واقعی داشته باشی حتی وقتی اپراتور DoH را می‌بندد. مسابقهٔ از خط خودت در همان بخش، جداگانه نمایش داده می‌شود.",
    sources: ["Cloudflare edge → DoH providers"] };
  await kvPut(env,key, JSON.stringify(out), { expirationTtl: 1800 });
  return out;
}

      /* --- حالت DNS روی گوشی: لیست رزولور + موقعیت خط (ph-changer-v1) --- */
      if (p === "/api/changer") {
        const list = changerList();
        const byKind = { global: 0, iran: 0, national: 0 };
        list.forEach((r) => { byKind[r.kind] = (byKind[r.kind] || 0) + 1; });
        return json({
          ok: true, at: Date.now(), count: list.length, by_kind: byKind,
          note: "این لیست برای «حالت DNS روی گوشی» است: اپ همان‌جا با DoT (یا UDP برای رزولور بومی) به رزولور انتخابی وصل می‌شود و پینگ/پکت‌لاس را زنده نشان می‌دهد. «کاندید، نه توصیه» — عدد واقعی روی خط خودت.",
          honesty: [
            "این حالت VPN ترافیکی نیست: فقط کوئری‌های DNS روی خود گوشی به رزولور انتخابی می‌روند؛ ترافیک بازی/مرور از هیچ سروری (از جمله ما) عبور نمی‌کند.",
            "DNS پینگ داخل مچ بازی را کم نمی‌کند؛ زمان نام‌یابی/اتصال و پایداری را بهتر می‌کند.",
            "اگر Private DNS سیستم روشن باشد، کوئری‌ها رمزنگاری‌شده‌اند و از این مسیر رد نمی‌شوند — اپ همین را می‌گوید.",
          ],
          resolvers: list,
        });
      }
      if (p === "/api/whoami") {
        const cf = (request && request.cf) || {};
        return json({
          ok: true, at: Date.now(),
          ip: request.headers.get("cf-connecting-ip") || null,
          country: cf.country || null, city: cf.city || null, region: cf.region || null,
          continent: cf.continent || null, timezone: cf.timezone || null,
          asn: cf.asn || null, as_org: cf.asOrganization || null, colo: cf.colo || null,
          http_protocol: cf.httpProtocol || null, tls_version: cf.tlsVersion || null,
          note: "موقعیت از لبهٔ شبکهٔ کلادفلر می‌آید (نه GPS) و تقریبی است؛ دقیق‌ترین عدد برای نزدیکی می‌تواند یک شهر فاصله داشته باشد.",
          source: "Cloudflare request.cf",
        });
      }

      if (p === "/api/dohrace") {
        const name = (url.searchParams.get("host") || "discord.com").trim().toLowerCase().slice(0, 80);
        if (!/^[a-z0-9][a-z0-9.\-]*\.[a-z0-9]{2,}$/.test(name)) return json({ ok: false, error: "دامنهٔ نامعتبر" }, 400);
        return json(await dohRace(env, name));
      }
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
        const out = { cc: cc || null, source: "public-dns.info + curated + NATIONAL_DNS", groups: [], servers: [] };
        const groupsAll = WORLD_CATALOG.curated_groups || [];
        const mkEntry = (e, g) => {
          const ips = v6only ? (e.v6 || []) : [...(e.v4 || []), ...(e.v6 || [])];
          if (!ips.length) return null;
          return { name: e.name, group: g.id, country: g.id === "iran" ? "IR" : null, ips, doh: e.doh || null,
            dot: e.dot || null, note: e.note || "", verified: e.verified !== false };
        };
        const globalIps = new Set();
        for (const g of groupsAll.filter((x) => x.id === "global-anycast"))
          for (const e of g.entries) [...(e.v4 || []), ...(e.v6 || [])].forEach((ip) => globalIps.add(ip));

        if (!cc) {   /* درخواست بدون کشور = گروه‌های سراسری */
          for (const g of groupsAll.filter((x) => x.id === "global-anycast"))
            for (const e of g.entries) { const r = mkEntry(e, g); if (r) out.groups.push(r); }
          out.note = "بدون پارامتر cc فقط گروه‌های anycast سراسری برمی‌گردد. برای لیست بومی یک کشور: ?cc=ES";
          return json(out);
        }

        /* --- لیست کشور: فقط چیزهای همین کشور؛ هیچ فال‌بک به لیست جهانی --- */
        const curIds = { iran: "IR" };
        for (const g of groupsAll) {
          if (g.id === "global-anycast") continue;
          if (curIds[g.id] === cc) for (const e of g.entries) { const r = mkEntry(e, g); if (r) out.groups.push(r); }
        }
        for (const nat of (NATIONAL_DNS || []).filter((x) => x.cc === cc)) {
          const ips = v6only ? (nat.v6 || []) : [...(nat.v4 || []), ...(nat.v6 || [])];
          if (!ips.length) continue;
          out.groups.push({ name: nat.name, group: "national", country: cc, ips, doh: nat.doh || null,
            dot: nat.dot || null, note: nat.note || "", verified: !!nat.verified });
        }
        const c = (WORLD_CATALOG.countries || {})[cc];
        if (c) {
          out.country = { cc, name: c.name_fa, count: c.count, v4: c.v4, v6: c.v6 };
          const seen = new Set();
          const rows2 = [];
          for (const s of (c.top || [])) {
            if (!s.ip || globalIps.has(s.ip) || seen.has(s.ip)) continue;
            if (v6only && s.v !== 6) continue;
            seen.add(s.ip);
            rows2.push({ ip: s.ip, v: s.v, as: s.as, asn: s.asn, city: s.city || "", sw: s.sw || "",
              dnssec: !!s.dnssec, reliability: s.rel });
          }
          rows2.sort((a, b) => (b.reliability || 0) - (a.reliability || 0));
          out.servers = rows2.slice(0, n);
          const asns = [...new Set(out.servers.map((x) => x.asn).filter(Boolean))];
          const cities = [...new Set(out.servers.map((x) => x.city).filter(Boolean))].slice(0, 6);
          out.distinct = {
            policy: "anycast سراسری از لیست کشوری حذف می‌شود تا لیست هر کشور واقعاً فرق کند",
            excluded_global: true, asn_count: asns.length, asn_sample: asns.slice(0, 6), cities,
            overlaps_global_ips: out.servers.filter((x) => globalIps.has(x.ip)).length,
          };
        }
        out.note = cc === "IR"
          ? "رزولورهای بومی ایران + سرورهای ثبت‌شدهٔ همین کشور. سرورهای داخل ایران (۱۰.x) از بیرون ایران قابل سنجش نیستند."
          : "این‌ها رزولورهای ثبت‌شدهٔ خودِ " + (out.country ? out.country.name : cc) + " هستند (منبع public-dns.info) — لیست anycast سراسری عمداً حذف شده تا با لیست کشورهای دیگر یکسان نباشد. ردپای هر ردیف: ASN/شهر/نرم‌افزار.";
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
        try { const raw = await kvGet(env,key); if (raw) cur = JSON.parse(raw); } catch {}
        cur.n++; cur.ok += b.ok === false ? 0 : 1; cur.sum += ms;
        cur.min = cur.min === null ? ms : Math.min(cur.min, ms);
        cur.max = cur.max === null ? ms : Math.max(cur.max, ms);
        cur.avg = Math.round((cur.sum / cur.n) * 10) / 10; cur.ts = Date.now();
        const wMain = await kvPut(env,key, JSON.stringify(cur));
        // ساعت طلایی + روند روزانه (به وقت ایران: UTC+3:30)
        const ir = new Date(Date.now() + 3.5 * 3600 * 1000);
        const hh = ir.getUTCHours(), day = ir.toISOString().slice(0, 10);
        let wAll = wMain;
        for (const hk of [`hr:${prov}:${carrier}:${hh}`, `d:${day}:${prov}:${carrier}`]) {
          let hcur = { n: 0, sum: 0, ok: 0 };
          try { const hr = await kvGet(env,hk); if (hr) hcur = JSON.parse(hr); } catch {}
          hcur.n++; hcur.ok += b.ok === false ? 0 : 1; hcur.sum += ms;
          hcur.avg = Math.round((hcur.sum / hcur.n) * 10) / 10;
          wAll = wAll && await kvPut(env,hk, JSON.stringify(hcur));
        }
        return json({ ok: true, key, cur, hour: hh, day, persisted: !!wAll, note: wAll ? "بی‌نام ذخیره شد: فقط استان/اپراتور/رزولور/عدد." : "سهمیهٔ روزانهٔ ذخیره‌سازی سرور تمام شد؛ عدد روی صفحهٔ تو هست ولی در آمار جمعی ثبت نشد." });
      }

      /* --- آمار استانی/اپراتوری (آنچه کاربران دیگر ثبت کرده‌اند) --- */
      if (p === "/api/stats") {
        const prov = (url.searchParams.get("province") || "").trim().slice(0, 24);
        const car = (url.searchParams.get("carrier") || "").trim().slice(0, 24);
        const prefix = (prov || car) ? `st:${prov}:${car}` : "st:";
        const list = await kvList(env,{ prefix, limit: 500 });
        const rows = [];
        for (const k of list.keys) {
          const raw = await kvGet(env,k.name);
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
        const list = await kvList(env,{ prefix: "st:", limit: 800 });
        const agg = new Map();
        for (const k of list.keys) {
          const raw = await kvGet(env,k.name);
          if (!raw) continue;
          const parts = k.name.split(":"); let v; try { v = JSON.parse(raw); } catch { continue; }
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
        const qq = (url.searchParams.get("q") || "").trim().toLowerCase();
        let listGames = Object.entries(GAMES.games);
        if (qq) listGames = listGames.filter(([k, g]) =>
          k.includes(qq) || (g.name || "").toLowerCase().includes(qq) || (g.name_fa || "").includes(qq));
        if (!slug) {
          const games2 = listGames.map(([k, g]) => {
            const all = Object.values(g.regions).flat();
            return { slug: k, fa: g.name_fa, name: g.name, publisher: g.publisher || "",
              regions: Object.keys(g.regions),
              servers: all.length, verified: all.filter((s) => s.v).length,
              unmeasurable: (g.unmeasurable || []).length };
          });
          return json({ ok: true, count: games2.length, total_servers: games2.reduce((a, b) => a + b.servers, 0),
            verified_servers: games2.reduce((a, b) => a + b.verified, 0),
            source: GAMES.source, verified_at: GAMES.verified_at, verified_by: GAMES.verified_by,
            regions_fa: GAMES.regions_fa, services: GAMES.services || null,
            games: games2 });
        }
        const g = GAMES.games[slug];
        if (!g) return json({ ok: false, error: "بازی پیدا نشد", available: Object.keys(GAMES.games) }, 404);
        const regions = reg ? { [reg]: g.regions[reg] || [] } : g.regions;
        const cnt = Object.values(regions).flat();
        return json({ ok: true, slug, fa: g.name_fa, name: g.name, publisher: g.publisher || "",
          regions_fa: GAMES.regions_fa, regions, source: GAMES.source, src: g.src || null,
          note: g.note || "", probe_note: g.probe_note || null, v_at: g.v_at || null,
          unmeasurable: g.unmeasurable || [], servers: cnt.length, verified: cnt.filter((s) => s.v).length });
      }

      /* --- پینگ زندهٔ سرور بازی از پروب‌های ایران --- */
      if (p === "/api/gameping") {
        const ips = (url.searchParams.get("ips") || "").split(",").map((x) => x.trim()).filter(Boolean).slice(0, 3);
        if (!ips.length || !ips.every((x) => /^\d{1,3}(\.\d{1,3}){3}$/.test(x))) return json({ ok: false, error: "ips نامعتبر" }, 400);
        const cc = (url.searchParams.get("cc") || "IR").toUpperCase().slice(0, 2);
        const outs = await Promise.all(ips.map(async (ip) => {
          const d = await gpProbe(env, { type: "ping", target: ip, locations: [{ country: cc }], limit: 3,
            measurementOptions: { packets: 4 } }, 600);
          const rows3 = (((d && d.results) || [])).map((r) => {
            const st = waveStats((r.result && r.result.timings) || []);
            const stats = (r.result && r.result.stats) || {};
            const loss = stats.loss != null ? stats.loss : 100;
            return { city: (r.probe || {}).city, network: (r.probe || {}).network, asn: (r.probe || {}).asn,
              avg: st ? st.avg : null, min: st ? st.min : null, max: st ? st.max : null, jitter: st ? st.jitter : null,
              loss, sanity: probeSanity(st, loss, 4) };
          });
          return { ip, ok: !!(d && d.results), rows: rows3, error: (d && d.error) || null, summary: sanitySummary(rows3) };
        }));
        return json({ ok: true, at: Date.now(), cc, results: outs,
          note: "پروب‌های داخل ایران دیتاسنتری‌اند، نه خط موبایل. اگر سرور بازی ICMP را بلاک کند، «سنجش‌پذیر نیست» را صادقانه نشان می‌دهیم و عدد نمی‌سازیم. پینگ داخل مچ را DNS کم نمی‌کند.",
          sources: ["Globalping"] });
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

      /* --- 🛰️ نقشهٔ مسیر: traceroute از داخل ایران + نام‌گذاری ASN/IX هر گام --- */
      if (p === "/api/path") {
        const target = (url.searchParams.get("target") || "1.1.1.1").trim().slice(0, 60);
        const cc = (url.searchParams.get("cc") || "IR").toUpperCase().slice(0, 2);
        if (!/^[a-z0-9.\-]+$/i.test(target)) return json({ ok: false, error: "هدف نامعتبر" }, 400);
        let gp = await gpRun(env, { type: "traceroute", target, limit: 1, locations: [{ country: cc }],
          measurementOptions: { protocol: "ICMP", port: 80 } }, 1800);
        if (!gp.ok) return json({ ok: false, error: gp.error, detail: gp.detail }, 502);
        let probe = (gp.results || [])[0] || {};
        let hops = (probe.hops || []).slice(0, 18);
        let proto = "ICMP";
        // بعضی شبکه‌ها ICMP/TCP را می‌بندند → نام را به آی‌پی تبدیل کن و دوباره بکش
        if (!hops.length && /[a-z]/i.test(target)) {
          try {
            const rq = await fetch("https://cloudflare-dns.com/dns-query", { method: "POST",
              headers: { "Content-Type": "application/dns-message", "Accept": "application/dns-message" }, body: dnsPacket(target) });
            const pd = parseDns(new Uint8Array(await rq.arrayBuffer()));
            const ip0 = (pd.a || [])[0];
            if (ip0) {
              const gp3 = await gpRun(env, { type: "traceroute", target: ip0, limit: 1, locations: [{ country: cc }],
                measurementOptions: { protocol: "ICMP", port: 80 } }, 1800);
              const pr3 = gp3.ok ? ((gp3.results || [])[0] || {}) : {};
              if ((pr3.hops || []).length) { probe = { ...pr3, resolved: ip0 }; hops = pr3.hops.slice(0, 18); proto = "ICMP (روی آی‌پی " + ip0 + ")"; }
            }
          } catch {}
        }
        // بعضی شبکه‌ها (دیسکورد و…) ICMP را می‌بندند → دوباره با TCP/443
        if (!hops.length) {
          const gp2 = await gpRun(env, { type: "traceroute", target, limit: 1, locations: [{ country: cc }],
            measurementOptions: { protocol: "TCP", port: 443 } }, 1800);
          if (gp2.ok) {
            const pr2 = (gp2.results || [])[0] || {};
            if ((pr2.hops || []).length) { probe = pr2; hops = pr2.hops.slice(0, 18); proto = "TCP/443"; }
          }
        }
        const enr = await Promise.all(hops.map((h) => h.ip ? asnOf(env, h.ip) : Promise.resolve({ asn: null, holder: null, kind: "lost" })));
        let prev = 0, biggest = { delta: -1, step: null }, steps = [];
        hops.forEach((h, i) => {
          const ms = h.ms == null ? null : h.ms;
          const delta = (ms != null && prev != null) ? Math.round(Math.max(0, ms - prev) * 10) / 10 : null;
          if (delta != null && delta > biggest.delta) biggest = { delta, step: i + 1 };
          if (ms != null) prev = ms;
          steps.push({ n: i + 1, ip: h.ip, ms: ms == null ? null : Math.round(ms * 10) / 10, delta, asn: enr[i].asn,
            holder: enr[i].holder, kind: enr[i].kind, ix: ixOf(h.ip || "") || irInternalOf(h.ip || ""),
            private: h.ip ? isPrivate(h.ip) : null });
        });
        return json({ ok: true, target, cc, protocol: proto, probe: { city: probe.city, asn: probe.asn, network: probe.network },
          steps, hop_count: steps.length, biggest_jump: biggest.step, empty: steps.length === 0,
          note_empty: steps.length === 0 ? "این شبکه حتی با TCP هم مسیرش را نشان نداد (فایروال سخت)." : null,
          first_public: (steps.find((x) => x.ip && !x.private) || {}).n || null,
          last_ms: steps.filter((x) => x.ms != null).slice(-1)[0]?.ms ?? null,
          note: "این مسیر از پروب دیتاسنتری داخل کشور گرفته شده، نه از خط موبایل تو. لینک‌های peering (IXP) در RIPEstat ثبت نمی‌شوند و با جدول محلی ما برچسب خورده‌اند." });
      }

      /* --- 🌡️ رادار: قطعی‌ها و رخدادهای اینترنت (کلادفلر) --- */
      if (p === "/api/radar") {
        const asn = (url.searchParams.get("asn") || "").replace(/[^0-9]/g, "").slice(0, 8);
        const [outages, hijacks, humans] = await Promise.all([
          radarGet(env, "annotations/outages?dateRange=1d&limit=8"),
          radarGet(env, "bgp/hijacks/events?dateRange=7d&limit=5"),
          radarGet(env, "http/summary/bot_class?dateRange=7d&location=IR"),
        ]);
        let series = null;
        if (asn) {
          const t = await radarGet(env, `bgp/timeseries?dateRange=1d&asn=${asn}&aggInterval=1h`);
          series = t.ok ? t.result : { error: t.error };
        }
        return json({ ok: true, asn: asn || null,
          outages: outages.ok ? (outages.result.annotations || []) : [], outages_error: outages.error || null,
          hijacks: hijacks.ok ? (hijacks.result.events || []) : [], hijacks_asn: hijacks.ok ? (hijacks.result.asn_info || []) : [],
          hijacks_error: hijacks.error || null,
          traffic_ir: humans.ok ? (humans.result.summary_0 || null) : null, traffic_error: humans.error || null,
          asn_series: series,
          note: "دادهٔ رادار کلادفلر (صنعتی). این‌ها «رخداد شبکه»‌اند، نه قضاوت دربارهٔ کیفیت خط تو." });
      }

      /* --- 🕐 ساعت طلایی: میانگین ساعتی نمونه‌های بی‌نام (به وقت ایران) --- */
      if (p === "/api/golden") {
        const prov = (url.searchParams.get("province") || "").trim().slice(0, 24);
        const car = (url.searchParams.get("carrier") || "").trim().slice(0, 24);
        const list = await kvList(env,{ prefix: `hr:${prov}:${car}`, limit: 800 });
        const hours = Array.from({ length: 24 }, () => ({ n: 0, sum: 0 }));
        for (const k of list.keys) {
          const raw = await kvGet(env,k.name); if (!raw) continue;
          const hh = parseInt(k.name.split(":")[3], 10); if (!(hh >= 0 && hh < 24)) continue;
          let v; try { v = JSON.parse(raw); } catch { continue; }
          hours[hh].n += v.n || 0; hours[hh].sum += (v.avg || 0) * (v.n || 0);
        }
        const rows = hours.map((h, i) => ({ hour: i, n: h.n, avg: h.n ? Math.round((h.sum / h.n) * 10) / 10 : null }));
        const valid = rows.filter((r) => r.n >= 3 && r.avg != null);
        const sorted = valid.slice().sort((a, b) => a.avg - b.avg);
        return json({ ok: true, province: prov || null, carrier: car || null, rows,
          best: sorted.slice(0, 3), worst: sorted.slice(-3).reverse(), samples: rows.reduce((a, b) => a + b.n, 0),
          note: "به وقت ایران، از نمونه‌های بی‌نام کاربران. با n کم، نتیجه معنادار نیست." });
      }

      /* --- 📈 روند روزانه (۳۰ روز) --- */
      if (p === "/api/trend") {
        const prov = (url.searchParams.get("province") || "").trim().slice(0, 24);
        const car = (url.searchParams.get("carrier") || "").trim().slice(0, 24);
        const days = Math.min(90, Math.max(7, parseInt(url.searchParams.get("days") || "30", 10) || 30));
        const list = await kvList(env,{ prefix: `d:${prov}:${car}`, limit: 900 });
        const byDay = new Map();
        for (const k of list.keys) {
          const raw = await kvGet(env,k.name); if (!raw) continue;
          const day = k.name.split(":")[1]; if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) continue;
          let v; try { v = JSON.parse(raw); } catch { continue; }
          const a = byDay.get(day) || { n: 0, sum: 0, ok: 0 };
          a.n += v.n || 0; a.sum += (v.avg || 0) * (v.n || 0); a.ok += v.ok || 0; byDay.set(day, a);
        }
        const today = new Date(); const rows = [];
        for (let i = days - 1; i >= 0; i--) {
          const dt = new Date(today.getTime() - i * 86400000).toISOString().slice(0, 10);
          const a = byDay.get(dt);
          rows.push({ day: dt, n: a ? a.n : 0, avg: a && a.n ? Math.round((a.sum / a.n) * 10) / 10 : null,
            ok_rate: a && a.n ? Math.round((a.ok / a.n) * 100) : null });
        }
        const vals = rows.filter((r) => r.avg != null);
        const first = vals[0] || null, last = vals[vals.length - 1] || null;
        return json({ ok: true, days, rows, first, last,
          delta: first && last ? Math.round((last.avg - first.avg) * 10) / 10 : null,
          note: "روند از نمونه‌های بی‌نام کاربران ساخته می‌شود؛ روزهای بدون نمونه خالی‌اند." });
      }

      /* --- 🎮 پروفایل هر بازی (آستانهٔ تجربی) --- */
      if (p === "/api/profile") {
        const slug = (url.searchParams.get("game") || "").trim();
        if (!slug) {
          return json({ ok: true, count: Object.keys(GAME_PROFILES.games || {}).length,
            note: GAME_PROFILES.note, games: Object.entries(GAME_PROFILES.games || {}).map(([k, v]) => ({ slug: k, fa: v.fa, good: v.good, ok: v.ok })) });
        }
        const g = (GAME_PROFILES.games || {})[slug];
        if (!g) return json({ ok: false, error: "پروفایل این بازی نیست", available: Object.keys(GAME_PROFILES.games || {}) }, 404);
        return json({ ok: true, slug, ...g, note: GAME_PROFILES.note });
      }
      /* --- 🎮 فهرست پروفایل‌ها برای ادغام --- */
      if (p === "/api/profiles") return json({ ok: true, ...GAME_PROFILES });

      /* --- 📤 دادهٔ باز (بی‌نام): JSON یا CSV --- */
      if (p === "/api/export") {
        const list = await kvList(env,{ prefix: "st:", limit: 1000 });
        const rows = [];
        for (const k of list.keys) {
          const raw = await kvGet(env,k.name); if (!raw) continue;
          const parts = k.name.split(":"); let v; try { v = JSON.parse(raw); } catch { continue; }
          rows.push({ province: parts[1], carrier: parts[2], resolver: parts.slice(3).join(":"),
            n: v.n || 0, ok: v.ok || 0, avg_ms: v.avg ?? null, min_ms: v.min ?? null, max_ms: v.max ?? null });
        }
        rows.sort((a, b) => (b.n - a.n));
        if ((url.searchParams.get("format") || "json") === "csv") {
          const head = "province,carrier,resolver,n,ok,avg_ms,min_ms,max_ms";
          const body = rows.map((r) => [r.province, r.carrier, r.resolver, r.n, r.ok, r.avg_ms, r.min_ms, r.max_ms].join(",")).join("\n");
          return new Response(head + "\n" + body, { headers: { "Content-Type": "text/csv; charset=utf-8",
            "Content-Disposition": 'attachment; filename="pinghab-open-data.csv"', ...CORS } });
        }
        return json({ ok: true, generated_at: new Date().toISOString(), count: rows.length, rows,
          license: "دادهٔ بی‌نام کاربران پینگ‌هاب — استفادهٔ آزاد با ذکر منبع",
          note: "هیچ شناسهٔ فردی ذخیره نمی‌شود؛ فقط استان/اپراتور/رزولور/عدد." });
      }

      /* --- 🤝 حالت تیمی --- */
      if (p === "/api/team") {
        if (method === "POST") {
          const b = await request.json().catch(() => null);
          if (!b || !b.action) return json({ ok: false, error: "دادهٔ نامعتبر" }, 400);
          if (b.action === "create") {
            const code = "T" + shortId().slice(0, 5).toUpperCase();
            const doc = { code, name: String(b.name || "تیم بدون نام").slice(0, 30), created: Date.now(), members: [] };
            await kvPut(env,`team:${code}`, JSON.stringify(doc), { expirationTtl: 60 * 60 * 24 * 90 });
            return json({ ok: true, ...doc });
          }
          if (b.action === "join") {
            const code = String(b.code || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6);
            const raw = await kvGet(env,`team:${code}`);
            if (!raw) return json({ ok: false, error: "تیم پیدا نشد" }, 404);
            const doc = JSON.parse(raw);
            const uid = String(b.uid || "").slice(0, 24);
            doc.members = (doc.members || []).filter((m) => m.uid !== uid);
            if (doc.members.length >= 20) return json({ ok: false, error: "تیم پر است (۲۰ نفر)" }, 400);
            doc.members.push({ uid, name: String(b.name || "بازیکن").slice(0, 24),
              province: String(b.province || "").slice(0, 24), carrier: String(b.carrier || "").slice(0, 24), ts: Date.now() });
            await kvPut(env,`team:${code}`, JSON.stringify(doc), { expirationTtl: 60 * 60 * 24 * 90 });
            return json({ ok: true, ...doc });
          }
          return json({ ok: false, error: "action نامعتبر (create|join)" }, 400);
        }
        const code = (url.searchParams.get("code") || "").toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6);
        if (!code) return json({ ok: false, error: "کد تیم لازم است" }, 400);
        const raw = await kvGet(env,`team:${code}`);
        if (!raw) return json({ ok: false, error: "تیم پیدا نشد" }, 404);
        const doc = JSON.parse(raw);
        const provs = [...new Set((doc.members || []).map((m) => m.province).filter(Boolean))];
        const carriers = [...new Set((doc.members || []).map((m) => m.carrier).filter(Boolean))];
        const list = await kvList(env,{ prefix: "st:", limit: 800 });
        const byRes = new Map();
        for (const k of list.keys) {
          const parts = k.name.split(":");
          if (provs.length && !provs.includes(parts[1])) continue;
          if (carriers.length && !carriers.includes(parts[2])) continue;
          const r2 = await kvGet(env,k.name); if (!r2) continue;
          let v; try { v = JSON.parse(r2); } catch { continue; }
          const res = parts.slice(3).join(":");
          const a = byRes.get(res) || { n: 0, sum: 0 };
          a.n += v.n || 0; a.sum += (v.avg || 0) * (v.n || 0); byRes.set(res, a);
        }
        const best = [...byRes.entries()].map(([resolver, a]) => ({ resolver, n: a.n, avg: a.n ? Math.round((a.sum / a.n) * 10) / 10 : null }))
          .filter((x) => x.n >= 2).sort((x, y) => x.avg - y.avg).slice(0, 5);
        return json({ ok: true, code: doc.code, name: doc.name, members: doc.members || [], best_shared: best,
          note: "اعضای تیم فقط با یک شناسهٔ تصادفی روی دستگاه خودشان شناخته می‌شوند؛ نه نام واقعی، نه شماره." });
      }

      /* --- 🕵️ فاز E: کالبدشکافی فیلترینگ --- */
      if (p === "/api/filter") {
        const host = (url.searchParams.get("host") || "").trim().toLowerCase().slice(0, 100);
        if (!/^[a-z0-9][a-z0-9.\-]*\.[a-z]{2,}$/.test(host)) return json({ ok: false, error: "دامنهٔ نامعتبر" }, 400);
        return json(await filterProbe(env, host));
      }
      if (p === "/api/vantage") {
        const host = (url.searchParams.get("host") || "").trim().toLowerCase().slice(0, 100);
        if (!/^[a-z0-9][a-z0-9.\-]*\.[a-z0-9]{2,}$|^\d{1,3}(\.\d{1,3}){3}$/.test(host)) return json({ ok: false, error: "هدف نامعتبر" }, 400);
        return json(await vantageProbe(env, host, url.searchParams.get("near") === "1"));
      }
      if (p === "/api/wave") {
        const host = (url.searchParams.get("host") || "1.1.1.1").trim().slice(0, 100);
        const packets = parseInt(url.searchParams.get("packets") || "14", 10) || 14;
        const cc = (url.searchParams.get("cc") || "IR").slice(0, 2);
        return json(await waveProbe(env, host, packets, cc));
      }
      if (p === "/api/asn") {
        const ip = (url.searchParams.get("ip") || "").trim().slice(0, 45);
        if (!/^[0-9a-fA-F.:]+$/.test(ip)) return json({ ok: false, error: "آی‌پی نامعتبر" }, 400);
        return json({ ok: true, ...(await asnInfo(env, ip)) });
      }
      if (p === "/api/scanner") return json(await scannerRun(env, url));
      if (p === "/api/ix") {
        const asn = parseInt(url.searchParams.get("asn") || "0", 10);
        if (!asn) return json({ ok: false, error: "asn لازم است" }, 400);
        return json(await ixInfo(env, asn));
      }
      if (p === "/api/ioda") {
        const cc = (url.searchParams.get("cc") || "IR").slice(0, 2).toUpperCase();
        const hours = parseInt(url.searchParams.get("hours") || "24", 10) || 24;
        return json(await iodaGet(env, cc, hours));
      }
      if (p === "/api/edns") return json(await ednsProbe(env));
      if (p === "/api/rtc") return rtcHandle(env, request, url);

      /* --- 📲 PWA: مانیفست و سرویس‌ورکر --- */
      if (p === "/manifest.json") {
        return new Response(JSON.stringify({
          name: "پینگ‌هاب — DNS و پینگ", short_name: "پینگ‌هاب", start_url: "/app", scope: "/",
          display: "standalone", background_color: "#000000", theme_color: "#ffc000", dir: "rtl", lang: "fa",
          description: "سنجش DNS، مسیر شبکه و آمادگی بازی روی خط خودت — بدون VPN، بدون وعدهٔ توخالی.",
          icons: [
            { src: "data:image/svg+xml," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" fill="#ffc000"/><text x="256" y="330" font-size="260" text-anchor="middle" font-family="sans-serif">⚡</text></svg>'), sizes: "512x512", type: "image/svg+xml", purpose: "any maskable" },
          ],
        }), { headers: { "Content-Type": "application/manifest+json; charset=utf-8", ...CORS } });
      }
      if (p === "/sw.js") {
        return new Response(`const C="pinghab-v3",A="pinghab-api-v1";
self.addEventListener("install",e=>{e.waitUntil(caches.open(C).then(c=>c.add("/app")).catch(()=>{}));self.skipWaiting()});
self.addEventListener("activate",e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==C&&k!==A).map(k=>caches.delete(k)))).then(()=>self.clients.claim()))});
function idb(){return new Promise((res,rej)=>{var r=indexedDB.open("ph-q",1);r.onupgradeneeded=function(){if(!r.result.objectStoreNames.contains("q"))r.result.createObjectStore("q",{autoIncrement:true})};r.onsuccess=function(){res(r.result)};r.onerror=function(){rej(r.error)}})}
function add(body){return idb().then(db=>new Promise(res=>{var tx=db.transaction("q","readwrite");tx.objectStore("q").add({body:body,at:Date.now()});tx.oncomplete=function(){res(true)};tx.onerror=function(){res(false)}})).catch(()=>false)}
function del(key){return idb().then(db=>new Promise(res=>{var tx=db.transaction("q","readwrite");tx.objectStore("q").delete(key);tx.oncomplete=function(){res(true)};tx.onerror=function(){res(false)}})).catch(()=>false)}
function count(){return idb().then(db=>new Promise(res=>{var tx=db.transaction("q","readonly");var rq=tx.objectStore("q").count();rq.onsuccess=function(){res(rq.result||0)};rq.onerror=function(){res(0)}})).catch(()=>0)}
function drain(){return idb().then(db=>new Promise(res=>{var tx=db.transaction("q","readonly");var rq=tx.objectStore("q").getAll();var rk=tx.objectStore("q").getAllKeys();var o={items:[],keys:[]};rq.onsuccess=function(){o.items=rq.result||[]};rk.onsuccess=function(){o.keys=rk.result||[]};tx.oncomplete=function(){res(o)};tx.onerror=function(){res(o)}})).then(o=>{var i=0;function next(){if(i>=o.items.length)return Promise.resolve();var it=o.items[i],key=o.keys[i];i++;return fetch("/api/report",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(it.body||{})}).then(r=>{if(r.ok)return del(key);}).catch(()=>{}).then(next)}return next()}).catch(()=>{})}
self.addEventListener("sync",e=>{if(e.tag==="ph-flush")e.waitUntil(drain())});
self.addEventListener("message",e=>{var p=e.data||{};if(p.type==="ph-status"){e.waitUntil(Promise.all([caches.open(A).then(c=>c.keys()).then(ks=>Promise.all(ks.map(rq=>c.match(rq).then(m=>({path:new URL(rq.url).pathname+new URL(rq.url).search,at:(m&&m.headers.get("x-ph-at"))?parseInt(m.headers.get("x-ph-at"),10):null}))))),count()]).then(r=>{if(e.source)e.source.postMessage({type:"ph-status",items:r[0],queued:r[1]})}))}});
self.addEventListener("fetch",e=>{var req=e.request;var u=new URL(req.url);if(u.origin!==location.origin)return;
if(req.method==="POST"&&u.pathname==="/api/report"){e.respondWith(fetch(req.clone()).then(r=>{if(r.ok)return r;throw 0}).catch(()=>req.clone().json().catch(()=>({})).then(b=>add(b)).then(()=>{if(self.registration.sync){return self.registration.sync.register("ph-flush").catch(()=>{})}}).then(()=>new Response(JSON.stringify({ok:true,queued:true}),{headers:{"Content-Type":"application/json"}}))));return}
if(req.method!=="GET")return;
if(u.pathname.indexOf("/api/")===0){e.respondWith(caches.open(A).then(c=>fetch(req).then(r=>{if(r.ok){var hd=new Headers(r.headers);hd.set("x-ph-at",String(Date.now()));var cl=r.clone();return cl.arrayBuffer().then(buf=>c.put(req,new Response(buf,{status:200,headers:hd})).catch(()=>{})).then(()=>r)}return r}).catch(()=>c.match(req).then(m=>{if(!m)return new Response(JSON.stringify({ok:false,offline:true}),{headers:{"Content-Type":"application/json"}});var h2=new Headers(m.headers);h2.set("x-ph-stale","1");return m.arrayBuffer().then(buf=>new Response(buf,{status:200,headers:h2}))}))));return}
e.respondWith(fetch(req).then(r=>{var cl=r.clone();caches.open(C).then(c=>c.put(req,cl)).catch(()=>{});return r}).catch(()=>caches.match(req).then(m=>m||caches.match("/app"))))});
`, { headers: { "Content-Type": "application/javascript; charset=utf-8", ...CORS } });
      }

      /* --- 🩺 صفحهٔ وضعیت عمومی --- */
      if (p === "/status") {
        const list = await kvList(env,{ prefix: "st:", limit: 400 });
        const rows = [];
        for (const k of list.keys) {
          const raw = await kvGet(env,k.name); if (!raw) continue;
          const parts = k.name.split(":"); let v; try { v = JSON.parse(raw); } catch { continue; }
          rows.push({ province: parts[1], carrier: parts[2], resolver: parts.slice(3).join(":"), ...v });
        }
        rows.sort((a, b) => (a.avg ?? 1e9) - (b.avg ?? 1e9));
        const radar = await radarGet(env, "annotations/outages?dateRange=1d&limit=6");
        const edge = await edgeCheckDoh(EDGE_RESOLVERS.slice(0, 8));
        return html(statusPage(rows.slice(0, 20), radar.ok ? (radar.result.annotations || []) : [], edge));
      }

      /* --- 📅 گزارش ماهانه (بهداشت اینترنت) --- */
      if (p === "/report") {
        const list = await kvList(env,{ prefix: "st:", limit: 1000 });
        const byProv = new Map(); let samples = 0, keyCount = 0;
        for (const k of list.keys) {
          const raw = await kvGet(env,k.name); if (!raw) continue;
          const parts = k.name.split(":"); let v; try { v = JSON.parse(raw); } catch { continue; }
          keyCount++; samples += v.n || 0;
          const a = byProv.get(parts[1]) || { n: 0, sum: 0, carriers: new Set() };
          a.n += v.n || 0; a.sum += (v.avg || 0) * (v.n || 0); a.carriers.add(parts[2]); byProv.set(parts[1], a);
        }
        const rows = [...byProv.entries()].map(([province, a]) => ({ province, n: a.n,
          avg: a.n ? Math.round((a.sum / a.n) * 10) / 10 : null, carriers: a.carriers.size })).sort((x, y) => x.avg - y.avg);
        return html(reportPage(rows, { keyCount, samples }));
      }

      /* --- 📘 مستندات API و دادهٔ باز --- */
      if (p === "/docs") return html(docsPage());

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
        await kvPut(env,`r:${id}`, JSON.stringify(doc), { expirationTtl: 60 * 60 * 24 * 90 });
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
        const raw = await kvGet(env,`r:${id}`);
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
