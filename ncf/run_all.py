#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCF · اجرای سرتاسری (یک فرمان، همه‌چیز)
=========================================================================
  python3 -m ncf.run_all

مراحل:
  ۱) سنجش زندهٔ شبکه      → ncf/live.json
  ۲) خودآزمون علت‌یابی     → ncf/diag.json
  ۳) بک‌تست شبیه‌ساز (۲ حالت سوئیچ) → ncf/bench.json
  ۴) گزارش HTML فارسی     → ncf/report.html

کل زمان: حدود ۴ تا ۶ دقیقه (بیشترش بک‌تست).
متغیر محیطی: NCF_SEEDS (پیش‌فرض ۱۲) برای تعداد seed در بک‌تست.
"""

from __future__ import annotations

import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # تا `ncf` به‌عنوان پکیج دیده شود


def step1_live() -> dict:
    """سنجش زندهٔ مسیرها روی شبکهٔ همین ماشین (بدون ذخیرهٔ محتوا)."""
    from ncf.observe import (PathObsSpec, environment_snapshot, observe_path, probe_tcp, probe_tls,
                             probe_udp_dns, sweep_udp_payload)

    print("۱) سنجش زندهٔ شبکه...", flush=True)
    env = environment_snapshot()
    out = {"environment": env, "ts": time.time()}

    # مسیرهای نامزد: حل‌کننده‌های عمومی (حل‌کننده‌های ایرانی از این ماشین در دسترس نیستند)
    specs = [
        PathObsSpec(id="cf", label="Cloudflare 1.1.1.1", dns_ip="1.1.1.1", tcp_ip="1.1.1.1",
                    sni="one.one.one.one"),
        PathObsSpec(id="google", label="Google 8.8.8.8", dns_ip="8.8.8.8", tcp_ip="8.8.8.8",
                    sni="dns.google"),
        PathObsSpec(id="quad9", label="Quad9 9.9.9.9", dns_ip="9.9.9.9", tcp_ip="9.9.9.9",
                    sni="dns.quad9.net"),
    ]
    paths = []
    for spec in specs:
        rtts, ok = [], 0
        for _ in range(8):
            o = probe_udp_dns(spec.dns_ip)
            if o.ok and o.rtt_ms:
                rtts.append(o.rtt_ms)
                ok += 1
        if rtts:
            s = sorted(rtts)
            q = lambda p: s[min(len(s) - 1, int(p * len(s)))]
            paths.append({"path": spec.id, "label": spec.label, "n": len(rtts), "ok": ok,
                          "p50": round(statistics.median(rtts), 2),
                          "p90": round(q(0.9), 2), "p95": round(q(0.95), 2),
                          "min": round(s[0], 2), "max": round(s[-1], 2),
                          "loss": round(1 - ok / 8, 3)})
        else:
            paths.append({"path": spec.id, "label": spec.label, "n": 0, "ok": 0, "loss": 1.0})
        ob = observe_path(spec, deep=False)
        if ob.get("summary"):
            paths[-1]["summary"] = ob["summary"]
    out["paths"] = paths

    t = probe_tcp("1.1.1.1", 443)
    tl = probe_tls("1.1.1.1", "one.one.one.one")
    out["tcp_ms"] = t.rtt_ms
    out["tls_ms"] = tl.rtt_ms
    out["tls_minus_tcp_ms"] = (round(tl.rtt_ms - t.rtt_ms, 2)
                               if (t.ok and tl.ok and t.rtt_ms and tl.rtt_ms) else None)
    sw = sweep_udp_payload("8.8.8.8", sizes=(512, 900, 1232, 1400, 1500))
    out["payload_sweep"] = sw
    gw = (env.get("gateway") or {})
    out["notes"] = (
        "گیت‌وی محلی و IPv6 از این ماشین در دسترس نبودند؛ جاروب حجم نشان می‌دهد "
        f"UDP بالای {sw.get('max_ok')} بایت پاسخ نمی‌گیرد (RTT نمونه‌های کوچک چند میلی‌ثانیه است). "
        "حل‌کننده‌های ایرانی (رادار/الکترو/شکن) از این ماشین قابل‌دسترس نیستند؛ "
        "برای همان‌ها لایهٔ سنجش باید از ماشین داخل ایران اجرا شود."
    )
    with open(os.path.join(HERE, "live.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"   ✅ {len(paths)} مسیر سنجیده شد → ncf/live.json")
    return out


def step2_diagnose() -> dict:
    """سه سناریوی ساختگی با علت معلوم تا موتور علت‌یابی قابل‌داوری باشد."""
    from ncf.diagnose import DiagnosisEngine, ProbeMatrix

    print("۲) خودآزمون علت‌یابی...", flush=True)
    eng = DiagnosisEngine()
    cases = {
        "مهار UDP توسط اپراتور": ProbeMatrix(
            gateway_ok=True, gateway_rtt=3, isp_dns_rtt=38, external_rtts={"1.1.1.1": 41},
            udp_loss_small=0.55, udp_loss_large=0.7, tcp_rtt=52, tls_rtt=95, max_ok_payload=900,
            ipv4_ok=True, ipv6_ok=None, multi_dest_rtts={"A": 45, "B": 140, "C": 48}, hour_local=22),
        "سرور مقصد خراب": ProbeMatrix(
            gateway_ok=True, gateway_rtt=2, isp_dns_rtt=30, external_rtts={"9.9.9.9": 33},
            tcp_rtt=35, tls_rtt=60, ipv4_ok=True, ipv6_ok=True, ipv6_rtt=40,
            multi_dest_rtts={"game-eu": 36, "game-me": 240, "cdn": 34}, hour_local=19),
        "وای‌فای محلی خراب": ProbeMatrix(
            gateway_ok=True, gateway_rtt=22, isp_dns_rtt=48, external_rtts={"8.8.8.8": 44, "1.1.1.1": 47},
            tcp_rtt=46, tls_rtt=78, ipv4_ok=True, ipv6_ok=True, ipv6_rtt=52,
            multi_dest_rtts={"A": 47, "B": 49, "C": 46}, hour_local=21),
    }
    out = {"cases": []}
    for title, m in cases.items():
        dd = eng.diagnose(m).to_dict()
        out["cases"].append({
            "case": title,
            "primary": dd["primary_label"],
            "probability": dd["probability"],
            "ranked": dd["ranked"][:5],
            "next_probes": dd["next_probes"][:4],
            "evidence": dd["evidence"][:4],
        })
        print(f"   • {title}: {dd['primary_label']} ({dd['probability']:.0%})")
    with open(os.path.join(HERE, "diag.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("   ✅ → ncf/diag.json")
    return out


def step3_bench() -> dict:
    from ncf.simulate import run_suite, render_summary

    seeds = int(os.environ.get("NCF_SEEDS", "12"))
    print(f"۳) بک‌تست شبیه‌ساز ({seeds} seed × ۲ حالت هزینهٔ سوئیچ) — چند دقیقه طول می‌کشد...", flush=True)
    suite = run_suite(seeds=seeds)
    for key in ("breaking", "smooth"):
        m = suite["modes"][key]
        print(render_summary({"app": suite["app"], "seeds": suite["seeds"], "ticks": suite["ticks"],
                              "switch_cost_scale": m["switch_cost_scale"], "summary": m["summary"],
                              "runtime_s": m["runtime_s"]}))
        print()
    cal = suite["modes"]["breaking"]["calibration"]
    print(f"   کالیبراسیون: n={cal['n']} Brier={cal['brier']} مهارت={cal['skill']}")
    with open(os.path.join(HERE, "bench.json"), "w", encoding="utf-8") as f:
        json.dump(suite, f, ensure_ascii=False, indent=1)
    print("   ✅ → ncf/bench.json")
    return suite


def step4_report() -> str:
    from ncf.report import main as report_main

    print("۴) ساخت گزارش HTML...", flush=True)
    report_main([])
    return os.path.join(HERE, "report.html")


def main() -> int:
    t0 = time.time()
    print("=" * 74)
    print("NCF · اجرای سرتاسری")
    print("=" * 74)
    step1_live()
    step2_diagnose()
    step3_bench()
    path = step4_report()
    print(f"\n✅ تمام. گزارش: {path}  (کل زمان: {time.time() - t0:.0f} ثانیه)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
