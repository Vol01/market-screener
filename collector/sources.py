"""Data sources. Every fetcher returns plain pandas objects and never raises:
a failed source is reported in `errors` and the rest of the page still builds."""

import os
import time
import json
import numpy as np
import pandas as pd
import requests

from universe import (CRYPTO_EXCLUDE_IDS, CRYPTO_EXCLUDE_SYMBOL_HINTS,
                      CRYPTO_TOP_N, CRYPTO_EXIT_RANK)

UA = {"User-Agent": "Mozilla/5.0 (market-screener; personal dashboard)"}
MOCK = os.environ.get("MOCK") == "1"
errors = []


def _err(where, e):
    msg = f"{where}: {type(e).__name__}: {e}"[:300]
    print("  ! " + msg)
    errors.append(msg)


def _get(url, params=None, headers=None, tries=4, timeout=30):
    h = dict(UA, **(headers or {}))
    for i in range(tries):
        r = requests.get(url, params=params, headers=h, timeout=timeout)
        if r.status_code == 429:
            wait = 20 * (i + 1)
            print(f"  rate limited by {url.split('/')[2]}, waiting {wait}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"rate limited: {url}")


# ---------------------------------------------------------------- Yahoo
def fetch_yahoo(tickers, period="2y"):
    """-> {ticker: DataFrame(close, volume)} indexed by date."""
    if MOCK:
        return _mock_yahoo(tickers)
    import yfinance as yf
    out = {}

    def take(df, t):
        try:
            if isinstance(df.columns, pd.MultiIndex):
                sub = df[t] if t in df.columns.get_level_values(0) else df.xs(t, axis=1, level=1)
            else:
                sub = df
            s = pd.DataFrame({"close": sub["Close"], "volume": sub.get("Volume")}).dropna(subset=["close"])
            if len(s) > 60:
                s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
                out[t] = s
        except Exception:
            pass

    chunks = [tickers[i:i + 40] for i in range(0, len(tickers), 40)]
    for ch in chunks:
        try:
            df = yf.download(ch, period=period, interval="1d", group_by="ticker", auto_adjust=True,
                             threads=True, progress=False)
            for t in ch:
                take(df, t)
        except Exception as e:
            _err("yahoo batch", e)
        time.sleep(2)
    missing = [t for t in tickers if t not in out]
    for t in missing:  # one retry, one by one
        try:
            df = yf.download(t, period=period, interval="1d", auto_adjust=True, progress=False)
            take(df, t)
        except Exception:
            pass
        time.sleep(1)
    still = [t for t in tickers if t not in out]
    if still:
        errors.append("yahoo: no data for " + ", ".join(still))
    print(f"  yahoo: {len(out)}/{len(tickers)} tickers")
    return out


# ---------------------------------------------------------------- FRED
def fetch_fred(series_ids, start="2023-01-01"):
    if MOCK:
        return _mock_fred(series_ids)
    key = os.environ.get("FRED_API_KEY")
    out = {}
    if not key:
        errors.append("fred: FRED_API_KEY is not set")
        return out
    for sid in series_ids:
        try:
            j = _get("https://api.stlouisfed.org/fred/series/observations",
                     {"series_id": sid, "api_key": key, "file_type": "json", "observation_start": start})
            obs = [(o["date"], o["value"]) for o in j.get("observations", []) if o["value"] not in (".", "")]
            s = pd.Series([float(v) for _, v in obs], index=pd.to_datetime([d for d, _ in obs]))
            out[sid] = s.sort_index()
        except Exception as e:
            _err(f"fred {sid}", e)
    print(f"  fred: {len(out)}/{len(series_ids)} series")
    return out


# ---------------------------------------------------------------- DefiLlama
def fetch_stablecoins():
    if MOCK:
        return _mock_line(700, 150e9, 0.0008, 0.002, daily=True)
    try:
        j = _get("https://stablecoins.llama.fi/stablecoincharts/all")
        idx = pd.to_datetime([int(x["date"]) for x in j], unit="s").normalize()
        vals = [x.get("totalCirculatingUSD", {}).get("peggedUSD", np.nan) for x in j]
        s = pd.Series(vals, index=idx).dropna()
        print(f"  defillama: {len(s)} days")
        return s[s.index >= pd.Timestamp.now() - pd.Timedelta(days=800)]
    except Exception as e:
        _err("defillama", e)
        return None


# ---------------------------------------------------------------- CoinGecko
CG = "https://api.coingecko.com/api/v3"


def _cg_headers():
    k = os.environ.get("COINGECKO_API_KEY")
    return {"x-cg-demo-api-key": k} if k else {}


def update_crypto_members(ranking, state, today):
    """Fixed-size top-N with hysteresis: a coin enters when it is in the top N,
    a member leaves only when it falls below CRYPTO_EXIT_RANK."""
    rank = {c["id"]: i + 1 for i, c in enumerate(ranking)}
    old = [m for m in state.get("members", []) if m in rank]
    keep = [m for m in old if rank[m] <= CRYPTO_EXIT_RANK]
    for c in ranking:
        if len(keep) >= CRYPTO_TOP_N:
            break
        if c["id"] not in keep:
            keep.append(c["id"])
    keep.sort(key=lambda m: rank[m])
    prev = set(state.get("members", []))
    added = [m for m in keep if m not in prev] if prev else []
    removed = [m for m in prev if m not in keep]
    state["members"] = keep
    state.setdefault("history", {})[today] = keep
    if added or removed:
        state.setdefault("log", []).append({"date": today, "in": added, "out": removed})
        state["log"] = state["log"][-60:]
    return keep, added, removed


def fetch_crypto(state, today):
    """-> (members [{id,symbol,name,rank,mcap}], {id: DataFrame(close, volume, mcap)}, added, removed)"""
    if MOCK:
        ranking = _mock_crypto_ranking()
    else:
        try:
            raw = _get(f"{CG}/coins/markets", {"vs_currency": "usd", "order": "market_cap_desc",
                                                "per_page": 60, "page": 1}, _cg_headers())
            ranking = [c for c in raw if c["id"] not in CRYPTO_EXCLUDE_IDS
                       and not any(h in c["symbol"].lower() for h in CRYPTO_EXCLUDE_SYMBOL_HINTS)]
        except Exception as e:
            _err("coingecko markets", e)
            return [], {}, [], []
    keep, added, removed = update_crypto_members(ranking, state, today)
    by_id = {c["id"]: c for c in ranking}
    members = [{"id": m, "symbol": by_id[m]["symbol"].upper(), "name": by_id[m]["name"],
                "rank": ranking.index(by_id[m]) + 1, "mcap": by_id[m].get("market_cap")} for m in keep]
    hist = {}
    for m in members:
        if MOCK:
            hist[m["id"]] = _mock_ohlc(700, daily=True, seed=hash(m["id"]) % 1000, mcap=m["mcap"])
            continue
        try:
            j = _get(f"{CG}/coins/{m['id']}/market_chart", {"vs_currency": "usd", "days": 365, "interval": "daily"},
                     _cg_headers())
            p = pd.DataFrame(j["prices"], columns=["ts", "close"])
            v = pd.DataFrame(j["total_volumes"], columns=["ts", "volume"])
            c = pd.DataFrame(j["market_caps"], columns=["ts", "mcap"])
            df = p.merge(v, on="ts").merge(c, on="ts")
            df.index = pd.to_datetime(df["ts"], unit="ms").dt.normalize()
            df = df[~df.index.duplicated(keep="last")][["close", "volume", "mcap"]]
            hist[m["id"]] = df
        except Exception as e:
            _err(f"coingecko {m['id']}", e)
            hist_y = _yahoo_crypto_fallback(m["symbol"])
            if hist_y is not None:
                hist[m["id"]] = hist_y
        time.sleep(0 if os.environ.get("COINGECKO_API_KEY") else 6)
    print(f"  coingecko: {len(hist)}/{len(members)} coins, members: {[m['symbol'] for m in members]}")
    return members, hist, added, removed


def _yahoo_crypto_fallback(sym):
    try:
        d = fetch_yahoo([f"{sym}-USD"], period="1y")
        df = d.get(f"{sym}-USD")
        if df is not None:
            df = df.copy()
            df["mcap"] = np.nan
            return df
    except Exception:
        pass
    return None


# ---------------------------------------------------------------- mock data (offline testing)
def _bdays(n):
    return pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)


