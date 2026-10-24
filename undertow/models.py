"""Models: machine-learning entry and exit models trained on the Buy & sell path, tested twice: walk-forward on the
stored history before they trade, then forward on paper from the moment they are trained.

Entry models score every coin passing every gate at every scan. The label is the paper trade opened at that reading
under the live exit (a +10% target, else sell after 8 hours, when this was written), after costs: did it make money
(classifiers), or how much (return models)? One sample per coin per hour, its first passing reading that hour, since a
coin's readings 15 minutes apart are nearly the same sample. Exit models score every open paper trade at every scan:
would selling now beat holding on under the live exit? The model sells when that probability reaches exit_thr; the
live exit's target and time limit still apply, so an exit model can only sell earlier than the live exit.

Overfitting controls, all reported on the Models tab:
  - walk-forward folds by time: each fold trains only on samples whose trades had closed before its test window
    opened (purging), so no training label reaches into a test window;
  - every metric is out of sample; the training AUC is shown only to expose the gap between the two;
  - small, regularised models (zoo.py), with entry thresholds set on training scores only (the top fifth);
  - a random-score control trained and traded the same way, and a luck line: what the luckiest of as many random
    pickers as there are models would have averaged on the same test samples (95th percentile);
  - the forward ledger: a model's paper trades start after it was trained, and it can go live only on the bar every
    rule faces (min_trades settled trades averaging min_edge % or more after costs, t >= z with errors clustered by
    coin, in two weekly reviews in a row).
Needs numpy, scikit-learn, xgboost-cpu and lightgbm (requirements-ml.txt) to train or score; the scanner runs without
them and then simply skips the models."""
import hashlib, json, math, os, pickle, time
from collections import defaultdict
import numpy as np
from . import trade as TRD, attention as ATT

H = 3600
# (slug, name, kind): cls classifiers, ret models of the return itself, seq the LSTM over the last scans
ALGOS = [
    ("logit", "Logistic regression", "cls"), ("rf", "Random forest", "cls"), ("et", "Extra trees", "cls"),
    ("gb", "Gradient boosting", "cls"), ("xgb", "XGBoost", "cls"), ("lgbm", "LightGBM", "cls"),
    ("knn", "k nearest neighbours", "cls"), ("nb", "Naive Bayes", "cls"), ("mlp", "Neural network (MLP)", "cls"),
    ("lstm", "LSTM (last 8 scans)", "seq"),
    ("ridge", "Ridge regression", "ret"), ("rf_ret", "Random forest (return)", "ret"),
    ("gb_ret", "Gradient boosting (return)", "ret"), ("xgb_ret", "XGBoost (return)", "ret"),
    ("lgbm_ret", "LightGBM (return)", "ret"),
]
RANDOM_ID = "random"
EXIT_ALGOS = [("logit", "Logistic regression"), ("rf", "Random forest"), ("gb", "Gradient boosting"),
              ("lgbm", "LightGBM"), ("mlp", "Neural network (MLP)")]
FAMILY = {"logit": "linear", "rf": "tree ensemble (bagging)", "et": "tree ensemble (bagging)", "gb": "boosted trees",
          "xgb": "boosted trees", "lgbm": "boosted trees", "knn": "instance-based", "nb": "probabilistic",
          "mlp": "neural network", "lstm": "recurrent neural network", "ridge": "linear", "rf_ret": "tree ensemble (bagging)",
          "gb_ret": "boosted trees", "xgb_ret": "boosted trees", "lgbm_ret": "boosted trees", RANDOM_ID: "control"}
ATT_ALL = set(ATT.KEYS) | {"tgm", "tgr"}                     # attention at the scan, Telegram counts included
ATT_MIN = {"gtr5_d15", "bst_d15", "ad_imp"}                  # attention on the minute data (minute.py)
PRICE_KEYS = [k for k, _l, _u in TRD.PATH_VARS] + ["c5m", "c1h", "c6h", "c24h", "dd24s"]
SIZE_KEYS = ["mc", "liq", "liq_pct", "age", "hold"]          # how big, how deep and how old the coin's market is
MIN_PRICE = ["m1", "m5", "m15", "m30", "up30", "dn30", "v5x", "bs5"]   # price and trading on the minute data
SEQ_POOL = ["r15", "r30", "ru6", "dd6", "vola", "c1h", "v1h_24", "bs1h", "nf1h_liq", "brd1h", "ss1h", "liqc1h",
            "gtr", "gtr5", "jtr", "bst", "tgg", "xfg"]
