"""Machine-learning study on the candle history: can any algorithm pick entries (or exits) that beat costs out of
sample? Walk-forward by time with an embargo the length of the label (so no training label overlaps a test one), every
metric out of sample, train AUC kept only to show the overfitting gap.
Usage: python3 -I tools/study/study_ml.py <study dir> <db> [out.json]   (merge.py says how to get the inputs)"""
import sys, os, time, math, json, warnings
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import numpy as np
import study_lib as L
from collections import defaultdict
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss, balanced_accuracy_score
from undertow.lstm import LSTM
from undertow import zoo as Z

warnings.filterwarnings("ignore")
H = 3600
POL = {"tp": 10, "max_h": 8}                  # the live exit when the study ran: +10% target, else sell after 8 hours
EMBARGO = (POL["max_h"] + 1) * H
t_start = time.time()

toks = L.load(sys.argv[1], sys.argv[2])
for t in toks:
    t["series"] = L.Series(t)
pts = L.decision_points(toks)
FEATS = [k for k in L.FEATS]
SEQ = ["r15", "r60", "ru6", "dd6", "vola", "vp1", "vp15", "accel"]
STEPS = 8

# ---------------------------------------------------------------- samples: one per coin-hour, label = the trade's result
first = {}
for ti, t, f in pts:
    first.setdefault((ti, int(t // H)), (ti, t, f))
ent = sorted(first.values(), key=lambda e: e[1])
rows = []
for ti, t, f in ent:
    s = toks[ti]["series"]
    if t + EMBARGO > s.end:
        continue
    r = L.simulate(s, t, POL)
    if r is None:
        continue
    seq, msk = [], []
    for k in range(STEPS - 1, -1, -1):
        g = L.features(s, t - k * 900) if k else f
        seq.append([(g or {}).get(c) if g and (g or {}).get(c) is not None else np.nan for c in SEQ])
        msk.append(1.0 if g else 0.0)
    rows.append({"ti": ti, "t": t, "f": f, "net": r[0], "seq": seq, "msk": msk})
print(f"{len(rows)} entry samples on {len({r['ti'] for r in rows})} coins, "
      f"{time.strftime('%d %b %H:%M', time.gmtime(rows[0]['t']))} to {time.strftime('%d %b %H:%M', time.gmtime(rows[-1]['t']))}; "
      f"{np.mean([r['net'] > 0 for r in rows]):.0%} made money after costs (average {np.mean([r['net'] for r in rows]):+.1f}%)", flush=True)


def matrix(rs, keys):
    X = np.array([[r["f"].get(k) if r["f"].get(k) is not None else np.nan for k in keys] for r in rs], float)
    for j, k in enumerate(keys):                 # sizes on a log scale
        if k in ("v1h", "v24", "mc", "liq", "age"):
            X[:, j] = np.log10(np.clip(X[:, j], 1e-6, None))
    return X


X_all = matrix(rows, FEATS)
y_all = np.array([r["net"] > 0 for r in rows], int)
net_all = np.array([r["net"] for r in rows])
t_all = np.array([r["t"] for r in rows])
coin_all = np.array([r["ti"] for r in rows])
S_all = np.array([r["seq"] for r in rows], float)
M_all = np.array([r["msk"] for r in rows], float)

# ---------------------------------------------------------------- walk-forward folds: 8-hour test windows
T0, T1 = t_all.min(), t_all.max()
folds, a = [], T0 + 20 * H
while a < T1:
    b = a + 8 * H
    tr = np.where(t_all < a - EMBARGO)[0]
    te = np.where((t_all >= a) & (t_all < b))[0]
    if len(tr) >= 300 and len(te) >= 50:
        folds.append((tr, te))
    a = b
print(f"{len(folds)} walk-forward folds; training sets {[len(f[0]) for f in folds]}, test sets {[len(f[1]) for f in folds]}", flush=True)


def clustered_t(vals, groups):
    vals, groups = np.asarray(vals, float), np.asarray(groups)
    if len(vals) < 3:
        return None
    m = vals.mean()
    by = defaultdict(float)
    for v, g in zip(vals, groups):
        by[g] += v - m
    k = len(by)
    se = math.sqrt(sum(x * x for x in by.values()) * k / (k - 1)) / len(vals) if k > 1 else None
    return m / se if se else None


def evaluate(name, fit_predict):
    """fit_predict(train idx, test idx) -> (test scores, train scores)."""
    oos = np.full(len(rows), np.nan)
    pick = np.zeros(len(rows), bool)
    tr_auc, fold_auc = [], []
    t0 = time.time()
    for tr, te in folds:
        p_te, p_tr = fit_predict(tr, te)
        oos[te] = p_te
        cut = np.quantile(p_tr, 0.8)                       # trade the top fifth of what the training data scored
        pick[te] = p_te >= cut
        if len(set(y_all[tr])) > 1:
            tr_auc.append(roc_auc_score(y_all[tr], p_tr))
        if len(set(y_all[te])) > 1:
            fold_auc.append(roc_auc_score(y_all[te], p_te))
    m = ~np.isnan(oos)
    y, p = y_all[m], np.clip(oos[m], 1e-6, 1 - 1e-6)
    sel = pick & m
    res = {"algorithm": name, "n_test": int(m.sum()), "auc": roc_auc_score(y, p), "auc_sd": float(np.std(fold_auc)),
           "train_auc": float(np.mean(tr_auc)) if tr_auc else None, "accuracy": float(((p >= 0.5) == y).mean()),
           "balanced_acc": balanced_accuracy_score(y, p >= 0.5), "brier": brier_score_loss(y, p), "logloss": log_loss(y, p),
           "base_win": float(y.mean()), "base_net": float(net_all[m].mean()),
           "picks": int(sel.sum()), "pick_win": float(y_all[sel].mean()) if sel.any() else None,
           "pick_net": float(net_all[sel].mean()) if sel.any() else None,
           "pick_t": clustered_t(net_all[sel], coin_all[sel]) if sel.sum() > 2 else None,
           "seconds": round(time.time() - t0, 1)}
    res["gap"] = res["train_auc"] - res["auc"] if res["train_auc"] is not None else None
    print(f"  {name:<22} AUC {res['auc']:.3f} ±{res['auc_sd']:.3f} (train {res['train_auc'] or 0:.3f}, gap {res['gap'] or 0:+.3f}) "
          f"acc {res['accuracy']:.3f} bal {res['balanced_acc']:.3f} Brier {res['brier']:.3f} | top fifth: {res['picks']} trades, "
          f"{(res['pick_win'] or 0):.0%} won, avg {(res['pick_net'] or 0):+.1f}% (t {res['pick_t'] or 0:+.1f}) vs all {res['base_net']:+.1f}% "
          f"| {res['seconds']}s", flush=True)
    return res


results = []
print("\nEntry models: does the trade (+10% target, else sell after 8h, $500, after costs) make money?", flush=True)
for name, factory in Z.TABULAR.items():
    def fp(tr, te, factory=factory):
        mdl = factory()
        mdl.fit(X_all[tr], y_all[tr])
        return mdl.predict_proba(X_all[te])[:, 1], mdl.predict_proba(X_all[tr])[:, 1]
    results.append(evaluate(name, fp))


def fp_lstm(tr, te):
    m = LSTM(len(SEQ), hidden=12, epochs=25, l2=3e-3, seed=0).fit(S_all[tr], M_all[tr], y_all[tr])
    return m.predict_proba(S_all[te], M_all[te]), m.predict_proba(S_all[tr], M_all[tr])


results.append(evaluate("LSTM (8 scans)", fp_lstm))
rng = np.random.default_rng(0)
results.append(evaluate("Random scores (control)", lambda tr, te: (rng.random(len(te)), rng.random(len(tr)))))

# ---------------------------------------------------------------- the same picks from models of the return itself
print("\nReturn models: predict the trade's net return (clipped to +/-60%), trade the top fifth of predictions", flush=True)
from scipy.stats import spearmanr
net_clip = np.clip(net_all, -60, 60)


def evaluate_reg(name, factory):
    oos = np.full(len(rows), np.nan)
    pick = np.zeros(len(rows), bool)
    ics, tr_ics = [], []
    t0 = time.time()
    for tr, te in folds:
        mdl = factory()
        mdl.fit(X_all[tr], net_clip[tr])
        p_te, p_tr = mdl.predict(X_all[te]), mdl.predict(X_all[tr])
        oos[te] = p_te
        pick[te] = p_te >= np.quantile(p_tr, 0.8)
        ics.append(spearmanr(p_te, net_all[te])[0])
        tr_ics.append(spearmanr(p_tr, net_all[tr])[0])
    m = ~np.isnan(oos)
    sel = pick & m
    res = {"algorithm": name, "kind": "return", "n_test": int(m.sum()), "ic": float(spearmanr(oos[m], net_all[m])[0]),
           "ic_sd": float(np.std(ics)), "train_ic": float(np.mean(tr_ics)), "picks": int(sel.sum()),
           "pick_win": float(y_all[sel].mean()) if sel.any() else None, "pick_net": float(net_all[sel].mean()) if sel.any() else None,
           "pick_t": clustered_t(net_all[sel], coin_all[sel]) if sel.sum() > 2 else None, "base_net": float(net_all[m].mean()),
           "seconds": round(time.time() - t0, 1)}
    print(f"  {name:<30} rank IC {res['ic']:+.3f} ±{res['ic_sd']:.3f} (train {res['train_ic']:+.3f}) | top fifth: {res['picks']} trades, "
          f"{(res['pick_win'] or 0):.0%} won, avg {(res['pick_net'] or 0):+.1f}% (t {res['pick_t'] or 0:+.1f}) vs all {res['base_net']:+.1f}% "
          f"| {res['seconds']}s", flush=True)
    return res


reg_results = [evaluate_reg(name, f) for name, f in Z.REGRESSION.items()]

# ---------------------------------------------------------------- exit models
print("\nExit models: once in a trade, does selling now beat holding two more hours?", flush=True)
EX_STATE = ["held_h", "ret", "peak_ret", "dd_peak"]
ex_rows = []
for k, r in enumerate(rows):
    s = toks[r["ti"]]["series"]
    p0 = s.price(r["t"])
    peak = p0
    for hh in range(1, POL["max_h"]):
        t = r["t"] + hh * H
        p = s.price(t)
        if not p or not p0:
            break
        for q in range(4):                                 # the peak at scan resolution since the last hour
            pq = s.price(t - q * 900)
            if pq:
                peak = max(peak, pq)
        later = s.price(min(t + 2 * H, r["t"] + POL["max_h"] * H))
        f = L.features(s, t)
        if not f or not later:
            continue
        ex_rows.append({"k": k, "t": t, "f": f, "held_h": hh, "ret": p / p0 - 1, "peak_ret": peak / p0 - 1,
                        "dd_peak": p / peak - 1, "y": int(later < p)})
EX_FEATS = FEATS + EX_STATE
Xe = np.array([[e["f"].get(c) if c in e["f"] and e["f"].get(c) is not None else e.get(c, np.nan) for c in EX_FEATS] for e in ex_rows], float)
for j, c in enumerate(EX_FEATS):
    if c in ("v1h", "v24", "mc", "liq", "age"):
        Xe[:, j] = np.log10(np.clip(Xe[:, j], 1e-6, None))
ye = np.array([e["y"] for e in ex_rows], int)
te_ = np.array([e["t"] for e in ex_rows])
ke = np.array([e["k"] for e in ex_rows])
print(f"{len(ex_rows)} exit decisions; selling beat holding 2h in {ye.mean():.0%} of them", flush=True)


def follow(k, decide):
    """Net return of trade k when the exit model may sell at each hourly check (target and time limit still apply)."""
    r = rows[k]
    s = toks[r["ti"]]["series"]
    p0 = s.price(r["t"])
    t = r["t"]
    while True:
        t += 900
        p = s.price(t)
        if not p:
            continue
        held = (t - r["t"]) / H
        if p / p0 >= 1 + POL["tp"] / 100 or held >= POL["max_h"] - 0.01 or decide(k, t):
            return L.net(p / p0, s.liq(r["t"]), s.liq(t))


ex_results = []
for name, factory in Z.EXIT.items():
    t0 = time.time()
    dec, oos_p, oos_y, trp = {}, [], [], []
    for tr, te in folds:
        tr_e = np.isin(ke, tr) & (te_ < t_all[te].min() - EMBARGO)
        te_e = np.isin(ke, te)
        if tr_e.sum() < 200 or te_e.sum() < 20:
            continue
        mdl = factory()
        mdl.fit(Xe[tr_e], ye[tr_e])
        p = mdl.predict_proba(Xe[te_e])[:, 1]
        trp.append(roc_auc_score(ye[tr_e], mdl.predict_proba(Xe[tr_e])[:, 1]))
        oos_p.extend(p); oos_y.extend(ye[te_e])
        for (kk, tt), pp in zip(zip(ke[te_e], te_[te_e]), p):
            dec[(int(kk), float(tt))] = pp >= 0.5
    tested = sorted({k for k, _ in dec})
    base = [follow(k, lambda k, t: False) for k in tested]
    mine = [follow(k, lambda k, t: dec.get((k, float(t)), False)) for k in tested]
    diff = np.array(mine) - np.array(base)
    res = {"algorithm": name, "n_decisions": len(oos_y), "auc": roc_auc_score(oos_y, oos_p) if len(set(oos_y)) > 1 else None,
           "train_auc": float(np.mean(trp)) if trp else None, "accuracy": float(np.mean((np.array(oos_p) >= 0.5) == np.array(oos_y))),
           "trades": len(tested), "net": float(np.mean(mine)), "base_net": float(np.mean(base)), "gain": float(diff.mean()),
           "gain_t": clustered_t(diff, [rows[k]["ti"] for k in tested]), "seconds": round(time.time() - t0, 1)}
    ex_results.append(res)
    print(f"  {name:<22} AUC {res['auc'] or 0:.3f} (train {res['train_auc'] or 0:.3f}) acc {res['accuracy']:.3f} | following it: "
          f"{res['net']:+.1f}% a trade vs {res['base_net']:+.1f}% for +10%/8h, gain {res['gain']:+.2f} pts (t {res['gain_t'] or 0:+.1f}) "
          f"on {res['trades']} trades | {res['seconds']}s", flush=True)

out = {"made": time.time(), "samples": len(rows), "coins": len({r['ti'] for r in rows}), "folds": len(folds),
       "base_win": float(y_all.mean()), "base_net": float(net_all.mean()), "entry": results, "entry_return": reg_results,
       "exit": ex_results,
       "exit_samples": len(ex_rows), "label": "net return after costs > 0 for +10% target, else sell after 8h, $500",
       "period": [float(T0), float(T1)], "seconds": round(time.time() - t_start)}
if len(sys.argv) > 3:
    json.dump(out, open(sys.argv[3], "w"), indent=1, default=float)
print(f"\ndone in {out['seconds']}s")
