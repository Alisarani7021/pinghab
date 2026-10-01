#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_round3.py — وصله‌های دور سوم «پینگ‌هاب» روی cloudflare/worker.src.mjs

۱) probeSanity: تشخیص پروب «نانشنه» (ساعت/ICMP کوانتش‌شده) + ICMP فیلترشده
۲) /api/wave: حذف پروب‌های نانشنه از جمع‌بندی + خلاصهٔ صادقانه
۳) /api/vantage: نشان‌زدن ردیف مشکوک و کنار گذاشتنش از بهترین/بدترین
۴) /api/dnslist: پایان تکرار لیست جهانی در کشورها + رزولورهای بومی + تقاطع صفر با anycast
۵) /api/dohrace: مسابقهٔ DoH از لبهٔ شبکه (همیشه عدد واقعی می‌دهد، حتی اگر خط کاربر بسته باشد)
۶) /api/games: کاتالوگ گسترده (۱۳ بازی / ۱۶۸ سرور) + سرویس‌ها + جست‌وجو
۷) /api/gameping: پینگ زندهٔ سرور بازی از پروب‌های ایران
اجرا: python3 tools/patch_round3.py   (idempotent — اگر وصله هست، رد می‌کند)
"""
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "cloudflare" / "worker.src.mjs"
s = SRC.read_text(encoding="utf-8")
orig_len = len(s)
applied, skipped = [], []


def sub(anchor, new, tag, count=1):
    global s
    if tag in s:
        skipped.append(tag)
        return
    if anchor not in s:
        raise SystemExit(f"ANCHOR NOT FOUND for {tag}: {anchor[:70]!r}")
    s = s.replace(anchor, new, count)
    applied.append(tag)


# ---------------------------------------------------------------- ۱) probeSanity
SANITY_CODE = r"""
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
  return { flags, spread, sd, trusted: !bad };
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
  return {
    valid: valid.length, quantized: q.length, icmp_filtered: f.length,
    min_ms: avgs.length ? Math.round(avgs[0]) : null,
    median_ms: avgs.length ? Math.round(avgs[Math.floor(avgs.length / 2)]) : null,
    max_ms: avgs.length ? Math.round(avgs[avgs.length - 1]) : null,
    credible: valid.length >= 2,
    excluded: q.concat(f).map((r) => ({ network: r.network, city: r.city, flags: r.sanity.flags, reasons: r.sanity.flags.map((x) => SANITY_FA[x]) })),
  };
}

