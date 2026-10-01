#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
patch_preflight.py — بازنویسی آزمون آمادگی (ph2-pf) در صفحه‌ها و در web/tools2-block.html

چرا: کاربر دو اجرای پشت‌سرهم ۴۵ و ۱۳ گرفت. ریشه‌ها:
  ۱) امتیاز، «پینگ به لبهٔ شبکهٔ ما» را با آستانهٔ سرور بازی (CS2 p50≤60ms) مقایسه می‌کرد؛
     روی خط موبایل ایران این مقایسه ذاتاً منفی است ⇒ حکم همیشه «آماده نیستی».
  ۲) بافر‌بلاست با یک نمونه‌گیری ۱٫۲ ثانیه‌ای وسط دانلود سنجیده می‌شد ⇒ عدد پرنوسان (±۶۴۰ms).
  ۳) امتیاز پله‌ای بود ⇒ با نویز کم، ۳۲ امتیاز می‌پرید.
حالا: امتیاز فقط از «پایداری خط» (نوسان/افت/صف/NAT) می‌آید و مؤلفه‌ها شفاف نمایش داده می‌شوند،
و پینگ واقعی سرور بازی جدا و با پروب‌های ایران سنجیده می‌شود.

اجرا: python3 tools/patch_preflight.py web/tools2-block.html cloudflare/app.html web/dns-radar.html
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

NEW_BB = '''  async function bufferbloat(){
    /* نسخهٔ ۲: قبل از بار، وسط بار (دو پنجره) و بعد از بار — تا هم «صف» و هم «بازگشت» دیده شود. */
    var idle = (await rttSamples(8)).filter(function(x){ return x!=null; });
    var loads = [];
    for (var k=0;k<3;k++) loads.push(fetch(ABS + "/api/load?bytes=1500000&r="+Math.random(), {cache:"no-store"}).catch(function(){}));
    var sleep2 = function(ms){ return new Promise(function(r){ setTimeout(r, ms); }); };
    await sleep2(900);
    var mid1 = (await rttSamples(6)).filter(function(x){ return x!=null; });
    await sleep2(700);
    var mid2 = (await rttSamples(6)).filter(function(x){ return x!=null; });
    loads.forEach(function(p){ p.then(function(r){ try{ r && r.body && r.body.cancel(); }catch(e){} }); });
    await sleep2(500);
    var after = (await rttSamples(6)).filter(function(x){ return x!=null; });
    var mi = med(idle), ml = med(mid1.concat(mid2)), ma = med(after);
    return { idle: mi, loaded: ml, after: ma,
      delta: (mi!=null && ml!=null) ? Math.round(ml-mi) : null,
      recovered: (ma!=null && mi!=null) ? Math.round(ma-mi) : null,
      spread_loaded: (mid1.concat(mid2).length>1) ? Math.round(Math.max.apply(null,mid1.concat(mid2))-Math.min.apply(null,mid1.concat(mid2))) : null,
      n_idle: idle.length, n_loaded: mid1.length+mid2.length };
  }
'''

NEW_SCORE = '''  function scorePreflight(game, rtt, dns, nat, bb, prof){
    /* امتیاز = پایداری خط. پینگ مطلق «خط تو → لبهٔ شبکهٔ ما» در امتیاز دخالت نمی‌کند،
       چون با آستانهٔ سرور بازی مقایسه‌شدنش غلط است. پینگ واقعی سرور بازی جدا سنجیده می‌شود. */
    var v = rtt.filter(function(x){ return x!=null; });
    var p50 = med(v);
    var jit = 0;
    if (v.length > 1){ var d=[]; for (var i=1;i<v.length;i++) d.push(Math.abs(v[i]-v[i-1])); jit = med(d); }
    var loss = Math.round(((rtt.length - v.length) / Math.max(1,rtt.length)) * 100);
    var g = (prof && prof.good) || { p50:60, jitter:10, loss:1 };
    var ok = (prof && prof.ok) || { p50:100, jitter:25, loss:5 };
    var clamp = function(x,a,b){ return Math.max(a, Math.min(b, x)); };
    var score = 100, reasons = [], parts = [];
    if (jit > ok.jitter) { score -= 25; reasons.push("نوسان بالا " + rnd(jit,0) + "ms"); }
    else if (jit > g.jitter) { score -= 10; reasons.push("نوسان مرزی " + rnd(jit,0) + "ms"); }
    else parts.push("نوسان خوب " + rnd(jit,0) + "ms");
    if (loss > ok.loss) { score -= 30; reasons.push("افت بسته " + fa(loss) + "٪"); }
    else if (loss > g.loss) { score -= 12; reasons.push("افت کم " + fa(loss) + "٪"); }
    else parts.push("بدون افت بسته");
    if (bb && bb.delta != null){
      if (bb.delta > 150) { score -= 22; reasons.push("صف شدید زیر بار (+" + rnd(bb.delta,0) + "ms)"); }
      else if (bb.delta > 60) { score -= 10; reasons.push("صف متوسط زیر بار (+" + rnd(bb.delta,0) + "ms)"); }
      else parts.push("صف کنترل‌شده (+" + rnd(bb.delta,0) + "ms)");
      if (bb.recovered != null){
        if (bb.recovered > 60) { score -= 6; reasons.push("بازگشت کند بعد از بار (+" + rnd(bb.recovered,0) + "ms)"); }
        else parts.push("بازگشت سریع بعد از بار");
      }
    }
    if (nat && nat.ok && /متقارن/.test(nat.type)) { score -= 8; reasons.push("NAT متقارن (میزبانی/عضویت سخت‌تر)"); }
    if (v.length < 6) reasons.push("نمونهٔ کم — اطمینان پایین");
    score = clamp(Math.round(score), 0, 100);
    return { score: score, p50: p50, jitter: Math.round(jit), loss: loss,
      samples: v.length, confidence: v.length >= 10 ? "بالا" : (v.length >= 6 ? "متوسط" : "پایین"),
      verdict: score >= 80 ? "پایداری خوب" : (score >= 55 ? "پایداری مرزی" : "پایداری ضعیف"),
      reasons: reasons, parts: parts, best: dns && dns[0] ? dns[0] : null,
      basis: "امتیاز فقط از پایداری خط (نوسان/افت/صف/NAT) است — نه پینگ مطلق. پینگ سرور بازی پایین‌تر، واقعی سنجیده می‌شود." };
  }
'''

