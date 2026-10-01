#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""درج بلوک فاز E (tools3) در هر دو سطح: cloudflare/app.html و web/dns-radar.html"""
import pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BLOCK = ROOT / "web" / "tools3-block.html"
TARGETS = [ROOT / "cloudflare" / "app.html", ROOT / "web" / "dns-radar.html"]

block = BLOCK.read_text(encoding="utf-8")
parts = block.split("<!--PH3-SCRIPT-->")
assert len(parts) == 2, "marker missing"
markup, script = parts[0].rstrip() + "\n", parts[1].strip() + "\n"

anchor1 = '<script>\n/* =========== ⚡ پینگ‌هاب ۲.۰'
anchor2 = '''  if (location.protocol !== "file:" && !/appassets\\.androidplatform\\.net$/.test(location.hostname) && "serviceWorker" in navigator){
    navigator.serviceWorker.register("/sw.js").catch(function(){});
  }
})();
</script>
'''

for t in TARGETS:
    src = t.read_text(encoding="utf-8")
    if "ph-p13" in src:
        print("already inlined:", t.name); continue
    assert anchor1 in src, f"anchor1 missing in {t.name}"
    assert anchor2 in src, f"anchor2 missing in {t.name}"
    src = src.replace(anchor1, markup + anchor1, 1)
    src = src.replace(anchor2, anchor2 + "\n" + script, 1)
    t.write_text(src, encoding="utf-8")
    print(f"inlined into {t.name}: {len(src)} chars, panels p13..p18 =",
          sum(src.count(f'id="ph-p{n}"') for n in range(13, 19)))
