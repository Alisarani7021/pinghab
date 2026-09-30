#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCF · لایهٔ تصمیم (Planning & Decision)
=========================================================================
تابع هدف، به‌صورت یک هزینهٔ قابل‌توضیح:

    J(p) = α·μ + β·tail(p95) + γ·loss·100 + δ·jitter + η·p_fail·100 + ε·switch_cost

ضرایب **ثابت نیستند**: به پروفایل اپلیکیشن وابسته‌اند (بازی در برابر دانلود در برابر ورود).
و تصمیم فقط argmin نیست، چون یک سیستم واقعی سه محدودیت سخت دارد:

  ۱) هزینهٔ سوئیچ (و ریسکش) باید در تصمیم دیده شود، نه بعد از آن.
  ۲) محدودیت پایداری: حداقل زمان ماندن + سقف تعداد سوئیچ در بازه (ضد فلاف).
  ۳) دروازهٔ ایمنی: وسط «لحظهٔ حساس» اپ، سوئیچ نکن مگر احتمال شکست واقعی بالا باشد.

خروجی، یک Decision قابل‌توضیح است: chosen، reason، انتظار هزینه، رقیب، سود خالص،
و اگر سوئیچ نشد، دقیقاً چه محدودیتی جلویش را گرفت (blocked_by) — برای بازرسی انسانی.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, asdict


# ----------------------------------------------------------------------------- پروفایل اپلیکیشن

@dataclass(frozen=True)
class AppProfile:
    key: str
    label: str
    alpha: float          # وزن تأخیر میانه
    beta: float           # وزن دنباله (p95)
    gamma: float          # وزن از دست رفتن بسته (×۱۰۰)
    delta: float          # وزن جیتر (تغییر متوالی)
    eta: float            # وزن احتمال شکست (×۱۰۰)
    switch_cost: float    # هزینهٔ سوئیچ (بر حسب همان یکای هزینه)
    min_dwell_s: float    # حداقل زمان ماندن روی یک مسیر
    max_switches_per_min: float
    critical_window: bool  # آیا لحظات حساس دارد؟ (وسط مچ بازی)
    # آستانهٔ مطلق «شکست کیفیت» برای این اپ (ms).
    # چرا مطلق؟ چون آستانهٔ نسبیِ هر مسیر (نسبت به بهترین رکورد خودش) بی‌عدالتی
    # سیستماتیک می‌سازد: مسیر با کیفیت بهتر، آستانهٔ سخت‌تری می‌گیرد و بدتر دیده می‌شود.
    # شاهد: بک‌تست سناریوی flappy (۲۴ سوئیچ بی‌دلیل به همین دلیل).
    fail_rtt_ms: float = 110.0


PROFILES: dict[str, AppProfile] = {
    # min_dwell بر اساس بک‌تست تنظیم شد: ۲۵ ثانیه در عمل باعث «گیر افتادن» روی مسیر خراب می‌شد
    "gameplay": AppProfile("gameplay", "گیم‌پلی (بازی رقابتی)", 1.0, 2.2, 160, 1.4, 220, 45.0, 8.0, 3.0, True, 110.0),
    "voice": AppProfile("voice", "ویس/چت صوتی", 0.8, 1.6, 220, 2.0, 200, 35.0, 7.0, 3.5, True, 165.0),
    "login": AppProfile("login", "ورود/لابی/فروشگاه", 0.9, 1.2, 260, 0.8, 500, 18.0, 12.0, 3.0, False, 420.0),
    "download": AppProfile("download", "دانلود آپدیت", 0.05, 0.2, 40, 0.15, 30, 6.0, 45.0, 6.0, False, 1500.0),
    "web": AppProfile("web", "مرور وب", 0.7, 1.0, 90, 0.6, 60, 12.0, 15.0, 4.0, False, 600.0),
    "cloud_game": AppProfile("cloud_game", "کلاد گیمینگ/ریموت دسکتاپ", 1.2, 2.6, 150, 2.2, 240, 40.0, 10.0, 2.0, True, 85.0),
}


