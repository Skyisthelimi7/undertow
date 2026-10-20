"""The Lab: which variables separate tokens that rose after they were observed from those that fell. Pure functions.

The scanner stores an observation for every candidate once an hour, and for every entry and exit as it happens:
the price, about 45 variables and the result of each shadow rule (a candidate gate that is recorded but never
applied). Each later run fills in what happened next: the multiple of the observed price at +1h, +6h and +24h, and
the high and low seen within 24 hours. This module turns those rows into evidence: for each variable, how well it
separates risers from fallers, a suggested line found on the earlier half of the data and tested on the later half,
and a verdict that stays "collecting" until the sample is big enough to mean something.
"""
import math

H = 3600

# key, label, unit: usd, pct (a level in %), chg (a change in %), share (0-1), frac (signed fraction), ratio,
# x (multiple), n, h, score
VARIABLES = [
    ("mc", "Market cap", "usd"), ("liq", "Liquidity", "usd"), ("liq_pct", "Liquidity ÷ market cap", "share"),
    ("lfdv", "Liquidity ÷ FDV", "ratio"), ("age", "Hours on a DEX", "h"),
    ("v5m", "Volume, 5 min", "usd"), ("v1h", "Volume, 1h", "usd"), ("v6h", "Volume, 6h", "usd"),
    ("v24h", "Volume, 24h", "usd"), ("turn", "24h volume ÷ market cap", "ratio"),
    ("v1h_24", "Volume pace: last hour vs 24h average", "x"), ("v6h_24", "Volume pace: last 6h vs 24h average", "x"),
    ("c5m", "Price change, 5 min","chg"), ("c1h", "Price change, 1h","chg"), ("c6h", "Price change, 6h","chg"),
    ("c24h", "Price change, 24h","chg"), ("bs1h", "Buys ÷ sells, 1h (trade counts)", "ratio"),
    ("bs24h", "Buys ÷ sells, 24h (trade counts)", "ratio"), ("nf1h", "Net buying, 1h", "usd"),
    ("nf1h_liq", "Net buying 1h ÷ liquidity", "frac"), ("nf6h", "Net buying, 6h", "usd"), ("nf24h", "Net buying, 24h", "usd"),
    ("ss1h", "Sells as a share of 1h volume", "share"), ("tr1h", "Wallets trading, 1h", "n"),
    ("brd1h", "Share of 1h traders who net-bought", "share"), ("ob24h", "Organic buyers, 24h", "n"),
    ("hold", "Holders", "n"), ("hc1h", "Holder change, 1h","chg"), ("hc24h", "Holder change, 24h","chg"),
    ("liqc1h", "Liquidity change, 1h","chg"), ("volc1h", "Volume change, 1h vs hour before","chg"),
    ("org", "Jupiter organic score", "score"), ("top10", "Top-10 holders' share", "pct"),
    ("dev", "Developer holding", "pct"), ("devm", "Deployer's launches", "n"), ("exit", "Exit cost of $500", "pct"),
    ("clu", "Largest wallet cluster, % of supply", "pct"), ("metamut", "Metadata changeable (1 = yes)", "n"),
    ("crs", "Crowd: share of open calls saying rug", "share"), ("crn", "Crowd: open calls", "n"),
    ("cvn", "Crowd: watch minus avoid votes", "n"), ("cfl", "Crowd: bundled and rug-suspected tags", "n"),
    ("rf", "Rug-study red flags", "n"), ("w10", "Wallets trading, 10 min", "n"), ("t5", "Top-5 buyers' share of buying", "share"),
    ("ss15", "Sells as a share of 15-min volume", "share"), ("mom", "Momentum score", "score"),
    ("ext", "Price vs 6h average", "frac"), ("dd24", "Price vs 24h high", "frac"),
    ("dd24s", "Price vs highest scan price in 24h", "frac"),
    ("tgm", "Telegram members", "n"), ("tgr", "Telegram bot-risk", "score"),
    ("sol24", "SOL price change, 24h","chg"), ("mkt1h", "Share of candidates rising, 1h", "share"),
]
VAR_KEYS = [v[0] for v in VARIABLES]


def _r(v):
    """Round to 4 significant figures to keep stored rows small; pass through None and non-numbers."""
    if isinstance(v, bool) or v is None or not isinstance(v, (int, float)):
        return v
    if v != v or v in (float("inf"), float("-inf")):
        return None
    return float(f"{v:.4g}") if isinstance(v, float) else v


def _div(a, b):
    return a / b if a is not None and b else None


