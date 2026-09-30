#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCF · موتور علت‌یابی (Causal Network Diagnosis)
=========================================================================
«ping رفت بالا» تشخیص نیست. تشخیص یعنی: کدام فرضیه، و با چه احتمالی؟

این ماژول از یک **ماتریس پروب تفاضلی**، فرضیه‌ها را امتیاز می‌دهد:
  - اگر گیت‌وی محلی خودش کند است → مشکل «دسترسی محلی» (وای‌فای/مودم/بار شبکهٔ خانه)
  - اگر resolver اپراتور بد است ولی بیرونی‌ها خوب‌اند → مشکل «DNS اپراتور»
  - اگر UDP درصد از دست رفتن دارد ولی TCP سالم است → «مهار/throttle UDP»
  - اگر TLS خیلی کندتر از TCP است → «دستکاری/رمزنگاری اجباری در مسیر»
  - اگر حجم‌های بزرگ UDP حذف می‌شوند → «فیلترینگ حجمی/مسئلهٔ MTU»
  - اگر IPv6 خراب و IPv4 سالم است → «افت IPv6»
  - اگر فقط یک مقصد بد است و بقیه خوب → «سمت مقصد»
  - اگر همهٔ مقاصد (چند ASN) بدند و محلی خوب → «ازدحام ترانزیت/پیرینگ»
  - اگر پرش پله‌ای ثبت شده و بقیه سالم → «تغییر مسیر»
خروجی: فرضیه‌های رتبه‌بندی‌شده با احتمال + شواهد + «پروب بعدی برای ابطال».

⚠️ این یک شبکهٔ بیزی کامل نیست؛ یک سیستم امتیازدهی خبره با قواعد صریح و قابل
   بازبینی است. مزیتش: قابل توضیح، قابل تست، و قابل جایگزینی با مدل احتمالاتی
   واقعی وقتی دادهٔ برچسب‌دار کافی جمع شد.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict

HYPOTHESES = {
    "local_access": "مشکل دسترسی محلی (وای‌فای/مودم/بار شبکهٔ خانه)",
    "isp_dns": "مشکل DNS اپراتور تو",
    "udp_throttle": "مهار یا افت عمدی UDP توسط اپراتور",
    "tls_interference": "دستکاری/TLS اجباری در مسیر (Middlebox)",
    "payload_filter": "فیلترینگ حجمی/مشکل MTU روی UDP",
    "ipv6_degradation": "افت مسیر IPv6",
    "destination_side": "مشکل سمت مقصد (سرور/CDN)",
    "transit_peering": "ازدحام ترانزیت یا پیرینگ اپراتور",
    "route_change": "تغییر مسیر (BGP/مسیر میانی)",
    "load_saturation": "اشباع ظرفیت (مصرف همزمان/پهنای‌باند)",
    "unknown": "علت مشخص نشد",
}


@dataclass
class Evidence:
    rule: str
    weight: float
    detail: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Diagnosis:
    primary: str
    primary_label: str
    probability: float
    ranked: list[tuple[str, float]] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    next_probes: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "primary": self.primary, "primary_label": self.primary_label,
            "probability": self.probability,
            "ranked": [{"hypothesis": h, "label": HYPOTHESES.get(h, h), "p": p} for h, p in self.ranked],
            "evidence": [e.to_dict() for e in self.evidence],
            "next_probes": self.next_probes,
            "actions": self.actions,
        }

    def render(self) -> str:
        lines = [f"🧠 تشخیص اصلی: {self.primary_label}  (احتمال {self.probability:.0%})", ""]
        lines.append("فرضیه‌ها به ترتیب احتمال:")
        for h, p in self.ranked:
            bar = "█" * int(p * 20)
            lines.append(f"  {p:5.0%} {bar:<20} {HYPOTHESES.get(h, h)}")
        if self.evidence:
            lines.append("\nشواهد:")
            for e in self.evidence[:8]:
                lines.append(f"  • {e.detail}  [{e.rule} +{e.weight:.1f}]")
        if self.next_probes:
            lines.append("\nپروب‌های بعدی برای ابطال فرضیه‌ها:")
            for i, np_ in enumerate(self.next_probes, 1):
                lines.append(f"  {i}. {np_}")
        if self.actions:
            lines.append("\nاقدام پیشنهادی (به ترتیب):")
            for i, a in enumerate(self.actions, 1):
                lines.append(f"  {i}. {a}")
        return "\n".join(lines)


