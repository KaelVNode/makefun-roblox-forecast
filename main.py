#!/usr/bin/env python3
"""Roblox Up-and-Coming top-10 forecaster (make.fun roblox-up-and-coming-forecast-01).

Model: rank random-walk Monte Carlo over the scored window.
- Each candidate game's rank follows a random walk with a per-game drift
  (shrunk recent rank trend + playing-growth effect, decaying over the
  horizon) and band-dependent noise calibrated from the history's
  consecutive-read rank changes.
- Games leave the chart (dropout + 28-day age-out from `created`, or
  first-seen + 28d when `created` is unknown) and can re-enter; brand-new
  games are covered by the unnamed share.
- P(game at place k) = frequency over (path, hour). Probabilities are honest
  MC frequencies, shrunk toward a calibrated unnamed share.
- Deterministic: fixed seed, stdlib only, no network.
"""
import json
import math
import os
import random
import sys
from datetime import datetime, timezone

SEED = 20261113
N_PATHS = int(os.environ.get("RB_N_PATHS", "3000"))
MAX_CANDIDATES = 80
UNNAMED_TARGET = float(os.environ.get("RB_UNNAMED", "0.25"))
P_CAP = 0.60
TAU_DRIFT_H = 36.0
SIGMA_MULT = float(os.environ.get("RB_SIGMA", "1.2"))
DRIFT_SHRINK = float(os.environ.get("RB_DRIFT", "0.5"))

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def sigma_for(rank):
    if rank <= 10:
        return 0.85 * SIGMA_MULT
    if rank <= 30:
        return 2.04 * SIGMA_MULT
    if rank <= 60:
        return 3.18 * SIGMA_MULT
    return 3.69 * SIGMA_MULT


def dropout_per_hour(rank):
    if rank <= 10:
        return 0.002
    if rank <= 30:
        return 0.004
    return 0.012


def load_history(input_dir):
    task = json.load(open(os.path.join(input_dir, "task.json")))
    rows = []
    with open(os.path.join(input_dir, "history.ndjson")) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    rows.sort(key=lambda r: r["at"])
    return task, rows


def build_series(rows):
    """Per-game series: list of (t_hours, rank, playing). Also first/last seen
    and created date when details are available."""
    series = {}
    details_created = {}
    for r in rows:
        t = parse_ts(r["at"]) / 3600.0
        det = r.get("details") or {}
        for g in r["up_and_coming"]:
            u = g["universe_id"]
            s = series.setdefault(u, [])
            s.append((t, float(g["rank"]),
                      float(g["playing"]) if g.get("playing") else None))
            d = det.get(str(u)) or det.get(u)
            if d and d.get("created") and u not in details_created:
                try:
                    details_created[u] = parse_ts(d["created"]) / 3600.0
                except Exception:
                    pass
    return series, details_created


def estimate_drifts(series, t_end):
    """Per-game drift (ranks/hour): shrunk slope of rank vs time over the
    recent window, plus a small playing-growth effect."""
    drifts = {}
    for u, ss in series.items():
        # recent window: last 96h of observations, at least 3 points
        recent = [p for p in ss if t_end - p[0] <= 96.0]
        if len(recent) < 3:
            recent = ss[-6:]
        if len(recent) < 3:
            drifts[u] = 0.0
            continue
        n = len(recent)
        mt = sum(p[0] for p in recent) / n
        mr = sum(p[1] for p in recent) / n
        num = sum((p[0] - mt) * (p[1] - mr) for p in recent)
        den = sum((p[0] - mt) ** 2 for p in recent)
        slope = num / den if den > 0 else 0.0
        # playing-growth effect: log playing slope over the same window
        grow = 0.0
        pts = [(p[0], math.log(p[2])) for p in recent if p[2] and p[2] > 0]
        if len(pts) >= 3:
            n2 = len(pts)
            mt2 = sum(p[0] for p in pts) / n2
            mg = sum(p[1] for p in pts) / n2
            den2 = sum((p[0] - mt2) ** 2 for p in pts)
            if den2 > 0:
                grow = sum((p[0] - mt2) * (p[1] - mg) for p in pts) / den2
        d = DRIFT_SHRINK * slope - 0.6 * max(-0.05, min(0.05, grow))
        drifts[u] = max(-0.40, min(0.40, d))
    return drifts