def features(d, m, j, mq=None, mom=None, tg=None, regime=None):
    """Every variable for one candidate at one moment. d: DEX Screener pair, m: scanner metrics, j: Jupiter record,
    mq: momentum quality (candle stats), mom: momentum score, tg: Telegram counts, regime: market-wide numbers."""
    d, m, j = d or {}, m or {}, j or {}
    vol, chg = d.get("vol") or {}, d.get("chg") or {}
    s1, s6, s24 = j.get("s1h") or {}, j.get("s6h") or {}, j.get("s24h") or {}
    sw = m.get("swarm") or {}
    mc, liq, v1, v6, v24 = d.get("mcap"), d.get("liq"), vol.get("h1"), vol.get("h6"), vol.get("h24")
    f = {
        "mc": mc, "liq": liq, "liq_pct": _div(liq, mc), "lfdv": m.get("lfdv"),
        "age": m["age_min"] / 60 if m.get("age_min") is not None else None,
        "v5m": vol.get("m5"), "v1h": v1, "v6h": v6, "v24h": v24, "turn": _div(v24, mc),
        "v1h_24": _div(v1 * 24, v24) if v1 is not None else None, "v6h_24": _div(v6 * 4, v24) if v6 is not None else None,
        "c5m": chg.get("m5"), "c1h": chg.get("h1"), "c6h": chg.get("h6"), "c24h": chg.get("h24"),
        "bs1h": _div(d.get("buys1"), d.get("sells1")), "bs24h": _div(d.get("buys24"), d.get("sells24")),
        "nf1h": s1.get("net_flow"), "nf1h_liq": _div(s1.get("net_flow"), liq), "nf6h": s6.get("net_flow"),
        "nf24h": s24.get("net_flow"), "ss1h": m.get("sell_share_1h"), "tr1h": s1.get("traders"),
        "brd1h": _div(s1.get("net_buyers"), s1.get("traders")), "ob24h": s24.get("organic_buyers"),
        "hold": m.get("holders"), "hc1h": s1.get("holder_change"), "hc24h": s24.get("holder_change"),
        "liqc1h": s1.get("liq_change"), "volc1h": s1.get("vol_change"), "org": j.get("organic"),
        "top10": m.get("top10"), "dev": m.get("creator_pct"), "devm": j.get("dev_mints"), "exit": m.get("exit_cost"),
        "clu": m.get("cluster_pct"),
        "metamut": None if m.get("meta_mutable") is None else int(bool(m["meta_mutable"])),
        # the crowd (rug calls, votes and tags from signed-in visitors), tested like any other variable
        "crs": (m.get("crowd") or {}).get("rug_share"), "crn": (m.get("crowd") or {}).get("calls"),
        "cvn": (m.get("crowd") or {}).get("net_votes"), "cfl": (m.get("crowd") or {}).get("bad_tags"),
        "rf": (m.get("risk") or {}).get("count"), "w10": sw.get("wallets_10m"), "t5": sw.get("top5_share"),
        "ss15": sw.get("sell_share_15m"), "mom": (mom or {}).get("score"),
        "ext": (mq or {}).get("extension"), "dd24": (mq or {}).get("drawdown_24h"),
        "dd24s": (regime or {}).get("dd24s"),
        "tgm": (tg or {}).get("members"), "tgr": (tg or {}).get("bot_risk"),
        "sol24": (regime or {}).get("sol24"), "mkt1h": (regime or {}).get("mkt1h"),
        # categories, used to split results rather than ranked
        "lp": j.get("launchpad") or "direct", "kind": m.get("venue_kind"), "q": (mq or {}).get("label"),
    }
    return {k: _r(v) for k, v in f.items() if v is not None}


_OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b}


def rule_results(f, rules):
    """{rule id: 1 or 0} for each shadow rule whose variable is known."""
    out = {}
    for rid, _label, key, op, at in rules:
        v = f.get(key)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[rid] = 1 if _OPS[op](v, at) else 0
    return out


# ------------------------------------------------------------------ outcomes, filled in run by run
HORIZONS = (("p1", 1), ("p6", 6), ("p24", 24))
UP_LEVELS = (10, 20, 30, 50, 100)        # % above the observed price: first time each was reached within 24h
DOWN_LEVELS = (10, 20, 30, 50, 80)       # % below it