# ----------------------------------------------------------------------------- ورودی مسیر

@dataclass
class PathView:
    """دید تصمیم‌گیرنده از یک مسیر (خروجی لایهٔ تخمین/پیش‌بینی، نه حقیقت)."""
    id: str
    label: str = ""
    mu: float | None = None            # میانهٔ تخمینی
    p95: float | None = None
    p99: float | None = None
    jitter: float | None = None        # تغییر متوالی (شکنجهٔ جیتری)
    loss: float = 0.0
    p_fail: float = 0.0                # احتمال شکست/افت شدید در افق کوتاه
    p_fail_h30: float | None = None
    recency_ok: bool = True            # داده تازه است؟
    extra_cost: float = 0.0
    mu_sd: float = 0.0                 # عدم‌قطعیت تخمین سطح (ms)
    likely_down: bool = False          # >=2 consecutive misses = effectively down
    down_prob: float = 0.0            # هزینهٔ اضافی مسیر (تونل/سهمیه/CPU)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Decision:
    chosen: str
    reason: str
    expected_cost: float
    current: str | None = None
    runner_up: str | None = None
    gain_vs_current: float | None = None
    blocked_by: str | None = None
    blocked_gain: float | None = None
    costs: dict[str, float] = field(default_factory=dict)
    switched: bool = False
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        s = f"→ انتخاب: {self.chosen}  (هزینهٔ انتظاری {self.expected_cost:.1f})"
        if self.switched:
            s += f"  · سوئیچ از {self.current}"
        s += f"\n   دلیل: {self.reason}"
        if self.runner_up:
            s += f"\n   رقیب: {self.runner_up}"
        if self.blocked_by:
            s += f"\n   ⛔ سوئیچ سودمندتر ({self.blocked_gain:.1f} سود) توسط «{self.blocked_by}» مسدود شد"
        if self.costs:
            ranked = sorted(self.costs.items(), key=lambda kv: kv[1])[:4]
            s += "\n   هزینه‌ها: " + " | ".join(f"{k}={v:.1f}" for k, v in ranked)
        return s


# ----------------------------------------------------------------------------- هستهٔ تصمیم