# what the LSTM reads in addition, in the sets about the minute data and the pool's size
SEQ_EXTRA = {"minute_price": ["m5", "m15", "up30", "dn30", "v5x", "bs5"], "attention_price_size": ["liq", "mc", "liq_pct"]}
SETS = {"no_attention": lambda k: k not in ATT_ALL and k not in ATT_MIN,
        "attention_price": lambda k: k in ATT_ALL or k in PRICE_KEYS,
        "price": lambda k: k in PRICE_KEYS,
        "attention": lambda k: k in ATT_ALL,
        "attention_price_size": lambda k: k in ATT_ALL or k in PRICE_KEYS or k in SIZE_KEYS,
        "minute_price": lambda k: k in PRICE_KEYS or k in MIN_PRICE}
STATE_KEYS = ["held_h", "ret_now", "peak_ret", "dd_peak", "liq_ratio"]
# sizes and counts on a log scale, flows on a signed log scale (matters for the linear, distance and neural models)
LOG_KEYS = {"mc", "liq", "v5m", "v1h", "v6h", "v24h", "hold", "xf", "tgm", "tr1h", "ob24h", "age", "web_age", "devm"}
SLOG_KEYS = {"nf1h", "nf6h", "nf24h"}


def set_keys(name):
    """The variables a model of this set reads (see config.MODEL_SETS); "all" and any set not defined here read
    every variable."""
    pick = SETS.get(name)
    return [k for k in TRD.VAR_KEYS if pick is None or pick(k)]


def seq_keys(name):
    """The variables the LSTM of this set reads at each of its last scans."""
    have = set(set_keys(name))
    return [k for k in SEQ_POOL + SEQ_EXTRA.get(name, []) if k in have]


def algos_for(set_name, set_algos=None):
    """The algorithms trained on a variable set: those config.MODEL_SET_ALGOS names for it, else every one."""
    want = (set_algos or {}).get(set_name)
    return [a for a in ALGOS if want is None or a[0] in want]


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def vec(f, keys):
    out = []
    for k in keys:
        v = (f or {}).get(k)
        if not _num(v):
            out.append(np.nan)
        elif k in LOG_KEYS:
            out.append(math.log10(max(v, 1e-6)))
        elif k in SLOG_KEYS:
            out.append(math.copysign(math.log10(1 + abs(v)), v))
        else:
            out.append(float(v))
    return out


def matrix(fs, keys):
    return np.array([vec(f, keys) for f in fs], float).reshape(len(fs), len(keys))


def sequence(rows, i, keys, steps, gap_s=30 * 60):
    """The last `steps` scans of a coin up to row i: (values [steps][keys], mask [steps]). A scan the coin did not pass
    every gate at, or one too far back (more than gap_s a step on average), is masked out."""
    X, M = [], []
    t_i = rows[i][0]
    for k in range(steps - 1, -1, -1):
        j = i - k
        f = rows[j][5] if j >= 0 else None
        ok = bool(f) and rows[j][1] == "I" and t_i - rows[j][0] <= (k + 1) * gap_s
        X.append(vec(f, keys) if ok else [0.0] * len(keys))
        M.append(1.0 if ok else 0.0)
    return X, M


def trade_state(in_ts, in_price, in_liq, peak_before, price, liq, now):
    """An open trade's state at one scan, for the exit models."""
    peak = max(peak_before or in_price, price)
    return {"held_h": (now - in_ts) / H, "ret_now": price / in_price - 1, "peak_ret": peak / in_price - 1,
            "dd_peak": price / peak - 1, "liq_ratio": (liq / in_liq) if liq and in_liq else None}


# ---------------------------------------------------------------- datasets from the path
def simulate(rows, i, pol, cfg, sell_at=None):
    """The paper trade opened at rows[i] under exit policy pol, as the ledger would step it (structure failure and a
    liquidity pull sell at once). sell_at(j, peak_before) -> True lets an exit model sell at scan j. Returns
    (net %, hours held, reason, index of the closing scan) or None if the path ends first."""
    ts, _s, price, liq = rows[i][:4]
    pos, s = {"in_ts": ts, "in_price": price, "in_liq": liq}, TRD.new_state(price)
    for j in range(i + 1, len(rows)):
        tj, sj, pj, lj, cj, _fj = rows[j]
        if not pj:
            continue
        guard = ("structure gate failed" if sj == "X" else
                 "liquidity pulled" if lj is not None and liq and lj < cfg["liq_pull"] * liq else None)
        sell = bool(sell_at and guard is None and sell_at(j, s["peak"]))
        res = TRD.step(pol, pos, s, pj, lj, cj, tj, cfg, guard, sell)
        if res:
            return res[0], res[1], res[2], j
    return None