RENDER_ADD = '''    try{
      var prev = JSON.parse(localStorage.getItem("ph2.pf.last")||"null");
      if (prev && prev.game === game){
        var diff = r.score - prev.score;
        html += '<div class="sub" style="margin-top:6px">اجرای قبلی همین بازی: <b>' + fa(prev.score) + '/۱۰۰</b> (' + ago(prev.at) +
          ') — تفاوت <b>' + (diff>0?"+":"") + fa(diff) + '</b>. روی خط موبایل تا ±۱۰ امتیاز نوسان طبیعی است؛ کمتر از آن را «تغییر واقعی» ندان.</div>';
      }
      localStorage.setItem("ph2.pf.last", JSON.stringify({ game: game, score: r.score, at: Date.now() }));
    }catch(e){}
    html += '<div class="sub" style="margin-top:6px">' + esc(r.basis||"") + ' · اطمینان: <b>' + esc(r.confidence||"—") + '</b> (' + fa(r.samples||0) + ' نمونه)</div>';
    if ((r.parts||[]).length) html += '<div style="margin-top:6px"><b>نقاط قوت:</b> ' + r.parts.map(function(x){ return '<span class="ph-badge ph-chip-ok">'+esc(x)+'</span>'; }).join(" ") + '</div>';
    html += '<div class="ph-card" style="margin-top:10px"><b>🎯 پینگ واقعی سرور بازی (از پروب‌های ایران)</b>' +
      '<div class="sub">این آزمون فقط «پایداری خط» را می‌سنجد. دکمهٔ زیر خودِ سرور بازی را از دیتاسنترهای داخل ایران پینگ می‌کند — عدد واقعی، با شبکهٔ پروب و اعتبار هر نمونه.</div>' +
      '<button class="wwbtn wwprimary" id="ph2-pf-gs" style="margin-top:8px">📡 سنجش سرور بازی</button><div id="ph2-pf-gsout"></div></div>';
    html += '</div>';   /* بستن کارت اصلی آزمون */
    out.innerHTML = html;
    var gs = q("ph2-pf-gs");
    if (gs) gs.onclick = async function(){
      var bo = q("ph2-pf-gsout");
      bo.innerHTML = '<div class="sub">در حال گرفتن سرورهای این بازی و پینگ زنده… (~۲۰ ثانیه)</div>';
      try{
        var gd = await jget("/api/games?game=" + encodeURIComponent(game));
        var firsts = [];
        Object.keys(gd.regions||{}).forEach(function(rg){ if ((gd.regions[rg]||[])[0]) firsts.push((gd.regions[rg])[0]); });
        firsts = firsts.slice(0, 3);
        if (!firsts.length) return bo.innerHTML = '<div class="ph-warn">سروری برای این بازی ثبت نشده.</div>';
        var gpr = await jget("/api/gameping?ips=" + encodeURIComponent(firsts.map(function(s2){ return s2.ip; }).join(",")) + "&cc=IR");
        var h2 = '<table style="width:100%;font-size:13px;border-collapse:collapse;margin-top:8px"><tr><th>سرور</th><th>آی‌پی</th><th>میانهٔ پروب‌های ایران</th><th>وضعیت</th></tr>';
        var bestMed = null;
        (gpr.results||[]).forEach(function(res){
          var meta = firsts.filter(function(s2){ return s2.ip === res.ip; })[0] || {};
          var sm = res.summary || {};
          h2 += '<tr><td>' + esc(meta.loc||res.ip) + '</td><td class="mono">' + esc(res.ip) + '</td><td>' +
            (sm.median_ms==null ? "—" : '<b>' + fa(sm.median_ms) + 'ms</b>') + '</td><td>' +
            (sm.median_ms==null ? '<span class="ph-bad">سنجش‌پذیر نبود (ICMP بسته)</span>'
              : (sm.credible ? '<span class="ph-badge ph-chip-ok">' + fa(sm.valid) + ' پروب معتبر</span>' : '<span class="ph-badge">اطمینان کم</span>')) + '</td></tr>';
          if (sm.median_ms != null && (bestMed==null || sm.median_ms<bestMed)) bestMed = sm.median_ms;
        });
        h2 += '</table>';
        if (bestMed != null){
          var gg = (prof && prof.good) || { p50:60 }, oo = (prof && prof.ok) || { p50:100 };
          var band = bestMed <= gg.p50 ? "در محدودهٔ «خوب» این بازی" : (bestMed <= oo.p50 ? "قابل بازی، نه رقابتی" : "دور از محدودهٔ رقابتی");
          h2 += '<div class="sub">بهترین سرور: <b>' + fa(Math.round(bestMed)) + 'ms</b> از دیتاسنتر ایران → ' + band +
            ' (آستانه‌های این بازی: خوب ≤' + fa(gg.p50) + 'ms · قابل بازی ≤' + fa(oo.p50) + 'ms).<br>' +
            'پینگ خط موبایل تو معمولاً از این عدد بالاتر است؛ برای عدد <b>خط خودت</b>، بخش «خط من» را ببین. DNS پینگ داخل مچ را کم نمی‌کند.</div>';
        } else {
          h2 += '<div class="warn-note sub">سرورهای این بازی به ICMP جواب ندادند — عدد نمی‌سازیم. از بخش «سرورهای بازی» سرور دیگری/رجین دیگری امتحان کن.</div>';
        }
        bo.innerHTML = h2;
      }catch(e){ bo.innerHTML = '<div class="ph-warn">خطا: ' + esc(e.message) + '</div>'; }
    };
'''


