"""Pure calculations on aligned price/volume series. No network here."""

import numpy as np
import pandas as pd

H = (5, 21, 63)  # 1W, 1M, 3M in trading days


def clip_score(x, lo=-3, hi=3):
    if x is None or not np.isfinite(x):
        return None
    return int(max(lo, min(hi, round(x))))


def last(s):
    s = s.dropna()
    return float(s.iloc[-1]) if len(s) else np.nan


# ------------------------------------------------------------ instrument-level
def rs_raw(p, b, h):
    """Relative return of p vs benchmark b over h bars."""
    r = (p / p.shift(h)) / (b / b.shift(h)) - 1
    return r


def rs_z(p, b, h):
    """RS over h, normalised by the instrument's own history of h-bar RS moves."""
    r = rs_raw(p, b, h).dropna()
    if len(r) < h + 40:
        return np.nan, np.nan
    sd = r.iloc[-252:].std()
    now = r.iloc[-1]
    if not np.isfinite(sd) or sd < 1e-12:  # instrument is its own benchmark
        return float(now), 0.0
    return float(now), float(now / sd)


def trend_score(p):
    p = p.dropna()
    if len(p) < 60:
        return None
    long_n = 200 if len(p) >= 210 else 100
    ma50, mal = p.rolling(50).mean().iloc[-1], p.rolling(long_n).mean().iloc[-1]
    c = p.iloc[-1]
    s = (1 if c > ma50 else -1) + (1 if c > mal else -1) + (1 if ma50 > mal else -1)
    return int(s)


def dollar_volume(df):
    if "volume" not in df or df["volume"].isna().all() or (df["volume"].fillna(0) <= 0).mean() > 0.5:
        return None
    return (df["close"] * df["volume"]).where(df["volume"] > 0)


def rel_volume(dv, short=20, long=120):
    if dv is None:
        return np.nan
    dv = dv.dropna()
    if len(dv) < long:
        return np.nan
    return float(dv.iloc[-short:].mean() / dv.iloc[-long:].mean())


def accumulation(df, n=20):
    """(volume on up days - volume on down days) / total volume over n bars, in [-1, 1]."""
    dv = dollar_volume(df)
    if dv is None:
        return np.nan
    ch = df["close"].diff()
    d = pd.DataFrame({"dv": dv, "ch": ch}).dropna().iloc[-n:]
    tot = d["dv"].sum()
    if not tot:
        return np.nan
    return float((d.loc[d.ch > 0, "dv"].sum() - d.loc[d.ch < 0, "dv"].sum()) / tot)


def above_ma50(p):
    p = p.dropna()
    if len(p) < 55:
        return np.nan
    return float(p.iloc[-1] > p.rolling(50).mean().iloc[-1])


def above_ma50_share(p, n=20):
    p = p.dropna()
    if len(p) < 50 + n:
        return np.nan
    ma = p.rolling(50).mean()
    return float((p.iloc[-n:] > ma.iloc[-n:]).mean())


def signal(ret21, relvol, acc, trend, rs21s):
    """Plain-language reading of price + volume. Returns (text, tone)."""
    if not np.isfinite(relvol) or not np.isfinite(acc):
        if trend is not None and trend >= 2 and (rs21s or 0) >= 1:
            return "Uptrend, leading", 1
        if trend is not None and trend <= -2 and (rs21s or 0) <= -1:
            return "Downtrend, lagging", -1
        return "—", 0
    if ret21 > 0 and relvol >= 1.15 and acc >= 0.1:
        return "Money flowing in", 1
    if ret21 < 0 and relvol >= 1.15 and acc <= -0.1:
        return "Money flowing out", -1
    if ret21 > 0 and acc <= -0.1:
        return "Distribution", -1
    if ret21 < 0 and acc >= 0.1:
        return "Accumulation", 1
    if ret21 > 0.02 and relvol < 0.85:
        return "Rally without volume", 0
    if trend is not None and trend >= 2:
        return "Uptrend", 1
    if trend is not None and trend <= -2:
        return "Downtrend", -1
    return "—", 0


