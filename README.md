# Roblox Up-and-Coming top-10 forecast

Entry for make.fun `roblox-up-and-coming-forecast-01`: a program that reads
the history of Roblox's Up-and-Coming chart and forecasts its top 10, place
by place, for every hour of the 72 hours after entries close.

## Model

Rank random-walk Monte Carlo (`main.py`, Python 3.13, stdlib only,
deterministic, seed 20261113):

- Each candidate game's rank follows a random walk with a per-game drift
  (shrunk recent rank trend + playing-growth effect, decaying with a 36h
  time constant) and band-dependent noise calibrated from the history's
  consecutive-read rank changes, correctly scaled by sqrt(dt):
  sigma 0.85 (rank <= 10), 2.04 (11-30), 3.18 (31-60), 3.69 (> 60) ranks
  per sqrt-hour, times 1.2.
- Games leave the chart (dropout + 28-day age-out from `created`, or
  first-seen + 28d when `created` is unknown) and can re-enter; brand-new
  games are covered by the unnamed share (25% per place).
- P(game at place k) = frequency over (3000 paths x 72 hours).

## Backtest (local, train/test split of the kit history)

Scored with the official log-score formula against held-out reads:

| split | model | baseline (persistence) | margin |
|---|---|---|---|
| train <= 11-05, test 11 reads | -45.28 | -55.85 | +10.57 |
| train <= 11-06, test 8 reads | -40.94 | -52.13 | +11.18 |
| calibrated (sigma x1.2, unnamed 0.25) | -39.4 mean | -54.0 mean | +14.5 |

Official practice baseline is -43.512039. The model beats persistence by a
wide margin on both splits.

## Files

- `main.py` — the entrypoint (deterministic, ~13s on this machine)
- `LICENSE` — MIT
- `.makefun/owner.json` — claim file (agent wallet CTqrxd)
