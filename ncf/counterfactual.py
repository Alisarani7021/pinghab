#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCF · موتور پادواقع (Counterfactual Engine)
=========================================================================
سؤال کلیدی: «اگر ۱۰ ثانیه پیش مسیر B را انتخاب می‌کردم، چه می‌شد؟»
همیشه نمی‌توان همهٔ مسیرها را هم‌زمان امتحان کرد؛ پس باید از داده‌ای که *داری*
نتیجهٔ کاری که *نکردی* را تخمین بزنی.

پیاده‌سازی: contextual bandit با رگرسیون ریج خطی به‌ازای هر action
(ویژگی‌ها: وضعیت‌های مشاهده‌شده) + عدم‌قطعیت از واریانس پسین.

نکات مهم مهندسی:
  • به‌روزرسانی با Sherman–Morrison (بدون معکوس‌گیری ماتریسی در هر گام)
  • خروجی «تخمین + بازهٔ اطمینان» است، نه یک عدد تک
  • ثبت لاگ «تصمیم/نتیجه» لازم است تا exploration واقعاً به یادگیری تبدیل شود
  • هیچ exploration روی کاربر واقعی انجام نمی‌شود؛ مدل از دادهٔ logged یاد می‌گیرد
    (این همان تفاوت contextual bandit ایمن با RL آزاد است)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


@dataclass
class Prediction:
    action: str
    mean: float
    sd: float

    def to_dict(self) -> dict:
        return {"action": self.action, "mean": round(self.mean, 2), "sd": round(self.sd, 2)}


class RidgeBandit:
    """
    رگرسیون ریج خطی برای هر action:  y ≈ xᵗθ  با پیشین N(0, (1/λ) I)

    posterior:  A = λI + Σ x xᵗ  ,  b = Σ x y  ,  θ = A⁻¹ b
    Sherman–Morrison:  A⁻¹ ← A⁻¹ − (A⁻¹x xᵗ A⁻¹)/(1 + xᵗ A⁻¹ x)
    """

    def __init__(self, actions: list[str], n_features: int, lam: float = 2.0, noise: float = 1.0):
        self.actions = list(actions)
        self.d = n_features
        self.lam = lam
        self.noise = noise
        self.Ainv: dict[str, list[list[float]]] = {}
        self.b: dict[str, list[float]] = {}
        self.count: dict[str, int] = {}
        for a in self.actions:
            self.Ainv[a] = [[1.0 / lam if i == j else 0.0 for j in range(self.d)] for i in range(self.d)]
            self.b[a] = [0.0] * self.d
            self.count[a] = 0

    # --- ابزار جبر خطی
    def _mv(self, M, v):
        return [sum(M[i][j] * v[j] for j in range(self.d)) for i in range(self.d)]

    def _outer(self, a, b):
        return [[a[i] * b[j] for j in range(self.d)] for i in range(self.d)]

    @staticmethod
    def _dot(a, b):
        return sum(x * y for x, y in zip(a, b))

    # --- به‌روزرسانی
    def update(self, action: str, x: list[float], y: float) -> None:
        if action not in self.Ainv:
            raise KeyError(action)
        Ainv = self.Ainv[action]
        Ax = self._mv(Ainv, x)
        denom = 1.0 + self._dot(x, Ax)
        Ainv_new = [[Ainv[i][j] - Ax[i] * Ax[j] / denom for j in range(self.d)] for i in range(self.d)]
        self.Ainv[action] = Ainv_new
        b = self.b[action]
        self.b[action] = [b[i] + x[i] * y for i in range(self.d)]
        self.count[action] += 1

    def theta(self, action: str) -> list[float]:
        return self._mv(self.Ainv[action], self.b[action])

    def predict(self, action: str, x: list[float]) -> Prediction:
        th = self.theta(action)
        mean = self._dot(th, x)
        Ax = self._mv(self.Ainv[action], x)
        var = self.noise * (1.0 + self._dot(x, Ax))
        return Prediction(action, mean, math.sqrt(max(var, 1e-9)))

    # --- پادواقع: چه می‌شد اگر؟
    def counterfactual(self, x: list[float], observed_action: str, observed_cost: float,
                       actions: list[str] | None = None) -> dict:
        acts = actions or self.actions
        preds = {a: self.predict(a, x) for a in acts}
        ents = sorted(preds.items(), key=lambda kv: kv[1].mean)
        best_action, best_pred = ents[0]
        observed_pred = preds.get(observed_action)
        regret = (observed_pred.mean - best_pred.mean) if observed_pred else None
        # اطمینان: آیا تفاضل از عدم‌قطعیت بزرگ‌تر است؟
        confident = bool(observed_pred and
                         abs(observed_pred.mean - best_pred.mean) > 1.0 * math.hypot(observed_pred.sd, best_pred.sd))
        return {
            "observed_action": observed_action, "observed_cost": round(observed_cost, 2),
            "counterfactual_best": best_action, "best_mean": round(best_pred.mean, 2),
            "estimated_regret": round(regret, 2) if regret is not None else None,
            "confident": confident,
            "all": [p.to_dict() for _, p in ents],
            "samples": {a: self.count[a] for a in acts},
        }

    def fits(self, min_samples: int = 3) -> bool:
        return all(self.count[a] >= min_samples for a in self.actions)

    def report(self) -> list[dict]:
        out = []
        for a in self.actions:
            th = self.theta(a)
            out.append({"action": a, "n": self.count[a],
                        "theta": [round(v, 3) for v in th]})
        return sorted(out, key=lambda x: -x["n"])


