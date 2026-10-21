"""Buy/sell signal study (research only; merge.py says how to run it; needs numpy and scipy). Decision points every
15 minutes from 5-minute GeckoTerminal candles, entry features from the candles (and the scanner's records where they
exist), outcomes and exit simulations from later candles. Every decision point is at or after the time the scanner
first saw the token, so no token is chosen with hindsight."""
import json, os, glob, math, sqlite3, bisect
import numpy as np
from collections import defaultdict

H = 3600
STEP = 900                 # the scan cadence
C5 = 300
FEE = 1.0                  # % per side (pool + creator fees; PumpSwap's dynamic fees reach about 1% on small caps)
ORDER = 500.0              # USD per position, the screener's standard size


def load(study_dir, db_path, min_candles=60):
    ds = json.load(open(os.path.join(study_dir, "ds.json")))
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    fs = {r["mint"]: r["first_seen"] for r in db.execute("select mint, first_seen from tokens")}
    sym = {r["mint"]: r["symbol"] for r in db.execute("select mint, symbol from tokens")}
    trans = defaultdict(list)
    for r in db.execute("select ts, mint, to_ from transitions order by ts"):
        trans[r["mint"]].append((r["ts"], r["to_"]))
    snapl = defaultdict(list)
    for r in db.execute("select mint, ts, liq, buys1, sells1 from snaps where liq is not null order by ts"):
        snapl[r["mint"]].append((r["ts"], r["liq"], r["buys1"], r["sells1"]))
    toks = []
    for f in sorted(glob.glob(os.path.join(study_dir, "c", "*.json"))):
        m = os.path.basename(f)[:-5]
        d = json.load(open(f))
        cs = d.get("c")
        if not cs or len(cs) < min_candles:
            continue
        a = np.array(cs, dtype=float)
        a = a[np.argsort(a[:, 0])]
        x = ds.get(m) or {}
        supply = x["mcap"] / x["price"] if x.get("mcap") and x.get("price") else None
        if not supply:
            continue
        toks.append({"mint": m, "sym": sym.get(m) or x.get("symbol"), "first_seen": fs.get(m), "a": a, "supply": supply,
                     "ds": x, "trans": trans.get(m, []), "snapl": snapl.get(m, []), "fetched": d.get("at")})
    return toks


class Series:
    """Fast window queries on one token's candles."""

    def __init__(self, tok):
        a = tok["a"]
        self.tok = tok
        self.ts, self.o, self.h, self.l, self.c, self.v = a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5]
        self.cumv = np.concatenate([[0.0], np.cumsum(self.v)])
        self.end = self.ts[-1] + C5
        x = tok["ds"]
        self.p_now, self.liq_now = x.get("price"), x.get("liq") or 0
        self.created = (x.get("created") or 0) / 1000 or None
        sl = tok["snapl"]
        self.sl_ts = [s[0] for s in sl]
        self.sl = sl

    def idx(self, t):
        """Index of the last candle closed by time t, or -1."""
        return bisect.bisect_right(self.ts, t - C5) - 1

    def price(self, t):
        i = self.idx(t)
        return self.c[i] if i >= 0 else None

    def ret(self, t, w):
        i, j = self.idx(t), self.idx(t - w)
        if i < 0 or j < 0 or self.ts[j] < t - w - 6 * H:
            return None
        return self.c[i] / self.c[j] - 1

    def vol(self, t, w):
        a = bisect.bisect_left(self.ts, t - w)
        b = bisect.bisect_right(self.ts, t - C5)
        return float(self.cumv[b] - self.cumv[a])

    def hi(self, t, w):
        a = bisect.bisect_left(self.ts, t - w)
        b = bisect.bisect_right(self.ts, t - C5)
        return float(self.h[a:b].max()) if b > a else None

    def lo(self, t, w):
        a = bisect.bisect_left(self.ts, t - w)
        b = bisect.bisect_right(self.ts, t - C5)
        return float(self.l[a:b].min()) if b > a else None

    def closes(self, t, w):
        a = bisect.bisect_left(self.ts, t - w)
        b = bisect.bisect_right(self.ts, t - C5)
        return self.c[a:b]

    def liq(self, t):
        """Pool liquidity at t: the scanner's reading within 20 minutes when there is one, else today's liquidity scaled
        by the square root of the price ratio (a constant-product pool with no deposits or withdrawals)."""
        if self.sl_ts:
            k = bisect.bisect_left(self.sl_ts, t)
            for j in (k - 1, k):
                if 0 <= j < len(self.sl) and abs(self.sl[j][0] - t) <= 1200:
                    return self.sl[j][1]
        p = self.price(t)
        if not p or not self.p_now or self.liq_now <= 0:
            return None
        return self.liq_now * math.sqrt(p / self.p_now)

    def state(self, t):
        """The screener's state at t from its transitions: 'IN', 'OUT' or None before the first record."""
        st = None
        for ts, to in self.tok["trans"]:
            if ts > t:
                break
            st = to
        return st


