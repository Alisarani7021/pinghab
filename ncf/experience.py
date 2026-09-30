#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NCF · گراف تجربه (Experience Graph)
=========================================================================
«دانش شبکه» تنها metrics نیست؛ رابطهٔ شرطی است:

    ISP × اپلیکیشن × مقصد × ساعت × مسیر × پروتکل  →  نتیجه

این ماژول همین را در SQLite نگه می‌دارد و کوئری‌های عملی می‌دهد:
  • بهترین مسیر برای «ایرانسل + پابجی + ساعت ۲۱» چیست؟
  • روند ۷ روز گذشتهٔ یک مسیر چگونه بوده؟
  • آیا افت امروز بی‌سابقه است یا تکرار الگوی هفتگی است؟

هیچ payloadی ذخیره نمی‌شود؛ فقط telemetry عددی + شناسه‌های درشت (ISP/شهر/برند اپ).
"""

from __future__ import annotations

import json
import sqlite3
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL    NOT NULL,
    isp           TEXT,
    asn           INTEGER,
    app           TEXT,
    dst_class     TEXT,
    path_id       TEXT,
    proto         TEXT,
    hour          INTEGER,
    weekday       INTEGER,
    rtt_p50       REAL,
    rtt_p95       REAL,
    rtt_p99       REAL,
    jitter        REAL,
    loss          REAL,
    p_fail        REAL,
    regime        TEXT,
    extra         TEXT
);
CREATE INDEX IF NOT EXISTS idx_obs_context ON observations(isp, app, hour);
CREATE INDEX IF NOT EXISTS idx_obs_path    ON observations(path_id, ts);

CREATE TABLE IF NOT EXISTS decisions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    chosen        TEXT,
    previous      TEXT,
    switched      INTEGER,
    cost_expected REAL,
    gain          REAL,
    reason        TEXT,
    blocked_by    TEXT,
    app           TEXT,
    context       TEXT
);

CREATE TABLE IF NOT EXISTS outcomes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL NOT NULL,
    decision_id   INTEGER,
    path_id       TEXT,
    realized_cost REAL,
    realized_rtt  REAL,
    realized_loss REAL,
    failed        INTEGER,
    FOREIGN KEY(decision_id) REFERENCES decisions(id)
);
"""


@dataclass
class Observation:
    isp: str = "unknown"
    asn: int | None = None
    app: str = "generic"
    dst_class: str = "unknown"
    path_id: str = ""
    proto: str = "udp"
    rtt_p50: float | None = None
    rtt_p95: float | None = None
    rtt_p99: float | None = None
    jitter: float | None = None
    loss: float | None = None
    p_fail: float | None = None
    regime: str | None = None
    ts: float | None = None
    extra: dict | None = None