# ----------------------------------------------------------------------------- ورودی: ماتریس پروب

@dataclass
class ProbeMatrix:
    """
    خروجی پروب‌های تفاضلی. همه‌چیز اختیاری است؛ هرچه بیشتر باشد تشخیص دقیق‌تر.
    مقادیر RTT بر حسب میلی‌ثانیه، نرخ‌ها کسری بین ۰ و ۱.
    """
    gateway_rtt: float | None = None
    gateway_ok: bool | None = None
    isp_dns_rtt: float | None = None          # resolver اپراتور
    external_rtts: dict[str, float] = field(default_factory=dict)   # resolverهای بیرونی
    udp_loss_small: float | None = None       # نرخ از دست رفتن UDP با پکت کوچک
    udp_loss_large: float | None = None       # نرخ از دست رفتن UDP با پکت بزرگ
    tcp_rtt: float | None = None
    tls_rtt: float | None = None
    max_ok_payload: int | None = None         # بزرگ‌ترین حجم UDP که رد شد
    ipv4_ok: bool | None = None
    ipv6_ok: bool | None = None
    ipv6_rtt: float | None = None
    multi_dest_rtts: dict[str, float] = field(default_factory=dict)  # مقصدهای چند ASN
    recent_route_change: bool = False
    route_change_magnitude: float | None = None
    local_baseline_rtt: float | None = None   # بهترین وضعیت تاریخی همین مسیر
    hour_local: int | None = None             # ساعت محلی (الگوی شبانه)
    concurrent_load_hint: float | None = None # شاهد بار زیاد محلی (۰..۱)

    def to_dict(self) -> dict:
        return asdict(self)


# ----------------------------------------------------------------------------- موتور