class DecisionEngine:
    def __init__(self, profile: str = "gameplay", safety_margin: float = 0.10,
                 critical_window_ratio: float = 0.25, confidence_gate: float = 0.80,
                 payback_s: float = 30.0):
        self.profile = PROFILES[profile]
        self.set_profile(profile)
        self.safety_margin = safety_margin              # حداقل سود نسبی برای سوئیچ
        # در لحظهٔ حساس، آستانهٔ سود بالا می‌رود (ولی نه تا حد فلج‌شدن). عدد از بک‌تست آمد.
        self.critical_window_ratio = critical_window_ratio
        self.confidence_gate = confidence_gate          # حداقل اطمینان آماری برای سوئیچ
        self.payback_s = payback_s                      # افق جبران هزینهٔ سوئیچ (تیک = ثانیه)
        self.switch_log: list[float] = []
        self.current: str | None = None
        self.current_since: float = 0.0

    def set_profile(self, key: str) -> None:
        if key not in PROFILES:
            raise KeyError(f"پروفایل ناشناس: {key}")
        self.profile = PROFILES[key]

    # --- تابع هدف
    def cost(self, p: PathView, is_current: bool) -> float:
        w = self.profile
        mu = p.mu if p.mu is not None else 999.0
        p95 = p.p95 if p.p95 is not None else mu * 1.6
        jit = p.jitter or 0.0
        c = (w.alpha * mu + w.beta * p95 + w.gamma * p.loss + w.delta * jit
             + w.eta * p.p_fail + p.extra_cost)
        # A path that is effectively down costs the app a lost tick per tick
        c += p.down_prob * (w.gamma * 1.0 + w.eta)
        if not is_current:
            c += w.switch_cost
        return round(c, 3)

    def _switches_last_minute(self, now: float) -> int:
        self.switch_log = [t for t in self.switch_log if now - t < 60]
        return len(self.switch_log)

    def decide(self, candidates: list[PathView], critical_now: bool = False,
               now: float | None = None) -> Decision:
        now = time.time() if now is None else now
        cand = [c for c in candidates if c.recency_ok]
        if not cand:
            return Decision(self.current or "none", "هیچ مسیری دادهٔ تازه ندارد", 999.0, current=self.current)

        costs = {c.id: self.cost(c, is_current=(c.id == self.current)) for c in cand}
        ranked = sorted(costs.items(), key=lambda kv: kv[1])
        best_id, best_cost = ranked[0]
        runner = ranked[1][0] if len(ranked) > 1 else None

        if self.current is None:                     # اولین تصمیم
            self.current = best_id
            self.current_since = now
            return Decision(best_id, "انتخاب آغازین (کمترین هزینهٔ انتظاری)", best_cost,
                            current=None, runner_up=runner, costs=costs, switched=True, ts=now)

        cur_cost = costs.get(self.current)
        if cur_cost is None:                          # مسیر فعلی داده ندارد → مهاجرت اجباری
            self.switch_log.append(now)
            prev = self.current
            self.current, self.current_since = best_id, now
            return Decision(best_id, "مسیر فعلی دادهٔ تازه ندارد (احتمال قطع)", best_cost,
                            current=prev, runner_up=runner, costs=costs, switched=True, ts=now)

        gain = cur_cost - best_cost
        gain_ratio = gain / max(cur_cost, 1e-6)
        best = next(c for c in cand if c.id == best_id)
        cur = next(c for c in cand if c.id == self.current)

        # --- ۱) پایداری: حداقل زمان ماندن
        dwell = now - self.current_since
        # --- ۲) سقف سوئیچ
        n_sw = self._switches_last_minute(now)

        # --- دروازهٔ ایمنی در لحظهٔ حساس
        urgent = best.p_fail > 0.6 and best.p_fail + 0.15 < cur.p_fail   # شکست محتمل رقیب
        if critical_now and self.profile.critical_window and not urgent:
            need = self.critical_window_ratio            # = حداقل سود نسبی در لحظهٔ حساس
            if gain_ratio < need:
                return Decision(self.current,
                                "لحظهٔ حساس اپ: بدون شاهد قوی سوئیچ نمی‌کنیم (جلوگیری از پرش وسط مچ)",
                                cur_cost, current=self.current, runner_up=best_id, gain_vs_current=round(gain, 2),
                                blocked_by="critical_window", blocked_gain=round(gain, 2), costs=costs, ts=now)

        # --- تشخیص اضطرار: مسیر فعلی در حال مردن است یا سود سوئیچ بسیار بزرگ است
        # مسیری که ≥۱۵٪ بسته می‌اندازد برای گیمینگ عملاً مرده است (شاهد: بک‌تست سناریوی burst)
        # اضطرار فقط با «شاهد سخت»: قطعی محرز، تلفات بستهٔ واقعی، یا برتری خردکنندهٔ هزینه.
        # احتمال شکست ۳۵٪ یک «سیگنال هزینه» است، نه «مرگ مسیر» — گنجاندنش اینجا
        # باعث می‌شد روی نویز هم سوئیچ اضطراری بزند (شاهد: بک‌تست سناریوی flappy).
        emergency = (cur.likely_down or cur.loss >= 0.15 or gain_ratio >= 0.5)
        hard_cap = self.profile.max_switches_per_min * 3

        # --- دروازهٔ شاهد آماری: تا وقتی اختلاف دو مسیر از عدم‌قطعیت خودشان کوچک‌تر
        # است، سوئیچ نمی‌کنیم. این همان چیزی است که «دنبال نویز افتادن» را می‌کشد.
        se = math.sqrt(max(cur.mu_sd, 0.0) ** 2 + max(best.mu_sd, 0.0) ** 2)
        gain_ms = gain / max(self.profile.alpha, 1e-6)
        z = gain_ms / max(se, 1.0)
        conf = 0.5 * (1 + math.erf(z / math.sqrt(2)))
        if not emergency and conf < self.confidence_gate:
            return Decision(self.current,
                            f"شاهد آماری کافی نیست (اطمینان {conf:.0%} < {self.confidence_gate:.0%}) — "
                            f"اختلاف {gain_ms:.1f}ms در برابر عدم‌قطعیت ±{se:.1f}ms",
                            cur_cost, current=self.current, runner_up=best_id,
                            gain_vs_current=round(gain, 2), blocked_by="weak_evidence",
                            blocked_gain=round(gain, 2), costs=costs, ts=now)

        # --- دورهٔ بازگشت سرمایه: سوئیچ باید هزینه‌اش را در افق نگه‌داری جبران کند.
        # بدون این قید، تفاوت ۵ms با هزینهٔ سوئیچ ۵۴۰ (پارگی اتصال) «به‌صرفه» دیده می‌شد
        # و سیستم بی‌دلیل جلسهٔ کاربر را می‌شکست.
        if not emergency and gain < self.profile.switch_cost / self.payback_s:
            return Decision(self.current,
                            f"سوئیچ هزینه‌اش را جبران نمی‌کند (سود {gain:.1f} < "
                            f"{self.profile.switch_cost / self.payback_s:.1f} در افق {self.payback_s:.0f} تیک)",
                            cur_cost, current=self.current, runner_up=best_id,
                            gain_vs_current=round(gain, 2), blocked_by="payback",
                            blocked_gain=round(gain, 2), costs=costs, ts=now)

        if gain_ratio < self.safety_margin:
            return Decision(self.current, f"سود سوئیچ ناکافی ({gain_ratio:.0%} < {self.safety_margin:.0%})",
                            cur_cost, current=self.current, runner_up=best_id,
                            gain_vs_current=round(gain, 2), costs=costs, ts=now)

        unhealthy_cur = (cur.p95 is not None and cur.p95 > (cur.mu or 0) * 1.45) or cur.loss > 0.10
        if dwell < self.profile.min_dwell_s and not emergency and not unhealthy_cur:
            return Decision(self.current, f"حداقل زمان ماندن ({self.profile.min_dwell_s:.0f} ثانیه) پر نشده",
                            cur_cost, current=self.current, runner_up=best_id,
                            gain_vs_current=round(gain, 2), blocked_by="min_dwell",
                            blocked_gain=round(gain, 2), costs=costs, ts=now)

        if n_sw >= self.profile.max_switches_per_min and not emergency:
            return Decision(self.current, f"سقف سوئیچ در دقیقه ({n_sw:.0f}) پر شده — ضد‌فلاف",
                            cur_cost, current=self.current, runner_up=best_id,
                            gain_vs_current=round(gain, 2), blocked_by="switch_rate",
                            blocked_gain=round(gain, 2), costs=costs, ts=now)
        if n_sw >= hard_cap:  # سقف سخت، حتی در حالت اضطرار
            return Decision(self.current, f"سقف سخت اضطراری ({hard_cap:.0f} سوئیچ در دقیقه) — جلوگیری از چرخش بی‌پایان",
                            cur_cost, current=self.current, runner_up=best_id,
                            gain_vs_current=round(gain, 2), blocked_by="hard_cap",
                            blocked_gain=round(gain, 2), costs=costs, ts=now)

        prev = self.current
        self.current, self.current_since = best_id, now
        self.switch_log.append(now)
        why = f"سود خالص {gain:.1f} ({gain_ratio:.0%}) — هزینهٔ سوئیچ لحاظ شد"
        if emergency and dwell < self.profile.min_dwell_s:
            why = f"🚨 سوئیچ اضطراری: مسیر فعلی در خطر شکست (p_fail={cur.p_fail:.0%}) — محدودیت ماندن نادیده گرفته شد"
        return Decision(best_id, why,
                        best_cost, current=prev, runner_up=runner, gain_vs_current=round(gain, 2),
                        costs=costs, switched=True, ts=now)

    # --- ساخت PathView از خروجی تخمین/پیش‌بینی
    @staticmethod
    def build_view(snapshot: dict, p_fail: float, extra_cost: float = 0.0) -> PathView:
        return PathView(
            id=snapshot["id"], label=snapshot.get("label", ""),
            mu=snapshot.get("p50"), p95=snapshot.get("p95"), p99=snapshot.get("p99"),
            jitter=snapshot.get("delta") or snapshot.get("jitter"), loss=snapshot.get("loss") or 0.0,
            p_fail=p_fail, recency_ok=snapshot.get("n", 0) > 0, extra_cost=extra_cost,
            mu_sd=float(snapshot.get("mu_sd") or 0.0),
            likely_down=bool(snapshot.get("likely_down")), down_prob=float(snapshot.get("down_prob") or 0.0),
        )