class ExperienceGraph:
    def __init__(self, path: str | Path = "experience.db"):
        self.path = str(path)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ------------------------------------------------------------------ نوشتن
    def add_observation(self, o: Observation) -> int:
        ts = o.ts or time.time()
        lt = time.localtime(ts)
        cur = self.db.execute(
            """INSERT INTO observations
               (ts, isp, asn, app, dst_class, path_id, proto, hour, weekday,
                rtt_p50, rtt_p95, rtt_p99, jitter, loss, p_fail, regime, extra)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ts, o.isp, o.asn, o.app, o.dst_class, o.path_id, o.proto, lt.tm_hour, lt.tm_wday,
             o.rtt_p50, o.rtt_p95, o.rtt_p99, o.jitter, o.loss, o.p_fail, o.regime,
             json.dumps(o.extra or {}, ensure_ascii=False)))
        self.db.commit()
        return cur.lastrowid

    def add_decision(self, d: dict) -> int:
        cur = self.db.execute(
            """INSERT INTO decisions (ts, chosen, previous, switched, cost_expected, gain, reason, blocked_by, app, context)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (d.get("ts", time.time()), d.get("chosen"), d.get("current"), int(bool(d.get("switched"))),
             d.get("expected_cost"), d.get("gain_vs_current"), d.get("reason"), d.get("blocked_by"),
             d.get("app"), json.dumps(d.get("context") or {}, ensure_ascii=False)))
        self.db.commit()
        return cur.lastrowid

    def add_outcome(self, decision_id: int | None, path_id: str, realized_cost: float,
                    rtt: float | None = None, loss: float | None = None, failed: bool = False) -> int:
        cur = self.db.execute(
            """INSERT INTO outcomes (ts, decision_id, path_id, realized_cost, realized_rtt, realized_loss, failed)
               VALUES (?,?,?,?,?,?,?)""",
            (time.time(), decision_id, path_id, realized_cost, rtt, loss, int(failed)))
        self.db.commit()
        return cur.lastrowid

    # ------------------------------------------------------------------ خواندن
    def context_rows(self, isp: str | None = None, app: str | None = None,
                     hour_from: int | None = None, hour_to: int | None = None,
                     days: float | None = None) -> list[sqlite3.Row]:
        q = "SELECT * FROM observations WHERE 1=1"
        args: list = []
        if isp:
            q += " AND isp = ?"; args.append(isp)
        if app:
            q += " AND app = ?"; args.append(app)
        if hour_from is not None and hour_to is not None:
            if hour_from <= hour_to:
                q += " AND hour BETWEEN ? AND ?"; args += [hour_from, hour_to]
            else:  # بازهٔ شبانه
                q += " AND (hour >= ? OR hour <= ?)"; args += [hour_from, hour_to]
        if days:
            q += " AND ts > ?"; args.append(time.time() - days * 86400)
        self.db.row_factory = sqlite3.Row
        return list(self.db.execute(q + " ORDER BY ts DESC LIMIT 5000", args))

    def best_path(self, isp: str, app: str, hour: int | None = None,
                  metric: str = "rtt_p95", window: int = 3) -> list[dict]:
        """
        «برای این ISP و این اپ و این ساعت، کدام مسیر معمولاً بهتر است؟»
        با میانگین وزنی روی چند ساعت مجاور (پنجرهٔ زمانی) برای داشتن نمونهٔ کافی.
        """
        hours = [(hour + k) % 24 for k in range(-window, window + 1)] if hour is not None else None
        rows = self.db.execute(
            f"""SELECT path_id, COUNT(*) n, AVG({metric}) avg_metric, MIN({metric}) best_metric,
                       AVG(loss) avg_loss, AVG(rtt_p50) avg_p50
                FROM observations
                WHERE isp = ? AND app = ? {"" if hours is None else "AND hour IN (%s)" % ",".join("?" * len(hours))}
                GROUP BY path_id HAVING n >= 2
                ORDER BY avg_metric ASC""" % ((),),
            [isp, app] + (hours or [])).fetchall()
        return [dict(r) for r in rows]

    def trend(self, path_id: str, days: float = 7, buckets: int = 7) -> list[dict]:
        since = time.time() - days * 86400
        rows = self.db.execute(
            """SELECT CAST((ts - ?) / ? AS INT) AS bucket,
                      COUNT(*) n, AVG(rtt_p50) p50, AVG(rtt_p95) p95, AVG(loss) loss
               FROM observations WHERE path_id = ? AND ts >= ?
               GROUP BY bucket ORDER BY bucket""",
            (since, (days * 86400) / buckets, path_id, since)).fetchall()
        return [dict(r) for r in rows]

    def decision_stats(self) -> dict:
        rows = self.db.execute("SELECT COUNT(*) n, SUM(switched) sw FROM decisions").fetchone()
        blocked = self.db.execute(
            "SELECT blocked_by, COUNT(*) n FROM decisions WHERE blocked_by IS NOT NULL GROUP BY blocked_by").fetchall()
        return {"decisions": rows[0] or 0, "switches": rows[1] or 0,
                "blocked": {b[0]: b[1] for b in blocked}}

    def counterfactual_dataset(self, path_id: str) -> list[tuple[float, float]]:
        """(هزینهٔ انتظاری، هزینهٔ واقعی) برای آموزش/کالیبره‌کردن مدل پادواقع."""
        rows = self.db.execute(
            """SELECT d.cost_expected, o.realized_cost
               FROM decisions d JOIN outcomes o ON o.decision_id = d.id
               WHERE d.chosen = ? AND d.cost_expected IS NOT NULL""", (path_id,)).fetchall()
        return [(r[0], r[1]) for r in rows]

    def summary(self) -> dict:
        n = self.db.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        paths = self.db.execute("SELECT DISTINCT path_id FROM observations").fetchall()
        isps = self.db.execute("SELECT DISTINCT isp FROM observations").fetchall()
        return {"observations": n, "paths": [p[0] for p in paths], "isps": [i[0] for i in isps],
                **self.decision_stats()}

    def close(self) -> None:
        self.db.close()


