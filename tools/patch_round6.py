#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_round6.py — افزودن «🎯 اسکنر IP و DNS» به پروژه (دور ۶)

۱) worker.src.mjs : تابع scannerRun/scannerOne + مسیر /api/scanner + خط مستندات /docs
۲) web/tools3-block.html : پنل ph-p21 (ورودی، دکمه‌ها، جدول نتیجه، خروجی CSV/JSON)
۳) tools/rebuild_pages.py : آیتم «اسکنر IP و DNS» در منوی همبرگری + سخت‌کردن phShow (تک‌پنلی‌شدن)
۴) cloudflare/deploy.py : چک‌های زندهٔ اسکنر
۵) نسخهٔ ۲.۵ → ۲.۶

اجرا: python3 tools/patch_round6.py   (idempotent — با نشانگرها محافظت شده)
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
W = ROOT / "cloudflare" / "worker.src.mjs"
T3 = ROOT / "web" / "tools3-block.html"
RP = ROOT / "tools" / "rebuild_pages.py"
DP = ROOT / "cloudflare" / "deploy.py"
SC = ROOT / "web" / "scanner-block.html"
SNIP = ROOT / "tools" / "scanner_worker_snippet.js"
TAG = "ph6-scan-v1"

report = []


def rw(p, old, new, label, guard=None, count=1):
    s = p.read_text(encoding="utf-8")
    if guard and guard in s:
        report.append(f"↷ {label}: از قبل هست")
        return False
    if old not in s:
        print(f"❌ لنگر پیدا نشد: {label}")
        sys.exit(1)
    s = s.replace(old, new, count)
    p.write_text(s, encoding="utf-8")
    report.append(f"✅ {label}")
    return True


# ------------------------------------------------------------------ ۱) worker
s = W.read_text(encoding="utf-8")
if TAG in s:
    report.append("↷ worker: از قبل هست")
else:
    snippet = SNIP.read_text(encoding="utf-8").rstrip() + "\n\n"
    anchor_fn = "/* ==================== /api/asn — Team Cymru (+ پشتیبان) ==================== */"
    assert anchor_fn in s, "anchor_fn"
    s = s.replace(anchor_fn, f"/* {TAG} */\n" + snippet + anchor_fn, 1)

    anchor_route = '      if (p === "/api/ix") {'
    assert anchor_route in s, "anchor_route"
    s = s.replace(anchor_route,
                  '      if (p === "/api/scanner") return json(await scannerRun(env, url));\n' + anchor_route, 1)

    anchor_doc = '    ["GET", "/api/asn?ip=…", "ASN هر آی‌پی (Team Cymru، پشتیبان RIPEstat)"],'
    assert anchor_doc in s, "anchor_doc"
    s = s.replace(anchor_doc, anchor_doc + '\n'
                  '    ["GET", "/api/scanner?ips=1.1.1.1,8.8.8.8&mode=ping|dns&from=ir|world", '
                  '"🎯 اسکنر IP/DNS (IPv4+IPv6+رنج): پینگ/رزولوشن از پروب‌ها + کشور و ASN"],', 1)
    W.write_text(s, encoding="utf-8")
    report.append("✅ worker: scannerRun + /api/scanner + docs")

# ------------------------------------------------------------------ ۲) پنل UI
t3 = T3.read_text(encoding="utf-8")
if 'id="ph6-go"' in t3:
    report.append("↷ tools3: از قبل هست")
else:
    block = SC.read_text(encoding="utf-8").strip()
    marker = "<!--PH3-SCRIPT-->"
    assert marker in t3, "PH3 marker"
    t3 = t3.replace(marker, block + "\n\n" + marker, 1)
    T3.write_text(t3, encoding="utf-8")
    report.append(f"✅ tools3: پنل ph-p21 ({len(block):,} chars)")

# ------------------------------------------------------------------ ۳) منو + phShow
rp = RP.read_text(encoding="utf-8")
if '"ph-p21"' in rp:
    report.append("↷ rebuild_pages: از قبل هست")