def entry_samples(path, pol, cfg):
    """One sample per coin per hour: its first reading that hour while passing every gate, labelled with the paper
    trade opened there under pol (net % after costs). Trades too close to the end of the path to have matured are
    left out, closed or not, so quick winners are not kept while slow losers are dropped."""
    out, end = [], TRD.path_end(path)
    for mint, rows in path.items():
        taken = set()
        for i, (ts, stt, price, _liq, _c, f) in enumerate(rows):
            if stt != "I" or not f or not price or int(ts // H) in taken:
                continue
            if not TRD.matured(ts, pol, end):
                break
            res = simulate(rows, i, pol, cfg)
            if res is None:
                continue
            taken.add(int(ts // H))
            out.append({"mint": mint, "ts": ts, "i": i, "j": res[3], "net": res[0], "h": res[1], "why": res[2], "f": f})
    out.sort(key=lambda s: s["ts"])
    return out


def exit_row(f, c1h, state):
    """An exit model's inputs: the coin's variables at that scan (only when it passed every gate, as in the path) and
    the trade's state."""
    g = dict(f) if f else {"c1h": c1h}
    g.update(state)
    return g


def exit_samples(path, samples, cfg, every, cap, seed=0):
    """Decision points inside the sample trades, every `every` scans while each is open: would selling then have beaten
    holding on to the policy's own exit? y = 1 when selling then gave the better net return."""
    import random
    out = []
    for k, s in enumerate(samples):
        rows = path[s["mint"]]
        ts0, _st, p0, l0 = rows[s["i"]][:4]
        peak, cnt = p0, 0
        for j in range(s["i"] + 1, s["j"]):
            tj, _sj, pj, lj, cj, fj = rows[j]
            if not pj:
                continue
            state = trade_state(ts0, p0, l0, peak, pj, lj, tj)
            peak = max(peak, pj)
            cnt += 1
            if cnt % every:
                continue
            out.append({"k": k, "mint": s["mint"], "ts": tj, "ts0": ts0, "x": exit_row(fj, cj, state),
                        "y": int(TRD.net_ret(pj / p0, l0, lj, cfg) > s["net"])})
    if len(out) > cap:
        out = sorted(random.Random(seed).sample(out, cap), key=lambda e: e["ts"])
    return out


# ---------------------------------------------------------------- statistics
def clustered_t(vals, groups):
    """t of the mean with errors clustered by coin."""
    vals = np.asarray(vals, float)
    if len(vals) < 3:
        return None
    m = vals.mean()
    by = defaultdict(float)
    for v, g in zip(vals, groups):
        by[g] += v - m
    k = len(by)
    if k < 2:
        return None
    se = math.sqrt(sum(x * x for x in by.values()) * k / (k - 1)) / len(vals)
    return float(m / se) if se > 0 else None


def auc(y, p):
    from sklearn.metrics import roc_auc_score
    y = np.asarray(y)
    return float(roc_auc_score(y, p)) if len(set(y.tolist())) > 1 else None


def spearman(a, b):
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) < 3:
        return None
    ra, rb = a.argsort().argsort(), b.argsort().argsort()
    c = np.corrcoef(ra, rb)[0, 1]
    return float(c) if c == c else None


def folds(ts, closed, cfg, gap=900):
    """Expanding-window folds: test windows tiling the later half of the period (at most five, each at least fold_h
    hours long). Each trains only on samples whose trades had closed (closed: their closing times) at least `gap`
    seconds before its test window opened, so no training label reaches into a test window: purging, rather than a
    fixed embargo, keeps the trades that closed early."""
    if len(ts) == 0:
        return []
    t0, t1 = float(ts.min()), float(ts.max())
    start = t0 + (t1 - t0) / 2
    k = int(min(5, (t1 - start) // (cfg["fold_h"] * H)))
    out = []
    for b in range(k):
        w = (t1 - start) / k
        a, e = start + b * w, (start + (b + 1) * w if b < k - 1 else t1 + 1)
        tr, te = np.where(closed < a - gap)[0], np.where((ts >= a) & (ts < e))[0]
        if len(tr) >= cfg["min_train"] and len(te) >= cfg["min_test"]:
            out.append((tr, te))
    return out


def luck(net, fold_te, picks_per_fold, draws, n_models, seed=0):
    """What random picking would have averaged on the same test samples, with the model's number of picks in each
    fold: (95th percentile of one random picker, 95th percentile of the best of n_models random pickers)."""
    rng = np.random.default_rng(seed)
    total = sum(picks_per_fold)
    if total < 5:
        return None, None
    means = np.zeros(draws)
    for te, k in zip(fold_te, picks_per_fold):
        if k:
            v = net[te]
            means += np.array([v[rng.choice(len(v), k, replace=False)].sum() for _ in range(draws)])
    means /= total
    one = float(np.quantile(means, 0.95))
    # the luckiest of n pickers at its 95th percentile: the random picker's spread, at the quantile 0.95^(1/n)
    from statistics import NormalDist
    z = NormalDist().inv_cdf(0.95 ** (1 / max(1, n_models)))
    return one, float(means.mean() + z * means.std())


# ---------------------------------------------------------------- fitting
def _factory(slug, kind):
    from . import zoo as Z
    if kind == "cls":
        name = dict((s, n) for s, n, _k in ALGOS)[slug]
        return Z.TABULAR[name]()
    if kind == "ret":
        return {"ridge": Z.ridge, "rf_ret": Z.random_forest_reg, "gb_ret": Z.gradient_boosting_reg,
                "xgb_ret": Z.xgboost_reg, "lgbm_ret": Z.lightgbm_reg}[slug]()
    if kind == "exit":
        return Z.EXIT[dict(EXIT_ALGOS)[slug]]()
    raise ValueError(kind)


class Fitted:
    """One trained entry or exit model with a common scoring call: score(X) or, for the LSTM, score(S, M). Columns
    with no value at all in the training data (a variable recorded only since later) are left out, the same way at
    training and at scoring."""

    def __init__(self, kind, model, cols=None):
        self.kind, self.model, self.cols = kind, model, cols

    def _x(self, X):
        return X if self.cols is None else X[:, self.cols]

    def score(self, X, M=None):
        if self.kind == "seq":
            return self.model.predict_proba(X, M)
        if self.kind == "ret":
            return np.asarray(self.model.predict(self._x(X)), float)
        return np.asarray(self.model.predict_proba(self._x(X))[:, 1], float)


def fit(slug, kind, X, y, net, S=None, M=None, seed=0):
    if kind == "seq":
        from .lstm import LSTM
        return Fitted("seq", LSTM(S.shape[2], hidden=12, epochs=25, l2=3e-3, seed=seed).fit(S, M, y))
    cols = np.where(~np.isnan(X).all(axis=0))[0]
    mdl = _factory(slug, kind)
    if kind == "ret":
        mdl.fit(X[:, cols], np.clip(net, -60, 60))
    else:
        mdl.fit(X[:, cols], y)
    return Fitted(kind, mdl, cols)


def leading(fitted, keys, n=5):
    """The variables a fitted model leans on most, where the library reports it (tree importances, linear weights)."""
    m = fitted.model
    if getattr(fitted, "cols", None) is not None:
        keys = [keys[c] for c in fitted.cols]
    est = m.steps[-1][1] if hasattr(m, "steps") else getattr(m, "model", m)
    imp = getattr(est, "feature_importances_", None)
    if imp is None and hasattr(est, "coef_"):
        imp = np.abs(np.ravel(est.coef_))
    if imp is None or len(imp) < len(keys):
        return []
    imp = np.asarray(imp[:len(keys)], float)
    if not imp.sum():
        return []
    order = np.argsort(-imp)[:n]
    return [[keys[i], round(float(imp[i] / imp.sum()), 3)] for i in order if imp[i] > 0]


# ---------------------------------------------------------------- training: everything the Models tab reports
def train_all(path, pol, cfg_trade, cfg, sets, out_dir, now=None, log=print, set_algos=None):
    """Walk-forward test then final fit of every algorithm on every variable set (set_algos: the algorithms of the sets
    that train only some, see algos_for), and of the exit models. Writes each final model to out_dir and returns the
    summary (also written as summary.json)."""
    import warnings
    warnings.filterwarnings("ignore")
    now = now or time.time()
    t_start = time.time()
    os.makedirs(out_dir, exist_ok=True)
    samples = entry_samples(path, pol, cfg_trade)
    coins = len({s["mint"] for s in samples})
    summary = {"trained_at": now, "label": {"policy": pol, "text": f"net return after costs > 0 for {TRD.exit_label(pol)}"},
               "samples": len(samples), "coins": coins, "sets": {k: {"label": v, "keys": set_keys(k)} for k, v in sets.items()},
               "cfg": {k: cfg[k] for k in ("top_share", "fold_h", "exit_thr", "luck_draws", "seq_steps", "exit_every")},
               "entry": [], "exit": []}
    if len(samples) < cfg["min_samples"] or coins < cfg["min_coins"]:
        summary["status"] = (f"collecting: {len(samples)} labelled samples on {coins} coins so far; training starts at "
                             f"{cfg['min_samples']} on {cfg['min_coins']}")
        _write(out_dir, summary)
        log(summary["status"])
        return summary
    ts = np.array([s["ts"] for s in samples])
    y = np.array([int(s["net"] > 0) for s in samples])
    net = np.array([s["net"] for s in samples])
    mints = np.array([s["mint"] for s in samples])
    closed = np.array([s["ts"] + s["h"] * H for s in samples])        # when each sample's trade closed
    fl = folds(ts, closed, cfg)
    summary.update(period=[float(ts.min()), float(ts.max())], folds=len(fl), base_win=float(y.mean()), base_net=float(net.mean()),
                   fold_sizes=[[int(len(a)), int(len(b))] for a, b in fl], purge="trades closed before the test window")
    log(f"{len(samples)} samples on {coins} coins, {len(fl)} walk-forward folds; base: {y.mean():.0%} made money, average {net.mean():+.2f}%")
    if not fl:
        summary["status"] = "collecting: not enough history yet for one walk-forward fold"
        _write(out_dir, summary)
        return summary
    n_models = sum(len(algos_for(k, set_algos)) for k in sets) + 1
    te_all = np.concatenate([te for _tr, te in fl])
    base_oos = float(net[te_all].mean())
    summary["base_oos_net"] = base_oos
    summary["base_oos_win"] = float(y[te_all].mean())

    def evaluate(mid, slug, kind, set_name, keys, X, S, M):
        t0 = time.time()
        oos, pick = np.full(len(samples), np.nan), np.zeros(len(samples), bool)
        tr_auc, fold_auc, per_fold = [], [], []
        rng = np.random.default_rng(int(hashlib.md5(mid.encode()).hexdigest()[:8], 16))
        for tr, te in fl:
            if kind == "random":
                p_te, p_tr = rng.random(len(te)), rng.random(len(tr))
            else:
                fm = fit(slug, kind, X[tr] if X is not None else None, y[tr], net[tr],
                         S[tr] if S is not None else None, M[tr] if M is not None else None)
                p_te = fm.score(S[te], M[te]) if kind == "seq" else fm.score(X[te])
                p_tr = fm.score(S[tr], M[tr]) if kind == "seq" else fm.score(X[tr])
            oos[te] = p_te
            cut = np.quantile(p_tr, 1 - cfg["top_share"])
            pick[te] = p_te >= cut
            per_fold.append(int((p_te >= cut).sum()))
            a_tr, a_te = auc(y[tr], p_tr), auc(y[te], p_te)
            if a_tr is not None:
                tr_auc.append(a_tr)
            if a_te is not None:
                fold_auc.append(a_te)
        m = ~np.isnan(oos)
        sel = pick & m
        p = oos[m]
        rec = {"id": mid, "slug": slug, "algo": dict((s, n) for s, n, _k in ALGOS).get(slug, "Random scores (control)"),
               "family": FAMILY.get(slug), "kind": kind, "set": set_name, "n_vars": len(keys) if keys else 0,
               "n_test": int(m.sum()), "auc": auc(y[m], p), "auc_sd": float(np.std(fold_auc)) if len(fold_auc) > 1 else None,
               "train_auc": float(np.mean(tr_auc)) if tr_auc else None}
        rec["gap"] = rec["train_auc"] - rec["auc"] if rec["train_auc"] is not None and rec["auc"] is not None else None
        if kind in ("cls", "seq", "random"):
            pc = np.clip(p, 1e-6, 1 - 1e-6)
            yy = y[m]
            rec.update(accuracy=float(((pc >= 0.5) == yy).mean()),
                       balanced_acc=float(0.5 * (((pc >= 0.5) & (yy == 1)).sum() / max(1, (yy == 1).sum())
                                                 + ((pc < 0.5) & (yy == 0)).sum() / max(1, (yy == 0).sum()))),
                       brier=float(np.mean((pc - yy) ** 2)), logloss=float(-np.mean(yy * np.log(pc) + (1 - yy) * np.log(1 - pc))))
        else:
            rec.update(accuracy=float(((p > 0) == (y[m] == 1)).mean()), ic=spearman(p, net[m]))
        rec.update(picks=int(sel.sum()), pick_coins=int(len(set(mints[sel].tolist()))),
                   pick_win=float(y[sel].mean()) if sel.any() else None, pick_net=float(net[sel].mean()) if sel.any() else None,
                   pick_med=float(np.median(net[sel])) if sel.any() else None,
                   pick_t=clustered_t(net[sel], mints[sel]) if sel.sum() > 2 else None, base_net=float(net[m].mean()))
        rec["edge"] = rec["pick_net"] - rec["base_net"] if rec["pick_net"] is not None else None
        one, best = luck(net, [te for _tr, te in fl], per_fold, cfg["luck_draws"], n_models)
        rec.update(luck_one=one, luck_best=best,
                   beats_luck=bool(rec["pick_net"] is not None and best is not None and rec["pick_net"] > best))
        rec["seconds_wf"] = round(time.time() - t0, 1)
        return rec

    for set_name in sets:
        keys = set_keys(set_name)
        X = matrix([s["f"] for s in samples], keys)
        sk = seq_keys(set_name)
        S_list, M_list = [], []
        for s in samples:
            a, b = sequence(path[s["mint"]], s["i"], sk, cfg["seq_steps"])
            S_list.append(a)
            M_list.append(b)
        S, M = np.array(S_list, float), np.array(M_list, float)
        for slug, _name, kind in algos_for(set_name, set_algos):
            mid = f"{slug}.{set_name}"
            try:
                rec = evaluate(mid, slug, kind, set_name, keys if kind != "seq" else sk, X, S, M)
                t0 = time.time()
                fm = fit(slug, kind, X, y, net, S, M)
                tr_scores = fm.score(S, M) if kind == "seq" else fm.score(X)
                rec["thr"] = float(np.quantile(tr_scores, 1 - cfg["top_share"]))
                rec["keys"] = sk if kind == "seq" else keys
                rec["leading"] = leading(fm, keys) if kind != "seq" else []
                rec["file"] = f"{mid}.pkl"
                with open(os.path.join(out_dir, rec["file"]), "wb") as fh:
                    pickle.dump(fm, fh, protocol=pickle.HIGHEST_PROTOCOL)
                rec["seconds_fit"] = round(time.time() - t0, 1)
                rec["train_rows"], rec["train_coins"] = len(samples), coins
            except Exception as e:                       # one library failing must not stop the others
                rec = {"id": mid, "slug": slug, "algo": _name, "family": FAMILY.get(slug), "kind": kind, "set": set_name,
                       "error": f"{type(e).__name__}: {e}"[:300]}
            summary["entry"].append(rec)
            log(f"  {mid:<28} " + (f"AUC {rec.get('auc') or 0:.3f} (train {rec.get('train_auc') or 0:.3f}) top fifth "
                                   f"{rec.get('picks')} avg {rec.get('pick_net') or 0:+.2f}% vs {rec.get('base_net') or 0:+.2f}% "
                                   f"luck {rec.get('luck_best') or 0:+.2f}%" if "error" not in rec else rec["error"]))
    rec = evaluate(RANDOM_ID, RANDOM_ID, "random", "none", [], None, None, None)
    rec.update(thr=1 - cfg["top_share"], keys=[], file=None, train_rows=len(samples), train_coins=coins)
    summary["entry"].append(rec)

    # ---- exit models
    summary["exit"] = train_exits(path, samples, pol, cfg_trade, cfg, fl, out_dir, log)
    summary["seconds"] = round(time.time() - t_start)
    summary["status"] = "ok"
    _write(out_dir, summary)
    return summary


def train_exits(path, samples, pol, cfg_trade, cfg, fl, out_dir, log):
    rows = exit_samples(path, samples, cfg_trade, cfg["exit_every"], cfg["max_exit_rows"])
    out = []
    if len(rows) < 500:
        return out
    keys = set_keys("all") + STATE_KEYS
    X = matrix([e["x"] for e in rows], keys)
    y = np.array([e["y"] for e in rows])
    ks = np.array([e["k"] for e in rows])
    s_ts = np.array([s["ts"] for s in samples])
    log(f"exit models: {len(rows)} decision points; selling then beat holding on in {y.mean():.0%}")

    def scan_rows(idx_samples):
        """Every scan of the given sample trades with its exit inputs: ([(k, j)], matrix), to replay a model's calls."""
        where, feats = [], []
        for k in idx_samples:
            s = samples[k]
            rws = path[s["mint"]]
            ts0_, _st, p0, l0 = rws[s["i"]][:4]
            peak = p0
            for j in range(s["i"] + 1, s["j"] + 1):
                tj, _sj, pj, lj, cj, fj = rws[j]
                if not pj:
                    continue
                feats.append(exit_row(fj, cj, trade_state(ts0_, p0, l0, peak, pj, lj, tj)))
                where.append((k, j))
                peak = max(peak, pj)
        return where, matrix(feats, keys) if feats else None

    s_closed = np.array([s["ts"] + s["h"] * H for s in samples])
    plan = []                                     # per fold: training rows, test rows, and the test trades' scans
    for tr, te in fl:
        # decision points from trades that had closed before the test window opened (their labels need the outcome)
        tr_e = np.isin(ks, tr) & (s_closed[ks] < s_ts[te].min() - 900)
        te_e = np.isin(ks, te)
        if tr_e.sum() >= 300 and te_e.sum() >= 50:
            plan.append((tr_e, te_e, te.tolist(), scan_rows(te.tolist())))
    for slug, name in EXIT_ALGOS:
        t0 = time.time()
        mpol = {**pol, "model": slug}                 # the live exit, plus this model's calls to sell earlier
        try:
            oos_p, oos_y, tr_aucs, tested, mine, base = [], [], [], [], [], []
            for tr_e, te_e, te_k, (where, Xd) in plan:
                fm = fit(slug, "exit", X[tr_e], y[tr_e], None)
                oos_p.extend(fm.score(X[te_e]).tolist())
                oos_y.extend(y[te_e].tolist())
                a_tr = auc(y[tr_e], fm.score(X[tr_e]))
                if a_tr is not None:
                    tr_aucs.append(a_tr)
                dec = dict(zip(where, fm.score(Xd).tolist())) if Xd is not None else {}
                for k in te_k:
                    s = samples[k]
                    r = simulate(path[s["mint"]], s["i"], mpol, cfg_trade,
                                 sell_at=lambda j, _pk, k=k: dec.get((k, j), 0) >= cfg["exit_thr"])
                    if r is None:
                        continue
                    tested.append(k)
                    mine.append(r[0])
                    base.append(s["net"])
            if not tested:
                continue
            diff = np.array(mine) - np.array(base)
            rec = {"id": f"x:{slug}", "slug": slug, "algo": name, "family": FAMILY.get(slug), "n_vars": len(keys),
                   "decisions": len(oos_y), "auc": auc(oos_y, oos_p), "train_auc": float(np.mean(tr_aucs)) if tr_aucs else None,
                   "accuracy": float(np.mean((np.array(oos_p) >= cfg["exit_thr"]) == np.array(oos_y))),
                   "sell_rate": float(np.mean(np.array(oos_p) >= cfg["exit_thr"])), "trades": len(tested),
                   "net": float(np.mean(mine)), "base_net": float(np.mean(base)), "gain": float(diff.mean()),
                   "gain_t": clustered_t(diff, [samples[k]["mint"] for k in tested]),
                   "early": float(np.mean(np.array(mine) != np.array(base)))}
            rec["gap"] = rec["train_auc"] - rec["auc"] if rec["train_auc"] is not None and rec["auc"] is not None else None
            fm = fit(slug, "exit", X, y, None)
            rec.update(keys=keys, file=f"x.{slug}.pkl", leading=leading(fm, keys), thr=cfg["exit_thr"])
            with open(os.path.join(out_dir, rec["file"]), "wb") as fh:
                pickle.dump(fm, fh, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as e:
            rec = {"id": f"x:{slug}", "slug": slug, "algo": name, "family": FAMILY.get(slug), "error": f"{type(e).__name__}: {e}"[:300]}
        rec["seconds"] = round(time.time() - t0, 1)
        out.append(rec)
        log(f"  x:{slug:<8} " + (f"AUC {rec.get('auc') or 0:.3f} (train {rec.get('train_auc') or 0:.3f}) following it "
                                 f"{rec.get('net') or 0:+.2f}% vs {rec.get('base_net') or 0:+.2f}%, gain {rec.get('gain') or 0:+.2f} "
                                 f"(t {rec.get('gain_t') or 0:+.1f})" if "error" not in rec else rec["error"]))
    return out


def _write(out_dir, summary):
    tmp = os.path.join(out_dir, "summary.json.tmp")
    with open(tmp, "w") as f:
        json.dump(_clean(summary), f, separators=(",", ":"), allow_nan=False)
    os.replace(tmp, os.path.join(out_dir, "summary.json"))


def _clean(o):
    if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
        return None
    if isinstance(o, (np.floating,)):
        return _clean(float(o))
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


# ---------------------------------------------------------------- the scan's side: load, score, decide
def read_summary(d):
    try:
        with open(os.path.join(d, "summary.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def rule_id(mid):
    return "m:" + mid


def rules_for(summary):
    """The bench rules the models trade through: one per trained entry model, plus the random control."""
    out = []
    for m in (summary or {}).get("entry") or []:
        if m.get("error") or (m["id"] != RANDOM_ID and not m.get("file")):
            continue
        set_label = ((summary.get("sets") or {}).get(m.get("set")) or {}).get("label")
        label = (f"{m['algo']}, {set_label}: top fifth of its scores" if m["id"] != RANDOM_ID
                 else "Random scores (control): a random fifth of readings")
        out.append({"id": rule_id(m["id"]), "label": label, "all": [], "model": m["id"], "source": "model"})
    return out


def exit_policies(summary):
    """Exit policies for the bench, one per exit model: the label's policy plus the model's call to sell earlier."""
    pol = ((summary or {}).get("label") or {}).get("policy") or {}
    out = []
    for e in (summary or {}).get("exit") or []:
        if e.get("error") or not e.get("file"):
            continue
        out.append({**{k: v for k, v in pol.items() if k not in ("id", "label")}, "id": e["id"], "model": e["slug"],
                    "algo": e["algo"]})
    return out


def coin_draw(mint, now, share):
    """The random control's pick for a coin at a scan: a fixed hash of both, true for about `share` of readings."""
    h = int(hashlib.md5(f"{mint}|{int(now)}".encode()).hexdigest()[:8], 16)
    return h / 0xFFFFFFFF < share


class Bank:
    """The trained models as the scan uses them. Never raises: anything missing or unreadable is left out, and the
    scan carries on without it."""

    def __init__(self, d, now, max_age_h):
        self.summary = read_summary(d) if d else None
        self.entry, self.exit, self.errors = {}, {}, []
        self.fresh = False
        if not self.summary or self.summary.get("status") != "ok":
            return
        self.age_h = (now - self.summary["trained_at"]) / H
        self.fresh = self.age_h <= max_age_h
        for m in self.summary.get("entry") or []:
            if m.get("file"):
                self._load(d, m, self.entry)
        for e in self.summary.get("exit") or []:
            if e.get("file"):
                self._load(d, e, self.exit)

    def _load(self, d, meta, into):
        try:
            with open(os.path.join(d, meta["file"]), "rb") as f:
                into[meta["id"]] = (meta, pickle.load(f))
        except Exception as e:                           # a version mismatch or a missing file skips that model only
            self.errors.append(f"{meta['id']}: {type(e).__name__}")

    def entry_scores(self, feats, seqs):
        """{model id: {mint: score}} for the coins passing every gate this scan. seqs: {mint: (rows, i)} for the LSTM."""
        mints = list(feats)
        out = {}
        if not mints or not self.fresh:
            return out
        steps = (self.summary.get("cfg") or {}).get("seq_steps") or 8
        for mid, (meta, fm) in self.entry.items():
            try:
                if meta["kind"] == "seq":
                    S, M = [], []
                    for mt in mints:
                        rows, i = seqs.get(mt, ([], -1))
                        if i >= 0:
                            a, b = sequence(rows, i, meta["keys"], steps)
                        else:
                            a, b = [[0.0] * len(meta["keys"])] * steps, [0.0] * steps
                        S.append(a)
                        M.append(b)
                    p = fm.score(np.array(S, float), np.array(M, float))
                else:
                    p = fm.score(matrix([feats[mt] for mt in mints], meta["keys"]))
                out[mid] = dict(zip(mints, [float(v) for v in p]))
            except Exception as e:
                self.errors.append(f"{mid}: {type(e).__name__}")
        return out

    def fired(self, scores, feats, now, share):
        """{model id: {mint: score}} for the coins each model would buy: a score at or above its threshold (and the
        random control's draw)."""
        out = {}
        for mid, sc in scores.items():
            thr = self.entry[mid][0].get("thr")
            if thr is not None:
                out[mid] = {mt: v for mt, v in sc.items() if v >= thr}
        if self.fresh and any(m["id"] == RANDOM_ID for m in self.summary.get("entry") or []):
            out[RANDOM_ID] = {mt: 1.0 for mt in feats if coin_draw(mt, now, share)}
        return out

    def exit_calls(self, items, thr):
        """items: [(sig id, policy id, inputs)] for open trades still undecided under an exit model's policy.
        Returns {(sig id, policy id): probability} and the set that the model says to sell."""
        probs, sells = {}, set()
        by = defaultdict(list)
        for sid, pid, x in items:
            by[pid].append((sid, x))
        for pid, lst in by.items():
            if pid not in self.exit or not self.fresh:
                continue
            meta, fm = self.exit[pid]
            try:
                p = fm.score(matrix([x for _s, x in lst], meta["keys"]))
            except Exception as e:
                self.errors.append(f"{pid}: {type(e).__name__}")
                continue
            for (sid, _x), v in zip(lst, p.tolist()):
                probs[(sid, pid)] = v
                if v >= thr:
                    sells.add((sid, pid))
        return probs, sells