# ----------------------------------------------------------------------------- خودآزمون

if __name__ == "__main__":
    print("=" * 74)
    print("NCF · خودآزمون موتور تصمیم")
    print("=" * 74)

    eng = DecisionEngine("gameplay")
    paths = [
        PathView("direct", "مستقیم", mu=40, p95=52, jitter=4, loss=0.00, p_fail=0.08),
        PathView("tr", "تونل ترکیه", mu=58, p95=70, jitter=3, loss=0.00, p_fail=0.05),
        PathView("eu", "تونل اروپا", mu=132, p95=165, jitter=9, loss=0.02, p_fail=0.20),
    ]

    print("\n۱) انتخاب آغازین (باید ارزان‌ترین را بگیرد):")
    d = eng.decide(paths, critical_now=False)
    print("  " + d.render().replace("\n", "\n  "))
    print(f"  → سیاست فعلی: {eng.current}")

    print("\n۲) افت شدید مسیر فعلی، وسط مچ (باید دروازهٔ ایمنی اجازهٔ سوئیچ بدهد):")
    for pv in paths:
        if pv.id == eng.current:
            pv.mu, pv.p95, pv.p99, pv.p_fail = 92, 140, 180, 0.78
        if pv.id == "tr":
            pv.p_fail = 0.06
    d = eng.decide(paths, critical_now=True)
    print("  " + d.render().replace("\n", "\n  "))
    print(f"  → سیاست جدید: {eng.current}  ({'✅ سوئیچ کرد' if d.switched else '⛔ سوئیچ نکرد'})")

    print("\n۳) افت کوچک مسیر فعلی، وسط مچ (باید جلوی پرش بی‌دلیل را بگیرد):")
    eng2 = DecisionEngine("gameplay")
    p1 = [PathView("direct", mu=44, p95=58, jitter=4, loss=0.0, p_fail=0.10),
          PathView("tr", mu=52, p95=66, jitter=3, loss=0.0, p_fail=0.06)]
    eng2.decide(p1, False)
    p1[0].mu, p1[0].p95 = 50, 68     # افت جزئی (سود کم)
    d = eng2.decide(p1, critical_now=True)
    print("  " + d.render().replace("\n", "\n  "))
    print("  → انتظار: چون سود کم است، وسط مچ سوئیچ نمی‌کند (margin/critical gate).")

    print("\n۴) پروفایل دانلود: پینگ کم‌اهمیت، افت بسته مهم:")
    eng3 = DecisionEngine("download")
    dl = [
        PathView("a", mu=70, p95=120, jitter=18, loss=0.22, p_fail=0.3),
        PathView("b", mu=140, p95=160, jitter=6, loss=0.002, p_fail=0.05),
    ]
    d = eng3.decide(dl)
    print("  " + d.render().replace("\n", "\n  "))
    print("  → انتظار: مسیر b با وجود پینگ بالاتر، انتخاب می‌شود چون افت بسته کم است.")
