"""Fetch everything, compute metrics, write docs/data.json.

Run:  python collector/build.py            (real data; needs FRED_API_KEY)
      MOCK=1 python collector/build.py     (synthetic data, offline test)
"""

import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
import sources as S  # noqa: E402
import metrics as M  # noqa: E402
from universe import CLASSES, BENCHMARK, FRED, all_yahoo_tickers  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(ROOT, "state", "state.json")
OUT = os.path.join(ROOT, "docs", "data.json")
HDAYS = {5: 7, 21: 30, 63: 91}


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not math.isfinite(float(o)) else round(float(o), 6)
    if isinstance(o, np.integer):
        return int(o)
    return o


def align(s, cal):
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s.reindex(s.index.union(cal)).ffill(limit=7).reindex(cal)


def align_df(df, cal):
    out = pd.DataFrame(index=cal)
    out["close"] = align(df["close"], cal)
    if "volume" in df:
        # volume is not forward-filled: a missing day has no volume
        v = df["volume"][~df["volume"].index.duplicated(keep="last")]
        out["volume"] = v.reindex(cal)
    return out


def main():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    state = load_state()
    print("Fetching Yahoo…")
    yh = S.fetch_yahoo(all_yahoo_tickers())
    print("Fetching FRED…")
    fred = S.fetch_fred(list(FRED))
    print("Fetching stablecoins…")
    stable = S.fetch_stablecoins()
    print("Fetching crypto top-10…")
    cmembers, chist, c_in, c_out = S.fetch_crypto(state, today)

    base = yh.get(BENCHMARK) if BENCHMARK in yh else yh.get("SPY")
    if base is None:
        raise SystemExit("No benchmark data (ACWI/SPY) — Yahoo is probably blocking. Aborting without overwriting data.json.")
    cal = base.index[base.index >= base.index[-1] - pd.Timedelta(days=730)]

    P = {t: align_df(df, cal) for t, df in yh.items()}

    # ---- crypto: members as coin-unit volume; CRYPTO10 = market-cap index
    mc_sum, vol_sum = None, None
    for m in cmembers:
        df = chist.get(m["id"])
        if df is None:
            continue
        d = pd.DataFrame({"close": df["close"], "volume": df["volume"] / df["close"]})
        P["CG:" + m["id"]] = align_df(d, cal)
        if "mcap" in df and df["mcap"].notna().any():
            mc = align(df["mcap"], cal)
            vu = df["volume"].reindex(cal)
            mc_sum = mc if mc_sum is None else mc_sum.add(mc, fill_value=0)
            vol_sum = vu if vol_sum is None else vol_sum.add(vu, fill_value=0)
    if mc_sum is not None:
        idx = mc_sum / 1e9
        P["CRYPTO10"] = pd.DataFrame({"close": idx, "volume": vol_sum / idx})
    crypto_cls = next(c for c in CLASSES if c["id"] == "crypto")
    crypto_cls["items"] = [{"t": "CG:" + m["id"], "n": m["name"], "sym": m["symbol"], "rank": m["rank"],
                            "new": m["id"] in c_in} for m in cmembers] + crypto_cls.get("extra", [])

    bench = P[BENCHMARK]["close"] if BENCHMARK in P else P["SPY"]["close"]

    # ---- recursive node builder
    def node(it, parent_close):
        df = P.get(it["t"])
        if df is None or df["close"].dropna().empty:
            return None
        st = M.instrument_stats(df, parent_close)
        kids = []
        for ch in it.get("items", []):
            k = node(ch, df["close"])
            if k:
                kids.append(k)
        breadth = None
        if kids:
            vals = [k["_st"]["above50"] for k in kids if np.isfinite(k["_st"]["above50"])]
            breadth = float(np.mean(vals)) if vals else None
        cells, raw = M.cells_from_stats(st, breadth=breadth)
        sig, tone = M.signal(st["ret21"], st["relvol"], st["acc"], st["trend"], cells[1])
        n = {"n": it["n"], "tk": it.get("sym") or it["t"], "cells": cells, "raw": raw, "sig": sig, "tone": tone,
             "_st": st}
        if it.get("rank"):
            n["rank"] = it["rank"]
            n["new"] = it.get("new", False)
        if it.get("noagg"):
            n["noagg"] = True
        if kids:
            n["children"] = kids
        return n

    def leaves(nodes):
        out = []
        for n in nodes:
            if n.get("noagg"):
                continue
            out += leaves(n["children"]) if n.get("children") else [n]
        return out

    classes_out = []
    for c in CLASSES:
        pdf = P.get(c["proxy"])
        if pdf is None or pdf["close"].dropna().empty:
            S.errors.append(f"class {c['name']}: proxy {c['proxy']} missing")
            continue
        st = M.instrument_stats(pdf, bench)
        items = [k for k in (node(it, pdf["close"]) for it in c["items"]) if k]
        lv = leaves(items)
        top = [n for n in items if not n.get("noagg")]
        # breadth now and 10 bars ago
        b_now = _breadth([_find_df(P, c, n) for n in lv], 0)
        b_prev = _breadth([_find_df(P, c, n) for n in lv], 10)
        # flow: dollar-volume weighted accumulation of top-level members; relvol of their summed volume
        dvs = [(n, n["_st"]["dv20"]) for n in top if np.isfinite(n["_st"]["dv20"])]
        totdv = sum(v for _, v in dvs)
        acc = (sum(n["_st"]["acc"] * v for n, v in dvs if np.isfinite(n["_st"]["acc"])) / totdv) if totdv else np.nan
        sumdv = None
        for n in top:
            df = _find_df(P, c, n)
            dv = M.dollar_volume(df) if df is not None else None
            if dv is not None:
                sumdv = dv if sumdv is None else sumdv.add(dv, fill_value=0)
        relvol = M.rel_volume(sumdv) if sumdv is not None else st["relvol"]
        if c["id"] == "crypto":
            relvol = st["relvol"]
        cells, raw = M.cells_from_stats(st, breadth=b_now, acc=acc, relvol=relvol)
        sig, tone = M.signal(st["ret21"], relvol, acc, st["trend"], cells[1])
        # concentration
        conc = "—"
        if totdv:
            lead_n, lead_v = max(dvs, key=lambda x: x[1])
            share = lead_v / totdv
            short = lead_n.get("tk") if len(lead_n["n"]) > 14 else lead_n["n"]
            conc = f"narrow: {short}" if share >= 0.5 else (f"led by {short}" if share >= 0.3 else "broad")
            conc_share = share
        else:
            conc_share = None
        # breadth label
        if b_now is None:
            btxt = "—"
        elif b_prev is not None and b_now - b_prev >= 0.1:
            btxt = "widening"
        elif b_prev is not None and b_now - b_prev <= -0.1:
            btxt = "narrowing"
        elif b_now >= 0.7:
            btxt = "broad"
        elif b_now <= 0.3:
            btxt = "narrow"
        else:
            btxt = "average"
        strength = {}
        for h in M.H:
            z = st[f"rs{h}z"]
            strength[str(h)] = (max(-3, min(3, z)) if np.isfinite(z) else 0) + (2 * acc if np.isfinite(acc) else 0)
        ratio = pdf["close"] / bench
        r63 = ratio.dropna().iloc[-63:]
        extreme = None
        if len(r63) == 63:
            if r63.iloc[-1] >= r63.max() and r63.iloc[-6] < r63.max():
                extreme = "high"
            elif r63.iloc[-1] <= r63.min() and r63.iloc[-6] > r63.min():
                extreme = "low"
        classes_out.append({
            "id": c["id"], "name": c["name"], "proxy": c["proxy"] if c["proxy"] != "CRYPTO10" else "top-10 index",
            "cells": cells, "raw": raw, "sig": sig, "tone": tone,
            "rs": {str(h): st[f"rs{h}"] for h in M.H}, "rsScore": {str(h): M.clip_score(st[f"rs{h}z"] * 1.5) for h in M.H},
            "strength": strength, "breadth": {"now": b_now, "prev": b_prev, "txt": btxt},
            "conc": {"txt": conc, "share": conc_share}, "dv20": st["dv20"], "relvol": relvol, "acc": acc,
            "rrg": M.rrg(pdf["close"], bench), "extreme": extreme,
            "children": [_strip(n) for n in items],
        })

    # ---- sector RRG inside US equities (vs SPY) for the change feed
    sector_rrg = {}
    if "SPY" in P:
        us = next(c for c in CLASSES if c["id"] == "us_eq")
        for it in us["items"]:
            if it.get("items") and it["t"] in P:
                r = M.rrg(P[it["t"]]["close"], P["SPY"]["close"])
                if r:
                    sector_rrg[it["n"]] = r

    overview = build_overview(P, fred, stable, cal, classes_out)
    changes = build_changes(classes_out, sector_rrg, overview, state, cmembers, today)

    data = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "asof": str(cal[-1].date()),
        "mock": S.MOCK,
        "errors": S.errors,
        "verdict": overview["verdict"],
        "conditions": overview["conditions"],
        "changes": changes,
        "classes": classes_out,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(clean(data), f, separators=(",", ":"))
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    state["last_run"] = data["generated"]
    state["regime_history"] = overview["verdict"]["regime"]["history"]
    with open(STATE, "w") as f:
        json.dump(state, f, indent=1)
    print(f"Wrote {OUT} ({os.path.getsize(OUT)//1024} KB), {len(S.errors)} warnings")


