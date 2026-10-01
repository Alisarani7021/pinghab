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
  const hit = await env.DNSRADAR_KV.get(key, "json");
  if (hit) return hit;
  const s = await gpSubmit(payload);
  if (s.err) return { ok: false, error: s.err };
  for (let i = 0; i < 9; i++) {
    await sleep(2200);
    const d = await gpFetch(s.id);
    if (d && d.status === "finished") {
      await env.DNSRADAR_KV.put(key, JSON.stringify(d), { expirationTtl: ttl });
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
async function chBudget(env, n) {
  if (!env || !env.DNSRADAR_KV) return true;
  try {
    const k = "chb:" + new Date(Date.now() + 3.5 * 3600 * 1000).toISOString().slice(0, 13);
    const cur = parseInt((await env.DNSRADAR_KV.get(k)) || "0", 10) || 0;
    if (cur + n > 120) return false;
    await env.DNSRADAR_KV.put(k, String(cur + n), { expirationTtl: 7200 });
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
  const hit = await env.DNSRADAR_KV.get(key, "json");
  if (hit && Date.now() - (hit.at || 0) < 20 * 60 * 1000) return { ...hit, cache: "hit" };
  const budget = await chBudget(env, 6);

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
      if (!anyDns && !anyTcp) return { available: false };
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

  const out = {
    ok: true, host, at: Date.now(), cache: "miss",
    neutral, neutral_ips: neutralIps,
    ir_dns: irRows, ir_via_public: tcpRows, ir_http: httpRows,
    sinkhole_ips: [...new Set(sinkLocal.concat(sinkViaPublic))],
    hijack, checkhost: chAvail ? ch : { available: false },
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
  await env.DNSRADAR_KV.put(key, JSON.stringify(out), { expirationTtl: 6 * 3600 });
  return out;
}

/* ==================== /api/vantage — نقطه‌به‌نقطه از شبکه‌های ایران ==================== */
async function vantageProbe(env, host, near) {
  const key = "vnt:v2:" + host.toLowerCase() + (near ? ":n" : "");
  const hit = await env.DNSRADAR_KV.get(key, "json");
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
    rows.push({
      city: (r.probe || {}).city, network: (r.probe || {}).network, asn: (r.probe || {}).asn,
      avg: st ? st.avg : null, min: st ? st.min : null, max: st ? st.max : null, jitter: st ? st.jitter : null,
      loss: stats.loss != null ? stats.loss : (st ? Math.max(0, Math.round((1 - st.n / 5) * 1000) / 10) : null),
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
  const live = rows.filter((r) => r.avg != null).sort((a, b) => a.avg - b.avg);
  const out = {
    ok: true, host, at: Date.now(), cache: "miss", rows,
    near: nearRows.slice(0, 8),
    summary: {
      networks: rows.length,
      reachable: rows.filter((r) => r.http_ok).length,
      best: live[0] ? { city: live[0].city, network: live[0].network, avg: live[0].avg } : null,
      worst: live.length ? { city: live[live.length - 1].city, network: live[live.length - 1].network, avg: live[live.length - 1].avg } : null,
      spread_ms: live.length ? Math.round(live[live.length - 1].avg - live[0].avg) : null,
    },
    note: "پینگ و HTTPS از شبکه‌های دیتاسنتری ایران؛ «تفاوت بهترین و بدترین شبکه» دقیقاً همان چیزی است که انتخاب رزولور/مسیر را معنادار می‌کند.",
    sources: ["Globalping"],
  };
  await env.DNSRADAR_KV.put(key, JSON.stringify(out), { expirationTtl: 3600 });
  return out;
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
    limit: 4, measurementOptions: { packets: n } }, 600);
  if (!d || !d.results) return { ok: false, error: (d && d.error) || "gp_empty" };
  const probes = d.results.map((r) => {
    const st = waveStats((r.result && r.result.timings) || []);
    const stats = (r.result && r.result.stats) || {};
    return { city: (r.probe || {}).city, network: (r.probe || {}).network, asn: (r.probe || {}).asn, tags: (r.probe || {}).tags || [],
      ok: !!(r.result && r.result.status === "finished"), loss: stats.loss != null ? stats.loss : (st ? Math.max(0, Math.round((1 - st.n / n) * 1000) / 10) : null),
      stats: st, resolved: (r.result && r.result.resolvedAddress) || null };
  });
  return { ok: true, target: host, packets: n, cc: (cc || "IR").toUpperCase(), at: Date.now(), probes,
    note: "پروب‌های دیتاسنتری ایران؛ جیتر = میانگین |اختلاف دو نمونهٔ پشت‌سرهم|.",
    sources: ["Globalping"] };
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
  const hit = await env.DNSRADAR_KV.get(key, "json");
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
  await env.DNSRADAR_KV.put(key, JSON.stringify(out), { expirationTtl: 30 * 86400 });
  return out;
}

/* ==================== /api/ix — PeeringDB ==================== */
async function ixInfo(env, asn) {
  const key = "ixd:" + asn;
  const hit = await env.DNSRADAR_KV.get(key, "json");
  if (hit) return { ...hit, cache: "hit" };
  try {
    const r = await fetch(`https://www.peeringdb.com/api/netixlan?asn=${asn}`, {
      headers: { Accept: "application/json", "User-Agent": CH_UA["User-Agent"] }, signal: AbortSignal.timeout(9000) });
    if (!r.ok) return { ok: false, asn, error: "pdb_" + r.status,
      note: "PeeringDB به درخواست‌های بی‌سرشناس/ابر سقف پاسخ نمی‌دهد؛ از این منبع فقط به‌عنوان مکمل استفاده می‌کنیم." };
    const j = await r.json();
    const rows = (j.data || []).map((x) => ({ name: x.name, speed_mbps: x.speed, ipv4: x.ipaddr4 || null }));
    const out = { ok: true, asn, count: rows.length, rows: rows.sort((a, b) => (b.speed_mbps || 0) - (a.speed_mbps || 0)).slice(0, 30),
      at: Date.now(), source: "PeeringDB",
      note: rows.length ? "" : "این ASN رکورد peering عمومی در PeeringDB ندارد — یعنی داده از این‌جا نمی‌آید، نه این‌که peering ندارد." };
    await env.DNSRADAR_KV.put(key, JSON.stringify(out), { expirationTtl: 7 * 86400 });
    return out;
  } catch { return { ok: false, asn, error: "pdb_net" }; }
}

/* ==================== /api/ioda ==================== */
async function iodaGet(env, cc, hours) {
  const key = "io:" + cc + ":" + hours;
  const hit = await env.DNSRADAR_KV.get(key, "json");
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
    await env.DNSRADAR_KV.put(key, JSON.stringify(out), { expirationTtl: 3600 });
    return out;
  } catch { return { ok: false, error: "ioda_net" }; }
}

/* ==================== /api/edns — TCP/53 از داخل ایران ==================== */
async function ednsProbe(env) {
  const key = "edns:v2";
  const hit = await env.DNSRADAR_KV.get(key, "json");
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
  await env.DNSRADAR_KV.put(key, JSON.stringify(out), { expirationTtl: 3600 });
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
    await env.DNSRADAR_KV.put(`rtc:${code}:${role}`, data, { expirationTtl: 900 });
    return json({ ok: true, code, role, ttl: 900 });
  }
  const role = String(url.searchParams.get("role") || "").slice(0, 10).toLowerCase();
  const raw = await env.DNSRADAR_KV.get(`rtc:${code}:${role}`);
  let data = null; try { data = raw ? JSON.parse(raw) : null; } catch {}
  return json({ ok: true, code, role, data, note: "اتاق ۱۵ دقیقه عمر دارد؛ داده فقط بین دو دستگاه خودتان رد و بدل می‌شود." });
}
