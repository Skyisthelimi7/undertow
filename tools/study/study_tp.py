"""Part 3: selling into strength. Take-profit exits without a stop (or with a wide one), by holding limit, on the same
entries, in each half of the window, at $500 and at $100; then the entry filters that do best under those exits.
Usage: python3 -I study_tp.py <study dir> <db>"""
import sys, os, time, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import study_lib as L
from collections import defaultdict

toks = L.load(sys.argv[1], sys.argv[2])
for t in toks:
    t["series"] = L.Series(t)
pts = L.decision_points(toks)
iso = lambda t: time.strftime("%m-%d %H:%M", time.gmtime(t))
ent = {}
for ti, t, f in pts:
    ent.setdefault((ti, int(t // (6 * 3600))), (ti, t, f))
ent = sorted(ent.values(), key=lambda e: e[1])
print(f"{len(ent)} entries (first in-range reading of each coin in each 6-hour block), {iso(ent[0][1])} to {iso(ent[-1][1])}")


def sim_all(pol, usd, entries):
    out = []
    for ti, t, f in entries:
        r = L.simulate(toks[ti]["series"], t, pol, usd=usd)
        if r:
            out.append((ti, t, r[0], r[1], r[2], f))
    return out


def line(name, tr, mid):
    a = L.summarise(tr)
    if not a.get("n"):
        return f"  {name:<26} no trades"
    h1 = L.summarise([x for x in tr if x[1] < mid])
    h2 = L.summarise([x for x in tr if x[1] >= mid])
    why = defaultdict(int)
    for x in tr:
        why[x[4]] += 1
    w = ", ".join(f"{k} {v / len(tr):.0%}" for k, v in sorted(why.items(), key=lambda kv: -kv[1]))
    return (f"  {name:<26} n={a['n']:>5} win {a['win']:.0%} mean {a['mean']:+6.1f}% (t {a['t']:+.1f}) med {a['med']:+5.1f}% "
            f"p10 {a['p10']:+6.1f} p90 {a['p90']:+6.1f} | 1st {h1.get('mean', float('nan')):+5.1f} (n {h1.get('n', 0)}, t {h1.get('t') or 0:+.1f})"
            f" 2nd {h2.get('mean', float('nan')):+5.1f} (n {h2.get('n', 0)}, t {h2.get('t') or 0:+.1f}) | {w}")


for H in (4, 8, 24):
    sub = [e for e in ent if e[1] + H * 3600 <= max(x[1] for x in ent) + 3600 * 0]
    mid = float(np.median([e[1] for e in sub]))
    print(f"\nHolding limit {H}h: {len(sub)} entries with a full {H}h behind them, split at {iso(mid)}")
    for usd in (500, 100):
        print(f" at ${usd}")
        print(line(f"hold {H}h", sim_all({"max_h": H}, usd, sub), mid))
        for tp in (10, 15, 20, 30, 50):
            for sl in (None, 50):
                print(line(f"tp +{tp}% {'no stop' if sl is None else 'stop -' + str(sl) + '%'}", sim_all({"tp": tp, "sl": sl, "max_h": H}, usd, sub), mid))

# entry filters under the best-looking family
print("\nEntry filters under 'take profit +20%, no stop, sell after 8h' at $500 (and at $100), same 6h-block entries")
FILTERS = {
    "all": lambda f: True,
    "not pushed (ru6 < 15)": lambda f: (f["ru6"] if f["ru6"] is not None else 999) < 15,
    "pushed (ru6 >= 30)": lambda f: (f["ru6"] or 0) >= 30,
    "calm (vola < 2.5)": lambda f: (f["vola"] if f["vola"] is not None else 99) < 2.5,
    "wild (vola >= 5)": lambda f: (f["vola"] or 0) >= 5,
    "liquid (liq >= $100k)": lambda f: (f["liq"] or 0) >= 1e5,
    "thin (liq < $40k)": lambda f: (f["liq"] or 0) < 4e4,
    "older than 7 days": lambda f: (f["age"] or 0) >= 168,
    "younger than 2 days": lambda f: f["age"] is not None and f["age"] < 48,
    "mcap >= $1m": lambda f: f["mc"] >= 1e6,
    "mcap < $300k": lambda f: f["mc"] < 3e5,
    "down 20%+ from 6h high": lambda f: (f["dd6"] or 0) <= -20,
    "within 5% of 6h high": lambda f: (f["dd6"] if f["dd6"] is not None else -99) >= -5,
    "24h down 30%+": lambda f: (f["r1440"] or 0) <= -30,
    "24h up": lambda f: (f["r1440"] or -1) > 0,
    "1h flat (-5..5%)": lambda f: f["r60"] is not None and -5 <= f["r60"] <= 5,
    "turnover <= 0.5": lambda f: (f["turn"] if f["turn"] is not None else 99) <= 0.5,
    "turnover >= 2": lambda f: (f["turn"] or 0) >= 2,
    "volume pace >= 1.5": lambda f: (f["vp1"] or 0) >= 1.5,
    "volume pace < 0.7": lambda f: f["vp1"] is not None and f["vp1"] < 0.7,
    "not pushed + liquid": lambda f: (f["ru6"] if f["ru6"] is not None else 999) < 15 and (f["liq"] or 0) >= 1e5,
    "not pushed + wild": lambda f: (f["ru6"] if f["ru6"] is not None else 999) < 15 and (f["vola"] or 0) >= 4,
    "not pushed + 1h flat + vp >= 1": lambda f: (f["ru6"] if f["ru6"] is not None else 999) < 15 and f["r60"] is not None and -5 <= f["r60"] <= 5 and (f["vp1"] or 0) >= 1,
}
sub = [e for e in ent if e[1] + 8 * 3600 <= max(x[1] for x in ent)]
mid = float(np.median([e[1] for e in sub]))
pol = {"tp": 20, "sl": None, "max_h": 8}
base5 = {(x[0], x[1]): x for x in sim_all(pol, 500, sub)}
base1 = {(x[0], x[1]): x for x in sim_all(pol, 100, sub)}
for name, flt in FILTERS.items():
    t5 = [x for k, x in base5.items() if flt(x[5])]
    t1 = [x for k, x in base1.items() if flt(x[5])]
    s1 = L.summarise(t1)
    print(line(name, t5, mid) + f" || $100: mean {s1.get('mean', float('nan')):+5.1f} (t {s1.get('t') or 0:+.1f})")