def patch(path: Path) -> bool:
    s = path.read_text(encoding="utf-8")
    if "ph2-pf-v2" in s:
        return False
    # ۱) بافر‌بلاست
    i = s.find("  async function bufferbloat(){")
    j = s.find("  function scorePreflight(game, rtt, dns, nat, bb, prof){")
    assert i != -1 and j != -1 and i < j, f"anchor1 in {path.name}"
    s = s[:i] + NEW_BB + s[j:]
    # ۲) امتیاز (اندیس‌ها پس از تغییر قبلی از نو حساب می‌شوند)
    j = s.find("  function scorePreflight(game, rtt, dns, nat, bb, prof){")
    k = s.find("  function kalmanish(samples){")
    assert j != -1 and k != -1 and j < k, f"anchor2 in {path.name}"
    s = s[:j] + NEW_SCORE + s[k:]
    # ۳) نمایش: مقایسه با اجرای قبلی + سنجش واقعی سرور بازی
    a = s.find("    html += '<div class=\"sub\" style=\"margin-top:8px\">همهٔ اعداد از دستگاه خودت است.")
    assert a != -1, f"anchor3 in {path.name}"
    b = s.find("    out.innerHTML = html;\n  };\n  var HIST_LOADED", a)
    assert b != -1, f"anchor4 in {path.name}"
    s = s[:a] + RENDER_ADD + s[b + len("    out.innerHTML = html;\n"):]
    s = s.replace("  function kalmanish(samples){", "  /* ph2-pf-v2: آزمون آمادگی بازنویسی شد (امتیاز = پایداری خط) */\n  function kalmanish(samples){", 1)
    assert "ph2-pf-v2" in s
    path.write_text(s, encoding="utf-8")
    return True


if __name__ == "__main__":
    targets = [Path(a) for a in sys.argv[1:]] or [ROOT / "web" / "tools2-block.html",
                                                 ROOT / "cloudflare" / "app.html", ROOT / "web" / "dns-radar.html"]
    for t in targets:
        try:
            changed = patch(t)
        except AssertionError as e:
            print("SKIP", t.name, e)
            continue
        try:
            rel = t.resolve().relative_to(ROOT)
        except ValueError:
            rel = t
        print(("patched  " if changed else "already  ") + str(rel))
