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
    return { ok: false, err: e.message || "ناموفق" };
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
