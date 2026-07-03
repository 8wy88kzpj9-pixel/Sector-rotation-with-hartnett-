#!/usr/bin/env python3
"""
US Sector & Theme Rotation Tracker — daily data pipeline.

Discipline:
- Sourced-or-null: a ticker that fails to download or has insufficient history
  is EXCLUDED and logged in data_quality. It is never estimated.
- A theme with < 60% valid members gets null metrics + a flag.
- RRG values are a documented z-score APPROXIMATION of JdK RS-Ratio/RS-Momentum,
  computed on weekly data. Quadrant flips on daily data are noise by design,
  so RRG is weekly-only.

Outputs:
  data.json     — full snapshot for the viewer (overwritten daily)
  history.json  — rolling 60-day breadth/return history per theme (appended)
"""

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).parent
BASKETS_FILE = ROOT / "baskets.json"
DATA_FILE = ROOT / "data.json"
HISTORY_FILE = ROOT / "history.json"

MIN_VALID_FRACTION = 0.6      # theme needs >= 60% members with data
HISTORY_DAYS = 60             # rolling history window
TRADING_DAYS = {"1D": 1, "1W": 5, "1M": 21, "3M": 63}


def log(msg):
    print(f"[rotation] {msg}", flush=True)


def load_baskets():
    with open(BASKETS_FILE) as f:
        return json.load(f)


def download_prices(tickers, period="16mo"):
    """Download daily OHLCV. Returns (close_df, volume_df, failed_list)."""
    log(f"downloading {len(tickers)} tickers...")
    df = yf.download(
        tickers=tickers, period=period, interval="1d",
        auto_adjust=True, group_by="ticker", threads=True, progress=False,
    )
    closes, volumes, failed = {}, {}, []
    for t in tickers:
        try:
            sub = df[t] if len(tickers) > 1 else df
            c = sub["Close"].dropna()
            v = sub["Volume"].dropna()
            # need at least ~8 months of data for 3M returns + RRG warmup
            if len(c) < 170:
                failed.append(t)
                continue
            closes[t] = c
            volumes[t] = v
        except Exception:
            failed.append(t)
    close_df = pd.DataFrame(closes).sort_index()
    vol_df = pd.DataFrame(volumes).sort_index()
    log(f"ok={close_df.shape[1]} failed={len(failed)} {failed}")
    return close_df, vol_df, failed


def pct_return(series, days):
    if len(series) <= days:
        return None
    prev, last = series.iloc[-1 - days], series.iloc[-1]
    if prev == 0 or pd.isna(prev) or pd.isna(last):
        return None
    return round(float(last / prev - 1) * 100, 2)


def equal_weight_index(close_df, members):
    """Equal-weight index: mean of member prices normalized to 100 at first common date."""
    cols = [m for m in members if m in close_df.columns]
    if not cols:
        return None, []
    sub = close_df[cols].dropna(how="all")
    normed = sub.divide(sub.apply(lambda s: s.dropna().iloc[0])) * 100
    return normed.mean(axis=1).dropna(), cols


def breadth_above_20dma(close_df, members, offset=0):
    """% of valid members whose close (at -1-offset) is above their 20DMA."""
    above = total = 0
    for m in members:
        if m not in close_df.columns:
            continue
        s = close_df[m].dropna()
        if len(s) < 21 + offset:
            continue
        idx = -1 - offset
        px = s.iloc[idx]
        dma = s.iloc[idx - 19: len(s) + idx + 1].mean() if offset else s.iloc[-20:].mean()
        total += 1
        if px > dma:
            above += 1
    return round(float(above) / total * 100, 1) if total else None


def dollar_vol_ratio(close_df, vol_df, members):
    """(sum of 5D avg dollar volume) / (sum of 20D avg dollar volume) across members."""
    num = den = 0.0
    for m in members:
        if m not in close_df.columns or m not in vol_df.columns:
            continue
        dv = (close_df[m] * vol_df[m]).dropna()
        if len(dv) < 20:
            continue
        num += dv.iloc[-5:].mean()
        den += dv.iloc[-20:].mean()
    return round(float(num / den), 2) if den else None


