# BTC 4-Hour Forecast — make.fun `btc-cent-forecast-01`

Entry for the make.fun bounty "Forecast Bitcoin's price 4 hours ahead,
12 times over 48 hours" ($250, deadline Sun 15 Nov 2026 15:00 WIB).
**Status: built and locally verified. NOT submitted** — submission (public
GitHub repo + Solana wallet + transcripts) is Ilham's step, not included here.

## Files in this folder

| File | Role |
|---|---|
| `main.py` | The entry (Python 3.13, stdlib only). This + `README.md` + `LICENSE` are the submission. |
| `README.md` | This file. |
| `LICENSE` | MIT (copied from the kit's starter). |
| `BUILD_LOG.md` | Full build log: kit, GPT-6 Astra consultations, validation numbers. |
| `btc-cent-forecast-01-kit/` | The official kit downloaded from make.fun (local scaffolding only, not submitted). |
| `test/` | Local scoring scripts (`score_local.py`, `walkforward.py`, `walkforward2.py`, `sign_check.py`). |
| `out/` | Outputs of the last local run on the 6 practice cases. |

## Strategy (designed with gpt-6-astra as quant consultant)

Work in log prices. The forecast is the last price moved a small, capped
amount toward a blended trend signal:

- Momentum `M = 0.45·(4·r60) + 0.35·r240 + 0.20·(r720/3)`, where `rW` is the
  log-return over the last W minutes. Each term is extrapolated to the
  240-minute horizon.
- EMA trend `E = 0.70·4·(logEMA30 − logEMA180) + 0.30·(logEMA180 − logEMA720)`.
- Combined signal `S = 0.75·M + 0.25·E`.
- Robust 1-minute volatility σ from the median absolute deviation of the
  last 720 one-minute log returns (max of the 240- and 720-return
  estimates); four-hour volatility `V4h = Pt·√240·σ`.
- Forecast `P̂ = Pt · exp(clip(0.10·S, −Clog, +Clog))`, with
  `C$ = min(0.75·V4h, 0.012·Pt)`.

Why this shape: MAE scoring rewards the conditional **median**, so the
forecast is a deliberately partial move toward the trend — never a full
extrapolation. The cap (≈0.75 of a recent 4h volatility, max 1.2% of
price) bounds the damage when the trend reverses. No mean-reversion or
intraday-seasonal term: both were judged unstable on a single noisy pool
(cbBTC/USDC Orca Whirlpool, not an index).

Shrinkage 0.10 was chosen after validation (see BUILD_LOG.md): it beats
persistence on the official practice cases while staying close to
persistence on a denser checkpoint grid, where stronger momentum (0.25)
lost badly. The evidence is genuinely mixed — 9 local checkpoints cannot
settle whether 4h BTC momentum has a real edge — so the small tilt is the
defensible choice. GPT-6 Astra reviewed the final code and agreed with
keeping 0.10.

## Contract (from the kit's RULES.txt)

- Input: `/input/<id>.in`, UTF-8 JSON, schema `makefun/btc-cent-case/v1`,
  one market `btc-usdc` with 4,320 one-minute closes (72h up to the
  checkpoint; last price = checkpoint close). The program reads every
  `*.in` in `$MAKEFUN_INPUT_DIR` (else `/input`), in name order.
- Output: `/output/<id>.out` (or `$MAKEFUN_OUTPUT_DIR`), exactly
  `{"forecasts": [{"case": "<id>", "price": <number>}]}` — one row, price
  finite, in (0, 10,000,000), rounded to 5 decimals.
- Stdlib only, offline, deterministic, ≤8 s / 1 CPU / 1024 MB per case.
- Score = mean absolute error in cents over the cases; a prize needs a
  score **strictly below** the house persistence baseline (guess = last
  price) and every case valid.

Assumptions (documented, per the brief): if a case file is not JSON, a
plain-text fallback accepts one price per line or CSV `timestamp,price`.
A JSON file with the wrong shape is **rejected** (exit non-zero) rather
than guessed from stray numbers. If fewer than 721 usable prices are
present, the forecast falls back to persistence (last price).

## Local results

Practice cases p00–p05 come from the kit. Ground truth for p00–p04 is
derived from the next case's checkpoint close (checkpoints are 4h apart,
so p0k's target is p0(k+1)'s last price); p05's target (2026-11-11
06:00Z) is **not in the kit**, so only 5 cases are scored locally.
The derivation is validated: the persistence error on p01 reproduces the
RULES.txt worst case ($766.9679) exactly.

| | MAE (cents) | MAE ($) |
|---|---|---|
| This entry (shrinkage 0.10) | **44,239.14** | $442.39 |
| Persistence baseline | 47,054.66 | $470.55 |
| Improvement | −2,815.52 (−5.98%) | |

Per case (cents): p00 32,428 (persist 31,711), p01 72,352 (76,697),
p02 33,906 (47,033), p03 56,103 (56,685), p04 26,406 (23,147).
Official 6-case persistence MAE (RULES.txt): 44,521.58 cents — our
5-case MAE is already below that figure, but p05 is unscored, so no
6-case claim is made.

Caveat: on a denser 9-checkpoint grid (every 2h over the same recording)
persistence wins (49,643c vs our 51,106c). The trend edge is small and
regime-dependent; the final (12 fresh cases, 15–17 Nov) may go either way.

## Verification

- `grade-local`: **not available for this bounty** — the scorer and
  reference data stay on make.fun's server; `grade-local` refuses the kit
  (RULES.txt / requirements). Local scoring above is our own harness.
- Two runs on the same practice input: **byte-identical** outputs.
- Runtime: ~0.12 s for all 6 practice cases (~0.02 s/case; limit 8 s).
- Imports: `json, math, os, statistics, sys` — stdlib only.
- Edge tests: malformed-JSON case is rejected (non-zero exit); plain-text
  input still works; short series falls back to persistence.

## Run locally

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=btc-cent-forecast-01-kit/input MAKEFUN_OUTPUT_DIR=out python3 main.py
python3 test/score_local.py out
```

## Still needed to submit (Ilham's part — not done here)

1. Public GitHub repo created after the competition opened, containing
   `main.py` (+ `README.md`, `LICENSE`), MIT licensed.
2. A Solana wallet linked to the make.fun account `@tunnelbluu`
   (currently none linked) — the wallet signs the entry and receives
   any prize in USDC.
3. Transcript bundle of the agent sessions that built the entry
   (`node cli/makefun.mjs bundle` from inside the unpacked kit).
4. Submit before **Sun 15 Nov 2026 15:00 WIB** (08:00 UTC).
