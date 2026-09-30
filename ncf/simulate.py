#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCF · شبیه‌ساز شبکه + بک‌تست سیاست‌ها
=========================================================================
بدون شبیه‌ساز، هیچ ادعایی قابل‌سنجش نیست. اینجا یک شبکهٔ زمان‌متغیر می‌سازیم
(ازدحام، پرش مسیر، قطعی تونل، لرزش) و ۵ سیاست را روی **همان** دنبالهٔ رویدادها
مقایسه می‌کنیم:

   random        → کف مطلق
   always_direct → «هیچ کاری نکن»
   instant_best  → کم‌پینگ‌ترین همین لحظه (سیاستی که اکثر ابزارها دارند)
   ewma_best     → EWMA + هیسترزیس (سیاست کلاسیک خوب)
   ncf           → حلقهٔ کامل: توزیع + پیش‌بینی + تابع هدف + هزینهٔ سوئیچ + دروازهٔ ایمنی
   oracle        → سقف نظری (حقیقت را می‌بیند) برای محاسبهٔ regret

نکات انصاف آزمایش:
  • همهٔ سیاست‌ها اطلاعات یکسانی دارند: در هر تیک، یک نمونهٔ نویزی از همهٔ مسیرها.
  • ساختن مدل، کاملاً درون سیاست است (NCF توزیع/کالمن دارد، بقیه ندارند).
  • هزینهٔ هر تیک روی «حقیقت» محاسبه می‌شود و همه یک تابع هزینه دارند.
  • نتیجه، میانگین چند seed است، نه یک اجرای خوش‌شانس.
