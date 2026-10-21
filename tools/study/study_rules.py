"""Part 2 of the study: does a push cool off, which entry rules clear costs, which exits work best.
Usage: python3 -I study_rules.py <study dir> <db>"""
import sys, os, time, math, pickle, itertools, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import study_lib as L
from collections import defaultdict

toks = L.load(sys.argv[1], sys.argv[2])
for t in toks:
    t["series"] = L.Series(t)
pts = L.decision_points(toks)
mid = float(np.median([p[1] for p in pts]))
iso = lambda t: time.strftime("%m-%d %H:%M", time.gmtime(t))
print(f"{len(toks)} tokens, {len(pts)} decision points, split {iso(mid)}")


def cl(vals):
    """mean, cluster-robust t (by token), n for [(token, value)]."""
    if len(vals) < 3:
        return None, None, len(vals)
    xs = np.array([v for _, v in vals])
    m = xs.mean()
    by = defaultdict(float)
    for k, v in vals:
        by[k] += v - m
    kk = len(by)
    se = math.sqrt(sum(r * r for r in by.values()) * kk / (kk - 1)) / len(xs) if kk > 1 else None
    return float(m), (m / se if se else None), len(xs)


# fixed-horizon gross outcomes for conditional tables
G = {}
for ti, t, f in pts:
    s = toks[ti]["series"]
    G[(ti, t)] = {h: (lambda m: None if m is None else (m - 1) * 100)(L.fwd(s, t, h * 3600)) for h in (1, 2, 4, 8)}


def table(name, cond):
    sel = [(ti, t, f) for ti, t, f in pts if cond(f)]
    out = [f"{name:<58} n={len(sel):>5} coins={len({x[0] for x in sel}):>4}"]
    for h in (1, 4, 8):
        v = [(ti, G[(ti, t)][h]) for ti, t, f in sel if G[(ti, t)][h] is not None]
        m, tt, n = cl(v)
        med = np.median([x[1] for x in v]) if v else None
        up = np.mean([x[1] > 0 for x in v]) if v else None
        out.append(f"+{h}h {m:+6.1f}% (t {tt:+.1f}) med {med:+5.1f} up {up:.0%}" if m is not None and tt is not None else f"+{h}h n/a")
    print("  " + " | ".join(out))


print("\nA. After a push: gross change over the next 1, 4 and 8 hours (mean, cluster t, median, share up)")
table("all in-range points", lambda f: True)
for lo, hi in ((0, 10), (10, 30), (30, 60), (60, 100), (100, 200), (200, 1e9)):
    table(f"rise from 6h low {lo}-{hi}%", lambda f, lo=lo, hi=hi: f["ru6"] is not None and lo <= f["ru6"] < hi)
for lo, hi in ((-1e9, -20), (-20, -5), (-5, 5), (5, 20), (20, 50), (50, 1e9)):
    table(f"1h change {lo}-{hi}%", lambda f, lo=lo, hi=hi: f["r60"] is not None and lo <= f["r60"] < hi)
print("  -- push, then the turn")
for push in (30, 60, 100):
    table(f"rise from 6h low >= {push}% and last 15 min down", lambda f, p=push: (f["ru6"] or 0) >= p and (f["r15"] or 0) < 0)
    table(f"rise from 6h low >= {push}% and last 15 min up", lambda f, p=push: (f["ru6"] or 0) >= p and (f["r15"] or 0) > 0)
    table(f"rise from 6h low >= {push}% and 10%+ off the 6h high", lambda f, p=push: (f["ru6"] or 0) >= p and (f["dd6"] or 0) <= -10)
print("  -- pullbacks")
for dd in (-10, -20, -30, -40):
    table(f"6h high {dd}% or more away, 24h change > 0", lambda f, d=dd: (f["dd6"] or 0) <= d and (f["r1440"] or -1) > 0)
    table(f"6h high {dd}% or more away, 24h change <= 0", lambda f, d=dd: (f["dd6"] or 0) <= d and f["r1440"] is not None and f["r1440"] <= 0)
