"""Unbiased check of stops and trailing stops: only entries with a full 8h (or 24h) of data behind them."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import study_lib as L
toks = L.load(sys.argv[1], sys.argv[2])
for t in toks:
    t["series"] = L.Series(t)
pts = L.decision_points(toks)
ent = {}
for ti, t, f in pts:
    ent.setdefault((ti, int(t // (6 * 3600))), (ti, t, f))
ent = sorted(ent.values(), key=lambda e: e[1])
end = max(x[1] for x in ent)
for H in (8, 24):
    sub = [e for e in ent if e[1] + H * 3600 <= end]
    mid = float(np.median([e[1] for e in sub]))
    print(f"\n{H}h limit, {len(sub)} matured entries, $500")
    pols = {"hold": {"max_h": H}, "tp10 no stop": {"tp": 10, "max_h": H}, "tp10 stop 15": {"tp": 10, "sl": 15, "max_h": H},
            "tp10 stop 25": {"tp": 10, "sl": 25, "max_h": H}, "tp20 stop 15": {"tp": 20, "sl": 15, "max_h": H},
            "stop 15 only": {"sl": 15, "max_h": H}, "stop 25 only": {"sl": 25, "max_h": H},
            "trail 15": {"trail": 15, "arm": 0, "max_h": H}, "trail 25 after +20": {"trail": 25, "arm": 20, "sl": 30, "max_h": H},
            "fade 10": {"drop1h": 10, "max_h": H}, "cool 20, 5% drop": {"cool": 20, "cool_drop": 5, "max_h": H}}
    for name, pol in pols.items():
        tr = []
        for ti, t, f in sub:
            r = L.simulate(toks[ti]["series"], t, pol)
            if r:
                tr.append((ti, t, r[0], r[1], r[2]))
        a = L.summarise(tr); h1 = L.summarise([x for x in tr if x[1] < mid]); h2 = L.summarise([x for x in tr if x[1] >= mid])
        print(f"  {name:<20} n={a['n']:>5} win {a['win']:.0%} mean {a['mean']:+6.1f}% (t {a['t']:+.1f}) med {a['med']:+5.1f} | halves {h1['mean']:+5.1f} / {h2['mean']:+5.1f}")