def _iter_items(items):
    for it in items:
        yield it
        yield from _iter_items(it.get("items", []))


def _find_df(P, c, n):
    tk = n["tk"]
    if tk in P:
        return P[tk]
    for it in _iter_items(c["items"]):
        if it.get("sym") == tk or it["t"] == tk:
            return P.get(it["t"])
    return None


def _breadth(dfs, lag):
    vals = []
    for df in dfs:
        if df is None:
            continue
        p = df["close"].dropna()
        if lag:
            p = p.iloc[:-lag]
        v = M.above_ma50(p)
        if np.isfinite(v):
            vals.append(v)
    return float(np.mean(vals)) if vals else None


def _strip(n):
    n = {k: v for k, v in n.items() if k != "_st"}
    if "children" in n:
        n["children"] = [_strip(k) for k in n["children"]]
    return n


# ------------------------------------------------------------ overview
def build_overview(P, fred, stable, cal, classes_out):
    def cl(t):
        return P[t]["close"] if t in P else None

    def ratio(a, b):
        x, y = cl(a), cl(b)
        return (x / y) if x is not None and y is not None else None

    def mean_z(series_list, h, pos=None):
        zs = []
        for s, sign in series_list:
            if s is None:
                continue
            z = M.z_change(s.iloc[:pos] if pos else s, h)
            if np.isfinite(z):
                zs.append(sign * z)
        return float(np.mean(zs)) if zs else np.nan

    t10yie = align(fred["T10YIE"], cal) if "T10YIE" in fred else None
    growth_in = [(ratio("CPER", "GLD"), 1), (ratio("XLY", "XLP"), 1), (ratio("HYG", "IEF"), 1)]
    infl_in = [(t10yie, 1), (ratio("DBC", "IEF"), 1), (ratio("TIP", "IEF"), 1)]

    def regime_at(pos=None):
        g, i = mean_z(growth_in, 63, pos), mean_z(infl_in, 63, pos)
        if not (np.isfinite(g) and np.isfinite(i)):
            return None, g, i
        name = ("Reflation" if i >= 0 else "Goldilocks") if g >= 0 else ("Stagflation" if i >= 0 else "Deflation")
        return name, g, i

    rname, g, i = regime_at()
    hist = []
    months = pd.Series(range(len(cal)), index=cal).groupby(cal.to_period("M")).last()
    for per, pos in list(months.items())[-12:]:
        nm, _, _ = regime_at(pos + 1)
        hist.append({"m": str(per), "r": nm})

    # risk appetite
    risk_parts = [("Stocks vs bonds", ratio("SPY", "IEF")), ("Credit vs treasuries", ratio("HYG", "IEF")),
                  ("Copper vs gold", ratio("CPER", "GLD")), ("USD/JPY (yen weaker)", cl("USDJPY=X"))]
    rz = [(n, M.z_change(s, 21)) for n, s in risk_parts if s is not None]
    rz = [(n, z) for n, z in rz if np.isfinite(z)]
    rscore = float(np.mean([z for _, z in rz])) if rz else np.nan
    risk = {"state": "Risk-on" if rscore > 0.35 else ("Risk-off" if rscore < -0.35 else "Neutral"),
            "tone": 1 if rscore > 0.35 else (-1 if rscore < -0.35 else 0), "score": rscore,
            "parts": [{"n": n, "z": z} for n, z in rz]}

    # breadth: tracked US single stocks
    us = next((c for c in classes_out if c["id"] == "us_eq"), None)
    stock_dfs = []
    for c in CLASSES:
        if c["id"] == "us_eq":
            for it in c["items"]:
                for s in it.get("items", []):
                    if s["t"] in P:
                        stock_dfs.append(P[s["t"]])
    b_now, b_prev = _breadth(stock_dfs, 0), _breadth(stock_dfs, 10)
    ew = ratio("RSP", "SPY")
    ew21 = M.change_over_days(ew, 30) if ew is not None else np.nan
    if b_now is None:
        bstate, btone = "—", 0
    elif b_prev is not None and b_now - b_prev <= -0.08:
        bstate, btone = "Narrowing", -1
    elif b_prev is not None and b_now - b_prev >= 0.08:
        bstate, btone = "Widening", 1
    elif b_now >= 0.65:
        bstate, btone = "Broad", 1
    elif b_now <= 0.35:
        bstate, btone = "Narrow", -1
    else:
        bstate, btone = "Stable", 0
    breadth = {"state": bstate, "tone": btone, "now": b_now, "prev": b_prev, "ew": ew21, "n": len(stock_dfs)}

    # liquidity inputs
    netliq = None
    if all(k in fred for k in ("WALCL", "WTREGEN", "RRPONTSYD")):
        idx = fred["WALCL"].index.union(fred["WTREGEN"].index).union(fred["RRPONTSYD"].index)
        w = fred["WALCL"].reindex(idx).ffill() / 1000
        t = fred["WTREGEN"].reindex(idx).ffill() / 1000
        r = fred["RRPONTSYD"].reindex(idx).ffill()
        netliq = (w - t - r).dropna()
    dxy = cl("DX-Y.NYB")
    ry = fred.get("DFII10")
    hy = fred.get("BAMLH0A0HYM2")
    vix = cl("^VIX")
    move = cl("^MOVE")

    cond_defs = [
        ("netliq", "Fed net liquidity", "money in the system", "FRED", netliq, 1, ("rising", "falling"), "bn"),
        ("dxy", "US dollar (DXY)", "price of money", "Yahoo", dxy, -1, ("strengthening", "weakening"), "lvl"),
        ("ry", "10Y real yield", "price of time", "FRED", ry, -1, ("rising", "falling"), "pct"),
        ("hy", "HY credit spreads", "credit stress", "FRED", hy, -1, ("widening", "tightening"), "pct"),
        ("vix", "VIX (equity fear)", "fear", "Yahoo", vix, -1, ("rising", "falling"), "lvl"),
        ("stable", "Stablecoin supply", "crypto money", "DefiLlama", stable, 1, ("growing", "shrinking"), "usd"),
    ]
    conditions = []
    liq_z = {h: [] for h in M.H}
    for cid, name, why, src, s, good, words, unit in cond_defs:
        if s is None or s.dropna().empty:
            conditions.append({"id": cid, "name": name, "why": why, "src": src, "missing": True})
            continue
        s = s.dropna()
        daily = align(s, cal)
        st = {}
        for h in M.H:
            z = M.z_change(daily, h)
            ch = M.change_over_days(s, HDAYS[h])
            if unit == "pct":  # yields / spreads: change in percentage points, not percent
                past = s[s.index <= s.index[-1] - pd.Timedelta(days=HDAYS[h])]
                ch = float(s.iloc[-1] - past.iloc[-1]) if len(past) else np.nan
            if not np.isfinite(z):
                st[str(h)] = {"txt": "—", "tone": 0, "chg": ch}
                continue
            if abs(z) < 0.5:
                txt, tone = "flat", 0
            else:
                txt = words[0] if z > 0 else words[1]
                tone = good * (1 if z > 0 else -1)
            st[str(h)] = {"txt": txt, "tone": tone, "chg": ch, "z": z}
            if cid in ("netliq", "dxy", "hy", "stable"):
                liq_z[h].append(good * z)
        conditions.append({"id": cid, "name": name, "why": why, "src": src, "value": float(s.iloc[-1]),
                           "unit": unit, "state": st, "spark": M.spark(s)})

    lz = {str(h): (float(np.mean(v)) if v else np.nan) for h, v in liq_z.items()}
    l21 = lz["21"]
    liquidity = {"state": "Expanding" if l21 > 0.35 else ("Contracting" if l21 < -0.35 else "Neutral"),
                 "tone": 1 if l21 > 0.35 else (-1 if l21 < -0.35 else 0), "score": lz}

    vp = [M.pct_rank(x) for x in (vix, move) if x is not None]
    vp = [x for x in vp if np.isfinite(x)]
    vpm = float(np.mean(vp)) if vp else np.nan
    vol = {"state": "Compressed" if vpm < 0.33 else ("Elevated" if vpm > 0.67 else "Normal"),
           "tone": 0 if vpm < 0.67 else -1, "pct": vpm,
           "vix": last_or_none(vix), "move": last_or_none(move)}

    verdict = {"regime": {"name": rname, "growth": g, "inflation": i, "history": hist},
               "risk": risk, "breadth": breadth, "liquidity": liquidity, "volatility": vol}
    return {"verdict": verdict, "conditions": conditions}