else:
    a1 = '    ("ph-p15", "⚡", "رزولوشن و مسابقه", "سنجش و رزولور"),'
    assert a1 in rp, "nav anchor"
    rp = rp.replace(a1, a1 + '\n    ("ph-p21", "🎯", "اسکنر IP و DNS", "سنجش و رزولور"),', 1)
    a2 = '''  function show(id, silent){
    var tab = document.querySelector('.ph-tab[data-target="' + id + '"]');
    if (tab) tab.click();
    else $$(".ph-panel").forEach(function(pn){ pn.className = "ph-panel" + (pn.id === id ? " on" : ""); });'''
    assert a2 in rp, "show anchor"
    rp = rp.replace(a2, '''  function show(id, silent){
    var tab = document.querySelector('.ph-tab[data-target="' + id + '"]');
    if (tab) tab.click();
    /* همیشه تک‌پنلی: بعضی هندلرهای تب قدیمی فقط گروه خودشان را خاموش می‌کنند */
    $$(".ph-panel").forEach(function(pn){ pn.className = "ph-panel" + (pn.id === id ? " on" : ""); });''', 1)
    rp = rp.replace('<span class="ph-badge mono">۲.۵</span>', '<span class="ph-badge mono">۲.۶</span>', 1)
    RP.write_text(rp, encoding="utf-8")
    report.append("✅ rebuild_pages: منو + phShow + نسخهٔ ۲.۶")

# ------------------------------------------------------------------ ۴) چک‌های deploy
dp = DP.read_text(encoding="utf-8")
if "ph6-scanner" in dp:
    report.append("↷ deploy.py: از قبل هست")
else:
    a3 = '''        ok = body.count('mn-dr') >= 2 and 'mn-acc' not in body
        results.append(("کشوی mn یکتاست", ok, str(body.count('mn-dr'))))
        print(f"  {'✅' if ok else '❌'} {'کشوی mn یکتا':34s} {'':>5s}  n={body.count('mn-dr')}")
    except Exception as e:
        print("  ❌ mn-drawer:", e)
'''
    assert a3 in dp, "deploy anchor"
    dp = dp.replace(a3, a3 + '''
    # --- دور ۶: اسکنر IP و DNS ---
    print("\\n  ── 🎯 اسکنر IP و DNS ──")
    count_in("/app پنل اسکنر", f"{SITE}/app", 'id="ph-p21"')
    count_in("/app ورودی اسکنر", f"{SITE}/app", 'id="ph6-in"')
    count_in("/app دکمهٔ اسکن", f"{SITE}/app", 'id="ph6-go"')
    count_in("/app سنجش از گوشی", f"{SITE}/app", 'id="ph6-dev"')
    count_in("/app آیتم منوی اسکنر", f"{SITE}/app", "اسکنر IP و DNS")
    count_in("/docs مسیر scanner", f"{SITE}/docs", "/api/scanner")
    try:
        st, raw = api(f"{SITE}/api/scanner?ips=1.1.1.1,8.8.8.8&mode=ping&packets=4", "x", "GET", None,
                      {"Authorization": "", "User-Agent": "PingHab/1.0"}, raw=True, timeout=90)
        j = json.loads(raw)
        rows = j.get("results") or []
        ok = st == 200 and j.get("ok") and len(rows) == 2 and all(("summary" in R or "error" in R) for R in rows)
        n_meas = sum(len(R.get("probes") or []) for R in rows)
        results.append(("اسکنر: دو هدف، پروب‌های واقعی", ok, f"probes={n_meas}"))
        print(f"  {'✅' if ok else '❌'} {'اسکنر live (ICMP از ایران)':34s} {str(st):>5s}  probes={n_meas} countries={len(j.get('countries') or [])}")
    except Exception as e:
        results.append(("اسکنر live", False, str(e)[:40]))
        print("  ❌ scanner-ping:", e)
    try:
        st, raw = api(f"{SITE}/api/scanner?ips=9.9.9.9&mode=dns", "x", "GET", None,
                      {"Authorization": "", "User-Agent": "PingHab/1.0"}, raw=True, timeout=90)
        j = json.loads(raw)
        R0 = (j.get("results") or [{}])[0]
        ok = st == 200 and j.get("ok") and ("dns" in R0)
        print(f"  {'✅' if ok else '❌'} {'اسکنر رزولوشن DNS':34s} {str(st):>5s}  ok_count={(R0.get('dns') or {}).get('ok_count')}")
        results.append(("اسکنر: رزولوشن DNS از ایران", ok, str((R0.get('dns') or {}).get('median_ms'))))
    except Exception as e:
        results.append(("اسکنر DNS", False, str(e)[:40]))
        print("  ❌ scanner-dns:", e)
''', 1)
    DP.write_text(dp, encoding="utf-8")
    report.append("✅ deploy.py: ۶ چک تازه")

for r in report:
    print(r)
