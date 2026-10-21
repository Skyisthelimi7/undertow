"""Correlations between every Buy & sell variable and the price. Pure functions; scan.py runs them once an hour.

Market cap is price times supply, and supply is fixed for these coins, so a market cap change is the price change and
one set of columns covers both. Four questions, each a rank (Spearman) correlation with its t, errors clustered by coin:
  size      does the variable just track market cap? (its level against log market cap, same reading)
  together  does it move with the price? (its change over the hour against the price change over the same hour)
  leads     does its change come first? (its change over the hour against the price change over the next hour)
  predicts  does its level say anything about what the price does next? (its level against the change over the next
            1, 4 and 12 hours), with the same figure for the earlier and the later half of the window: a correlation
            that flips sign between the halves is noise however large it looks.
The sample is the Buy & sell path: every scan's reading of every coin that passed every gate, thinned to one reading
per coin per hour so a coin's readings 15 minutes apart do not count as independent evidence. Variables worked out
from the price itself (its recent changes, distance from highs and lows) move with the price by construction, so
"together" is left blank for them."""
import bisect, math
from collections import defaultdict
from . import trade as TRD, attention as ATT, minute as MIN

H = 3600
# variables derived from the price: their co-movement with it is arithmetic, not evidence. Liquidity counts too: half a
# pool is the coin itself, so its dollar value moves with the price, and the ratios with market cap in them follow
PRICE_DERIVED = {"r15", "r30", "r3h", "ru6", "dd6", "vola", "hi_h", "c5m", "c1h", "c6h", "c24h", "dd24s", "mc", "liq",
                 "liq_pct", "lfdv", "turn", "exit", "m1", "m5", "m15", "m30", "up30", "dn30"}
# positive quantities compare on a log scale over the hour; the rest as plain differences
LOG_KEYS = {"mc", "liq", "v5m", "v1h", "v6h", "v24h", "hold", "xf", "tgm", "tr1h", "age", "web_age"}
GROUPS = [
    ("Price path", ("r15", "r30", "r3h", "ru6", "dd6", "vola", "hi_h", "c5m", "c1h", "c6h", "c24h", "dd24s")),
    ("Size and liquidity", ("mc", "liq", "liq_pct", "lfdv", "age", "exit")),
    ("Trading", ("v5m", "v1h", "v6h", "v24h", "turn", "v1h_24", "v6h_24", "bs1h", "bs24h", "nf1h", "nf1h_liq", "nf6h",
                 "nf24h", "ss1h", "tr1h", "brd1h", "liqc1h", "volc1h", "mom")),
    ("Holders", ("hold", "hc1h", "hc24h", "org", "top10", "rf")),
    ("Attention", tuple(ATT.KEYS) + ("tgm", "tgr")),
    ("Market", ("mkt1h", "sol24")),
    ("Minute data", tuple(MIN.KEYS)),
]


def group_of(key):
    for g, keys in GROUPS:
        if key in keys:
            return g
    return "Other"


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def ranks(xs):
    """Average ranks (ties share their mean rank), 0-based."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


try:                                   # numpy when the scan has it (the models' install brings it); same result without
    import numpy as _np
except ImportError:
    _np = None


def _np_ranks(a):
    order = a.argsort(kind="mergesort")
    r = _np.empty(len(a))
    r[order] = _np.arange(len(a), dtype=float)
    _v, inv, cnt = _np.unique(a, return_inverse=True, return_counts=True)
    return (_np.bincount(inv, weights=r) / cnt)[inv]


def _np_spearman_t(xs, ys, groups):
    x, y = _np.asarray(xs, float), _np.asarray(ys, float)
    n = len(x)
    rx, ry = _np_ranks(x), _np_ranks(y)
    sx, sy = rx.std(), ry.std()
    if not sx or not sy:
        return None
    prod = (rx - rx.mean()) / sx * ((ry - ry.mean()) / sy)
    rho = float(prod.mean())
    _g, codes = _np.unique(_np.asarray(groups), return_inverse=True)
    k = int(codes.max()) + 1 if n else 0
    s = _np.bincount(codes, weights=prod - rho, minlength=k)
    se = math.sqrt(float((s * s).sum()) * k / (k - 1)) / n if k > 1 else None
    return {"rho": rho, "t": rho / se if se else None, "n": n, "coins": k}


def spearman_t(xs, ys, groups):
    """Spearman's rho with a t from errors clustered by group: rho is the mean product of the standardised ranks, and
    its standard error comes from the spread of each group's summed deviations. {rho, t, n, coins} or None."""
    n = len(xs)
    if n < 10:
        return None
    if _np is not None:
        return _np_spearman_t(xs, ys, groups)
    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx) / n)
    sy = math.sqrt(sum((b - my) ** 2 for b in ry) / n)
    if not sx or not sy:
        return None
    prod = [(a - mx) / sx * (b - my) / sy for a, b in zip(rx, ry)]
    rho = sum(prod) / n
    by = defaultdict(float)
    for p, g in zip(prod, groups):
        by[g] += p - rho
    k = len(by)
    se = math.sqrt(sum(v * v for v in by.values()) * k / (k - 1)) / n if k > 1 else None
    return {"rho": rho, "t": rho / se if se else None, "n": n, "coins": k}


