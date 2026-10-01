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