def cost_pct(liq, usd=ORDER, fee=FEE):
    """One side's cost in %: the pool fee plus the price impact of `usd` against a constant-product pool."""
    if not liq or liq <= 0:
        return 100.0
    y = liq / 2
    return min(100.0, usd / (y + usd) * 100 + fee)


FEATS = ("r5", "r15", "r30", "r60", "r180", "r360", "r720", "r1440", "dd24", "dd6", "ru6", "ext6", "vp1", "vp15",
         "v1h", "v24", "vola", "greens", "age", "mc", "liq", "turn", "pos6", "accel")


def features(s, t):
    p = s.price(t)
    if not p:
        return None
    f = {}
    for k, w in (("r5", 300), ("r15", 900), ("r30", 1800), ("r60", 3600), ("r180", 3 * H), ("r360", 6 * H),
                 ("r720", 12 * H), ("r1440", 24 * H)):
        r = s.ret(t, w)
        f[k] = None if r is None else r * 100
    h24, h6, l6 = s.hi(t, 24 * H), s.hi(t, 6 * H), s.lo(t, 6 * H)
    f["dd24"] = (p / h24 - 1) * 100 if h24 else None
    f["dd6"] = (p / h6 - 1) * 100 if h6 else None
    f["ru6"] = (p / l6 - 1) * 100 if l6 else None
    cl6 = s.closes(t, 6 * H)
    f["ext6"] = (p / cl6.mean() - 1) * 100 if len(cl6) >= 6 else None
    f["pos6"] = (p - l6) / (h6 - l6) if h6 and l6 and h6 > l6 else None
    v1, v24, v15, v6 = s.vol(t, H), s.vol(t, 24 * H), s.vol(t, 900), s.vol(t, 6 * H)
    f["v1h"], f["v24"] = v1, v24
    f["vp1"] = v1 * 24 / v24 if v24 > 0 else None
    f["vp15"] = v15 * 24 / v6 if v6 > 0 else None
    if len(cl6) >= 12:
        lr = np.diff(np.log(np.maximum(cl6, 1e-30)))
        f["vola"] = float(lr.std() * 100)
        g = 0
        for k in range(len(cl6) - 1, 0, -1):
            if cl6[k] > cl6[k - 1]:
                g += 1
            else:
                break
        f["greens"] = g
    else:
        f["vola"] = f["greens"] = None
    f["age"] = (t - s.created) / H if s.created else None
    f["mc"] = p * s.tok["supply"]
    f["liq"] = s.liq(t)
    f["turn"] = v24 / f["mc"] if f["mc"] else None
    r60, r15 = f["r60"], f["r15"]
    f["accel"] = (r15 - (r60 - r15) / 3) if r60 is not None and r15 is not None else None   # last 15 min vs the 45 before
    return f


def in_range(f):
    return (f and f["mc"] and 20_000 <= f["mc"] <= 20_000_000 and f["v24"] >= 20_000 and f["v1h"] >= 2_000
            and (f["age"] is None or f["age"] >= 1) and (f["liq"] or 0) >= 5_000)


def decision_points(toks, t_min=None):
    """[(tok index, t, features)] every 15 minutes from first sight (or t_min) while in range, with at least 1h of
    candles after t."""
    out = []
    for ti, tok in enumerate(toks):
        s = tok["series"]
        start = max(tok["first_seen"] or 0, s.ts[0] + 6 * H, t_min or 0)
        t = math.ceil(start / STEP) * STEP
        while t <= s.end - H:
            f = features(s, t)
            if in_range(f):
                out.append((ti, t, f))
            t += STEP
    return out


# ---------------------------------------------------------------- outcomes
def fwd(s, t, T):
    """Gross multiple from the price at t to the price at t+T (None if the data ends before)."""
    if t + T > s.end:
        return None
    p0, p1 = s.price(t), s.price(t + T)
    return p1 / p0 if p0 and p1 else None


def net(mult, liq0, liq1, usd=ORDER, fee=FEE):
    """Net return in % after one entry and one exit at their costs."""
    c0, c1 = cost_pct(liq0, usd, fee) / 100, cost_pct(liq1, usd, fee) / 100
    return (mult * (1 - c0) * (1 - c1) - 1) * 100