class DiagnosisEngine:
    def __init__(self, temperature: float = 1.0):
        self.temperature = temperature

    def diagnose(self, m: ProbeMatrix) -> Diagnosis:
        scores: dict[str, float] = {h: 0.15 for h in HYPOTHESES if h != "unknown"}
        ev: list[Evidence] = []
        next_probes: list[str] = []
        actions: list[str] = []

        # ۱) لایهٔ محلی
        if m.gateway_ok is False:
            scores["local_access"] += 1.6
            ev.append(Evidence("gateway_unreachable", 1.6, "گیت‌وی محلی جواب نداد → رادیو/مودم/کابل مشکوک"))
            next_probes.append("دوباره گیت‌وی را تست کن با پورت‌های ۸۰/۴۴۳/۵۳ و از دستگاه دوم")
        elif m.gateway_ok and m.gateway_rtt is not None:
            if m.gateway_rtt > 15:
                scores["local_access"] += 2.4
                ev.append(Evidence("gateway_slow", 2.4, f"RTT گیت‌وی محلی {m.gateway_rtt}ms است (سالم: زیر ۵ms)"))
            elif m.gateway_rtt > 7:
                scores["local_access"] += 1.0
                ev.append(Evidence("gateway_borderline", 1.0, f"RTT گیت‌وی {m.gateway_rtt}ms — مرزی"))
            else:
                scores["local_access"] -= 0.5
                ev.append(Evidence("gateway_fast", -0.5, f"مسیر محلی سالم است (گیت‌وی {m.gateway_rtt}ms)"))
        if m.concurrent_load_hint is not None and m.concurrent_load_hint > 0.6:
            scores["load_saturation"] += 1.5
            ev.append(Evidence("local_load", 1.5, "شاهد بار سنگین محلی (دانلود/آپدیت همزمان)"))

        # ۲) DNS اپراتور در برابر بیرون
        ext = [v for v in m.external_rtts.values() if v]
        best_ext = min(ext) if ext else None
        if m.isp_dns_rtt and best_ext:
            ratio = m.isp_dns_rtt / max(best_ext, 1)
            if ratio > 1.6 and m.isp_dns_rtt - best_ext > 14:
                scores["isp_dns"] += 2.2
                ev.append(Evidence("isp_dns_slow", 2.2,
                                   f"DNS اپراتور {m.isp_dns_rtt:.0f}ms در برابر بهترین بیرونی {best_ext:.0f}ms"))
                actions.append(f"DNS را به بهترین resolver بیرونی تغییر بده (≈{best_ext:.0f}ms)")
            else:
                scores["isp_dns"] -= 0.4
                ev.append(Evidence("isp_dns_ok", -0.4, "DNS اپراتور نسبت به بیرون بد نیست"))
        elif m.isp_dns_rtt is None:
            next_probes.append("RTT resolver اپراتور را اندازه بگیر (DNS پیش‌فرض را بپرس)")

        # ۳) UDP در برابر TCP (مهار پروتکلی)
        if m.udp_loss_small is not None and m.tcp_rtt is not None:
            if m.udp_loss_small > 0.25 and m.tcp_rtt < (m.gateway_rtt or 0) + 120:
                scores["udp_throttle"] += 2.6
                ev.append(Evidence("udp_loss_tcp_ok", 2.6,
                                   f"از دست رفتن UDP {m.udp_loss_small:.0%} در حالی که TCP/TLS کار می‌کند"))
                actions.append("مسیرهای UDP-محور را موقتاً کنار بگذار یا از پوشش رمزنگاری‌شده (DoH/DoT) استفاده کن")
            elif m.udp_loss_small > 0.10:
                scores["udp_throttle"] += 1.1
                ev.append(Evidence("udp_loss_mild", 1.1, f"از دست رفتن UDP {m.udp_loss_small:.0%}"))

        # ۴) دستکاری TLS
        if m.tls_rtt and m.tcp_rtt:
            extra = m.tls_rtt - m.tcp_rtt
            if extra > 60:
                scores["tls_interference"] += 1.9
                ev.append(Evidence("tls_extra", 1.9, f"دست‌دادن TLS {extra:.0f}ms کندتر از TCP → middlebox"))
            elif extra > 25:
                scores["tls_interference"] += 0.8
                ev.append(Evidence("tls_extra_mild", 0.8, f"اضافه‌بار TLS {extra:.0f}ms"))
            else:
                scores["tls_interference"] -= 0.3

        # ۵) حجم UDP / MTU
        if m.udp_loss_large is not None and m.udp_loss_small is not None:
            if m.udp_loss_large - m.udp_loss_small > 0.3:
                scores["payload_filter"] += 2.4
                ev.append(Evidence("payload_gap", 2.4,
                                   f"از دست رفتن با پکت بزرگ {m.udp_loss_large:.0%} ولی کوچک {m.udp_loss_small:.0%}"))
                actions.append("کاهش MTU (۱۴۰۰) را روی مودم/تونل آزمایش کن")
        if m.max_ok_payload is not None and m.max_ok_payload < 1232:
            scores["payload_filter"] += 1.6
            ev.append(Evidence("payload_ceiling", 1.6, f"سقف حجم UDP زنده = {m.max_ok_payload} بایت"))
            next_probes.append("جاروب ریز حجم (۱۰۰۰..۱۵۰۰) برای پیدا کردن مرز دقیق")

        # ۶) IPv6
        if m.ipv4_ok and m.ipv6_ok is False:
            scores["ipv6_degradation"] += 2.0
            ev.append(Evidence("v6_broken", 2.0, "IPv6 کار نمی‌کند ولی IPv4 سالم است"))
            actions.append("در تنظیمات شبکه IPv6 را خاموش کن تا مسیر روی IPv4 پایدار بماند")
        elif m.ipv4_ok and m.ipv6_ok and m.ipv6_rtt:
            ext_min = min(ext) if ext else m.ipv6_rtt
            if m.ipv6_rtt > ext_min * 1.5:
                scores["ipv6_degradation"] += 1.2
                ev.append(Evidence("v6_slow", 1.2, f"IPv6 ({m.ipv6_rtt:.0f}ms) کندتر از IPv4 ({ext_min:.0f}ms)"))

        # ۷) مقصد در برابر ترانزیت
        md = {k: v for k, v in m.multi_dest_rtts.items() if v}
        if len(md) >= 3:
            vals = sorted(md.values())
            worst = vals[-1]
            best = vals[0]
            spread = worst - best
            if spread > 0.75 * max(best, 1):
                slow = [k for k, v in md.items() if v > best * 1.5]
                scores["destination_side"] += 1.7
                ev.append(Evidence("dest_specific", 1.7,
                                   f"فقط {', '.join(slow)} بد است؛ بقیه خوب‌اند (پراکندگی {spread:.0f}ms)"))
                next_probes.append("همان مقصد را از resolver دیگر تست کن (تغییر endpoint مسیر)")
            else:
                scores["transit_peering"] += 1.5
                scores["destination_side"] -= 0.6
                ev.append(Evidence("all_dest_bad", 1.5,
                                   f"همهٔ مقاصد ({len(md)}) به‌طور یکنواخت کندند → مشکل مسیر بین‌شبکه‌ای"))

        # ۸) تغییر مسیر
        if m.recent_route_change:
            mag = f" (پرش ≈{m.route_change_magnitude:.0f}ms)" if m.route_change_magnitude else ""
            scores["route_change"] += 1.8
            ev.append(Evidence("route_step", 1.8, f"پرش پله‌ای تازه در RTT ثبت شد{mag}"))
            next_probes.append("تغییر ASN/مسیر را با چند مقصد هم‌زمان بررسی کن")

        # ۹) الگوی زمانی
        if m.hour_local is not None and 20 <= m.hour_local <= 23:
            scores["transit_peering"] += 0.6
            ev.append(Evidence("peak_hour", 0.6, f"ساعت {m.hour_local} (اوج مصرف) — ازدحام شبانه محتمل‌تر است"))

        # ۱۰) نرمال‌سازی با softmax
        keys = list(scores.keys())
        mx = max(scores.values())
        exps = {k: math.exp((scores[k] - mx) / self.temperature) for k in keys}
        total = sum(exps.values())
        probs = sorted(((k, exps[k] / total) for k in keys), key=lambda x: -x[1])

        # اگر همه‌چیز سالم بود، صادقانه بگو «علتی پیدا نشد»
        top_h, top_p = probs[0]
        healthy_evidence = [e for e in ev if e.weight < 0]
        if top_p < 0.3 and healthy_evidence:
            probs = [("unknown", 0.55)] + [(k, p * 0.45) for k, p in probs if k != "unknown"]

        if not next_probes:
            next_probes = ["پروب‌ها را تکرار کن در ساعت اوج تا الگو تثبیت شود"]
        if not actions:
            actions = ["اول مشکل را در سطح محلی (وای‌فای/مودم) رد کن، بعد در سطح مسیر"]

        return Diagnosis(
            primary=probs[0][0], primary_label=HYPOTHESES.get(probs[0][0], probs[0][0]),
            probability=round(probs[0][1], 3), ranked=[(k, round(p, 3)) for k, p in probs],
            evidence=ev, next_probes=next_probes[:4], actions=actions[:4],
        )