/* ==================== /api/wave — آزمون موج ==================== */"""

sub("\n/* ==================== /api/wave — آزمون موج ==================== */", SANITY_CODE, "sanity")

# ---------------------------------------------------------------- ۲) waveProbe
OLD_WAVE = '''async function waveProbe(env, host, packets, cc) {
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
}'''
NEW_WAVE = '''async function waveProbe(env, host, packets, cc) {
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
  let control = null;
  try {
    const d2 = await gpProbe(env, { type: "ping", target: "1.1.1.1", locations: [{ country: (cc || "IR").toUpperCase() }],
      limit: 6, measurementOptions: { packets: Math.min(8, n) } }, 600);
    const map = {};
    ((d2 && d2.results) || []).forEach((r) => {
      const st = waveStats((r.result && r.result.timings) || []);
      map[((r.probe || {}).network || "") + "|" + ((r.probe || {}).city || "")] = st ? st.avg : null;
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
  return { ok: true, target: host, packets: n, cc: (cc || "IR").toUpperCase(), at: Date.now(), probes,
    summary: sum2, control_target: "1.1.1.1", control: control || null,
    note: "پروب‌های دیتاسنتری ایران؛ جیتر = میانگین |اختلاف دو نمونهٔ پشت‌سرهم|. پروبی که عدد ثابت روی «هدف و کنترل» بدهد، از جمع‌بندی کنار گذاشته می‌شود و صریح علامت می‌خورد.",
    sources: ["Globalping"] };
}'''
sub(OLD_WAVE, NEW_WAVE, "wave_v2")

# ---------------------------------------------------------------- ۳) vantage
sub('''    rows.push({
      city: (r.probe || {}).city, network: (r.probe || {}).network, asn: (r.probe || {}).asn,
      avg: st ? st.avg : null, min: st ? st.min : null, max: st ? st.max : null, jitter: st ? st.jitter : null,
      loss: stats.loss != null ? stats.loss : (st ? Math.max(0, Math.round((1 - st.n / 5) * 1000) / 10) : null),
      http_ok: !!h.ok, http_ms: h.total_ms != null ? h.total_ms : null,
    });''',
    '''    const sLoss = stats.loss != null ? stats.loss : (st ? Math.max(0, Math.round((1 - st.n / 5) * 1000) / 10) : 100);
    rows.push({
      city: (r.probe || {}).city, network: (r.probe || {}).network, asn: (r.probe || {}).asn,
      avg: st ? st.avg : null, min: st ? st.min : null, max: st ? st.max : null, jitter: st ? st.jitter : null,
      loss: sLoss, sanity: probeSanity(st, sLoss, 5),
      http_ok: !!h.ok, http_ms: h.total_ms != null ? h.total_ms : null,
    });''', "vantage_sanity")

sub('''  const live = rows.filter((r) => r.avg != null).sort((a, b) => a.avg - b.avg);''',
    '''  const live = rows.filter((r) => r.avg != null && (!r.sanity || r.sanity.trusted)).sort((a, b) => a.avg - b.avg);
  const suspect = rows.filter((r) => r.sanity && !r.sanity.trusted);''', "vantage_live")

sub('''      spread_ms: live.length ? Math.round(live[live.length - 1].avg - live[0].avg) : null,
    },''',
    '''      spread_ms: live.length ? Math.round(live[live.length - 1].avg - live[0].avg) : null,
      trusted: live.length, excluded: suspect.length,
      excluded_rows: suspect.map((r) => ({ network: r.network, city: r.city, avg: r.avg, why: (r.sanity.flags || []).map((x) => SANITY_FA[x]) })),
      credible: live.length >= 2,
    },''', "vantage_summary")

# ---------------------------------------------------------------- ۴) dnslist
OLD_DNSLIST = '''        const out = { cc: cc || null, source: "public-dns.info + curated", groups: [], servers: [] };
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
        return json(out);'''
NEW_DNSLIST = '''        const out = { cc: cc || null, source: "public-dns.info + curated + NATIONAL_DNS", groups: [], servers: [] };
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
        return json(out);'''
sub(OLD_DNSLIST, NEW_DNSLIST, "dnslist_v2")

# NATIONAL_DNS + /api/dohrace  (قبل از /api/dnslist تزریق می‌شوند)
NATIONAL = '''
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
  const hit = await env.DNSRADAR_KV.get(key, "json");
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
  await env.DNSRADAR_KV.put(key, JSON.stringify(out), { expirationTtl: 1800 });
  return out;
}

'''
sub('''      if (p === "/api/dnslist") {''', NATIONAL + '''      if (p === "/api/dohrace") {
        const name = (url.searchParams.get("host") || "discord.com").trim().toLowerCase().slice(0, 80);
        if (!/^[a-z0-9][a-z0-9.\\-]*\\.[a-z0-9]{2,}$/.test(name)) return json({ ok: false, error: "دامنهٔ نامعتبر" }, 400);
        return json(await dohRace(env, name));
      }
      if (p === "/api/dnslist") {''', "dohrace")

# ---------------------------------------------------------------- ۶) games
OLD_GAMES = '''        if (!slug) {
          return json({ ok: true, count: Object.keys(GAMES.games).length, source: GAMES.source,
            regions_fa: GAMES.regions_fa,
            games: Object.entries(GAMES.games).map(([k, g]) => ({ slug: k, fa: g.name_fa, name: g.name,
              regions: Object.keys(g.regions), servers: Object.values(g.regions).reduce((a, b) => a + b.length, 0) })) });
        }
        const g = GAMES.games[slug];
        if (!g) return json({ ok: false, error: "بازی پیدا نشد", available: Object.keys(GAMES.games) }, 404);
        const regions = reg ? { [reg]: g.regions[reg] || [] } : g.regions;
        return json({ ok: true, slug, fa: g.name_fa, name: g.name, regions_fa: GAMES.regions_fa, regions, source: GAMES.source });'''
NEW_GAMES = '''        const qq = (url.searchParams.get("q") || "").trim().toLowerCase();
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
          unmeasurable: g.unmeasurable || [], servers: cnt.length, verified: cnt.filter((s) => s.v).length });'''
sub(OLD_GAMES, NEW_GAMES, "games_v2")

# ---------------------------------------------------------------- ۷) gameping
sub('''      /* --- آی‌پی‌های کلادفلر دامنه‌های ایرانی (MIT — CF-Web) --- */''',
    '''      /* --- پینگ زندهٔ سرور بازی از پروب‌های ایران --- */
      if (p === "/api/gameping") {
        const ips = (url.searchParams.get("ips") || "").split(",").map((x) => x.trim()).filter(Boolean).slice(0, 3);
        if (!ips.length || !ips.every((x) => /^\\d{1,3}(\\.\\d{1,3}){3}$/.test(x))) return json({ ok: false, error: "ips نامعتبر" }, 400);
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

      /* --- آی‌پی‌های کلادفلر دامنه‌های ایرانی (MIT — CF-Web) --- */''', "gameping")

# ---------------------------------------------------------------- ۸) مستندات API
sub('''    ["GET", "/api/games?game=cs2", "کاتالوگ ۹ بازی · ۱۴۱ سرور (MIT)"],''',
    '''    ["GET", "/api/games?q=pubg", "کاتالوگ ۱۳ بازی · ۱۶۸ سرور (تأییدشده با پینگ واقعی + منبع)"],
    ["GET", "/api/gameping?ips=1.1.1.1", "پینگ زندهٔ سرور بازی از پروب‌های ایران"],
    ["GET", "/api/dohrace?host=…", "🏁 مسابقهٔ DoH از لبهٔ شبکه (همیشه عدد واقعی)"],''', "docs")

SRC.write_text(s, encoding="utf-8")
print(f"bytes: {orig_len} → {len(s)}")
print("applied:", applied)
print("already-present:", skipped)