print("  -- quiet, then volume")
table("volume pace 1h >= 2x, 1h change 0-15%", lambda f: (f["vp1"] or 0) >= 2 and f["r60"] is not None and 0 <= f["r60"] < 15)
table("volume pace 1h >= 2x, 1h change >= 15%", lambda f: (f["vp1"] or 0) >= 2 and (f["r60"] or 0) >= 15)
table("swing size (vola) under 2%", lambda f: f["vola"] is not None and f["vola"] < 2)
table("swing size (vola) over 6%", lambda f: f["vola"] is not None and f["vola"] > 6)
table("older than 7 days", lambda f: (f["age"] or 0) >= 168)
table("younger than 1 day", lambda f: f["age"] is not None and f["age"] < 24)
table("market cap over $1m", lambda f: f["mc"] >= 1e6)
table("market cap under $200k", lambda f: f["mc"] < 2e5)

# ---------------------------------------------------------------- entry rules as trades, with exits
RULES = {
    "any (first in-range point, then every 4h after an exit)": lambda f: True,
    "steady climber: 24h up, 6h up, within 10% of 6h high, swing < 4%": lambda f: (f["r1440"] or -1) > 0 and (f["r360"] or -1) > 0 and (f["dd6"] or -99) >= -10 and (f["vola"] or 99) < 4,
    "dip in an uptrend: 24h up >20%, 15-35% off 6h high": lambda f: (f["r1440"] or -1) > 20 and -35 <= (f["dd6"] or 0) <= -15,
    "fresh breakout: 1h +10-40%, rise from 6h low < 60%, volume pace >= 1.5": lambda f: 10 <= (f["r60"] or -99) <= 40 and (f["ru6"] or 999) < 60 and (f["vp1"] or 0) >= 1.5,
    "calm and liquid: swing < 2.5%, liquidity >= $100k": lambda f: (f["vola"] or 99) < 2.5 and (f["liq"] or 0) >= 1e5,
    "older than 3 days, 6h up, within 15% of 6h high": lambda f: (f["age"] or 0) >= 72 and (f["r360"] or -1) > 0 and (f["dd6"] or -99) >= -15,
    "low swing, near high, mcap >= $500k": lambda f: (f["vola"] or 99) < 3 and (f["dd6"] or -99) >= -8 and f["mc"] >= 5e5,
    "not pushed: rise from 6h low < 15%, near 24h high (within 25%)": lambda f: (f["ru6"] or 999) < 15 and (f["dd24"] or -99) >= -25,
    "momentum: 3h +20%+, 15 min up, swing < 6%": lambda f: (f["r180"] or -1) >= 20 and (f["r15"] or -1) > 0 and (f["vola"] or 99) < 6,
}
EXITS = {k: L.EXITS[k] for k in ("hold1h", "hold4h", "hold24h", "tp20_sl15", "tp30_sl25", "tp50_sl25", "tp100_sl40",
                                  "trail15_arm0", "trail25_arm0", "trail25_arm20", "trail35_arm50", "cool30_d5",
                                  "cool50_d10", "fade10", "fade20")}


def fmt(s):
    if not s.get("n"):
        return "no trades"
    return (f"n={s['n']:>4} coins={s['tokens']:>3} win {s['win']:.0%} mean {s['mean']:+6.1f}% (t {s['t'] if s['t'] is not None else 0:+.1f}) "
            f"med {s['med']:+5.1f}% hold {s['hold_h']:.1f}h")


print("\nB. Entry rules as sequential trades (one at a time per coin, 1h wait after each exit), net of costs at $500,")
print("   checked at each 15-min scan with that scan's price. Each rule is fixed in advance, so both halves are out of sample.")
for name, rule in RULES.items():
    print(f"\n  {name}")
    for en, pol in EXITS.items():
        tr = L.trades(pts, toks, rule, pol)
        a = L.summarise(tr)
        h1 = L.summarise([x for x in tr if x[1] < mid])
        h2 = L.summarise([x for x in tr if x[1] >= mid])
        print(f"    {en:<14} {fmt(a)} | 1st {h1.get('mean', float('nan')):+6.1f}% (n {h1.get('n', 0)}) | 2nd {h2.get('mean', float('nan')):+6.1f}% (n {h2.get('n', 0)})")

# Exits compared on the same matured entries: see study_tp.py and study_stops.py.