"""

from __future__ import annotations

import math
import os
import random
import statistics
import time
from dataclasses import dataclass, field, replace
from types import SimpleNamespace

from .estimate import StateEstimator, RttWindow
from .forecast import KalmanRTT, ProbabilityCalibrator
from .decide import DecisionEngine, PathView, PROFILES


# ----------------------------------------------------------------------------- مدل شبکه

@dataclass
class SimPath:
    id: str
    base_rtt: float
    tunnel: bool = False
    # حالت نهفته
    cong: float = 0.0            # آفست ازدحام (فرایند بازگشت به میانگین)
    fail_until: int = -1
    loss_base: float = 0.005
    drift: float = 0.0

    def rtt_true(self, t: int) -> float:
        if t <= self.fail_until:
            return 600.0
        return max(8.0, self.base_rtt + self.cong + self.drift)

    def loss_true(self, t: int) -> float:
        if t <= self.fail_until:
            return 1.0
        return min(0.95, self.loss_base + max(0.0, self.cong) / 400.0)

    def failed(self, t: int) -> bool:
        return t <= self.fail_until


class NetSim:
    """شبیه‌ساز شبکهٔ زمان‌متغیر با رویدادهای ازدحام/قطع/تغییر مسیر."""

    def __init__(self, scenario: str, seed: int, ticks: int = 900, noise_sigma: float = 3.0):
        self.scenario = scenario
        self.rng = random.Random(seed * 7919 + 11)      # پویایی نهفتهٔ شبکه
        self.rng_app = random.Random(seed * 104729 + 7)  # زمان‌بندی اپلیکیشن
        self.ticks = ticks
        self.noise_sigma = noise_sigma
        self.paths = self._make_paths()
        self.rtt: dict[str, float | None] = {}      # نمونهٔ محقق‌شدهٔ همین تیک (همه می‌بینند)
        self.truth_now: dict[str, dict] = {}
        self._critical = self._make_critical_schedule()

    def _make_critical_schedule(self) -> dict[int, bool]:
        """زمان‌بندی «لحظهٔ حساس اپ» — از سمت اپ، مستقل از سیاست."""
        r, out, t = self.rng_app, {}, 0
        while t < self.ticks:
            critical = r.random() < 0.5
            dur = r.randint(20, 90) if critical else r.randint(10, 40)
            for k in range(t, min(self.ticks, t + dur)):
                out[k] = critical
            t += dur
        return out

    def app_critical(self, t: int) -> bool:
        return bool(self._critical.get(t, False))

    def _make_paths(self) -> list[SimPath]:
        r = self.rng
        if self.scenario == "stable":
            return [SimPath("direct", 42), SimPath("tr", 55, tunnel=True), SimPath("eu", 128, tunnel=True)]
        if self.scenario == "congestion":
            return [SimPath("direct", 44), SimPath("tr", 52, tunnel=True), SimPath("eu", 130, tunnel=True)]
        if self.scenario == "burst":
            return [SimPath("direct", 45), SimPath("tr", 50, tunnel=True), SimPath("eu", 132, tunnel=True)]
        if self.scenario == "flappy":
            return [SimPath("direct", 46 + r.uniform(-6, 6)), SimPath("tr", 52 + r.uniform(-6, 6)),
                    SimPath("eu", 120 + r.uniform(-10, 10), tunnel=True)]
        return [SimPath("direct", 45), SimPath("tr", 55, tunnel=True)]

    def step(self, t: int) -> None:
        r = self.rng
        for p in self.paths:
            # فرایند بازگشت به میانگین برای ازدحام
            p.cong *= 0.86
            p.cong += r.gauss(0, 1.4)
            p.cong = max(-6.0, min(220.0, p.cong))

            if self.scenario == "stable":
                if r.random() < 0.002:
                    p.cong += r.uniform(2, 8)
            elif self.scenario == "congestion":
                if r.random() < 0.05:
                    p.cong += r.uniform(8, 55)
                if r.random() < 0.006:                     # تغییر مسیر دائمی
                    p.drift += r.choice([-1, 1]) * r.uniform(8, 35)
            elif self.scenario == "burst":
                if r.random() < 0.02:
                    p.cong += r.uniform(20, 90)
                if r.random() < 0.012:                     # رویداد پیرینگ: قطع چند ثانیه‌ای
                    p.fail_until = t + r.randint(8, 45)
                if r.random() < 0.008:
                    p.drift += r.choice([-1, 1]) * r.uniform(5, 25)
            elif self.scenario == "flappy":
                if r.random() < 0.25:                      # نویز درخواستی: چیزی واقعاً خراب نیست
                    p.cong += r.uniform(-18, 18)
            # خرابی تونل (مستقل از سناریو، ولی بیشتر در burst)
            if p.tunnel and r.random() < (0.004 if self.scenario == "burst" else 0.0012):
                p.fail_until = t + r.randint(5, 25)

        # --- محقق‌کردن حقیقت این تیک برای همهٔ مسیرها، یک‌بار و برای همه یکسان ---
        # درسِ بک‌تست: قبلاً «تلفات بسته» به سیاست نشان داده نمی‌شد ولی در تابع هزینه
        # جریمه می‌شد → سیاست با چشم بسته بازی می‌کرد. حالا نمونهٔ محقق‌شده هم‌زمان
        # مبنای مشاهدهٔ سیاست است و هم مبنای هزینهٔ اپ.
        loss_true, failed = {}, {}
        for p in self.paths:
            lt = p.loss_true(t)
            lost = (t <= p.fail_until) or (r.random() < lt)
            self.rtt[p.id] = None if lost else max(5.0, p.rtt_true(t) + r.gauss(0, self.noise_sigma))
            loss_true[p.id] = lt
            failed[p.id] = bool(t <= p.fail_until)
        self.truth_now = {pid: {"lost": self.rtt[pid] is None, "rtt": self.rtt[pid],
                                "loss_true": loss_true[pid], "failed": failed[pid]}
                          for pid in self.rtt}

    def observe(self, t: int, pid: str) -> float | None:
        """نمونهٔ محقق‌شدهٔ همین تیک برای این مسیر (None = بسته از دست رفت)."""
        return self.rtt.get(pid)

    def observe_all(self, t: int) -> dict[str, float | None]:
        """همهٔ سیاست‌ها بودجهٔ سنجش یکسان دارند (پروب همزمان همهٔ مسیرها)."""
        return {p.id: self.rtt.get(p.id) for p in self.paths}

    def truth(self, pid: str) -> SimPath:
        return next(x for x in self.paths if x.id == pid)


# ----------------------------------------------------------------------------- جریان رویداد (منبع یگانهٔ حقیقت)

class StreamView:
    """نمای مکانی-زمانی رویدادها برای سیاست‌ها (بدون دسترسی به آینده)."""

    def __init__(self, meta: dict, stream: list[dict]):
        self.paths = meta["paths"]          # شیءهای سبک با id/base_rtt
        self.stream = stream
        self.ticks = len(stream)
        self.t = 0
        self.truth_now: dict[str, dict] = stream[0]["truth"]
        self.rtt: dict[str, float | None] = stream[0]["rtt"]

    def set_tick(self, t: int) -> None:
        self.t = t
        self.truth_now = self.stream[t]["truth"]
        self.rtt = self.stream[t]["rtt"]

    def app_critical(self, t: int) -> bool:
        return bool(self.stream[t]["critical"])

    def observe_all(self, t: int) -> dict[str, float | None]:
        return self.stream[t]["rtt"]


def precompute_stream(scenario: str, seed: int, ticks: int = 900) -> tuple[dict, list[dict]]:
    """
    کل حقیقت را یک‌بار جلو می‌برد و ثبت می‌کند.

    چرا؟ (۱) همهٔ سیاست‌ها دقیقاً روی یک جریان رویداد اجرا می‌شوند (اعتبار آزمایش)،
    (۲) oracle می‌تواند بهینهٔ واقعی باشد (برنامه‌ریزی پویا روی کل افق) نه حریصِ یک‌تیکی،
    (۳) جیتر هر مسیر |rtt_t − rtt_{t−1}| از پیش معلوم است.
    """
    sim = NetSim(scenario, seed, ticks=ticks)
    stream: list[dict] = []
    prev: dict[str, float | None] = {p.id: None for p in sim.paths}
    for t in range(ticks):
        sim.step(t)
        delta = {}
        for p in sim.paths:
            r0, r1 = prev[p.id], sim.rtt[p.id]
            delta[p.id] = abs(r1 - r0) if (r0 is not None and r1 is not None) else 0.0
        stream.append({
            "critical": sim.app_critical(t),
            "rtt": dict(sim.rtt),
            "truth": {pid: dict(v) for pid, v in sim.truth_now.items()},
            "delta": delta,
        })
        prev = dict(sim.rtt)
    meta = {"paths": [SimpleNamespace(id=p.id, base_rtt=p.base_rtt, tunnel=p.tunnel) for p in sim.paths],
            "tail_ref": min(p.base_rtt for p in sim.paths) * 1.25}
    return meta, stream


# ----------------------------------------------------------------------------- تابع هزینهٔ اپلیکیشن

def tick_cost(profile, sample: dict, delta: float,
              prev_choice: str | None, choice: str, tail_ref: float) -> tuple[float, bool]:
    """
    هزینهٔ واقعی یک تیک برای اپلیکیشن — روی نمونهٔ محقق‌شدهٔ همان تیک.

    اگر بسته برسد: α·RTT + β·دنباله + γ·نرخ‌تلفات‌زمینه + δ·|ΔRTT| + (η اگر قطع باشد)
    اگر نرسد:     γ·۱ + η  (تیکِ بی‌پاسخ = یک هیتچ کامل برای اپ)
    این دقیقاً همان اطلاعاتی است که سیاست دریافت کرده است → مقایسهٔ عادلانه.
    """
    if sample["lost"]:
        c = profile.gamma * 1.0 + profile.eta
        return (c + (profile.switch_cost if prev_choice is not None and choice != prev_choice else 0.0),
                sample["failed"])
    rtt = sample["rtt"]
    tail = max(0.0, rtt - tail_ref)
    c = (profile.alpha * rtt + profile.beta * tail + profile.gamma * sample["loss_true"]
         + profile.delta * delta)
    if prev_choice is not None and choice != prev_choice:
        c += profile.switch_cost
    return c, sample["failed"]


# ----------------------------------------------------------------------------- سیاست‌ها

class Policy:
    name = "policy"

    def reset(self, sim: NetSim, profile) -> None:
        self.sim, self.profile = sim, profile
        self.current = None

    def decide(self, t: int, obs: dict[str, float | None]) -> str:
        raise NotImplementedError


class RandomPolicy(Policy):
    name = "random"

    def decide(self, t, obs):
        return random.choice([p.id for p in self.sim.paths])


class AlwaysDirectPolicy(Policy):
    name = "always_direct"

    def decide(self, t, obs):
        return "direct"


class InstantBestPolicy(Policy):
    """کم‌پینگ‌ترین همین لحظه — همان کاری که اکثر «ابزارهای بهینه‌ساز» می‌کنند."""
    name = "instant_best"

    def decide(self, t, obs):
        avail = {k: v for k, v in obs.items() if v is not None}
        if not avail:
            return self.current or "direct"
        return min(avail.items(), key=lambda kv: kv[1])[0]


class EwmaBestPolicy(Policy):
    """EWMA + هیسترزیس: سیاست کلاسیک قابل‌احترام (رقابتی واقعی برای NCF)."""
    name = "ewma_best"

    def __init__(self, halflife: float = 10.0, margin: float = 0.12, min_dwell: float = 15.0):
        self.halflife, self.margin, self.min_dwell = halflife, margin, min_dwell

    def reset(self, sim, profile):
        super().reset(sim, profile)
        self.ewma = {p.id: None for p in sim.paths}
        self.since = 0

    def decide(self, t, obs):
        alpha = 1 - math.exp(-math.log(2) / self.halflife)
        for k, v in obs.items():
            if v is None:
                if self.ewma[k] is not None:
                    self.ewma[k] = self.ewma[k] * 1.15 + 30 * 0.15      # جریمهٔ نبودن نمونه
            else:
                self.ewma[k] = v if self.ewma[k] is None else self.ewma[k] + alpha * (v - self.ewma[k])
        if self.current is None:
            self.current, self.since = min(self.ewma.items(), key=lambda kv: kv[1] or 9e9)[0], t
            return self.current
        best = min(self.ewma.items(), key=lambda kv: kv[1] or 9e9)[0]
        cur = self.ewma[self.current] or 9e9
        bst = self.ewma[best] or 9e9
        if best != self.current and (cur - bst) / max(cur, 1e-6) > self.margin and (t - self.since) >= self.min_dwell:
            self.current, self.since = best, t
        return self.current


class NcfPolicy(Policy):
    """حلقهٔ کامل NCF: توزیع + پیش‌بینی + تابع هدف + هزینهٔ سوئیچ + دروازهٔ ایمنی."""
    name = "ncf"

    def __init__(self, profile_key: str = "gameplay", deg_horizon: float = 10.0):
        self.profile_key = profile_key
        self.horizon = deg_horizon
        self.calib_preds: list[float] = []
        self.calib_outcomes: list[int] = []

    def reset(self, sim, profile):
        super().reset(sim, profile)
        self.est = StateEstimator()
        self.kalman: dict[str, KalmanRTT] = {}
        for p in sim.paths:
            self.est.register(p.id, p.id)
            self.kalman[p.id] = KalmanRTT()
        self.engine = DecisionEngine(self.profile_key)
        self.calibrator = ProbabilityCalibrator()
        self.pending: list[tuple[int, str, float, float]] = []  # (due, path, p_raw, p_cal) برای کالیبراسیون

    def _p_fail(self, pid: str) -> float:
        st = self.est.paths[pid]
        base = st.floor_p50 or 40.0
        # آستانهٔ «شکست کیفیت» = نیاز مطلق اپ (ms)، ولی برای مسیرهایی که ذاتاً
        # کندتر از نیاز اپ‌اند، آستانه بالا می‌رود تا احتمال اشباع نشود.
        thr = max(self.engine.profile.fail_rtt_ms, base * 1.10)
        k = self.kalman[pid]
        p_rtt = k.p_exceed(thr, self.horizon) if k.level is not None else 0.0
        p_loss = min(1.0, (st.loss_ewma.mean or 0.0) * 2.5)
        p_down = min(0.97, 0.45 * (st.miss_streak - 1)) if st.miss_streak >= 2 else 0.0
        recent = st.cusum.recent_change(within_s=20) is not None
        p = 1 - (1 - p_rtt) * (1 - p_loss) * (1 - p_down)
        if recent:
            p = min(0.99, p * 1.3)
        # اصلاح خوش‌بینی: احتمال خام از کالیبراتور آنلاین می‌گذرد (درسِ بک‌تست)
        p_cal = self.calibrator.calibrate(p)
        self._last_raw_p = p
        return round(min(0.99, max(0.01, p_cal)), 3)

    def decide(self, t, obs):
        # ۱) به‌روزرسانی تخمین‌گر با مشاهدات این تیک
        for pid, v in obs.items():
            self.est.update(pid, v)
            if v is not None:
                self.kalman[pid].update(v)
            else:
                self.kalman[pid].predict(1.0)      # نبود نمونه = رشد عدم‌قطعیت (نه بی‌خبری)

        # ۲) ارزیابی کالیبراسیون پیش‌بینی‌های قبلی
        still = []
        for due, pid, p_raw, p_cal in self.pending:
            if t >= due:
                snap = self.est.paths[pid].window.summary()
                base = self.est.paths[pid].floor_p50 or 40.0
                deg = (snap["p95"] or 0) > base * 1.5 or (snap["loss"] or 0) > 0.15
                self.calib_preds.append(p_cal)
                self.calib_outcomes.append(1 if deg else 0)
                self.calibrator.observe(p_raw, 1 if deg else 0)   # ← حلقهٔ یادگیری کالیبراسیون
            else:
                still.append((due, pid, p_raw, p_cal))
        self.pending = still

        # ۳) ساخت دید مسیرها و ثبت پیش‌بینی‌های جدید
        views = []
        for p in self.sim.paths:
            pid = p.id
            p_fail = self._p_fail(pid)
            snap = self.est.paths[pid].decision_view(self.kalman[pid], p_fail, horizon_s=self.horizon)
            snap["id"], snap["label"] = pid, pid
            if snap["n"] >= 4:
                self.pending.append((t + int(self.horizon), pid, getattr(self, "_last_raw_p", p_fail), p_fail))
            views.append(DecisionEngine.build_view(snap, p_fail))

        # ۴) تصمیم
        d = self.engine.decide(views, critical_now=self.sim.app_critical(t), now=float(t))
        return d.chosen


class OraclePolicy(Policy):
    """
    سقف نظری واقعی: کل آیندهٔ جریان رویداد را می‌بیند و مسئلهٔ «کمینه‌سازی هزینهٔ کل
    با هزینهٔ سوئیچ» را با برنامه‌ریزی پویا (حالت = مسیر تیک قبل) دقیق حل می‌کند.
    """
    name = "oracle"

    def reset(self, sim, profile):
        super().reset(sim, profile)
        self.plan = self._solve_optimal(sim, profile)

    def _solve_optimal(self, sim, profile) -> list[str]:
        ids = [p.id for p in sim.paths]
        tail_ref = min(p.base_rtt for p in sim.paths) * 1.25
        # هزینهٔ هر تیک برای هر مسیر (بدون هزینهٔ سوئیچ)
        C: list[dict[str, float]] = []
        for t, tick in enumerate(sim.stream):
            row = {}
            for pid in ids:
                c, _ = tick_cost(profile, tick["truth"][pid], tick["delta"][pid], None, pid, tail_ref)
                row[pid] = c
            C.append(row)
        sc = profile.switch_cost
        idx = {pid: i for i, pid in enumerate(ids)}
        # V[t][i] = کمینهٔ هزینهٔ تیک‌های ۰..t با پایان روی مسیر i
        V: list[list[float]] = []
        back: list[list[int]] = []
        V.append([C[0][pid] for pid in ids])
        back.append([-1] * len(ids))
        for t in range(1, len(C)):
            vrow, brow = [0.0] * len(ids), [0] * len(ids)
            for i, pid in enumerate(ids):
                best_q, best_v = 0, 9e18
                for qi in range(len(ids)):
                    cand = V[t - 1][qi] + (sc if qi != i else 0.0)
                    if cand < best_v:
                        best_v, best_q = cand, qi
                vrow[i] = C[t][pid] + best_v
                brow[i] = best_q
            V.append(vrow)
            back.append(brow)
        last = min(range(len(ids)), key=lambda i: V[-1][i])
        plan = [ids[last]]
        for t in range(len(C) - 1, 0, -1):
            last = back[t][last]
            plan.append(ids[last])
        plan.reverse()
        return plan

    def decide(self, t, obs):
        return self.plan[t] if t < len(self.plan) else "direct"


POLICIES = [RandomPolicy, AlwaysDirectPolicy, InstantBestPolicy, EwmaBestPolicy, NcfPolicy, OraclePolicy]


# ----------------------------------------------------------------------------- اجرای یک سناریو

def run_scenario(scenario: str, seed: int, policy: Policy, app: str = "gameplay",
                 ticks: int = 900, switch_cost_scale: float = 1.0,
                 precomputed: tuple[dict, list[dict]] | None = None) -> dict:
    meta, stream = precomputed if precomputed else precompute_stream(scenario, seed, ticks)
    sim = StreamView(meta, stream)
    base = PROFILES[app]
    # هزینهٔ سوئیچ واقعی به قابلیت انتقال بستگی دارد:
    #   • حالت «نرم»  (MPTCP/QUIC migration با پشتیبانی دو سر): هزینه ≈ چند ده میلی‌ثانیه
    #   • حالت «پاره‌کننده» (بدون پشتیبانی سرور مقصد): سوئیچ = ری‌ست جلسه ≈ صدها میلی‌ثانیه
    profile = replace(base, switch_cost=base.switch_cost * switch_cost_scale)
    policy.reset(sim, profile)
    tail_ref_global = meta["tail_ref"]
    base_rtt = {p.id: p.base_rtt for p in sim.paths}

    costs, switches, bad, fails = [], 0, 0, 0
    prev_choice = None
    for t in range(len(stream)):
        sim.set_tick(t)
        obs = sim.observe_all(t)                     # بودجهٔ سنجش یکسان برای همهٔ سیاست‌ها
        choice = policy.decide(t, obs)
        tick = stream[t]
        c, failed = tick_cost(profile, tick["truth"][choice], tick["delta"][choice],
                              prev_choice, choice, tail_ref_global)
        costs.append(c)
        if prev_choice is not None and choice != prev_choice:
            switches += 1
        if failed:
            fails += 1
        smp = tick["truth"][choice]
        if smp["lost"] or (smp["rtt"] or 0) > base_rtt[choice] * 1.5:
            bad += 1
        prev_choice = choice

    mean_cost = statistics.fmean(costs)
    p95_cost = sorted(costs)[int(len(costs) * 0.95) - 1]
    return {
        "scenario": scenario, "seed": seed, "policy": policy.name, "app": app,
        "mean_cost": round(mean_cost, 2), "p95_cost": round(p95_cost, 2),
        "switches": switches, "switch_rate_per_min": round(switches / (ticks / 60), 2),
        "bad_frac": round(bad / ticks, 3), "fail_frac": round(fails / ticks, 3),
        "calib": (len(policy.calib_preds) if isinstance(policy, NcfPolicy) else 0),
    }


def benchmark(scenarios: tuple[str, ...] = ("stable", "congestion", "burst", "flappy"),
              seeds: int = 12, app: str = "gameplay", ticks: int = 900,
              policies: list[type[Policy]] | None = None,
              switch_cost_scale: float = 1.0) -> dict:
    policies = policies or POLICIES
    rows: list[dict] = []
    calib_all = {"preds": [], "outcomes": []}
    t0 = time.time()
    for scenario in scenarios:
        for seed in range(seeds):
            shared = precompute_stream(scenario, seed, ticks)   # یک جریان، همهٔ سیاست‌ها
            for P in policies:
                pol = P()
                r = run_scenario(scenario, seed, pol, app=app, ticks=ticks,
                                 switch_cost_scale=switch_cost_scale, precomputed=shared)
                rows.append(r)
                if isinstance(pol, NcfPolicy):
                    calib_all["preds"] += pol.calib_preds
                    calib_all["outcomes"] += pol.calib_outcomes

    # خلاصه‌سازی: میانگین روی seedها، regret نسبت به oracle
    summary: dict[str, dict[str, dict]] = {}
    for scenario in scenarios:
        summary[scenario] = {}
        sc_rows = [r for r in rows if r["scenario"] == scenario]
        oracle_mean = statistics.fmean([r["mean_cost"] for r in sc_rows if r["policy"] == "oracle"])
        for pol in sorted({r["policy"] for r in sc_rows}):
            pr = [r for r in sc_rows if r["policy"] == pol]
            mean_cost = statistics.fmean([r["mean_cost"] for r in pr])
            summary[scenario][pol] = {
                "mean_cost": round(mean_cost, 2),
                "p95_cost": round(statistics.fmean([r["p95_cost"] for r in pr]), 2),
                "switches": round(statistics.fmean([r["switches"] for r in pr]), 1),
                "switch_rate_per_min": round(statistics.fmean([r["switch_rate_per_min"] for r in pr]), 2),
                "bad_frac": round(statistics.fmean([r["bad_frac"] for r in pr]), 3),
                "fail_frac": round(statistics.fmean([r["fail_frac"] for r in pr]), 3),
                "regret_pct": round((mean_cost - oracle_mean) / max(oracle_mean, 1e-9) * 100, 2),
            }
    for r in rows:
        r["switch_cost_scale"] = switch_cost_scale
    return {"rows": rows, "summary": summary, "calib": calib_all, "switch_cost_scale": switch_cost_scale,
            "runtime_s": round(time.time() - t0, 2), "seeds": seeds, "ticks": ticks, "app": app}


def render_summary(res: dict) -> str:
    out = []
    out.append("=" * 100)
    mode = {1.0: "سوئیچ نرم (MPTCP/QUIC)", }.get(res.get("switch_cost_scale", 1.0),
                                                  f"سوئیچ پاره‌کنندهٔ اتصال ×{res.get('switch_cost_scale', 1.0):.0f}")
    out.append(f"NCF · بک‌تست سیاست‌ها | اپلیکیشن: {res['app']} | {res['seeds']} seed × {res['ticks']} تیک "               f"| هزینهٔ سوئیچ: {mode} "
               f"| زمان اجرا: {res['runtime_s']}s")
    out.append("=" * 100)
    pols = ["random", "always_direct", "instant_best", "ewma_best", "ncf", "oracle"]
    for scenario, table in res["summary"].items():
        out.append(f"\n▸ سناریو: {scenario}")
        out.append(f"  {'سیاست':<14}{'هزینهٔ میانگین':>15}{'هزینهٔ p95':>13}{'سوئیچ/دقیقه':>14}{'زمان بد':>10}{'regret':>10}")
        out.append("  " + "-" * 76)
        for pol in pols:
            if pol not in table:
                continue
            t = table[pol]
            mark = "★" if pol == "ncf" else " "
            out.append(f" {mark}{pol:<14}{t['mean_cost']:>15,.1f}{t['p95_cost']:>13,.1f}"
                       f"{t['switch_rate_per_min']:>14,.2f}{t['bad_frac']*100:>9,.1f}%{t['regret_pct']:>9,.1f}%")
    return "\n".join(out)


def run_suite(seeds: int = 12, app: str = "gameplay", ticks: int = 900,
              modes: tuple[float, ...] = (1.0, 12.0)) -> dict:
    """اجرای بک‌تست در دو حالت هزینهٔ سوئیچ + جمع‌بندی کالیبراسیون (برای گزارش)."""
    from .forecast import calibration_report
    out = {"app": app, "seeds": seeds, "ticks": ticks, "modes": {}}
    for scale in modes:
        res = benchmark(seeds=seeds, app=app, ticks=ticks, switch_cost_scale=scale)
        cal = calibration_report(res["calib"]["preds"], res["calib"]["outcomes"])
        key = "smooth" if scale <= 1.0 else "breaking"
        out["modes"][key] = {
            "switch_cost_scale": scale,
            "summary": res["summary"],
            "runtime_s": res["runtime_s"],
            "calibration": cal,
        }
    return out


if __name__ == "__main__":
    import json
    suite = run_suite(seeds=int(os.environ.get("NCF_SEEDS", "12")))
    for key in ("smooth", "breaking"):
        m = suite["modes"][key]
        print(render_summary({"app": suite["app"], "seeds": suite["seeds"], "ticks": suite["ticks"],
                              "switch_cost_scale": m["switch_cost_scale"], "summary": m["summary"],
                              "runtime_s": m["runtime_s"]}))
        print()
    cal = suite["modes"]["breaking"]["calibration"]
    print(f"\u25b8 کالیبراسیون احتمال شکست (NCF): n={cal['n']} | Brier={cal['brier']} | "
          f"مهارت نسبت به پایه={cal['skill']}")
    for b in cal["bins"]:
        print(f"    {b['bin']:<10} n={b['n']:<6} پیش‌بینی={b['predicted']:<7} واقعیت={b['observed']}")
    path = os.path.join(os.path.dirname(__file__), "bench.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(suite, f, ensure_ascii=False, indent=1)
    print(f"\n\u2705 نتیجه در {path} ذخیره شد")