def instrument_stats(df, bench):
    p = df["close"]
    st = {}
    for h in H:
        raw, z = rs_z(p, bench, h)
        st[f"rs{h}"] = raw
        st[f"rs{h}z"] = z
    st["trend"] = trend_score(p)
    dv = dollar_volume(df)
    st["dv20"] = float(dv.dropna().iloc[-20:].mean()) if dv is not None and len(dv.dropna()) >= 20 else np.nan
    st["relvol"] = rel_volume(dv)
    st["acc"] = accumulation(df)
    st["ma50share"] = above_ma50_share(p)
    st["above50"] = above_ma50(p)
    pp = p.dropna()
    st["ret21"] = float(pp.iloc[-1] / pp.iloc[-22] - 1) if len(pp) > 22 else np.nan
    st["ret5"] = float(pp.iloc[-1] / pp.iloc[-6] - 1) if len(pp) > 6 else np.nan
    st["last"] = last(p)
    return st


def cells_from_stats(st, breadth=None, acc=None, relvol=None):
    """7 matrix cells: RS 1W, RS 1M, RS 3M, Trend, Volume, Accumulation, >MA50."""
    rv = st["relvol"] if relvol is None else relvol
    ac = st["acc"] if acc is None else acc
    ma = st["ma50share"] if breadth is None else breadth
    cells = [
        clip_score(st["rs5z"] * 1.5),
        clip_score(st["rs21z"] * 1.5),
        clip_score(st["rs63z"] * 1.5),
        st["trend"],
        clip_score(np.log2(rv) * 3) if np.isfinite(rv) and rv > 0 else None,
        clip_score(ac * 7.5) if np.isfinite(ac) else None,
        clip_score((ma - 0.5) * 6.5) if np.isfinite(ma) else None,
    ]
    raw = [st["rs5"], st["rs21"], st["rs63"], st["trend"], rv, ac, ma]
    return cells, [None if (v is None or (isinstance(v, float) and not np.isfinite(v))) else round(float(v), 4)
                   for v in raw]


# ------------------------------------------------------------ RRG
def rrg(p, b, n=50, m=10, tail=5, step=5):
    rs = (p / b).dropna()
    if len(rs) < n + m + tail * step:
        return None
    rr = 100 * rs / rs.rolling(n).mean()
    rm = 100 * rr / rr.rolling(m).mean()
    d = pd.DataFrame({"x": rr, "y": rm}).dropna()
    pts = d.iloc[::-1].iloc[::step].iloc[:tail].iloc[::-1]
    x, y = float(d.x.iloc[-1]), float(d.y.iloc[-1])
    x5, y5 = float(d.x.iloc[-6]), float(d.y.iloc[-6])
    return {"x": round(x, 3), "y": round(y, 3), "quad": quadrant(x, y), "quad5": quadrant(x5, y5),
            "tail": [[round(a, 3), round(c, 3)] for a, c in zip(pts.x, pts.y)]}


def quadrant(x, y):
    if x >= 100 and y >= 100:
        return "Leading"
    if x >= 100:
        return "Weakening"
    if y >= 100:
        return "Improving"
    return "Lagging"


# ------------------------------------------------------------ macro helpers
def z_change(s, h, window=504):
    """Change over h bars divided by the sd of h-bar changes (log for positive series)."""
    s = s.dropna()
    if len(s) < h + 30:
        return np.nan
    x = np.log(s) if (s > 0).all() else s
    ch = (x - x.shift(h)).dropna().iloc[-window:]
    sd = ch.std()
    return float(ch.iloc[-1] / sd) if sd else np.nan


def z_change_at(s, h, pos, window=504):
    s = s.dropna()
    s = s.iloc[:pos] if pos else s
    return z_change(s, h, window)


def pct_rank(s, window=252):
    s = s.dropna().iloc[-window:]
    if len(s) < 30:
        return np.nan
    return float((s < s.iloc[-1]).mean())


def change_over_days(s, days):
    s = s.dropna()
    if len(s) < 3:
        return np.nan
    t = s.index[-1] - pd.Timedelta(days=days)
    past = s[s.index <= t]
    if not len(past):
        return np.nan
    a, b = past.iloc[-1], s.iloc[-1]
    return float(b / a - 1) if a > 0 and b > 0 else float(b - a)


def spark(s, days=182, points=26):
    s = s.dropna()
    s = s[s.index >= s.index[-1] - pd.Timedelta(days=days)]
    if len(s) < 3:
        return []
    idx = np.linspace(0, len(s) - 1, min(points, len(s))).astype(int)
    v = s.iloc[idx].values
    lo, hi = v.min(), v.max()
    rng = hi - lo or 1
    return [round(float(10 + 90 * (a - lo) / rng), 1) for a in v]
