#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_round5.py — اندپوینت‌های «حالت DNS روی گوشی» برای cloudflare/worker.src.mjs

۱) /api/changer  → لیست تمیز رزولورها برای تغییردهندهٔ DNS اپ (DoT/DoH/UDP + برچسب منبع)
۲) /api/whoami   → کشور/شهر/ASN/اپراتور/PoP همان درخواست (از request.cf) برای داشبورد اپ
اجرا: python3 tools/patch_round5.py   (idempotent)
"""
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "cloudflare" / "worker.src.mjs"
s = SRC.read_text(encoding="utf-8")
if "ph-changer-v1" in s:
    print("already patched"); raise SystemExit(0)

CODE = r'''
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

'''
anchor = "/* --- رزولورهای بومی شناخته‌شدهٔ چند کشور"
assert anchor in s, "anchor NATIONAL_DNS"
s = s.replace(anchor, CODE + anchor, 1)

ROUTES = '''      /* --- حالت DNS روی گوشی: لیست رزولور + موقعیت خط (ph-changer-v1) --- */
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

'''
route_anchor = '      if (p === "/api/dohrace") {'
assert route_anchor in s, "route anchor"
s = s.replace(route_anchor, ROUTES + route_anchor, 1)

DOC = '''    ["GET", "/api/changer", "🚀 لیست رزولورها برای حالت DNS روی گوشی (DoT/DoH + بومی)"],
    ["GET", "/api/whoami", "📶 کشور/شهر/ASN/PoP همین درخواست (لبهٔ کلادفلر)"],
'''
doc_anchor = '    ["GET", "/api/dohrace?host=…", "🏁 مسابقهٔ DoH از لبهٔ شبکه (همیشه عدد واقعی)"],\n'
assert doc_anchor in s, "docs anchor"
s = s.replace(doc_anchor, doc_anchor + DOC, 1)

SRC.write_text(s, encoding="utf-8")
print("patched:", len(s))