def main():
    task, rows = load_history(INPUT_DIR)
    places = int(task.get("places", 10))
    window = task.get("window", {})
    n_hours = int(window.get("slots", 72))
    out_name = task.get("output", "forecast.json")
    if not rows:
        raise SystemExit("empty history")

    series, created = build_series(rows)
    t_end = parse_ts(rows[-1]["at"]) / 3600.0
    last_chart = {}
    for g in rows[-1]["up_and_coming"]:
        last_chart[g["universe_id"]] = float(g["rank"])

    # Candidate set: current chart + games ever in top 30 + recent top-10
    # holders, ranked by a priority score (current rank, then best rank).
    best_rank = {}
    for u, ss in series.items():
        best_rank[u] = min(p[1] for p in ss)
    cand = []
    for u in set(list(last_chart) + list(best_rank)):
        cur = last_chart.get(u, 1e9)
        cand.append((min(cur, best_rank[u] + 5.0), cur, u))
    cand.sort()
    cand = [u for _, _, u in cand[:MAX_CANDIDATES]]

    drifts = estimate_drifts(series, t_end)
    rng = random.Random(SEED)

    # Age-out deadline per game (hours): created + 28d, else first_seen + 28d.
    age_out = {}
    for u in cand:
        ss = series[u]
        base = created.get(u, ss[0][0])
        age_out[u] = base + 28.0 * 24.0

    # Initial state per game: (rank, alive)
    init = {}
    for u in cand:
        if u in last_chart:
            init[u] = (last_chart[u], True)
        else:
            # not in last chart: start at last known rank, dormant
            init[u] = (series[u][-1][1], False)

    counts = {}  # (universe_id, place) -> hits
    top10_score = {u: 0.0 for u in cand}  # sum of (11 - place) over samples
    n_samples = N_PATHS * n_hours

    for _ in range(N_PATHS):
        # state arrays, indexed by candidate position
        rank = [init[u][0] for u in cand]
        alive = [init[u][1] for u in cand]
        dr = [drifts.get(u, 0.0) for u in cand]
        ao = [age_out[u] for u in cand]
        for h in range(1, n_hours + 1):
            t_now = t_end + h
            decay = math.exp(-h / TAU_DRIFT_H)
            for i in range(len(cand)):
                if alive[i]:
                    r = rank[i]
                    step = dr[i] * decay + rng.gauss(0.0, sigma_for(r))
                    r += step
                    if r < 1.0:
                        r = 1.0
                    elif r > 200.0:
                        r = 200.0
                    rank[i] = r
                    # dropout / age-out
                    if t_now >= ao[i] or rng.random() < dropout_per_hour(r):
                        alive[i] = False
                else:
                    # re-entry of a game that left (rare)
                    if rng.random() < 0.002:
                        alive[i] = True
                        rank[i] = min(200.0, rank[i] + rng.gauss(0.0, 5.0))
            # top places this hour: 10 smallest ranks among alive
            idx = [i for i in range(len(cand)) if alive[i]]
            if not idx:
                continue
            idx.sort(key=lambda i: rank[i])
            for place, i in enumerate(idx[:places], start=1):
                u = cand[i]
                counts[(u, place)] = counts.get((u, place), 0) + 1
                top10_score[u] += (places + 1 - place)

    # Convert to probabilities, keep top 100 per place, shrink to unnamed target.
    probabilities = []
    for place in range(1, places + 1):
        rows_p = []
        for u in cand:
            c = counts.get((u, place), 0)
            if c:
                rows_p.append((c, u))
        rows_p.sort(reverse=True)
        rows_p = rows_p[:100]
        total = sum(c for c, _ in rows_p) / n_samples
        if total <= 0:
            continue
        # scale so the named sum is at most (1 - UNNAMED_TARGET)
        scale = min(1.0, (1.0 - UNNAMED_TARGET) / total)
        for c, u in rows_p:
            p = (c / n_samples) * scale
            if p >= 0.0005:
                probabilities.append({"universe_id": u, "place": place,
                                      "p": round(min(p, P_CAP), 6)})

    # top10: order by mean simulated standing (highest top10_score first)
    order = sorted(cand, key=lambda u: (-top10_score[u], best_rank[u]))
    top10 = order[:places]
    # fill with current chart order if short (should not happen)
    if len(top10) < places:
        for u in sorted(last_chart, key=lambda u: last_chart[u]):
            if u not in top10:
                top10.append(u)
            if len(top10) == places:
                break

    out = {"probabilities": probabilities, "top10": top10}
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(os.path.join(OUTPUT_DIR, out_name), "w") as f:
        f.write(json.dumps(out, sort_keys=False) + "\n")


if __name__ == "__main__":
    main()