def simulate(s, t0, pol, step=STEP, usd=ORDER, fee=FEE):
    """Hold from t0 under exit policy `pol`, checking at each scan (every `step`) with that scan's price, the way the
    paper ledger does. Returns (net %, hours held, reason) or None when the data ends before the policy decides."""
    p0 = s.price(t0)
    if not p0:
        return None
    peak = p0
    T = pol.get("max_h", 24) * H
    t = t0
    prev = p0
    while True:
        t += step
        if t > s.end:
            return None
        p = s.price(t)
        if not p:
            continue
        x = p / p0
        peak = max(peak, p)
        why = None
        if pol.get("sl") is not None and x <= 1 - pol["sl"] / 100:
            why = "stop"
        elif pol.get("tp") is not None and x >= 1 + pol["tp"] / 100:
            why = "target"
        elif pol.get("trail") is not None and peak / p0 >= 1 + pol.get("arm", 0) / 100 and p <= peak * (1 - pol["trail"] / 100):
            why = "trail"
        elif pol.get("cool") is not None and peak / p0 >= 1 + pol["cool"] / 100 and p / prev - 1 <= -pol.get("cool_drop", 5) / 100:
            why = "cooled"
        elif pol.get("drop1h") is not None:
            r = s.ret(t, H)
            if r is not None and r * 100 <= -pol["drop1h"] and t - t0 >= H:
                why = "fading"
        if why is None and t - t0 >= T:
            why = "time"
        prev = p
        if why:
            return net(x, s.liq(t0), s.liq(t), usd, fee), (t - t0) / H, why


EXITS = {}
for T in (1, 2, 4, 8, 24):
    EXITS[f"hold{T}h"] = {"max_h": T}
for tp in (20, 30, 50, 100):
    for sl in (15, 25, 40, None):
        EXITS[f"tp{tp}_sl{sl or 'x'}"] = {"tp": tp, "sl": sl, "max_h": 24}
for arm in (0, 20, 50):
    for tr in (15, 25, 35):
        EXITS[f"trail{tr}_arm{arm}"] = {"trail": tr, "arm": arm, "sl": 30, "max_h": 24}
for cool in (30, 50, 100):
    for cd in (5, 10):
        EXITS[f"cool{cool}_d{cd}"] = {"cool": cool, "cool_drop": cd, "sl": 30, "max_h": 24}
for d in (10, 20):
    EXITS[f"fade{d}"] = {"drop1h": d, "sl": 30, "max_h": 24}


def trades(points, toks, rule, pol, cooldown_h=1.0, t_lo=None, t_hi=None):
    """Sequential trades per token: enter at the first point where rule(f) holds, exit under pol, wait cooldown_h,
    then look again. Returns [(tok index, t entry, net %, hours, reason)]."""
    by = defaultdict(list)
    for ti, t, f in points:
        if (t_lo is None or t >= t_lo) and (t_hi is None or t < t_hi):
            by[ti].append((t, f))
    out = []
    for ti, lst in by.items():
        s = toks[ti]["series"]
        free_at = -1
        for t, f in lst:
            if t + (pol.get("max_h", 24) + 1) * H > s.end:
                break                  # too close to the end to have matured: early winners would be kept, slow losers lost
            if t < free_at or not rule(f):
                continue
            r = simulate(s, t, pol)
            if r is None:
                break
            out.append((ti, t, r[0], r[1], r[2]))
            free_at = t + r[1] * H + cooldown_h * H
    return out


def summarise(tr, toks=None):
    """n, win share, mean and median net %, compounded value of equal stakes, and a t-statistic with errors clustered
    by token (a token's trades move together)."""
    if not tr:
        return {"n": 0}
    xs = np.array([x[2] for x in tr])
    by = defaultdict(list)
    for x in tr:
        by[x[0]].append(x[2])
    k = len(by)
    mean = xs.mean()
    # cluster-robust standard error of the mean
    resid = [sum(v) - len(v) * mean for v in by.values()]
    se = math.sqrt(sum(r * r for r in resid)) / len(xs) * math.sqrt(k / (k - 1)) if k > 1 else None
    return {"n": len(xs), "tokens": k, "win": float((xs > 0).mean()), "mean": float(mean), "med": float(np.median(xs)),
            "se": se, "t": float(mean / se) if se else None, "p10": float(np.percentile(xs, 10)),
            "p90": float(np.percentile(xs, 90)), "hold_h": float(np.mean([x[3] for x in tr]))}