def hourly(path):
    """{mint: [(ts, price, f, liq)]}: each coin's first passing reading in each hour, from the Buy & sell path."""
    out = {}
    for mint, rows in path.items():
        seen, lst = set(), []
        for ts, st, price, liq, _c, f in rows:
            hb = int(ts // H)
            if st == "I" and f and price and hb not in seen:
                seen.add(hb)
                lst.append((ts, price, f, liq))
        if lst:
            out[mint] = lst
    return out


def price_after(rows, ts, hours, tol_h=1.0):
    """The first scan price at or after ts + hours (within tol_h), from a coin's full path rows."""
    lo, hi = 0, len(rows)
    t = ts + hours * H
    while lo < hi:
        mid = (lo + hi) // 2
        if rows[mid][0] < t:
            lo = mid + 1
        else:
            hi = mid
    for j in range(lo, min(lo + 6, len(rows))):
        if rows[j][0] > t + tol_h * H:
            break
        if rows[j][2]:
            return rows[j][2]
    return None


def change(key, a, b):
    """The variable's change from a to b: a log ratio for positive quantities, else the difference."""
    if key in LOG_KEYS:
        return math.log(b / a) if a and b and a > 0 and b > 0 else None
    return b - a


def analyse(path, now, cfg, keys=None, labels=None):
    """Every variable's four correlations. path: {mint: [(ts, state, price, liq, c1h, f)]} ascending."""
    keys = list(keys or TRD.VAR_KEYS)
    labels = labels or {k: (l, u) for k, l, u in TRD.VARIABLES}
    hz = list(cfg["horizons_h"])
    pts = hourly(path)
    # forward price changes and the reading an hour earlier, once per point
    rec = []
    for mint, lst in pts.items():
        rows = path[mint]
        prev = None
        for ts, price, f, liq in lst:
            fwd = {}
            for h in hz:
                p2 = price_after(rows, ts, h)
                fwd[h] = (p2 / price - 1) * 100 if p2 else None
            back = prev if prev and 40 * 60 <= ts - prev[0] <= 80 * 60 else None
            rec.append((ts, mint, price, f, fwd, back))
            prev = (ts, price, f)
    rec.sort(key=lambda r: r[0])
    mid = rec[len(rec) // 2][0] if rec else now
    out = {"ts": now, "points": len(rec), "coins": len(pts), "since": rec[0][0] if rec else None, "horizons": hz,
           "mid": mid, "vars": []}
    for k in keys:
        row = {"key": k, "label": labels.get(k, (k, ""))[0], "unit": labels.get(k, (k, ""))[1], "group": group_of(k),
               "price_derived": k in PRICE_DERIVED}
        lv = [(r[0], r[1], r[3][k], r) for r in rec if _num(r[3].get(k))]
        row["n"] = len(lv)
        if len(lv) < cfg["min_n"]:
            out["vars"].append(row)
            continue
        if k != "mc":
            xs = [(v, math.log10(r[3]["mc"])) for _t, _m, v, r in lv if _num(r[3].get("mc")) and r[3]["mc"] > 0]
            row["size"] = _rnd(spearman_t([a for a, _ in xs], [b for _, b in xs], [m for _t, m, _v, r in lv
                                                                                 if _num(r[3].get("mc")) and r[3]["mc"] > 0]))
        row["predicts"] = {}
        for h in hz:
            sel = [(t, m, v, r[4][h]) for t, m, v, r in lv if r[4][h] is not None]
            if len(sel) < cfg["min_n"]:
                continue
            res = spearman_t([s[2] for s in sel], [s[3] for s in sel], [s[1] for s in sel]) or {}
            a = [s for s in sel if s[0] < mid]
            b = [s for s in sel if s[0] >= mid]
            r1 = spearman_t([s[2] for s in a], [s[3] for s in a], [s[1] for s in a]) if len(a) >= 30 else None
            r2 = spearman_t([s[2] for s in b], [s[3] for s in b], [s[1] for s in b]) if len(b) >= 30 else None
            res["rho1"], res["rho2"] = (r1 or {}).get("rho"), (r2 or {}).get("rho")
            res["verdict"] = verdict(res, cfg)
            row["predicts"][str(h)] = _rnd(res)
        # changes over the hour: with the price over the same hour, and with the price over the next hour
        ch = []
        for t, m, v, r in lv:
            back = r[5]
            if not back or not _num(back[2].get(k)):
                continue
            d = change(k, back[2][k], v)
            if d is None:
                continue
            ch.append((t, m, d, (r[2] / back[1] - 1) * 100 if back[1] else None, r[4].get(1)))
        if not row["price_derived"]:
            sel = [c for c in ch if c[3] is not None]
            if len(sel) >= cfg["min_n"]:
                row["together"] = _rnd(spearman_t([c[2] for c in sel], [c[3] for c in sel], [c[1] for c in sel]))
        sel = [c for c in ch if c[4] is not None]
        if len(sel) >= cfg["min_n"]:
            res = spearman_t([c[2] for c in sel], [c[4] for c in sel], [c[1] for c in sel]) or {}
            res["verdict"] = verdict(res, cfg)
            row["leads"] = _rnd(res)
        out["vars"].append(row)
    return out


def verdict(res, cfg):
    if not res or res.get("rho") is None:
        return "collecting"
    if res.get("coins", 0) < cfg["min_coins"]:
        return "collecting"
    strong = abs(res["rho"]) >= cfg["min_rho"] and abs(res.get("t") or 0) >= cfg["z"]
    if "rho1" in res:
        r1, r2 = res.get("rho1"), res.get("rho2")
        strong = strong and r1 is not None and r2 is not None and r1 * r2 > 0 and r1 * res["rho"] > 0
    return "holds" if strong else "weak"


def _rnd(d):
    if not d:
        return d
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


# ---------------------------------------------------------------- minute horizons
def _after(ts_list, rows, t, tol):
    """The first minute price at or after t (within tol seconds) from one coin's readings."""
    j = bisect.bisect_left(ts_list, t)
    while j < len(rows) and rows[j]["ts"] <= t + tol:
        if rows[j].get("price"):
            return rows[j]["price"]
        j += 1
    return None


def analyse_fast(coins, passing, feeds, now, cfg):
    """Every minute variable (minute.py) against the price change over the next few minutes: the question quick rules
    bet on. coins: (mint, its minute readings ascending) for each coin (store.ticks_by_coin); passing: [(scan time,
    {mints passing every gate})] ascending (store.passing_sets); feeds: DEX Screener feed entries (for ad impressions).
    A reading counts when its coin passed every gate at the scan before the one running at the time (the gates quick
    rules could have known), one reading per coin every every_min minutes so a coin's minutes do not count as
    independent evidence. Returns the same shape as analyse(), with horizons in minutes."""
    hz = list(cfg["fast_horizons_min"])
    every = cfg["fast_every_min"] * 60
    ads = MIN.Ads(feeds)
    scan_ts = [p[0] for p in passing]
    rec = []
    for m, rows in coins:
        ts_list = [t["ts"] for t in rows]
        coin, last = MIN.Coin(), -1e18
        for t in rows:
            coin.add(t)
            if t["ts"] - last < every or not t.get("price"):
                continue
            j = bisect.bisect_right(scan_ts, t["ts"]) - 2         # the scan before the one running at this minute
            if j < 0 or m not in passing[j][1] or t["ts"] - scan_ts[j] > cfg["fast_stale_min"] * 60:
                continue
            fwd = {}
            for h in hz:
                p2 = _after(ts_list, rows, t["ts"] + h * 60, max(120, h * 12))
                fwd[h] = (p2 / t["price"] - 1) * 100 if p2 else None
            if all(v is None for v in fwd.values()):
                continue
            rec.append((t["ts"], m, MIN.features(coin, t, ads.at(m, t["ts"])), fwd))
            last = t["ts"]
    rec.sort(key=lambda r: r[0])
    mid = rec[len(rec) // 2][0] if rec else now
    labels = {k: (l, u) for k, l, u in MIN.VARIABLES}
    out = {"ts": now, "points": len(rec), "coins": len({r[1] for r in rec}), "since": rec[0][0] if rec else None,
           "horizons_min": hz, "mid": mid, "every_min": cfg["fast_every_min"], "vars": []}
    for k in MIN.KEYS:
        row = {"key": k, "label": labels[k][0], "unit": labels[k][1], "group": "Minute data",
               "price_derived": k in PRICE_DERIVED}
        lv = [(r[0], r[1], r[2][k], r[3]) for r in rec if _num(r[2].get(k))]
        row["n"] = len(lv)
        row["predicts"] = {}
        for h in hz:
            sel = [(t, m, v, fw[h]) for t, m, v, fw in lv if fw[h] is not None]
            if len(sel) < cfg["min_n"]:
                continue
            res = spearman_t([x[2] for x in sel], [x[3] for x in sel], [x[1] for x in sel]) or {}
            a = [x for x in sel if x[0] < mid]
            b = [x for x in sel if x[0] >= mid]
            r1 = spearman_t([x[2] for x in a], [x[3] for x in a], [x[1] for x in a]) if len(a) >= 30 else None
            r2 = spearman_t([x[2] for x in b], [x[3] for x in b], [x[1] for x in b]) if len(b) >= 30 else None
            res["rho1"], res["rho2"] = (r1 or {}).get("rho"), (r2 or {}).get("rho")
            res["verdict"] = verdict(res, cfg)
            row["predicts"][str(h)] = _rnd(res)
        out["vars"].append(row)
    return out
