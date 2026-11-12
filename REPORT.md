# Roblox Up-and-Coming forecast — build report

Competition: roblox-up-and-coming-forecast-01 ($500, deadline 2026-11-13 06:00 UTC / 13:00 WIB).
Built 2026-11-13 ~00:30 WIB in a single agent session.

## Model (main.py, 9,049 bytes, Python 3.13 stdlib only)

Rank random-walk Monte Carlo over the 72-hour scored window, 3000 paths,
seed 20261113 (deterministic: two runs byte-identical, ~13s):

- Per-game drift: shrunk slope of rank vs time over the last 96h (min 3
  points), clipped to ±0.40 ranks/hour, shrink 0.5, plus a playing-growth
  term (-0.6 × log-playing slope, clipped ±0.05/hour), decaying with
  tau = 36h.
- Noise: band sigmas calibrated from consecutive-read rank changes scaled
  by sqrt(dt): 0.85 / 2.04 / 3.18 / 3.69 ranks per sqrt-hour for ranks
  <=10 / 11-30 / 31-60 / >60, times a 1.2 multiplier (sweep winner).
- Dropout per hour: 0.002 / 0.004 / 0.012 by band; age-out at created +
  28 days (first-seen + 28d when `created` is unknown — the practice
  history has no details at all); re-entry 0.002/hour.
- Candidates: top 80 by (current rank, best rank). Unnamed share 25% per
  place; per-row cap 0.60; rows below p 0.0005 dropped.
- Output: exactly {probabilities, top10}; place sums ~0.747, max p 0.149,
  22,733 bytes on the full practice history.

## Calibration (local backtest, official log-score formula)

Two train/test splits of the kit's 34-read history; baseline = kit starter
(persistence) scored on the same test reads:

| config | split 1 (11 reads) | split 2 (8 reads) | mean |
|---|---|---|---|
| base (sigma as first estimated, unnamed 0.20) | -45.28 | -40.94 | -43.11 |
| unnamed 0.30 | -44.71 | -39.51 | -42.11 |
| sigma x1.25 | -43.79 | -40.30 | -42.05 |
| sigma x2.0, unnamed 0.30 | -40.76 | -38.33 | -39.55 |
| corrected sigmas, unnamed 0.25, sigma x1.2 | -40.13 | -38.64 | -39.39 |

Key correction found during calibration: the first sigma estimates divided
rank change by dt instead of sqrt(dt), underestimating hourly diffusion
~2.4x. Correctly scaled sigmas (0.85/2.04/3.18/3.69) plus a 1.2 multiplier
won the sweep. Final margin over persistence: ~+14.5 nats (mean -39.4 vs
-54.0). Official practice baseline: -43.512039 (different window — not
directly comparable; the margin on identical splits is the signal).

## Verification (this session)

- Two runs on the full practice history: byte-identical output.
- Output shape: exactly 2 keys; top10 10 distinct; <= 45 rows/place
  (limit 100); place sums <= 0.75 (limit 1); max p 0.149; 22,733 bytes
  (limit 1,048,576).
- main.py: strict UTF-8, no NUL, 9,049 bytes.

## Files in the repo

- main.py, LICENSE (MIT, SPDX line), README.md, REPORT.md (this file),
  .makefun/owner.json (wallet CTqrxd).
