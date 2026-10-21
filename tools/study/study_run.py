"""Part 1 of the study: baselines and one variable at a time.
Usage: python3 -I study_run.py <study dir> <db> [out.json]"""
import sys, os, time, math, json, pickle
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from scipy.stats import spearmanr
import study_lib as L
from collections import defaultdict

toks = L.load(sys.argv[1], sys.argv[2])
for t in toks:
    t["series"] = L.Series(t)
pts = L.decision_points(toks)
print(f"{len(toks)} tokens with candles; {len(pts)} in-range decision points on {len({p[0] for p in pts})} tokens")
ts_all = [p[1] for p in pts]
mid = float(np.median(ts_all))
iso = lambda t: time.strftime("%m-%d %H:%M", time.gmtime(t))
print("span", iso(min(ts_all)), "->", iso(max(ts_all)), "| split at", iso(mid))

HZ = (("1h", 3600), ("4h", 4 * 3600), ("24h", 24 * 3600))
rows = []
for ti, t, f in pts:
    s = toks[ti]["series"]
    out = {}
    for k, T in HZ:
        m = L.fwd(s, t, T)
        l1 = s.liq(t + T) if m is not None else None
        out[k] = None if m is None else L.net(m, f["liq"], l1)
        out["s" + k] = None if m is None else L.net(m, f["liq"], l1, usd=100)
        out["g" + k] = None if m is None else (m - 1) * 100
    rows.append((ti, t, f, out))
pickle.dump({"rows": rows, "mid": mid}, open(os.path.join(sys.argv[1], "study_rows.pkl"), "wb"))


def cl_mean(vals):
    if len(vals) < 2:
        return None, None, len(vals)
    xs = np.array([v for _, v in vals])
    m = xs.mean()
    by = defaultdict(float)
    for k, v in vals:
        by[k] += v - m
    kk = len(by)
    se = math.sqrt(sum(r * r for r in by.values()) * kk / (kk - 1)) / len(xs) if kk > 1 else None
    return float(m), se, len(xs)


def f2(v, spec):
    return format(v, spec) if v is not None else "  n/a"


# cost at entry
c500 = [L.cost_pct(f["liq"]) for _, _, f, _ in rows]
c100 = [L.cost_pct(f["liq"], usd=100) for _, _, f, _ in rows]
print(f"one-side cost incl. {L.FEE}% fee: $500 median {np.median(c500):.2f}% (p25 {np.percentile(c500, 25):.2f}, p75 "
      f"{np.percentile(c500, 75):.2f}); $100 median {np.median(c100):.2f}%")

print("\nBaseline: every in-range decision point (15-min grid), held for a fixed time")
for k, _ in HZ:
    for half, cond in (("all", lambda t: True), ("1st", lambda t: t < mid), ("2nd", lambda t: t >= mid)):
        g = [(ti, o["g" + k]) for ti, t, f, o in rows if o[k] is not None and cond(t)]
        if len(g) < 30:
            continue
        mg, sg, n = cl_mean(g)
        mn, _, _ = cl_mean([(ti, o[k]) for ti, t, f, o in rows if o[k] is not None and cond(t)])
        ms, _, _ = cl_mean([(ti, o["s" + k]) for ti, t, f, o in rows if o[k] is not None and cond(t)])
        up = np.mean([v > 0 for _, v in g])
        med = np.median([v for _, v in g])
        print(f"  hold {k:>3} {half}: n={n:>6}  gross mean {mg:+6.2f}% (se {sg:.2f})  median {med:+6.2f}%  rose {up:.0%}  "
              f"net at $500 {mn:+6.2f}%  at $100 {ms:+6.2f}%")

print("\nOne variable at a time: GROSS return over the next 4h by fifth of the variable, mean (cluster t); "
      "rank correlation in each half")
for k in L.FEATS:
    vals = [(ti, t, f[k], o["g4h"]) for ti, t, f, o in rows if f.get(k) is not None and o["g4h"] is not None]
    if len(vals) < 300:
        continue
    v = np.array([x[2] for x in vals])
    qs = np.quantile(v, [0.2, 0.4, 0.6, 0.8])
    line = []
    for q in range(5):
        lo = -np.inf if q == 0 else qs[q - 1]
        hi = np.inf if q == 4 else qs[q]
        sel = [(x[0], x[3]) for x in vals if (lo <= x[2] < hi) or (q == 4 and x[2] >= lo)]
        m, se, n = cl_mean(sel)
        line.append(f"{m:+6.1f}({m / se if se else 0:+.1f})" if m is not None else "  n/a ")
    hh = []
    for cond in (lambda t: t < mid, lambda t: t >= mid):
        sub = [x for x in vals if cond(x[1])]
        hh.append(spearmanr([x[2] for x in sub], [x[3] for x in sub])[0] if len(sub) > 50 else float("nan"))
    print(f"  {k:>7}: cuts {', '.join(f'{c:.3g}' for c in qs):<34} | " + " ".join(line) +
          f" | rho {hh[0]:+.3f}, {hh[1]:+.3f}")
