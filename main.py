"""btc-cent-forecast-01 entry: volatility-scaled, shrunk momentum forecast.

Strategy (designed with gpt-6-astra as quant consultant; see README.md):
  - Work in log prices. Signal S blends multi-window momentum with an
    EMA-trend term, both extrapolated to the 240-minute horizon:
        M = 0.45 * (4 * r60) + 0.35 * r240 + 0.20 * (r720 / 3)
        E = 0.70 * 4 * (logEMA30 - logEMA180) + 0.30 * (logEMA180 - logEMA720)
        S = 0.75 * M + 0.25 * E
    where rW = log(Pt) - log(Pt-W).
  - Robust 1-minute volatility sigma from the median absolute deviation of
    the last 720 one-minute log returns (fallback: max of the 240- and
    720-return estimates). Four-hour volatility V4h = Pt * sqrt(240) * sigma.
  - Forecast = Pt * exp(clip(SHRINKAGE * S, -Clog, +Clog)), with
    C$ = min(0.75 * V4h, 0.012 * Pt).  SHRINKAGE = 0.10 (default).
    The forecast therefore stays close to persistence and can move at most
    ~0.75 of a recent 4h volatility (and never more than 1.2% of price).
  - MAE scoring rewards the conditional median, so the forecast is a
    deliberately partial move toward the trend estimate, never a full
    extrapolation. No mean-reversion or intraday-seasonal term: the
    consultant advised both are unstable on a single noisy pool.

Contract (from the kit's RULES.txt):
  - Reads every *.in in $MAKEFUN_INPUT_DIR (else /input), sorted by name.
    Each is UTF-8 JSON: {"schema": "makefun/btc-cent-case/v1", ...,
    "markets": [{"id": "btc-usdc", "prices": [4320 closes]}]}.
    A defensive fallback also accepts one price per line or CSV
    "timestamp,price" files (see _load_prices); the graded format is JSON.
  - Writes /output/<id>.out (or $MAKEFUN_OUTPUT_DIR) as exactly:
        {"forecasts": [{"case": "<id>", "price": <number>}]}
    price rounded to 5 decimals, inside (0, 10_000_000).
  - Stdlib only, deterministic (no randomness, no wall clock, no network),
    well under the 8 s / 1 CPU / 1024 MB per-case cap.
"""

import json
import math
import os
import statistics
import sys

# --- tunables (validated locally; see test/walkforward.py) -----------------
SHRINKAGE = 0.10          # base fraction of the trend signal applied
                          # (0.25 won the official 5 practice cases by 12%
                          # but lost on the denser 9-checkpoint grid by 7.6%;
                          # 0.10 keeps a 6% edge on the official 5 at only
                          # ~3% cost on the 9-point grid — see BUILD_LOG.md)
ADAPTIVE = False          # if True: 0.15 when r60/r240 disagree, 0.35 when
                          # r60, r240, r720 agree and |r240| > 0.5 * V4h (log)
W_MOM_60 = 0.45           # weight of 60-min momentum (x4 to 240-min scale)
W_MOM_240 = 0.35          # weight of 240-min momentum
W_MOM_720 = 0.20          # weight of 720-min momentum (/3 to 240-min scale)
W_EMA = 0.25              # weight of the EMA term in S (momentum: 0.75)
EMA_SPANS = (30, 180, 720)
VOL_WINDOW = 720          # returns used for the robust volatility estimate
CAP_VOL_MULT = 0.75       # cap as a multiple of recent 4h volatility
CAP_PCT = 0.012           # hard cap as a fraction of the last price

MIN_PRICE = 0.00001
MAX_PRICE = 9_999_999.99999


def price5(x):
    """x kept on the grid's 5 decimals and inside the scorer's (0, 10M)."""
    if not math.isfinite(x):
        raise ValueError("forecast is not finite")
    return round(min(MAX_PRICE, max(MIN_PRICE, x)) * 1e5) / 1e5


def _ema(log_prices, span):
    """Exponential moving average over log prices (stdlib only)."""
    alpha = 2.0 / (span + 1.0)
    out = log_prices[0]
    for v in log_prices[1:]:
        out += alpha * (v - out)
    return out


def _robust_sigma(log_rets):
    """1.4826 * MAD of log returns; 0.0 when degenerate."""
    if not log_rets:
        return 0.0
    med = statistics.median(log_rets)
    mad = statistics.median([abs(r - med) for r in log_rets])
    return 1.4826 * mad


