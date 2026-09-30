#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCF · لایهٔ پیش‌بینی (Forecasting) + کالیبراسیون
=========================================================================
دو سؤال: «الان چه خبر است؟» و «۵ تا ۳۰ ثانیهٔ بعد چه می‌شود؟»

  KalmanRTT     → فیلتر کالمن یک‌بعدی با حالت [سطح، رانش]؛ پیش‌بینی با بازهٔ اطمینان
  p_exceed      → احتمال عبور از آستانه در افق h (پایهٔ «احتمال افت کیفیت»)
  calibrate     → سنجش صداقتِ احتمال‌ها: Brier score + جدول رلیابیلیتی

⚠️ اصل طراحی: عددی که به‌عنوان «۸۲٪ احتمال» می‌دهیم باید واقعاً ۸۲٪ باشد.
   اگر کالیبره نباشد، کل حلقهٔ تصمیم روی شن ساخته شده. پس تابع calibrate() بخشی
   از خود سیستم است، نه ابزار جانبی.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


def _phi(x: float) -> float:
    """تابع توزیع تجمعی نرمال استاندارد (بدون scipy)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class Forecast:
    horizon_s: float
    mean: float
    sd: float
    p50: float
    p90: float
    lo: float
    hi: float

    def to_dict(self) -> dict:
        return {"horizon_s": self.horizon_s, "mean": round(self.mean, 2), "sd": round(self.sd, 2),
                "p50": round(self.p50, 2), "p90": round(self.p90, 2),
                "lo": round(self.lo, 2), "hi": round(self.hi, 2)}


class KalmanRTT:
    """
    فیلتر کالمن با مدل رانش ثابت:  x = [level, drift]
        x_{t+1} = F x_t + w ,  F = [[1, dt], [0, 1]]
        z_t     = level + v

    q_level  : نویز فرایند سطح (چقدر انتظار داریم سطح خودسرانه بچرخد)
    q_drift  : نویز فرایند رانش (چقدر رانش می‌تواند تغییر کند)
    r_default: واریانس نویز اندازه‌گیری (اگر داده ندهیم، از داده تخمین زده می‌شود)
    """

    def __init__(self, q_level: float = 1.2, q_drift: float = 0.02, r_default: float = 6.0):
        self.q_level, self.q_drift, self.r = q_level, q_drift, r_default
        self.x = [None, 0.0]                      # [level, drift]
        self.P = [[25.0, 0.0], [0.0, 0.05]]
        self.n = 0
        self.innov_hist: list[float] = []
        self.log: list[tuple[float, float]] = []  # (t, level) برای گزارش

    @property
    def level(self) -> float | None:
        return self.x[0]

    @property
    def level_sd(self) -> float:
        """انحراف معیار تخمین سطح (√P₀₀) — برای ساختن دنبالهٔ پیش‌بینی‌شده."""
        return math.sqrt(max(self.P[0][0], 1e-9))

    @property
    def drift(self) -> float:
        return self.x[1] or 0.0

    def predict(self, dt: float = 1.0) -> None:
        if self.x[0] is None:
            return
        lv, dr = self.x
        self.x = [lv + dr * dt, dr]
        # P = F P Fᵗ + Q
        p00, p01, p10, p11 = self.P[0][0], self.P[0][1], self.P[1][0], self.P[1][1]
        self.P = [
            [p00 + dt * (p01 + p10) + dt * dt * p11 + self.q_level * dt, p01 + dt * p11],
            [p10 + dt * p11, p11 + self.q_drift * dt],
        ]

    def update(self, z: float, r: float | None = None) -> None:
        r = self.r if r is None else max(1e-3, r)
        if self.x[0] is None:
            self.x = [z, 0.0]
            self.P = [[r, 0.0], [0.0, 0.05]]
            self.n = 1
            self.log.append((self.n, z))
            return
        self.predict(1.0)
        y = z - self.x[0]
        S = self.P[0][0] + r
        k0, k1 = self.P[0][0] / S, self.P[1][0] / S
        self.x = [self.x[0] + k0 * y, self.x[1] + k1 * y]
        p00, p01, p10, p11 = self.P[0][0], self.P[0][1], self.P[1][0], self.P[1][1]
        self.P = [
            [(1 - k0) * p00, (1 - k0) * p01],
            [p10 - k1 * p00, p11 - k1 * p01],
        ]
        self.n += 1
        self.innov_hist.append(y)
        if len(self.innov_hist) > 60:
            self.innov_hist.pop(0)
        # نویز اندازه‌گیری را از نوآوری‌ها بازتخمین بزن (آداپتیو)
        if len(self.innov_hist) >= 10:
            self.r = max(0.5, min(400.0, 0.7 * self.r + 0.3 * statistics.fmean([i * i for i in self.innov_hist[-15:]])))
        self.log.append((self.n, self.x[0]))

    def forecast(self, horizon_s: float) -> Forecast | None:
        if self.x[0] is None:
            return None
        lv, dr = self.x
        mean = lv + dr * horizon_s
        var = self.P[0][0] + 2 * horizon_s * self.P[0][1] + horizon_s * horizon_s * self.P[1][1]
        sd = math.sqrt(max(var, 1e-6))
        return Forecast(horizon_s, mean, sd,
                        p50=mean,
                        p90=mean + 1.2816 * sd,
                        lo=mean - 1.96 * sd,
                        hi=mean + 1.96 * sd)

    def p_exceed(self, threshold: float, horizon_s: float) -> float:
        """احتمال اینکه RTT در افق h از آستانه بگذرد."""
        f = self.forecast(horizon_s)
        if not f or f.sd <= 0:
            return 0.0
        return round(min(0.999, max(0.001, 1 - _phi((threshold - f.mean) / f.sd))), 4)


def degradation_probability(state, threshold: float | None = None, horizon_s: float = 10.0) -> float:
    """
    احتمال «افت کیفیت» برای یک PathState: ترکیب دو منبع
      ۱) کالمن روی RTT (روند + عدم‌قطعیت)
      ۲) نرخ از دست رفتن نمایی (loss)
    آستانهٔ پیش‌فرض = ۱.۴ برابر بهترین P50 تاریخی همان مسیر.
    """
    snap = state.window.summary()
    base = state.floor_p50 or snap.get("p50") or None
    if base is None:
        return 0.5
    thr = threshold if threshold is not None else base * 1.4 + 5.0
    k = getattr(state, "_kalman", None)
    p_rtt = k.p_exceed(thr, horizon_s) if k else 0.0
    p_loss = min(1.0, (state.loss_ewma.mean or 0.0) * 3.0)
    p = 1 - (1 - p_rtt) * (1 - p_loss)
    return round(min(0.99, max(0.01, p)), 3)


class PathForecaster:
    """نگه‌دارندهٔ فیلتر کالمن برای هر مسیر + تولید پیش‌بینی‌های افق‌دار."""

    def __init__(self, horizons: tuple[float, ...] = (5.0, 15.0, 30.0)):
        self.horizons = horizons
        self.filters: dict[str, KalmanRTT] = {}

    def update(self, pid: str, rtt: float | None) -> None:
        k = self.filters.setdefault(pid, KalmanRTT())
        if rtt is not None:
            k.update(rtt)
            if not hasattr(k, "_path"):
                k._path = pid

    def forecast_path(self, pid: str) -> dict:
        k = self.filters.get(pid)
        if not k:
            return {}
        return {f"{int(h)}s": k.forecast(h).to_dict() for h in self.horizons if k.forecast(h)}

    def p_deg(self, pid: str, horizon_s: float = 10.0, threshold: float | None = None) -> float:
        k = self.filters.get(pid)
        if not k or k.level is None:
            return 0.5
        thr = threshold if threshold is not None else (k.level * 1.4 + 5.0)
        return k.p_exceed(thr, horizon_s)


# ----------------------------------------------------------------------------- کالیبراسیون

class ProbabilityCalibrator:
    """
    بازکالیبراسیون آنلاین احتمال: اگر سیستم گفت «۸۰٪» ولی در واقعیت ۶۰٪ رخ داد،
    همان‌جا اصلاح می‌شود. روش: جدول رلیابیلیتی + پلاس‌شدن با نرخ تجربی همان بازه
    (shrinkage بر اساس تعداد نمونه‌های همان بازه). مثل یک isotonic regression آنلاین.

    ⚠️ این بخش اختیاری نیست: بدون آن، «۸۲٪ احتمال» فقط یک عدد تزئینی است.
    """

    def __init__(self, bins: int = 5, min_n: int = 12, max_weight: float = 0.85):
        self.bins = bins
        self.min_n = min_n
        self.max_weight = max_weight
        self.count = [0] * bins          # تعداد نمونه‌ها
        self.hits = [0] * bins           # تعداد رخدادها
        self.corrections: list[float] = []

    def _bin(self, p: float) -> int:
        return min(self.bins - 1, max(0, int(p * self.bins)))

    def _rate(self, i: int) -> float | None:
        if self.count[i] < max(3, self.min_n // 3):
            return None
        # هموارسازی لاجیستیک برای پایداری
        r = (self.hits[i] + 0.5) / (self.count[i] + 1.0)
        return r

    def calibrate(self, p: float) -> float:
        i = self._bin(p)
        r = self._rate(i)
        if r is None:
            return p
        w = min(self.max_weight, self.count[i] / max(self.min_n, 1))
        out = (1 - w) * p + w * r
        self.corrections.append(round(out - p, 4))
        return round(min(0.99, max(0.01, out)), 4)

    def observe(self, p_raw: float, outcome: int) -> None:
        i = self._bin(p_raw)
        self.count[i] += 1
        self.hits[i] += outcome

    def report(self) -> dict:
        rows = []
        for i in range(self.bins):
            if self.count[i]:
                rows.append({"bin": f"{int(i*100/self.bins)}–{int((i+1)*100/self.bins)}%",
                             "n": self.count[i], "observed": round(self.hits[i] / self.count[i], 3)})
        return {"bins": rows, "mean_shift": round(sum(self.corrections) / len(self.corrections), 4)
                if self.corrections else None}


def brier_score(preds: list[float], outcomes: list[int]) -> float:
    """امتیاز بریر: هرچه کمتر بهتر. ۰ = کامل، ۰.۲۵ = بی‌فایده."""
    if not preds:
        return float("nan")
    return round(sum((p - o) ** 2 for p, o in zip(preds, outcomes)) / len(preds), 4)


def reliability_bins(preds: list[float], outcomes: list[int], bins: int = 5) -> list[dict]:
    """جدول رلیابیلیتی: آیا «۸۰٪» واقعاً ۸۰٪ از اوقات رخ داده؟"""
    out = []
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        sel = [(p, o) for p, o in zip(preds, outcomes) if lo <= p < hi or (i == bins - 1 and p == 1.0)]
        if not sel:
            continue
        out.append({
            "bin": f"{int(lo*100)}–{int(hi*100)}%",
            "n": len(sel),
            "predicted": round(statistics.fmean([p for p, _ in sel]), 3),
            "observed": round(statistics.fmean([o for _, o in sel]), 3),
        })
    return out


def calibration_report(preds: list[float], outcomes: list[int]) -> dict:
    bs = brier_score(preds, outcomes)
    base = statistics.fmean(outcomes) if outcomes else None
    base_rate_brier = round(statistics.fmean([(base - o) ** 2 for o in outcomes]), 4) if outcomes else None
    skill = None
    if bs is not None and base_rate_brier:  # Brier Skill Score نسبت به «همیشه میانگین»
        skill = round(1 - bs / base_rate_brier, 3)
    errs = [abs(p - o) for p, o in zip(preds, outcomes)]
    return {
        "n": len(preds), "brier": bs, "baseline_brier": base_rate_brier, "skill": skill,
        "bins": reliability_bins(preds, outcomes),
        "mean_abs_error": round(statistics.fmean(errs), 4) if errs else None,
        "overconfident": bool(errs and statistics.fmean(preds) > statistics.fmean(outcomes) + 0.1),
    }


# ----------------------------------------------------------------------------- خودآزمون

if __name__ == "__main__":
    import random
    random.seed(7)
    print("=" * 74)
    print("NCF · خودآزمون پیش‌بینی و کالیبراسیون (دادهٔ مصنوعی)")
    print("=" * 74)

    # فرایند AR(1) + پرش رژیم: شبیه RTT یک مسیر در دنیای واقعی
    level, drift, samples = 40.0, 0.0, []
    for t in range(1200):
        if random.random() < 0.004:                 # رویداد ازدحام
            drift += random.uniform(1.5, 4.0)
        if random.random() < 0.01:
            drift *= 0.5
        drift = max(-1.2, min(3.0, drift))
        level = max(12.0, level + drift + random.gauss(0, 3.2))
        samples.append(level)

    k = KalmanRTT()
    preds, outcomes = [], []
    errors = []
    for t, z in enumerate(samples):
        if k.level is not None and t > 30:
            thr = 60.0
            p = k.p_exceed(thr, 5.0)
            future = samples[min(t + 5, len(samples) - 1)]
            preds.append(p)
            outcomes.append(1 if future > thr else 0)
            f = k.forecast(5.0)
            errors.append(abs(f.mean - future))
        k.update(z)

    rep = calibration_report(preds, outcomes)
    print(f"\nنمونه‌ها: {rep['n']}")
    print(f"خطای مطلق میانگین پیش‌بینی ۵ ثانیه بعد: {round(statistics.fmean(errors), 2)} ms")
    print(f"Brier: {rep['brier']}  (مبنا «همیشه میانگین»: {rep['baseline_brier']})")
    print(f"مهارت (Skill): {rep['skill']}   ← هرچه نزدیک‌تر به ۱ بهتر")
    print("\nجدول رلیابیلیتی (پیش‌بینی‌شده در برابر مشاهده‌شده):")
    print(f"  {'بازه':<10} {'تعداد':>6} {'پیش‌بینی':>10} {'واقعیت':>9}")
    for b in rep["bins"]:
        print(f"  {b['bin']:<10} {b['n']:>6} {b['predicted']:>10} {b['observed']:>9}")
    print("\nتفسیر: اگر «پیش‌بینی» و «واقعیت» به هم نزدیک باشند، احتمال‌های سیستم قابل اعتمادند.")

    # --- همان پیش‌بینی‌ها، این بار از فیلتر کالیبراتور آنلاین عبور می‌کنند
    cal = ProbabilityCalibrator()
    cal_preds = []
    for p_raw, y in zip(preds, outcomes):
        cal_preds.append(cal.calibrate(p_raw))
        cal.observe(p_raw, y)
    rep2 = calibration_report(cal_preds, outcomes)
    print("\nپس از کالیبراسیون آنلاین (همان داده):")
    print(f"  Brier: {rep['brier']} → {rep2['brier']}   |   "
          f"مهارت: {rep['skill']} → {rep2['skill']}")
    for b in rep2["bins"]:
        print(f"  {b['bin']:<10} {b['n']:>6} {b['predicted']:>10} {b['observed']:>9}")
    print("\nتفسیر: اگر «پیش‌بینی» و «واقعیت» به هم نزدیک باشند، احتمال‌های سیستم قابل اعتمادند.")
    print("قاعدهٔ محصول: تا کالیبره نشود، هیچ عدد احتمالی به کاربر نشان داده نمی‌شود.")