def step(o, price, now, tol_s):
    """Fold one later price into an observation's outcome. o: dict with ts, price and the outcome fields. Returns
    the fields that changed. A horizon is recorded from the first price seen within tol_s after it; if no run lands
    in that window, it stays empty rather than being guessed."""
    if not price or not o.get("price"):
        return {}
    x, age = price / o["price"], now - o["ts"]
    ch = {}
    if 0 < age <= 24 * H + tol_s:
        if o.get("hi") is None or x > o["hi"]:
            ch["hi"] = x
        if o.get("lo") is None or x < o["lo"]:
            ch["lo"] = x
        for key, lim in (("up50_ts", 1.5), ("x2_ts", 2.0)):
            if o.get(key) is None and x >= lim:
                ch[key] = now
        if o.get("dn80_ts") is None and x <= 0.2:
            ch["dn80_ts"] = now
        cross = dict(o.get("cross") or {})
        for lv in UP_LEVELS:
            if f"u{lv}" not in cross and x >= 1 + lv / 100:
                cross[f"u{lv}"] = now
        for lv in DOWN_LEVELS:
            if f"d{lv}" not in cross and x <= 1 - lv / 100:
                cross[f"d{lv}"] = now
        if cross != (o.get("cross") or {}):
            ch["cross"] = cross
    for key, h in HORIZONS:
        if o.get(key) is None and h * H <= age <= h * H + tol_s:
            ch[key] = x
    if age > 24 * H + tol_s:
        ch["done"] = 1
    return ch


def rugged(o):
    """The rug study's label within 24h: fell to 0.2x before ever reaching 1.5x. None while undecided."""
    if o.get("dn80_ts") is not None and (o.get("up50_ts") is None or o["dn80_ts"] < o["up50_ts"]):
        return True
    if o.get("up50_ts") is not None or o.get("done"):
        return False
    return None


