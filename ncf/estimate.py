#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCF · لایهٔ تخمین وضعیت (State Estimator)
=========================================================================
وضعیت واقعی شبکه هیچ‌وقت مستقیم دیده نمی‌شود؛ فقط مشاهدات داریم. این لایه
از مشاهدات، «توزیع» می‌سازد (نه یک عدد) و تغییر رژیم را تشخیص می‌دهد:

  RttWindow      → کوانتایل‌ها (P50/P90/P95/P99)، jitter (MAD)، نرخ از دست رفتن
  Ewma           → میانگین/واریانس نمایی (پیرشدن داده‌های قدیمی)
  CusumDetector  → تشخیص نقطهٔ تغییر (onset افت کیفیت) با آمارهٔ استانداردشده
  RegimeTracker  → برچسب رژیم: stable / drifting / degraded / pathological
  PathState      → همهٔ موارد بالا برای یک مسیر + تاریخچهٔ تغییرات

نکتهٔ طراحی: توزیع‌محوری، نه میانگین‌محوری — برای بازی P95/P99 مهم‌تر از P50 است.
"""

from __future__ import annotations

import math
import statistics
import time
from collections import deque
from dataclasses import dataclass, field, asdict


# ----------------------------------------------------------------------------- پنجرهٔ نمونه‌ها

class RttWindow:
    """پنجرهٔ لغزان RTT با کوانتایل‌ها و آماره‌های مقاوم."""

    def __init__(self, size: int = 120, horizon_s: float | None = 300.0):
        self.size = size
        self.horizon_s = horizon_s
        self.samples: deque[tuple[float, float | None]] = deque(maxlen=size)

    def add(self, rtt: float | None, ts: float | None = None) -> None:
        ts = time.time() if ts is None else ts
        self.samples.append((ts, rtt))
        if self.horizon_s:
            cutoff = ts - self.horizon_s
            while self.samples and self.samples[0][0] < cutoff:
                self.samples.popleft()

    # --- آماره‌ها
    def values(self) -> list[float]:
        return [v for _, v in self.samples if v is not None]

    def n(self) -> int:
        return len(self.samples)

    def loss_rate(self) -> float | None:
        if not self.samples:
            return None
        lost = sum(1 for _, v in self.samples if v is None)
        return round(lost / len(self.samples), 4)

    def quantile(self, q: float) -> float | None:
        vals = sorted(self.values())
        if not vals:
            return None
        if len(vals) == 1:
            return round(vals[0], 2)
        pos = q * (len(vals) - 1)
        lo, hi = math.floor(pos), math.ceil(pos)
        if lo == hi:
            return round(vals[lo], 2)
        return round(vals[lo] + (vals[hi] - vals[lo]) * (pos - lo), 2)

    def median(self) -> float | None:
        return self.quantile(0.5)

    def jitter_mad(self) -> float | None:
        """میانگین قدرمطلق انحراف از میانه — معیار مقاوم نوسان."""
        vals = self.values()
        if len(vals) < 2:
            return None
        med = statistics.median(vals)
        return round(statistics.mean(abs(v - med) for v in vals), 2)

    def consecutive_delta(self) -> float | None:
        """میانگین |اختلاف دو نمونهٔ متوالی| — «شکنجهٔ» جیتری که اپ حس می‌کند."""
        vals = self.values()
        if len(vals) < 2:
            return None
        return round(statistics.mean(abs(b - a) for a, b in zip(vals, vals[1:])), 2)

    def summary(self) -> dict:
        return {
            "n": self.n(),
            "loss": self.loss_rate(),
            "p50": self.quantile(0.5),
            "p90": self.quantile(0.9),
            "p95": self.quantile(0.95),
            "p99": self.quantile(0.99),
            "jitter": self.jitter_mad(),
            "delta": self.consecutive_delta(),
            "min": min(self.values()) if self.values() else None,
            "max": max(self.values()) if self.values() else None,
        }


class Ewma:
    """میانگین و واریانس نمایی (نیمه‌عمر مشخص) — برای تعقیب سریع روند."""

    def __init__(self, halflife: float = 10.0):
        self.halflife = halflife
        self._alpha = 1 - math.exp(-math.log(2) / halflife)
        self.mean: float | None = None
        self.var: float | None = None
        self.n = 0

    def add(self, x: float) -> None:
        self.n += 1
        if self.mean is None:
            self.mean, self.var = x, 0.0
            return
        delta = x - self.mean
        self.mean += self._alpha * delta
        self.var = (1 - self._alpha) * (self.var + self._alpha * delta * delta)

    @property
    def sd(self) -> float:
        return math.sqrt(max(self.var or 0.0, 0.0))


# ----------------------------------------------------------------------------- تشخیص نقطهٔ تغییر

@dataclass
class ChangePoint:
    ts: float
    kind: str            # "up" | "down"
    magnitude_ms: float
    baseline_ms: float
    z: float


class CusumDetector:
    """
    تشخیص نقطهٔ تغییر با CUSUM روی دادهٔ استانداردشده.
    هدف: «کِی افت شروع شد؟» — ورودیِ موتور علت‌یابی و پیش‌بینی.

    k = آستانهٔ رانش (بر حسب سیگما)، h = آستانهٔ هشدار.
    """

    def __init__(self, k: float = 0.75, h: float = 5.0, warmup: int = 8, min_sigma: float = 1.5):
        self.k, self.h, self.warmup, self.min_sigma = k, h, warmup, min_sigma
        self.baseline: list[float] = []
        self.sp = 0.0
        self.sm = 0.0
        self.changes: list[ChangePoint] = []
        self.last_change_ts = 0.0

    def _sigma(self) -> float:
        if len(self.baseline) < 3:
            return self.min_sigma
        return max(self.min_sigma, statistics.pstdev(self.baseline))

    def add(self, x: float | None, ts: float | None = None) -> ChangePoint | None:
        ts = time.time() if ts is None else ts
        if x is None:
            # از دست رفتن نمونه خودش نشانه است، ولی CUSUM را با آن آلوده نمی‌کنیم
            return None
        if len(self.baseline) < self.warmup:
            self.baseline.append(x)
            return None

        mu = statistics.fmean(self.baseline)
        sigma = self._sigma()
        z = (x - mu) / sigma
        self.sp = max(0.0, self.sp + z - self.k)
        self.sm = max(0.0, self.sm - z - self.k)

        cp = None
        if self.sp > self.h and self.sp >= self.sm:
            cp = ChangePoint(ts, "up", round(sigma * self.sp, 2), round(mu, 2), round(z, 2))
            self.sp = self.sm = 0.0
        elif self.sm > self.h:
            cp = ChangePoint(ts, "down", -round(sigma * self.sm, 2), round(mu, 2), round(z, 2))
            self.sp = self.sm = 0.0

        if cp:
            self.changes.append(cp)
            self.last_change_ts = ts
            # پس از تغییر، مبنای جدید از داده‌های تازه ساخته می‌شود (adaptation)
            self.baseline = self.baseline[-max(3, self.warmup // 2):] + [x]
        else:
            # پیرشدن آرام مبنا تا سیستم با شرایط جدید هم‌گام شود
            self.baseline.append(x)
            if len(self.baseline) > 40:
                self.baseline = self.baseline[-40:]
        return cp

    def recent_change(self, within_s: float = 30.0, now: float | None = None) -> ChangePoint | None:
        now = time.time() if now is None else now
        if self.changes and (now - self.changes[-1].ts) <= within_s:
            return self.changes[-1]
        return None


# ----------------------------------------------------------------------------- رژیم

@dataclass
class Regime:
    label: str          # stable | drifting | degraded | pathological | unknown
    reason: str
    severity: float     # 0..1
    color: str


def classify_regime(win: RttWindow, ewma: Ewma, cp: CusumDetector,
                    floor_p50: float | None = None) -> Regime:
    """
    برچسب رژیم از ترکیب توزیع + نرخ از دست رفتن + نقطهٔ تغییر.
    floor_p50 = بهترین P50 مشاهده‌شدهٔ تاریخی این مسیر (مبنای نسبی، نه مطلق).
    """
    s = win.summary()
    if s["n"] == 0:
        return Regime("unknown", "بدون داده", 0.0, "muted")
    loss = s["loss"] or 0.0
    p50, p95 = s["p50"], s["p95"]
    jitter = s["jitter"] or 0.0

    base = floor_p50 or p50 or 1.0
    ratio = (p50 / base) if p50 else 1.0
    tail_ratio = (p95 / base) if p95 else 1.0

    if loss >= 0.25 or tail_ratio >= 2.5 or loss >= 0.10 and jitter * 2 > base:
        return Regime("pathological", f"افت شدید: loss={loss:.0%}, p95={p95}",
                      min(1.0, 0.6 + loss), "dead")
    if loss >= 0.06 or ratio >= 1.5 or tail_ratio >= 1.8:
        cp_recent = cp.recent_change(within_s=60)
        why = "افت پایدار" if ratio >= 1.5 else "دنبالهٔ بلند (لگ)"
        if cp_recent and cp_recent.kind == "up":
            why += f" · شروع تغییر {int(time.time() - cp_recent.ts)} ثانیه پیش"
        return Regime("degraded", why, min(0.95, 0.4 + ratio / 3), "meh")
    if tail_ratio >= 1.3 or jitter > 0.25 * base:
        return Regime("drifting", "نوسان ملایم/روند نامطمئن", 0.35, "ok")
    return Regime("stable", f"پایدار (p50={p50}, jitter={jitter})", 0.05, "great")


# ----------------------------------------------------------------------------- وضعیت یک مسیر

@dataclass
class PathState:
    id: str
    label: str
    window: RttWindow = field(default_factory=lambda: RttWindow())
    # پنجرهٔ سریع: «وضعیت الان» را از تاریخچه جدا می‌کند.
    # درسِ بک‌تست: میانهٔ پنجرهٔ بلند، رویدادهای قدیمی را با وضعیت جاری قاطی می‌کرد و
    # تخمینگر مسیر سالم را خراب و مسیر خراب را سالم می‌دید.
    fast: RttWindow = field(default_factory=lambda: RttWindow(size=20, horizon_s=None))
    ewma: Ewma = field(default_factory=lambda: Ewma(halflife=12))
    loss_ewma: Ewma = field(default_factory=lambda: Ewma(halflife=20))
    cusum: CusumDetector = field(default_factory=CusumDetector)
    floor_p50: float | None = None      # بهترین P50 تاریخی
    regime: Regime | None = None
    last_update: float = 0.0
    miss_streak: int = 0          # نمونه‌های از‌دست‌رفتهٔ متوالی (= تشخیص سریع قطعی)
    fast_ewma: Ewma = field(default_factory=lambda: Ewma(halflife=3.0))
    n_updates: int = 0
    history: deque = field(default_factory=lambda: deque(maxlen=90))

    def update(self, rtt: float | None, ts: float | None = None) -> ChangePoint | None:
        ts = time.time() if ts is None else ts
        self.window.add(rtt, ts)
        self.fast.add(rtt, ts)
        self.last_update = ts
        self.n_updates += 1
        if rtt is not None:
            self.ewma.add(rtt)
            self.fast_ewma.add(rtt)
            self.loss_ewma.add(0.0)
            self.miss_streak = 0
            cp = self.cusum.add(rtt, ts)
        else:
            self.loss_ewma.add(1.0)
            self.miss_streak += 1     # دو تا پشت‌سرهم = «عملاً قطع» (مانند dead-peer detection)
            cp = None
        p50 = self.fast.quantile(0.5) or self.window.quantile(0.5)
        if p50 is not None:
            self.floor_p50 = p50 if self.floor_p50 is None else min(self.floor_p50, p50)
        self.regime = classify_regime(self.fast if self.fast.n() >= 3 else self.window,
                                      self.ewma, self.cusum, self.floor_p50)
        self.history.append((ts, p50))
        return cp

    def decision_view(self, kalman=None, p_fail: float = 0.0, horizon_s: float = 0.0) -> dict:
        """
        نمای تصمیم: ترکیب فیلتر سریع (وضعیت الان) + پنجره (رفتار دنباله) + کالیبراسیون.
        قاعده‌ها:
          • mu از فیلتر کالمن (اگر باشد) وگرنه میانهٔ پنجرهٔ سریع  → واکنش سریع بدون نویز
          • p95 = بیشینهٔ (mu + ۱.۲۸σ) و p95 پنجرهٔ سریع            → دنبالهٔ واقعی
          • loss از EWMA (نه پنجرهٔ بلند)                          → وضعیت جاری از دست رفتن
          • اگر جریان نمونه قطع شده باشد، mu جریمهٔ «نبودن» می‌خورد (انتظار هزینهٔ قطعی)
        """
        f = self.fast.summary()
        w = self.window.summary()
        # تصمیم روی «افزونهٔ پیش‌بینی‌شده» گرفته می‌شود، نه آخرین نمونه.
        # درسِ بک‌تست ۵: اگر دامنهٔ لحظه‌ای مبنای تصمیم باشد، نویز گذرا با استهلاک واقعی
        # قاطی می‌شود و سیستم روی «اسپایک» پرش می‌کند. وضعیت رانشِ کالمن، استهلاک
        # پایدار را خودش می‌گیرد؛ نوسانِ گذرا برمی‌گردد.
        mu = None
        sd = None
        if kalman is not None and getattr(kalman, "level", None) is not None:
            fcast = kalman.forecast(horizon_s) if horizon_s > 0 else None
            if fcast is not None:
                mu, sd = fcast.mean, fcast.sd
            else:
                mu, sd = kalman.level, kalman.level_sd
        if mu is None:
            mu = f["p50"] or w["p50"]
        loss = self.loss_ewma.mean or 0.0
        if mu is not None and loss > 0.05:
            mu = mu * (1.0 + 1.0 * loss)          # تلفات واقعی = تأخیر انتظاری بیشتر (بدون جریمهٔ تکراری)
        p95 = None
        if mu is not None:
            p95 = mu + 1.28 * (sd or 0.0)
        if not horizon_s and f["p95"]:
            # فقط وقتی پیش‌بینی در دست نیست، دنبالهٔ پنجرهٔ سریع جایگزین می‌شود
            p95 = max(p95 or 0.0, f["p95"])
        # اگر جریان نمونه قطع شده باشد، «عملاً قطع» فرض می‌شود (تصمیم‌گیری ایمن)
        likely_down = self.miss_streak >= 2
        down_prob = min(0.97, 0.45 * (self.miss_streak - 1)) if likely_down else 0.0
        if likely_down:
            mu = (mu or (self.floor_p50 or 60.0)) * (1.0 + 2.0 * down_prob)
        mu_sd = sd if sd is not None else 0.0
        return {
            "id": self.id, "label": self.label,
            "mu_sd": round(mu_sd, 3),
            "miss_streak": self.miss_streak, "likely_down": likely_down, "down_prob": round(down_prob, 3),
            "p50": round(mu, 2) if mu is not None else None,
            "p95": round(p95, 2) if p95 is not None else None,
            "p99": f["p99"] or w["p99"],
            "delta": f["delta"] if f["delta"] is not None else w["delta"],
            "jitter": f["jitter"] if f["jitter"] is not None else w["jitter"],
            "loss": round(loss, 4),
            "loss_window": w["loss"],
            "n": f["n"],
            "n_window": w["n"],
            "floor_p50": self.floor_p50,
            "regime": asdict(self.regime) if self.regime else None,
            "p_fail": p_fail,
        }

    def snapshot(self) -> dict:
        s = self.window.summary()
        return {
            "id": self.id, "label": self.label,
            **s,
            "p50_fast": self.fast.quantile(0.5),
            "p95_fast": self.fast.quantile(0.95),
            "delta_fast": self.fast.consecutive_delta(),
            "ewma": round(self.ewma.mean, 2) if self.ewma.mean is not None else None,
            "ewma_sd": round(self.ewma.sd, 2),
            "loss_ewma": round(self.loss_ewma.mean or 0.0, 3),
            "floor_p50": self.floor_p50,
            "regime": asdict(self.regime) if self.regime else None,
            "changes": [asdict(c) for c in self.cusum.changes[-3:]],
            "n_updates": self.n_updates,
        }


# ----------------------------------------------------------------------------- مجموعهٔ مسیرها

class StateEstimator:
    """نگه‌دارندهٔ وضعیت تخمینی همهٔ مسیرهای نامزد."""

    def __init__(self):
        self.paths: dict[str, PathState] = {}
        self.events: deque = deque(maxlen=200)

    def register(self, pid: str, label: str) -> PathState:
        if pid not in self.paths:
            self.paths[pid] = PathState(pid, label)
        return self.paths[pid]

    def update(self, pid: str, rtt: float | None, ts: float | None = None) -> ChangePoint | None:
        st = self.paths.get(pid)
        if not st:
            return None
        cp = st.update(rtt, ts)
        if cp:
            self.events.append({"ts": cp.ts, "path": pid, "kind": cp.kind, "mag": cp.magnitude_ms})
        return cp

    def snapshot(self) -> list[dict]:
        out = []
        for st in self.paths.values():
            s = st.snapshot()
            if s["n"]:
                out.append(s)
        return sorted(out, key=lambda x: (x["p50"] is None, x["p50"] or 9e9))

    def best_by(self, key: str = "p50") -> dict | None:
        cand = [s for s in self.snapshot() if s.get(key) is not None]
        return min(cand, key=lambda s: s[key]) if cand else None