def last_or_none(s):
    if s is None:
        return None
    s = s.dropna()
    return float(s.iloc[-1]) if len(s) else None


# ------------------------------------------------------------ change feed
def build_changes(classes_out, sector_rrg, overview, state, cmembers, today):
    ch = []
    hist = overview["verdict"]["regime"]["history"]
    if len(hist) >= 2 and hist[-1]["r"] and hist[-2]["r"] and hist[-1]["r"] != hist[-2]["r"]:
        ch.append({"p": 100, "tone": 0, "i": "⇄", "t": f"Macro regime shifted: {hist[-2]['r']} → {hist[-1]['r']}."})
    good = {"Leading": 1, "Improving": 1, "Weakening": -1, "Lagging": -1}
    for c in classes_out:
        r = c.get("rrg")
        if r and r["quad"] != r["quad5"]:
            ch.append({"p": 80 if r["quad"] in ("Leading", "Lagging") else 60, "tone": good[r["quad"]],
                       "i": "↑" if good[r["quad"]] > 0 else "↓",
                       "t": f"{c['name']} moved from {r['quad5']} to {r['quad']} vs world equities."})
        if c.get("extreme") == "high":
            ch.append({"p": 70, "tone": 1, "i": "↑", "t": f"{c['name']}: new 3-month high in relative strength."})
        if c.get("extreme") == "low":
            ch.append({"p": 70, "tone": -1, "i": "↓", "t": f"{c['name']}: new 3-month low in relative strength."})
    for n, r in sector_rrg.items():
        if r["quad"] != r["quad5"] and r["quad"] in ("Leading", "Lagging"):
            ch.append({"p": 50, "tone": good[r["quad"]], "i": "↑" if good[r["quad"]] > 0 else "↓",
                       "t": f"US {n.lower()} moved into {r['quad']} vs the S&P 500."})
    b = overview["verdict"]["breadth"]
    if b["now"] is not None and b["prev"] is not None and abs(b["now"] - b["prev"]) >= 0.1:
        up = b["now"] > b["prev"]
        ch.append({"p": 75, "tone": 1 if up else -1, "i": "↑" if up else "↓",
                   "t": f"US breadth {'improved' if up else 'deteriorated'}: {round(b['now']*100)}% of tracked stocks "
                        f"above MA50 vs {round(b['prev']*100)}% two weeks ago."})
    names = {m["id"]: m["symbol"] for m in cmembers}
    cutoff = (pd.Timestamp(today) - pd.Timedelta(days=7)).strftime("%Y-%m-%d")
    for e in state.get("log", []):
        if e["date"] >= cutoff and (e["in"] or e["out"]):
            ins = ", ".join(names.get(x, x) for x in e["in"]) or "—"
            outs = ", ".join(x for x in e["out"]) or "—"
            ch.append({"p": 90, "tone": 0, "i": "⇄", "t": f"Crypto top-10 changed: in {ins}, out {outs}."})
    ch.sort(key=lambda x: -x["p"])
    return ch[:8]


if __name__ == "__main__":
    main()