# ------------------------------------------------------------------ statistics (standard library only)
def _ranks(xs):
    """Average ranks (1-based) with ties sharing their mean rank."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def auc(values, labels):
    """Probability that a randomly chosen riser has a higher value than a randomly chosen faller (ties count half).
    0.5 = no signal; above 0.5 higher values rose more; below 0.5 lower values rose more. Returns (auc, se)."""
    n1 = sum(1 for y in labels if y)
    n0 = len(labels) - n1
    if n1 == 0 or n0 == 0:
        return None, None
    r = _ranks(values)
    a = (sum(r[i] for i, y in enumerate(labels) if y) - n1 * (n1 + 1) / 2) / (n1 * n0)
    q1, q2 = a / (2 - a), 2 * a * a / (1 + a)
    var = (a * (1 - a) + (n1 - 1) * (q1 - a * a) + (n0 - 1) * (q2 - a * a)) / (n1 * n0)     # Hanley & McNeil (1982)
    return a, math.sqrt(max(var, 0.0))


def spearman(xs, ys):
    if len(xs) < 3:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    sy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return sxy / (sx * sy) if sx and sy else None


def _median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _quantile(sorted_xs, q):
    if not sorted_xs:
        return None
    i = min(len(sorted_xs) - 1, max(0, int(round(q * (len(sorted_xs) - 1)))))
    return sorted_xs[i]


def _summ(pairs):
    """pairs: [(value, multiple)]. Share that rose, median multiple."""
    if not pairs:
        return {"n": 0, "up": None, "med": None}
    xs = [p[1] for p in pairs]
    return {"n": len(xs), "up": sum(1 for x in xs if x > 1) / len(xs), "med": _median(xs)}


def best_cut(train, min_keep):
    """The single line on a variable that gave the highest share of risers on the training rows while keeping at
    least min_keep of them. train: [(value, multiple)]. Returns (op, threshold, keep, share up) or None."""
    if len(train) < 10:
        return None
    vals = sorted(v for v, _ in train)
    best = None
    for q in (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
        at = _quantile(vals, q)
        for op in (">=", "<="):
            kept = [x for v, x in train if _OPS[op](v, at)]
            keep = len(kept) / len(train)
            if keep < min_keep or len(kept) < 5:
                continue
            up = sum(1 for x in kept if x > 1) / len(kept)
            if best is None or up > best[3] + 1e-9 or (abs(up - best[3]) <= 1e-9 and keep > best[2]):
                best = (op, at, keep, up)
    return best


def judge(n, n_test, a, se, lift_in, lift_out, n_kept_out, cfg):
    """Verdict for a variable. Works: the rank signal is clear (AUC at least cfg['min_auc_gap'] from 0.5 and more than
    cfg['z'] standard errors from it; 2.5 rather than 1.96 because some 50 variables are tested at once) and the line
    found on the earlier half lifts the share that rose by at least cfg['min_lift'] in both halves. Weak: one of those
    holds. None: neither. Collecting: fewer than cfg['min_n'] rows, or fewer than cfg['min_test'] in the later half."""
    if n < cfg["min_n"] or n_test < cfg["min_test"] or a is None:
        return "collecting"
    clear = abs(a - 0.5) >= cfg["min_auc_gap"] and abs(a - 0.5) > cfg["z"] * (se if se is not None else 1)
    holds = (n_kept_out >= 10 and lift_in is not None and lift_out is not None
             and lift_in >= cfg["min_lift"] and lift_out >= cfg["min_lift"])
    if clear and holds:
        return "works"
    if clear or holds:
        return "weak"
    return "none"


def analyse_variable(rows, key, horizon, cfg):
    """rows: time-ordered observations with f (features) and the horizon multiple. Returns the variable's record."""
    pairs = [(r["f"][key], r[horizon], r["ts"]) for r in rows
             if isinstance(r["f"].get(key), (int, float)) and r.get(horizon) is not None]
    pairs.sort(key=lambda p: p[2])
    n = len(pairs)
    out = {"key": key, "n": n}
    if n < 8:
        out["verdict"] = "collecting"
        return out
    vals, mults = [p[0] for p in pairs], [p[1] for p in pairs]
    a, se = auc(vals, [x > 1 for x in mults])
    rho = spearman(vals, [math.log(max(x, 1e-6)) for x in mults])
    order = sorted(range(n), key=lambda i: vals[i])
    fifths = []
    for k in range(5):
        idx = order[k * n // 5:(k + 1) * n // 5]
        if idx:
            s = _summ([(vals[i], mults[i]) for i in idx])
            fifths.append({"lo": _r(vals[idx[0]]), "hi": _r(vals[idx[-1]]), "n": s["n"], "up": _r(s["up"]), "med": _r(s["med"])})
    half = n // 2
    train, test = [(v, x) for v, x, _ in pairs[:half]], [(v, x) for v, x, _ in pairs[half:]]
    cut = best_cut(train, cfg["min_keep"])
    base_in = _summ(train)["up"]
    base_out = _summ(test)["up"]
    cut_rec, lift_in, lift_out, n_out = None, None, None, 0
    if cut:
        op, at, keep, up_in = cut
        kept_out = [(v, x) for v, x in test if _OPS[op](v, at)]
        s_out = _summ(kept_out)
        n_out = s_out["n"]
        lift_in = up_in - base_in if base_in is not None else None
        lift_out = (s_out["up"] - base_out) if s_out["up"] is not None and base_out is not None else None
        cut_rec = {"op": op, "at": _r(at), "keep_in": _r(keep), "up_in": _r(up_in), "base_in": _r(base_in),
                   "n_out": n_out, "keep_out": _r(n_out / len(test)) if test else None, "up_out": _r(s_out["up"]),
                   "base_out": _r(base_out), "med_out": _r(s_out["med"])}
    out.update({"auc": _r(a), "se": _r(se), "rho": _r(rho), "fifths": fifths, "cut": cut_rec,
                "verdict": judge(n, len(test), a, se, lift_in, lift_out, n_out, cfg)})
    return out


def analyse_rule(rows, rule, horizon, cfg):
    rid, label, key, op, at = rule
    known = [r["rules"][rid] for r in rows if r.get("rules") and rid in r["rules"]]
    pairs = [(r["rules"][rid], r[horizon], r["ts"], rugged(r)) for r in rows
             if r.get("rules") and rid in r["rules"] and r.get(horizon) is not None]
    pairs.sort(key=lambda p: p[2])
    n = len(pairs)

    def grp(ps, flag):
        xs = [x for f, x, _t, _g in ps if f == flag]
        rg = [g for f, _x, _t, g in ps if f == flag and g is not None]
        s = _summ([(0, x) for x in xs])
        s["rug"] = _r(sum(1 for g in rg if g) / len(rg)) if rg else None
        return s

    yes, no = grp(pairs, 1), grp(pairs, 0)
    half = n // 2
    ty, tn = grp(pairs[:half], 1), grp(pairs[:half], 0)
    oy, on = grp(pairs[half:], 1), grp(pairs[half:], 0)
    lift = lambda a, b: (a["up"] - b["up"]) if a["up"] is not None and b["up"] is not None else None
    li, lo = lift(ty, tn), lift(oy, on)
    z = None                                   # two-proportion z-test on the whole sample
    if yes["n"] and no["n"]:
        k = yes["up"] * yes["n"] + no["up"] * no["n"]
        p = k / (yes["n"] + no["n"])
        se = math.sqrt(p * (1 - p) * (1 / yes["n"] + 1 / no["n"]))
        z = (yes["up"] - no["up"]) / se if se else None
    if n < cfg["min_n"] or n - half < cfg["min_test"] or min(oy["n"], on["n"]) < 10:
        verdict = "collecting"
    elif z is not None and z >= cfg["z"] and li is not None and lo is not None and li >= cfg["min_lift"] and lo >= cfg["min_lift"]:
        verdict = "helps"
    elif z is not None and z <= -cfg["z"] and li is not None and lo is not None and li <= -cfg["min_lift"] and lo <= -cfg["min_lift"]:
        verdict = "hurts"
    else:
        verdict = "none"
    return {"id": rid, "label": label, "n": n, "keep": _r(yes["n"] / n) if n else None,
            "n_all": len(known), "keep_all": _r(sum(known) / len(known)) if known else None,
            "pass": {k: _r(v) for k, v in yes.items()}, "fail": {k: _r(v) for k, v in no.items()},
            "lift_in": _r(li), "lift_out": _r(lo), "z": _r(z), "verdict": verdict}


def exit_result(o, tp, sl):
    """What a position opened at the observation would have returned (as a fraction) with a take-profit at +tp% and
    a stop at -sl% (sl None = no stop), else sold at +24h. When both levels were first seen in the same run, the stop
    is assumed to have come first. None if the day's outcome is not in yet."""
    cross = o.get("cross") or {}
    t_up = cross.get(f"u{tp}")
    t_dn = cross.get(f"d{sl}") if sl else None
    if t_up is not None and (t_dn is None or t_up < t_dn):
        return tp / 100
    if t_dn is not None:
        return -sl / 100
    return o["p24"] - 1 if o.get("p24") is not None else None


def exit_rules(rows):
    """Every take-profit and stop pair on the grid, against simply holding for 24 hours."""
    done = [r for r in rows if r.get("p24") is not None]
    out = []
    if not done:
        return {"n": 0, "hold": None, "rules": []}

    def score(results):
        rs = [x for x in results if x is not None]
        if not rs:
            return None
        return {"n": len(rs), "win": _r(sum(1 for x in rs if x > 0) / len(rs)), "mean": _r(sum(rs) / len(rs)),
                "med": _r(_median(rs))}
    hold = score([r["p24"] - 1 for r in done])
    for tp in UP_LEVELS:
        for sl in (None,) + DOWN_LEVELS[:4]:
            s = score([exit_result(r, tp, sl) for r in done])
            if s:
                out.append({"tp": tp, "sl": sl, **s})
    out.sort(key=lambda e: -(e["mean"] or -9))
    return {"n": len(done), "hold": hold, "rules": out}


def populations(rows):
    """Three views of the observations, each one row per token or per token-day so a token watched for hours is not
    counted dozens of times: entries (first entry per token), passing (first hourly row per token-day that passed
    every gate) and all (first hourly row per token-day, passed or not)."""
    entries, passing, everything = {}, {}, {}
    for r in sorted(rows, key=lambda r: r["ts"]):
        day = int(r["ts"] // 86400)
        if r["ev"] == "entry":
            entries.setdefault(r["mint"], r)
        if r["ev"] in ("hourly", "entry"):          # an entry is also that hour's observation of the token
            everything.setdefault((r["mint"], day), r)
            if r.get("passed"):
                passing.setdefault((r["mint"], day), r)
    return {"entries": list(entries.values()), "passing": list(passing.values()), "all": list(everything.values())}


def baseline(rows, horizon):
    xs = [r[horizon] for r in rows if r.get(horizon) is not None]
    rg = [rugged(r) for r in rows if r.get("done") or r.get("dn80_ts") is not None or r.get("up50_ts") is not None]
    rg = [g for g in rg if g is not None]
    s = _summ([(0, x) for x in xs])
    return {"n": len(rows), "n_out": s["n"], "up": _r(s["up"]), "med": _r(s["med"]),
            "p25": _r(_quantile(sorted(xs), 0.25)), "p75": _r(_quantile(sorted(xs), 0.75)),
            "rug": _r(sum(1 for g in rg if g) / len(rg)) if rg else None, "n_rug": len(rg)}


def analyse(rows, rules, cfg, horizons=("p6", "p24")):
    """The Lab's whole output: for each population and horizon, the baseline, every variable and every rule."""
    pops = populations(rows)
    out = {"cfg": cfg, "pops": {}}
    for name, pr in pops.items():
        pr = sorted(pr, key=lambda r: r["ts"])
        res = {}
        for h in horizons:
            res[h] = {"base": baseline(pr, h),
                      "vars": [analyse_variable(pr, k, h, cfg) for k in VAR_KEYS],
                      "rules": [analyse_rule(pr, rule, h, cfg) for rule in rules]}
        if name in ("entries", "passing"):
            res["exits"] = exit_rules(pr)
        out["pops"][name] = res
    return out