def _mock_line(n, start, drift, vol, daily=False, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range(end=pd.Timestamp.today().normalize(), periods=n) if daily else _bdays(n)
    r = rng.normal(drift, vol, n)
    return pd.Series(start * np.exp(np.cumsum(r)), index=idx)


def _mock_ohlc(n, daily=False, seed=0, mcap=None):
    rng = np.random.default_rng(seed)
    drift = rng.normal(0.0003, 0.0006)
    vol = rng.uniform(0.006, 0.03)
    close = _mock_line(n, rng.uniform(20, 400), drift, vol, daily, seed)
    base = rng.uniform(1e6, 5e8)
    regime = 1 + 0.6 * np.sin(np.linspace(0, rng.uniform(3, 9), n) + rng.uniform(0, 6))
    volume = base * regime * rng.lognormal(0, 0.35, n) / close.values * 100
    df = pd.DataFrame({"close": close, "volume": volume})
    if mcap:
        df["mcap"] = close / close.iloc[-1] * mcap
    return df


def _mock_yahoo(tickers):
    out = {}
    for i, t in enumerate(tickers):
        df = _mock_ohlc(520, seed=i + 7)
        if t.endswith("=X") or t.startswith("^") or t == "DX-Y.NYB":
            df["volume"] = 0.0
        out[t] = df
    return out


def _mock_fred(ids):
    base = {"WALCL": 6.6e6, "WTREGEN": 8e5, "RRPONTSYD": 300, "DFII10": 1.8, "T10YIE": 2.3, "T10Y2Y": 0.4,
            "BAMLH0A0HYM2": 3.2}
    out = {}
    for i, s in enumerate(ids):
        line = _mock_line(700, 1.0, 0, 0.004, daily=True, seed=100 + i) * base.get(s, 1)
        if s in ("WALCL", "WTREGEN"):
            line = line.resample("W-WED").last()
        out[s] = line
    return out


def _mock_crypto_ranking():
    names = [("bitcoin", "btc", "Bitcoin", 1.8e12), ("ethereum", "eth", "Ethereum", 4.2e11),
             ("tether", "usdt", "Tether", 1.8e11), ("ripple", "xrp", "XRP", 1.3e11),
             ("binancecoin", "bnb", "BNB", 1.2e11), ("solana", "sol", "Solana", 9e10),
             ("usd-coin", "usdc", "USDC", 7e10), ("tron", "trx", "TRON", 2.6e10),
             ("dogecoin", "doge", "Dogecoin", 2.4e10), ("cardano", "ada", "Cardano", 2.0e10),
             ("hyperliquid", "hype", "Hyperliquid", 1.5e10), ("chainlink", "link", "Chainlink", 1.1e10),
             ("staked-ether", "steth", "Lido Staked Ether", 3e11)]
    rows = [{"id": a, "symbol": b, "name": c, "market_cap": d} for a, b, c, d in names]
    rows.sort(key=lambda r: -r["market_cap"])
    return [r for r in rows if r["id"] not in CRYPTO_EXCLUDE_IDS
            and not any(h in r["symbol"] for h in CRYPTO_EXCLUDE_SYMBOL_HINTS)]