def matrix_from_observation(env: dict, path_obs: list[dict], state_snapshot: list[dict],
                            route_change: dict | None = None) -> ProbeMatrix:
    """تبدیل خروجی لایهٔ مشاهده/تخمین به ماتریس پروب برای موتور علت‌یابی."""
    m = ProbeMatrix()
    gw = env.get("gateway") or {}
    m.gateway_ok = gw.get("ok")
    m.gateway_rtt = gw.get("rtt_ms")
    v6 = env.get("ipv6") or {}
    m.ipv6_ok = v6.get("ok")
    m.ipv6_rtt = v6.get("rtt_ms")
    m.ipv4_ok = any(p.get("ok") for p in path_obs)

    ext = {}
    for p in path_obs:
        for o in p.get("obs", []):
            if o["kind"] in ("dns_udp", "tcp", "tls") and o.get("ok") and o.get("rtt_ms"):
                ext.setdefault(o["target"], o["rtt_ms"])
                if o["kind"] == "tcp":
                    m.tcp_rtt = o["rtt_ms"]
                if o["kind"] == "tls":
                    m.tls_rtt = o["rtt_ms"]
    m.external_rtts = dict(sorted(ext.items(), key=lambda kv: kv[1])[:6])
    sweep = next((p.get("payload_sweep") for p in path_obs if p.get("payload_sweep")), None)
    if sweep:
        m.max_ok_payload = sweep.get("max_ok")
        sizes = sweep.get("sizes") or {}
        small = [v for k, v in sizes.items() if k <= 900 and v.get("ok") is not None]
        large = [v for k, v in sizes.items() if k >= 1400 and v.get("ok") is not None]
        if small:
            m.udp_loss_small = round(1 - sum(1 for v in small if v["ok"]) / len(small), 3)
        if large:
            m.udp_loss_large = round(1 - sum(1 for v in large if v["ok"]) / len(large), 3)
    for s in state_snapshot:
        if s.get("loss") is not None and m.udp_loss_small is None:
            m.udp_loss_small = s["loss"]
    if route_change and route_change.get("kind") == "up":
        m.recent_route_change = True
        m.route_change_magnitude = route_change.get("mag")
    return m