def rrg_series(theme_index, bench_daily, window, trail):
    """Weekly z-score approximation of RS-Ratio / RS-Momentum. Returns trail list."""
    wk_theme = theme_index.resample("W-FRI").last().dropna()
    wk_bench = bench_daily.resample("W-FRI").last().dropna()
    joined = pd.concat([wk_theme, wk_bench], axis=1, keys=["t", "b"]).dropna()
    if len(joined) < window + trail + 2:
        return None
    rs = joined["t"] / joined["b"] * 100
    mean, std = rs.rolling(window).mean(), rs.rolling(window).std()
    ratio = 100 + (rs - mean) / std.replace(0, math.nan)
    roc = ratio.diff()
    m2, s2 = roc.rolling(window).mean(), roc.rolling(window).std()
    momentum = 100 + (roc - m2) / s2.replace(0, math.nan)
    pts = pd.concat([ratio, momentum], axis=1).dropna().iloc[-trail:]
    if pts.empty:
        return None
    return [[round(float(r), 2), round(float(m), 2)] for r, m in pts.values]


def quadrant(ratio, momentum):
    if ratio is None or momentum is None:
        return None
    if ratio >= 100 and momentum >= 100:
        return "Leading"
    if ratio < 100 and momentum >= 100:
        return "Improving"
    if ratio >= 100 and momentum < 100:
        return "Weakening"
    return "Lagging"


def main():
    baskets = load_baskets()
    bench = baskets["benchmark"]
    rrg_p = baskets["rrg_params"]

    all_tickers = {bench}
    for th in baskets["themes"]:
        all_tickers.update(th["members"])
    close_df, vol_df, failed = download_prices(sorted(all_tickers))

    if bench not in close_df.columns:
        log("FATAL: benchmark download failed — refusing to write partial data.json")
        sys.exit(1)

    bench_close = close_df[bench].dropna()
    as_of = str(close_df.index[-1].date())

    themes_out, rrg_out = [], {}
    for th in baskets["themes"]:
        members = th["members"]
        valid = [m for m in members if m in close_df.columns]
        frac = len(valid) / len(members) if members else 0
        entry = {
            "name": th["name"], "type": th["type"], "etfs": th.get("etfs", []),
            "members": members, "valid_members": valid,
            "insufficient_data": frac < MIN_VALID_FRACTION,
        }
        if frac < MIN_VALID_FRACTION:
            entry.update({k: None for k in
                          ["ret_1d", "ret_1w", "ret_1m", "ret_3m", "rel_1m_spy",
                           "breadth", "breadth_3d_ago", "dollar_vol_ratio", "quadrant"]})
            themes_out.append(entry)
            continue

        idx, _ = equal_weight_index(close_df, valid)
        rets = {p: pct_return(idx, d) for p, d in TRADING_DAYS.items()}
        spy_1m = pct_return(bench_close, TRADING_DAYS["1M"])
        entry["ret_1d"], entry["ret_1w"] = rets["1D"], rets["1W"]
        entry["ret_1m"], entry["ret_3m"] = rets["1M"], rets["3M"]
        entry["rel_1m_spy"] = (round(rets["1M"] - spy_1m, 2)
                               if rets["1M"] is not None and spy_1m is not None else None)
        entry["breadth"] = breadth_above_20dma(close_df, valid)
        entry["breadth_3d_ago"] = breadth_above_20dma(close_df, valid, offset=3)
        entry["dollar_vol_ratio"] = dollar_vol_ratio(close_df, vol_df, valid)

        trail = rrg_series(idx, bench_close, rrg_p["window_weeks"], rrg_p["trail_weeks"])
        if trail:
            rrg_out[th["name"]] = trail
            entry["quadrant"] = quadrant(*trail[-1])
        else:
            entry["quadrant"] = None
        themes_out.append(entry)

    spy_stats = {p: pct_return(bench_close, d) for p, d in TRADING_DAYS.items()}

    data = {
        "SEED_VERSION": baskets["SEED_VERSION"],
        "DATA_VERSION": as_of,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "benchmark": bench,
        "benchmark_returns": spy_stats,
        "rrg_params": rrg_p,
        "themes": themes_out,
        "rrg": rrg_out,
        "data_quality": {
            "failed_tickers": failed,
            "themes_flagged_insufficient": [t["name"] for t in themes_out if t["insufficient_data"]],
        },
    }
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=1)
    log(f"wrote data.json (DATA_VERSION={as_of})")

    # ---- rolling history for breadth-trend alerts ----
    history = []
    if HISTORY_FILE.exists():
        try:
            history = json.load(open(HISTORY_FILE))
        except Exception:
            history = []
    history = [h for h in history if h["date"] != as_of]  # idempotent re-runs
    history.append({
        "date": as_of,
        "themes": {t["name"]: {"breadth": t["breadth"], "ret_1d": t["ret_1d"]}
                   for t in themes_out},
    })
    history = sorted(history, key=lambda h: h["date"])[-HISTORY_DAYS:]
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, indent=1)
    log(f"wrote history.json ({len(history)} days)")


if __name__ == "__main__":
    main()