# ----------------------------------------------------------------------------- خودآزمون

if __name__ == "__main__":
    import random
    random.seed(5)
    db_path = "/tmp/ncf_experience_test.db"
    Path(db_path).unlink(missing_ok=True)
    g = ExperienceGraph(db_path)

    print("=" * 74)
    print("NCF · خودآزمون گراف تجربه")
    print("=" * 74)

    isps = ["ایرانسل", "همراه اول"]
    paths = {"direct": 46, "tr": 58, "eu": 135}
    now = time.time()
    for i in range(900):
        isp = random.choice(isps)
        hour = random.choice([10, 14, 21, 21, 21, 23])
        for pid, base in paths.items():
            # ساعت ۲۱ برای direct بدتر می‌شود (الگوی واقعی شبانه) و تونل ترکیه پایدارتر است
            penalty = (18 if (pid == "direct" and hour >= 20) else 0)
            rtt = base + penalty + random.gauss(0, 4)
            g.add_observation(Observation(
                isp=isp, app="pubg", dst_class="game-server", path_id=pid, proto="udp",
                rtt_p50=round(rtt, 1), rtt_p95=round(rtt * 1.35, 1), rtt_p99=round(rtt * 1.6, 1),
                jitter=round(abs(random.gauss(3, 2)), 1), loss=round(abs(random.gauss(0.01, 0.02)), 3),
                p_fail=round(random.uniform(0, 0.3), 2), regime="stable",
                ts=now - random.uniform(0, 6 * 86400) + i * 0.01))

    print("\n۱) بهترین مسیر در ساعت ۲۱ برای ایرانسل + pubg:")
    for r in g.best_path("ایرانسل", "pubg", hour=21, metric="rtt_p95"):
        print(f"   {r['path_id']:8s} n={r['n']:>4}  p95={r['avg_metric']:.1f}  p50={r['avg_p50']:.1f}  loss={r['avg_loss']:.3f}")

    print("\n۲) بهترین مسیر در ساعت ۱۴ (خارج از اوج) — الگو باید تغییر کند:")
    for r in g.best_path("ایرانسل", "pubg", hour=14, metric="rtt_p95"):
        print(f"   {r['path_id']:8s} n={r['n']:>4}  p95={r['avg_metric']:.1f}  p50={r['avg_p50']:.1f}")

    print("\n۳) روند مسیر direct در ۷ روز:")
    for b in g.trend("direct"):
        print(f"   بازهٔ {b['bucket']}: p50={b['p50']:.1f} p95={b['p95']:.1f} loss={b['loss']:.3f} (n={b['n']})")

    print("\n۴) خلاصهٔ گراف:", json.dumps(g.summary(), ensure_ascii=False))
    print("   اندازهٔ فایل:", round(Path(db_path).stat().st_size / 1024, 1), "KB")
    g.close()