def features(snapshot: dict, hour: float | None = None, extra: list[float] | None = None) -> list[float]:
    """
    بردار ویژگی برای مدل پادواقع. عمداً کوچک و قابل‌توضیح است:
      [1, p50/100, jitter/20, loss, p_fail, sin(hour), cos(hour)]
    """
    p50 = (snapshot.get("p50") or 0) / 100.0
    jit = (snapshot.get("delta") or snapshot.get("jitter") or 0) / 20.0
    loss = snapshot.get("loss") or 0.0
    pf = snapshot.get("p_fail") or 0.0
    h = hour if hour is not None else 0.0
    f = [1.0, p50, jit, loss, pf, math.sin(2 * math.pi * h / 24), math.cos(2 * math.pi * h / 24)]
    if extra:
        f.extend(extra)
    return f


# ----------------------------------------------------------------------------- خودآزمون

if __name__ == "__main__":
    print("=" * 74)
    print("NCF · خودآزمون موتور پادواقع (مدل باید ضرایب پنهان را کشف کند)")
    print("=" * 74)

    random.seed(11)
    actions = ["direct", "tr", "eu"]
    # ضرایب پنهان دنیای واقعی: هر مسیر حساسیت متفاوتی به وضعیت دارد
    TRUE = {
        "direct": [8.0, 55.0, 3.5, 120.0, 90.0, 0.0, 0.0],   # به افت حساس است
        "tr":     [30.0, 22.0, 1.2, 60.0, 55.0, 0.0, 0.0],   # پایهٔ بالاتر ولی مقاوم
        "eu":     [70.0, 40.0, 2.0, 80.0, 70.0, 0.0, 0.0],   # گران
    }
    n_feat = len(TRUE["direct"])
    bandit = RidgeBandit(actions, n_feat, lam=1.5, noise=4.0)

    # جمع‌آوری دادهٔ لاگ‌شده (سیاست اکتشافی محدود، شبیه production با canary کوچک)
    for i in range(400):
        x = [1.0, random.uniform(0.2, 1.4), random.uniform(0, 1.5), random.random() * 0.25,
             random.random(), random.uniform(-1, 1), random.uniform(-1, 1)]
        a = random.choices(actions, weights=[0.6, 0.3, 0.1])[0]
        y = sum(c * xi for c, xi in zip(TRUE[a], x)) + random.gauss(0, 3.5)
        bandit.update(a, x, y)

    print("\nضرایب آموخته‌شده (باید به TRUE نزدیک باشند):")
    for row in bandit.report():
        a = row["action"]
        print(f"  {a:7s} n={row['n']:>4}  θ={row['theta']}\n           TRUE={TRUE[a]}")

    print("\nتخمین پادواقع در سه وضعیت متفاوت:")
    scenarios = {
        "شبکهٔ سالم (p50=40, loss=0, p_fail=0.05)": [1.0, 0.40, 0.2, 0.0, 0.05, 0.0, 1.0],
        "افت شدید (p50=95, loss=0.2, p_fail=0.8)": [1.0, 0.95, 1.0, 0.2, 0.80, 0.0, 1.0],
        "پینگ متوسط ولی جیتر بالا (p50=60, jitter=1.2)": [1.0, 0.60, 1.2, 0.05, 0.3, 0.0, 1.0],
    }
    for title, x in scenarios.items():
        cf = bandit.counterfactual(x, observed_action="direct", observed_cost=sum(c * xi for c, xi in zip(TRUE["direct"], x)))
        print(f"\n  ▸ {title}")
        print(f"     بهترین برآورد: {cf['counterfactual_best']} (~{cf['best_mean']}) | "
              f"افسوس تخمینی اگر direct رفته باشی: {cf['estimated_regret']} | اطمینان: {cf['confident']}")
        for p in cf["all"]:
            print(f"       {p['action']:7s} {p['mean']:8.2f} ± {p['sd']:.2f}")