def forecast(prices, shrinkage=SHRINKAGE, adaptive=ADAPTIVE):
    """Point forecast of the price 240 minutes after the last close."""
    clean = [p for p in prices if isinstance(p, (int, float))
             and math.isfinite(p) and p > 0]
    if not clean:
        raise ValueError("no usable prices")
    last = clean[-1]
    if len(clean) < 721:
        # Not enough history to form the signals: fall back to persistence.
        return price5(last)

    logs = [math.log(p) for p in clean]
    n = len(logs)

    def ret(w):
        return logs[-1] - logs[-1 - w]

    r60, r240, r720 = ret(60), ret(240), ret(720)
    m = W_MOM_60 * (4.0 * r60) + W_MOM_240 * r240 + W_MOM_720 * (r720 / 3.0)
    e30, e180, e720 = (_ema(logs, s) for s in EMA_SPANS)
    e = 0.70 * 4.0 * (e30 - e180) + 0.30 * (e180 - e720)
    s = (1.0 - W_EMA) * m + W_EMA * e

    # Robust 4h volatility: max of the 240- and 720-return MAD estimates.
    rets = [logs[i] - logs[i - 1] for i in range(1, n)]
    sig = max(_robust_sigma(rets[-240:]), _robust_sigma(rets[-VOL_WINDOW:]))
    v4h_log = math.sqrt(240.0) * sig  # in log points

    k = shrinkage
    if adaptive:
        if (r60 > 0) != (r240 > 0):
            k = 0.15
        elif (r60 > 0) == (r240 > 0) == (r720 > 0) and abs(r240) > 0.5 * v4h_log:
            k = 0.35
    delta = k * s

    cap_log = math.log1p(min(CAP_VOL_MULT * v4h_log, CAP_PCT))
    delta = max(-cap_log, min(cap_log, delta))
    # Clamp in log space before exponentiating: exp() can never overflow,
    # and the result stays inside the scorer's price bounds by construction.
    log_pred = max(math.log(MIN_PRICE),
                   min(math.log(MAX_PRICE), math.log(last) + delta))
    return price5(math.exp(log_pred))


def _load_prices(path):
    """Prices from a case file.

    Canonical input is JSON with exactly one market holding a price list.
    The plain-text fallback (one price per line, or CSV "timestamp,price")
    runs ONLY when the file is not JSON at all. A JSON document with the
    wrong shape is rejected loudly instead of being silently mis-parsed:
    a malformed JSON case must fail, never produce a guess from stray
    numbers in its metadata. Returns (declared case id or None, prices).
    """
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    try:
        case = json.loads(text)
    except json.JSONDecodeError:
        return None, _load_prices_text(path, text)
    if not isinstance(case, dict):
        raise ValueError(f"{path}: case JSON is not an object")
    markets = case.get("markets")
    if not isinstance(markets, list) or len(markets) != 1:
        raise ValueError(f"{path}: expected exactly one market")
    market = markets[0]
    if not isinstance(market, dict):
        raise ValueError(f"{path}: market is not an object")
    prices = market.get("prices")
    if not isinstance(prices, list) or not prices:
        raise ValueError(f"{path}: market has no prices")
    try:
        out = [float(p) for p in prices]
    except (TypeError, ValueError):
        raise ValueError(f"{path}: prices are not numbers")
    return case.get("case"), out


def _load_prices_text(path, text):
    """Legacy plain-text fallback: one price per line, or CSV last column."""
    prices = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.replace(";", ",").split(",")]
        try:
            prices.append(float(parts[-1]))
        except ValueError:
            continue
    if not prices:
        raise ValueError(f"{path}: no prices found")
    return prices


def main():
    input_dir = os.environ.get("MAKEFUN_INPUT_DIR") or "/input"
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR") or "/output"
    os.makedirs(output_dir, exist_ok=True)
    names = sorted(f for f in os.listdir(input_dir) if f.endswith(".in"))
    if not names:
        raise SystemExit(f"no .in files in {input_dir}")
    for name in names:
        case_id = name[: -len(".in")]
        declared, prices = _load_prices(os.path.join(input_dir, name))
        # The filename is authoritative for the case id (the grader names
        # the output after the input file); a mismatched id inside the
        # JSON is a data error, not something to silently paper over.
        if declared is not None and declared != case_id:
            raise ValueError(
                f"{name}: case id {declared!r} != filename id {case_id!r}")
        out = {"forecasts": [{"case": case_id, "price": forecast(prices)}]}
        with open(os.path.join(output_dir, f"{case_id}.out"),
                  "w", encoding="utf-8") as fh:
            fh.write(json.dumps(out) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