# ----------------------------------------------------------------------------- خودآزمون

if __name__ == "__main__":
    print("=" * 74)
    print("NCF · خودآزمون موتور علت‌یابی (سه سناریوی ساختگی)")
    print("=" * 74)
    eng = DiagnosisEngine()

    cases = {
        "وای‌فای محلی خراب": ProbeMatrix(
            gateway_ok=True, gateway_rtt=22, isp_dns_rtt=48, external_rtts={"8.8.8.8": 44, "1.1.1.1": 47},
            tcp_rtt=46, tls_rtt=78, ipv4_ok=True, ipv6_ok=True, ipv6_rtt=52,
            multi_dest_rtts={"A": 47, "B": 49, "C": 46}, hour_local=21),
        "مهار UDP توسط اپراتور": ProbeMatrix(
            gateway_ok=True, gateway_rtt=3, isp_dns_rtt=38, external_rtts={"1.1.1.1": 41},
            udp_loss_small=0.55, udp_loss_large=0.7, tcp_rtt=52, tls_rtt=95, max_ok_payload=900,
            ipv4_ok=True, ipv6_ok=None, multi_dest_rtts={"A": 45, "B": 140, "C": 48}, hour_local=22),
        "سرور مقصد خراب": ProbeMatrix(
            gateway_ok=True, gateway_rtt=2, isp_dns_rtt=30, external_rtts={"9.9.9.9": 33},
            tcp_rtt=35, tls_rtt=60, ipv4_ok=True, ipv6_ok=True, ipv6_rtt=40,
            multi_dest_rtts={"game-eu": 36, "game-me": 240, "cdn": 34}, hour_local=19),
    }
    for title, m in cases.items():
        d = eng.diagnose(m)
        print(f"\n{'─' * 74}\n🔍 سناریو: {title}\n{'─' * 74}")
        print(d.render())
