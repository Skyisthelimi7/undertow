"""Buy and sell signals that have to earn their place. Pure functions: scan.py stores what they return.

Every scan, each coin that passes every gate is checked against the entry rules on the bench. A rule that fires opens
a paper trade at that scan's price. Every later scan steps each open trade through every exit policy on the bench, so
one entry gives a result under each way of selling it. Nothing is bought: the record says what following a rule would
have returned after pool fees and price impact on a fixed position size, priced the way the scan sees the market
(one price per scan, so a stop fills at the next scan's price, not at its level).

The weekly review reads those records:
  entry rules  live after promote_after reviews in a row in which the rule's forward record (trades opened after it
               joined the bench, so it was never fitted to them) clears costs: at least min_trades settled trades, an
               average net return of at least min_edge %, and t >= z with errors clustered by coin. Retired after
               retire_after reviews in a row of a losing record, or when it fires too rarely to judge.
  exit policy  switches when another policy beat it on the same entries (a paired comparison) in switch_after reviews
               in a row, by at least switch_min_gain points with t >= z.
  variables    scored on every gate-passing coin: does the variable separate coins that rose over the next hours from
               coins that fell, the same way in both halves of the window? Variables that do seed new rules; variables
               that keep showing nothing stop seeding rules and are checked again later.
"""
import math, time
from collections import defaultdict
from . import lab as LAB, attention as ATT, minute as MIN

H = 3600
OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b}
OP_WORDS = {">=": "at least", ">": "above", "<=": "at most", "<": "below"}

# ---------------------------------------------------------------- variables
# The scanner's own price history (one price a scan) gives the short-term shape of the move; the rest are the Lab's
# variables, with the Lab's labels and units.
PATH_VARS = [
    ("r15", "Price change since the last scan (about 15 min)", "chg"),
    ("r30", "Price change, last 30 min", "chg"),
    ("r3h", "Price change, last 3h", "chg"),
    ("ru6", "Rise from its 6h low", "chg"),
    ("dd6", "Price vs its 6h high", "chg"),
    ("vola", "Typical move between scans, last 6h", "pct"),
    ("hi_h", "Hours since its 24h high", "h"),
]
LAB_KEYS = ("c5m", "c1h", "c6h", "c24h", "v5m", "v1h", "v6h", "v24h", "v1h_24", "v6h_24", "bs1h", "bs24h", "nf1h",
            "nf1h_liq", "nf6h", "nf24h", "ss1h", "tr1h", "brd1h", "hold", "hc1h", "hc24h", "liqc1h", "volc1h", "org",
            "top10", "exit", "rf", "age", "mc", "liq", "liq_pct", "lfdv", "turn", "dd24s", "mkt1h", "sol24", "mom",
            "tgm", "tgr") + tuple(ATT.KEYS)          # attention (attention.py), from the scan it started being recorded
_LAB_DEFS = {k: (k, l, u) for k, l, u in LAB.VARIABLES}
# the minute data's short-window variables (minute.py) come last: quick rules read them at every minute, and the scan
# records them with each reading too
VARIABLES = PATH_VARS + [_LAB_DEFS[k] for k in LAB_KEYS if k in _LAB_DEFS] + MIN.VARIABLES
VAR_KEYS = [v[0] for v in VARIABLES]
# kept with every paper trade (with the rule's own variables) so the page can say what the coin looked like
SHOWN_AT_ENTRY = ["mc", "liq", "age", "c1h", "c6h", "c24h", "ru6", "dd6", "vola", "nf1h", "brd1h", "org"]


def _at(prices, t, tol):
    """The last scan price at or before t, if that scan was within tol seconds of t."""
    best = None
    for ts, p in prices:
        if ts > t:
            break
        best = (ts, p)
    return best[1] if best and t - best[0] <= tol and best[1] else None


def path_features(prices, now, price):
    """Short-term shape from the scanner's own prices: prices = [(ts, price)] ascending over the last 24h, this scan
    excluded; price is this scan's."""
    if not price:
        return {}
    past = [(t, p) for t, p in prices if p and t < now - 60]
    f = {}
    for key, w in (("r15", 900), ("r30", 1800), ("r3h", 3 * H)):
        q = _at(past, now - w + 300, max(900, w // 2))
        if q:
            f[key] = (price / q - 1) * 100
    six = [p for t, p in past if t >= now - 6 * H] + [price]
    if len(six) >= 4:
        f["ru6"] = (price / min(six) - 1) * 100
        f["dd6"] = (price / max(six) - 1) * 100
    pts = [(t, p) for t, p in past if t >= now - 6 * H] + [(now, price)]
    if len(pts) >= 7:
        lr = [math.log(b / a) for (_, a), (_, b) in zip(pts, pts[1:]) if a > 0 and b > 0]
        if len(lr) >= 6:
            m = sum(lr) / len(lr)
            f["vola"] = math.sqrt(sum((x - m) ** 2 for x in lr) / (len(lr) - 1)) * 100
    day = [(t, p) for t, p in past if t >= now - 24 * H] + [(now, price)]
    if len(day) >= 4:
        t_hi = max(day, key=lambda tp: tp[1])[0]
        f["hi_h"] = (now - t_hi) / H
    return f


def decision_features(lab_f, path_f):
    """The variables the entry rules read, rounded to 4 significant figures so stored rows stay small."""
    f = {k: lab_f[k] for k in LAB_KEYS if isinstance(lab_f.get(k), (int, float)) and not isinstance(lab_f.get(k), bool)}
    f.update({k: v for k, v in path_f.items() if v is not None})
    return {k: LAB._r(v) for k, v in f.items()}


# ---------------------------------------------------------------- rules
def fires(rule, f):
    """True when every condition of the rule holds on f. A missing value never satisfies a condition. A model's rule
    has no conditions: it fires on its model's score (scan.py), never here."""
    if rule.get("model"):
        return False
    for key, op, at in rule["all"]:
        v = (f or {}).get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not OPS[op](v, at):
            return False
    return True


def unmet(rule, f):
    """The conditions that do not hold, as (key, op, threshold, value or None)."""
    out = []
    for key, op, at in rule["all"]:
        v = (f or {}).get(key)
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and OPS[op](v, at)
        if not ok:
            out.append((key, op, at, v if isinstance(v, (int, float)) else None))
    return out


# ---------------------------------------------------------------- costs and exits
def cost_pct(liq, usd, fee):
    """One side's cost in %: the pool and creator fees plus the price impact of `usd` in a constant-product pool
    holding `liq` in total (half each side)."""
    if not liq or liq <= 0:
        return 100.0
    return min(100.0, usd / (liq / 2 + usd) * 100 + fee)


def net_ret(x, liq_in, liq_out, cfg):
    """Net return in % for a price multiple x, after paying costs to get in and to get out."""
    c0 = cost_pct(liq_in, cfg["usd"], cfg["fee_pct"]) / 100
    c1 = cost_pct(liq_out, cfg["usd"], cfg["fee_pct"]) / 100
    return (x * (1 - c0) * (1 - c1) - 1) * 100


def exit_label(p):
    """Plain words for an exit policy."""
    parts = [f"sell when the {p.get('algo', p['model'])} exit model says selling now beats holding"] if p.get("model") else []
    if p.get("tp") is not None:
        parts.append(f"take profit at +{p['tp']:g}%")
    if p.get("trail") is not None:
        parts.append(f"sell {p['trail']:g}% below the peak" + (f" once up {p['arm']:g}%" if p.get("arm") else ""))
    if p.get("cool") is not None:
        parts.append(f"after a +{p['cool']:g}% push, sell on the first scan that falls {p.get('cool_drop', 5):g}%")
    if p.get("fade") is not None:
        parts.append(f"sell if it falls {p['fade']:g}% in an hour")
    if p.get("sl") is not None:
        parts.append(f"stop at {-p['sl']:g}%")
    mh = p.get("max_h", 24)
    parts.append(f"sell after {mh * 60:g} min at the latest" if mh < 1 else f"sell after {mh:g}h at the latest")
    return "; ".join(parts)


def new_state(price):
    return {"peak": price, "prev": price}


def step(pol, pos, st, price, liq, c1h, now, cfg, guard=None, sell=False, tick=False):
    """One scan for one open trade under one exit policy. pos: in_ts, in_price, in_liq. st: {peak, prev}, updated in
    place. guard: a reason to sell at once whatever the policy says. sell: an exit model's call to sell now (for a
    policy with a model; its target and time limit still apply). tick: a minute reading between scans rather than a
    scan's; "cooled off" compares one scan's price with the last, so it is judged at scans only. Returns None to hold,
    or (net %, hours held, reason, price)."""
    x = price / pos["in_price"]
    st["peak"] = max(st["peak"], price)
    peak_x = st["peak"] / pos["in_price"]
    held = (now - pos["in_ts"]) / H
    why = guard
    if why is None:
        if pol.get("sl") is not None and x <= 1 - pol["sl"] / 100:
            why = "stop"
        elif pol.get("tp") is not None and x >= 1 + pol["tp"] / 100:
            why = "target"
        elif pol.get("trail") is not None and peak_x >= 1 + pol.get("arm", 0) / 100 and price <= st["peak"] * (1 - pol["trail"] / 100):
            why = "trailing stop"
        elif (not tick and pol.get("cool") is not None and peak_x >= 1 + pol["cool"] / 100 and st["prev"]
              and price / st["prev"] - 1 <= -pol.get("cool_drop", 5) / 100):
            why = "cooled off"
        elif pol.get("fade") is not None and held >= 1 and c1h is not None and c1h <= -pol["fade"]:
            why = "fading"
        elif sell and pol.get("model"):
            why = "model said sell"
        elif held >= pol.get("max_h", 24) - 0.01:
            why = "time"
    if not tick:
        st["prev"] = price
    if why is None:
        return None
    return (net_ret(x, pos["in_liq"], liq, cfg), held, why, price)


def levels(pol, pos, peak):
    """Prices at which the policy sells, for the page: stop, target, trailing stop (once armed) and the time limit."""
    p0 = pos["in_price"]
    out = {"stop": p0 * (1 - pol["sl"] / 100) if pol.get("sl") is not None else None,
           "target": p0 * (1 + pol["tp"] / 100) if pol.get("tp") is not None else None,
           "trail": None, "trail_armed": False, "until": pos["in_ts"] + pol.get("max_h", 24) * H}
    if pol.get("trail") is not None:
        armed = peak / p0 >= 1 + pol.get("arm", 0) / 100
        out["trail_armed"] = armed
        out["trail"] = peak * (1 - pol["trail"] / 100) if armed else None
        if armed and out["stop"] is not None and out["trail"] < out["stop"]:
            out["trail"] = out["stop"]
    if pol.get("cool") is not None:
        out["cool_armed"] = peak / p0 >= 1 + pol["cool"] / 100
    return out


def guard_for(obs, sig, cfg):
    """A reason to sell at once: the coin failed a structure gate, its pool lost most of its liquidity since entry, or
    nothing has priced it for several scans."""
    if obs is None:
        return "no market data" if sig.get("miss", 0) + 1 >= cfg["max_miss"] else None
    if obs.get("hard"):
        return "structure gate failed"
    if obs.get("liq") is not None and sig.get("in_liq") and obs["liq"] < cfg["liq_pull"] * sig["in_liq"]:
        return "liquidity pulled"
    return None


def start_states(price, policies):
    """A new trade's state under each exit policy on the bench when it opens; only those are followed."""
    return {pid: new_state(price) for pid in policies}


def advance(sig, obs, now, policies, cfg, tick=False):
    """Step one paper trade through each exit policy still undecided for it, with this scan's reading of its coin.
    sig: in_ts, in_price, in_liq, out {policy: [net, hours, reason, ts, price]}, st {policy: {peak, prev}} (one entry
    per undecided policy), miss, last_price, last_liq. obs: {price, liq, c1h, hard, xm} or None when nothing prices
    the coin this scan; xm: {policy: True} where an exit model says sell this trade now. A policy no longer on the
    bench is dropped. tick: obs is a minute reading between scans (see step). Returns (out, st, miss, last_price,
    last_liq, done)."""
    out, st = dict(sig.get("out") or {}), {k: dict(v) for k, v in (sig.get("st") or {}).items()}
    miss, lp, ll = sig.get("miss") or 0, sig.get("last_price") or sig["in_price"], sig.get("last_liq") or sig["in_liq"]
    guard = guard_for(obs if obs and obs.get("price") else None, sig, cfg)
    if not obs or not obs.get("price"):
        miss += 1
        if guard is None:
            return out, st, miss, lp, ll, not st
        price, liq, c1h = lp, ll, None
    else:
        miss, price, liq, c1h = 0, obs["price"], obs.get("liq"), obs.get("c1h")
        lp, ll = price, liq if liq is not None else ll
    pos = {"in_ts": sig["in_ts"], "in_price": sig["in_price"], "in_liq": sig["in_liq"]}
    xm = (obs or {}).get("xm") or {}
    for pid in list(st):
        pol = policies.get(pid)
        if pol is None:
            st.pop(pid)
            continue
        r = step(pol, pos, st[pid], price, liq, c1h, now, cfg, guard, bool(xm.get(pid)), tick)
        if r:
            out[pid] = [LAB._r(r[0]), round(r[1], 3), r[2], now, LAB._r(r[3])]
            st.pop(pid)
    return out, st, miss, lp, ll, not st


def ref_closed(sig, out, policies, now):
    """When the trade closed under the policy that governs it (its rule's exit, or the live exit when it opened), or
    None while still open. A governing policy no longer on the bench counts as closed now."""
    if sig.get("ref_out_ts") is not None:
        return sig["ref_out_ts"]
    if sig["ref"] in out:
        return out[sig["ref"]][3]
    return now if sig["ref"] not in policies else None


# ---------------------------------------------------------------- backtests on the stored path
def matured(ts, pol, now):
    """A trade counts in a record only once every trade opened at that time has had time to close under the policy
    (max_h plus an hour): counting only the ones that closed early would keep the quick winners and drop the slow
    losers still open."""
    return ts <= now - (pol.get("max_h", 24) + 1) * H


def path_end(path):
    return max((rows[-1][0] for rows in path.values() if rows), default=0)


def backtest(path, rule, pol, cfg, t_lo=None, t_hi=None):
    """Trades the ledger would have made on the stored path: path = {mint: [(ts, state, price, liq, c1h, f)]} ascending.
    One trade at a time per coin, at most one every reentry_h hours. Entries too close to the end of the path to
    have matured are left out, whether or not they closed."""
    out, end = [], path_end(path)
    for mint, rows in path.items():
        free, n, i = -1.0, len(rows), 0
        while i < n:
            ts, stt, price, liq, c1h, f = rows[i]
            i += 1
            if ts < free or stt != "I" or not price or not f or (t_lo and ts < t_lo) or (t_hi and ts >= t_hi):
                continue
            if not matured(ts, pol, end):
                break
            if not fires(rule, f):
                continue
            pos, s, res = {"in_ts": ts, "in_price": price, "in_liq": liq}, new_state(price), None
            for tj, sj, pj, lj, cj, _fj in rows[i:]:
                if not pj:
                    continue
                guard = ("structure gate failed" if sj == "X" else
                         "liquidity pulled" if lj is not None and liq and lj < cfg["liq_pull"] * liq else None)
                res = step(pol, pos, s, pj, lj, cj, tj, cfg, guard)
                if res:
                    break
            if res is None:
                break
            out.append({"mint": mint, "in_ts": ts, "ret": res[0], "h": res[1], "why": res[2]})
            free = ts + max(res[1], cfg["reentry_h"]) * H
    return out


# ---------------------------------------------------------------- statistics
def summarise(trades, key="ret"):
    """n, coins, share that made money, mean and median net %, and t with errors clustered by coin (a coin's trades
    move together, so counting them as independent would overstate the evidence)."""
    xs = [t[key] for t in trades if t.get(key) is not None]
    if not xs:
        return {"n": 0, "coins": 0}
    n = len(xs)
    mean = sum(xs) / n
    by = defaultdict(float)
    for t in trades:
        if t.get(key) is not None:
            by[t["mint"]] += t[key] - mean
    k = len(by)
    se = math.sqrt(sum(r * r for r in by.values()) * k / (k - 1)) / n if k > 1 else None
    s = sorted(xs)
    return {"n": n, "coins": k, "win": sum(1 for x in xs if x > 0) / n, "mean": mean, "med": s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2,
            "t": mean / se if se else None, "best": s[-1], "worst": s[0],
            "hold_h": sum(t.get("h") or 0 for t in trades) / n}


def _r(d):
    return {k: (LAB._r(v) if isinstance(v, float) else v) for k, v in (d or {}).items()}


def halves(trades):
    """The same summary for the earlier and the later half of the trades, by entry time."""
    if len(trades) < 4:
        return None, None
    ts = sorted(t["in_ts"] for t in trades)
    mid = ts[len(ts) // 2]
    return summarise([t for t in trades if t["in_ts"] < mid]), summarise([t for t in trades if t["in_ts"] >= mid])


def spearman(xs, ys):
    return LAB.spearman(xs, ys)


# ---------------------------------------------------------------- the review
def new_policy(exit_pool, default_exit):
    return {"version": 1, "last_review": None, "next_review": None, "exit": default_exit,
            "exits": {e["id"]: {"id": e["id"]} for e in exit_pool}, "rules": [], "vars": {}, "log": []}


def _day(ts):
    return time.strftime("%d %b %Y", time.gmtime(ts))


def _streak(rec, verdict):
    s = rec.get("streak") or {}
    rec["streak"] = {"verdict": verdict, "n": s.get("n", 0) + 1 if s.get("verdict") == verdict else 1}
    return rec["streak"]["n"]


def _fmt(s):
    if not s or not s.get("n"):
        return "no settled trades"
    t = f", t {s['t']:.1f}" if s.get("t") is not None else ""
    return f"{s['n']} trades on {s['coins']} coins, {s['win'] * 100:.0f}% made money, average {s['mean']:+.1f}% after costs{t}"


def judge_rule(fwd, bt, cfg, live=False):
    """Verdict on an entry rule from its forward record (and its backtest on the stored path). Returns (verdict, why)."""
    m, z, e = cfg["min_trades"], cfg["z"], cfg["min_edge"]
    why = f"forward: {_fmt(fwd)}; backtest: {_fmt(bt)}"
    if fwd.get("n", 0) >= m:
        if fwd["mean"] >= e and (fwd.get("t") or 0) >= z and (bt.get("n", 0) < m or bt["mean"] > 0):
            return "earns", why
        if fwd["mean"] <= 0 or (fwd.get("t") or 0) <= -z:
            return "loses", why
        return "unclear", why
    if not live and bt.get("n", 0) >= 2 * m and bt["mean"] <= -e and (bt.get("t") or 0) <= -z:
        return "loses", why
    return "collecting", why


def outcomes(path, cfg, hours=4, tol_h=1.0):
    """Every gate-passing reading with what happened over the next `hours`, read from the first scan at or after that
    time (within tol_h): [(ts, mint, features, net % after costs, price change %)]. Worked out once per review and
    shared by every variable and warning."""
    out = []
    for mint, rows in path.items():
        j, n = 0, len(rows)
        for i, (ts, stt, price, liq, _c, f) in enumerate(rows):
            if stt != "I" or not f or not price:
                continue
            j = max(j, i + 1)
            while j < n and rows[j][0] < ts + hours * H:
                j += 1
            if j >= n or rows[j][0] > ts + (hours + tol_h) * H or not rows[j][2]:
                continue
            x = rows[j][2] / price
            out.append((ts, mint, f, net_ret(x, liq, rows[j][3], cfg), (x - 1) * 100))
    return out


def judge_var(pts_all, key, cfg):
    """Does the variable separate gate-passing coins that rose over the next hours from those that fell, the same way
    in both halves of the window? pts_all: outcomes(). Returns a record with the rank correlation in each half, the
    average net return by fifth, and a verdict: signal, no signal or collecting."""
    pts = [(ts, f[key], r, mint) for ts, mint, f, r, _g in pts_all
           if isinstance(f.get(key), (int, float)) and not isinstance(f.get(key), bool)]
    rec = {"key": key, "n": len(pts), "coins": len({p[3] for p in pts})}
    if len(pts) < cfg["var_min_n"] or rec["coins"] < 20:
        rec["verdict"] = "collecting"
        return rec
    pts.sort()
    half = len(pts) // 2
    r1 = spearman([p[1] for p in pts[:half]], [p[2] for p in pts[:half]])
    r2 = spearman([p[1] for p in pts[half:]], [p[2] for p in pts[half:]])
    vals = sorted(p[1] for p in pts)
    cuts = [vals[int(len(vals) * q)] for q in (0.2, 0.4, 0.6, 0.8)]
    fifths = []
    for q in range(5):
        lo, hi = (cuts[q - 1] if q else -math.inf), (cuts[q] if q < 4 else math.inf)
        sel = [{"mint": p[3], "ret": p[2], "in_ts": p[0]} for p in pts if lo <= p[1] < hi or (q == 4 and p[1] >= lo)]
        s = summarise(sel)
        fifths.append({"lo": LAB._r(lo if q else vals[0]), "hi": LAB._r(hi if q < 4 else vals[-1]), "n": s["n"],
                       "mean": LAB._r(s.get("mean")), "win": LAB._r(s.get("win"))})
    top, bot = fifths[4]["mean"], fifths[0]["mean"]
    rec.update({"rho1": LAB._r(r1), "rho2": LAB._r(r2), "fifths": fifths, "cuts": [LAB._r(c) for c in cuts]})
    same = r1 is not None and r2 is not None and r1 * r2 > 0
    strong = same and min(abs(r1), abs(r2)) >= cfg["var_min_rho"]
    rec["verdict"] = "signal" if strong else "no signal"
    if strong and top is not None and bot is not None:
        rec["better"] = "high" if top > bot else "low"
    return rec


def judge_warning(pts_all, w, cfg, hours=4):
    """A sell-side warning (a state such as "risen 30% off its 6h low") against every other gate-passing reading: the
    price change over the next `hours` in that state and outside it, before costs. pts_all: outcomes(). It holds when
    coins in the state did worse by at least warn_gap points with t >= z (errors clustered by coin)."""
    inside, rest = [], []
    for ts, mint, f, _net, ch in pts_all:
        (inside if fires(w, f) else rest).append({"mint": mint, "ret": ch, "in_ts": ts})
    a, b = summarise(inside), summarise(rest)
    rec = {"in": _r(a), "out": _r(b), "hours": hours}
    if a.get("n", 0) < cfg["min_trades"] or a.get("coins", 0) < 10 or b.get("n", 0) < cfg["min_trades"]:
        rec["verdict"] = "collecting"
        return rec
    # the gap's t: both sides' cluster-robust errors combined
    se_a = abs(a["mean"] / a["t"]) if a.get("t") else None
    se_b = abs(b["mean"] / b["t"]) if b.get("t") else None
    gap = a["mean"] - b["mean"]
    t = gap / math.sqrt(se_a ** 2 + se_b ** 2) if se_a and se_b else None
    rec.update(gap=LAB._r(gap), t=LAB._r(t), share_lower=LAB._r(1 - a["win"]))
    rec["verdict"] = "holds" if gap <= -cfg["warn_gap"] and t is not None and t <= -cfg["z"] else "does not hold"
    return rec


def suggest_rules(var_recs, have, cfg):
    """New candidate rules from variables that showed a signal: the fifth with the best average net return. Only
    variables whose better end is at the top or bottom fifth give a one-line rule."""
    out = []
    for v in var_recs:
        if v.get("verdict") != "signal" or not v.get("better") or not v.get("cuts"):
            continue
        op, at = (">=", v["cuts"][3]) if v["better"] == "high" else ("<=", v["cuts"][0])
        rid = f"auto_{v['key']}_{'hi' if op == '>=' else 'lo'}"
        if rid in have:
            continue
        label = next((l for k, l, _u in VARIABLES if k == v["key"]), v["key"])
        out.append({"id": rid, "label": f"{label}: {OP_WORDS[op]} {at:g} (its best fifth when added)",
                    "all": [[v["key"], op, at]], "source": "variable with a signal"})
    return out


def pooled(trades_by_rule):
    """One record per coin and entry time across rules, so an entry two rules share counts once."""
    seen, out = set(), []
    for lst in trades_by_rule.values():
        for t in lst:
            k = (t["mint"], round(t["in_ts"]))
            if k not in seen:
                seen.add(k)
                out.append(t)
    return out


def compare_exits(entries, live_id, cfg, exits, now):
    """Paired comparison of every exit policy with the live one on the same entries. entries: [{mint, in_ts, out:
    {policy: net}}]. Each pair is judged on entries old enough for both policies to have closed every trade (see
    matured), so a policy that closes early is not flattered by its unfinished losers being left out. Returns
    {policy: {n, mean, win, med, gain, t}} where gain is the average improvement over the live policy."""
    res = {}
    mh = lambda pid: (exits.get(pid) or {}).get("max_h", 24)
    for pid in sorted({p for e in entries for p in e["out"]} & set(exits)):
        ripe = {"max_h": max(mh(pid), mh(live_id))}
        ok = [e for e in entries if matured(e["in_ts"], ripe, now)]
        both = [e for e in ok if e["out"].get(pid) is not None and e["out"].get(live_id) is not None]
        own = [{"mint": e["mint"], "ret": e["out"][pid], "in_ts": e["in_ts"]} for e in entries
               if e["out"].get(pid) is not None and matured(e["in_ts"], {"max_h": mh(pid)}, now)]
        diff = [{"mint": e["mint"], "ret": e["out"][pid] - e["out"][live_id], "in_ts": e["in_ts"]} for e in both]
        s, d = summarise(own), summarise(diff)
        res[pid] = {"n": s["n"], "mean": LAB._r(s.get("mean")), "win": LAB._r(s.get("win")), "med": LAB._r(s.get("med")),
                    "gain": LAB._r(d.get("mean")) if pid != live_id else 0.0, "t": LAB._r(d.get("t")) if pid != live_id else None}
    return res


def run_review(policy, path, fwd_by_rule, now, cfg, entry_pool, exit_pool, default_exit, warnings=()):
    """One weekly review. path: {mint: [(ts, state, price, liq, c1h, f)]} for the window. fwd_by_rule: {rule id:
    [{mint, in_ts, out: {policy: net %}, live}]} settled forward trades. Returns (policy, changes)."""
    policy = policy or new_policy(exit_pool, default_exit)
    ripe = outcomes(path, cfg)
    policy["warnings"] = [{"id": w["id"], "last": {**judge_warning(ripe, w, cfg), "ts": now}} for w in warnings]
    exits = {e["id"]: e for e in exit_pool}
    for e in exit_pool:
        policy["exits"].setdefault(e["id"], {"id": e["id"]})
    if policy.get("exit") not in exits:
        policy["exit"] = default_exit
    live_exit = exits[policy["exit"]]
    changes = []

    def log(what, rid, label, reason):
        changes.append({"ts": now, "what": what, "id": rid, "label": label, "reason": reason})

    def own_exit(r):                       # a rule may name its own exit (quick rules do); else the live one
        return exits.get(r.get("exit")) or live_exit

    # 1. variables: which ones separate risers from fallers among gate-passing coins
    var_recs = []
    for key in VAR_KEYS:
        rec = policy["vars"].setdefault(key, {"key": key, "status": "active"})
        v = judge_var(ripe, key, cfg)
        rec["last"] = {k: v.get(k) for k in ("n", "coins", "rho1", "rho2", "fifths", "verdict", "better")}
        rec["last"]["ts"] = now
        n = _streak(rec, v["verdict"])
        if rec["status"] == "active" and v["verdict"] == "no signal" and n >= cfg["var_retire_after"]:
            rec.update(status="retired", since=now, reason=f"Stopped seeding new rules on {_day(now)}: no signal in {n} reviews in a row.")
            log("variable set aside", key, key, rec["reason"])
        elif rec["status"] == "retired" and (v["verdict"] == "signal" or now - (rec.get("since") or now) >= cfg["retest_after_days"] * 86400):
            rec.update(status="active", since=now, reason=f"Back on {_day(now)}.")
        if rec["status"] == "active":
            var_recs.append(v)

    # 2. entry rules: forward record (and a backtest on the stored path) under the live exit
    promos = 0
    for r in policy["rules"]:
        if r["status"] not in ("testing", "live"):
            continue
        since = r.get("since") if r["status"] == "live" else r.get("added")
        rx = own_exit(r)
        fw = [{"mint": t["mint"], "in_ts": t["in_ts"], "ret": t["out"].get(rx["id"]), "h": None}
              for t in fwd_by_rule.get(r["id"], []) if t["in_ts"] >= (since or 0) and matured(t["in_ts"], rx, now)]
        fw = [t for t in fw if t["ret"] is not None]
        # models and quick rules (which read minute data the stored path does not hold) are judged forward only
        bt = [] if r.get("model") or r.get("fast") else backtest(path, r, rx, cfg)
        fs, bs = summarise(fw), summarise(bt)
        h1, h2 = halves(bt)
        verdict, why = judge_rule(fs, bs, cfg, live=r["status"] == "live")
        r["last"] = {"ts": now, "verdict": verdict, "why": why, "fwd": _r(fs), "bt": _r(bs),
                     "bt_halves": [_r(h1), _r(h2)] if h1 else None}
        n = _streak(r, verdict)
        if r["status"] == "testing":
            if verdict == "earns" and n >= cfg["promote_after"] and promos < cfg["max_promotions"] \
                    and sum(1 for x in policy["rules"] if x["status"] == "live") < cfg["max_live"]:
                r.update(status="live", since=now, reason=f"Live from {_day(now)} after {n} reviews in a row: {why}.")
                promos += 1
                log("live", r["id"], r["label"], r["reason"])
            elif verdict == "loses" and n >= cfg["retire_after"]:
                r.update(status="retired", since=now, reason=f"Retired on {_day(now)} after {n} reviews in a row of losing: {why}.")
                log("retired", r["id"], r["label"], r["reason"])
            elif verdict == "collecting" and n >= cfg["stale_after"]:
                r.update(status="retired", since=now, reason=f"Retired on {_day(now)}: it fired too rarely to judge in {n} reviews ({why}).")
                log("retired", r["id"], r["label"], r["reason"])
        elif verdict == "loses" and (n >= cfg["retire_after"] or (fs.get("t") or 0) <= -cfg["z"]):
            r.update(status="retired", since=now, reason=f"Taken off live on {_day(now)}: {why}.")
            log("retired", r["id"], r["label"], r["reason"])

    # 3. exits: every policy against the live one on the same entries (forward trades, else the backtest's entries).
    # Quick rules' trades are left out: the live exit is chosen for the scans' rules, and quick entries are another
    # population (the Buy & sell tab compares exits on them separately)
    since = now - cfg["window_days"] * 86400
    quick = {r["id"] for r in policy["rules"] if r.get("fast")}
    entries = pooled({rid: [t for t in lst if t.get("out") and since <= t["in_ts"]] for rid, lst in fwd_by_rule.items()
                      if rid not in quick})
    basis, at = "forward trades", now
    if sum(1 for e in entries if matured(e["in_ts"], {"max_h": 24}, now)) < cfg["min_trades"]:
        entries = backtest_entries(path, [r for r in policy["rules"] if r["status"] in ("testing", "live")
                                          and not r.get("fast")], exits, cfg)
        basis, at = "backtest", path_end(path)
    cmp_ = compare_exits(entries, policy["exit"], cfg, exits, at)
    best = None
    for pid, c in cmp_.items():
        rec = policy["exits"].setdefault(pid, {"id": pid})
        rec["last"] = {"ts": now, "basis": basis, **c}
        if pid == policy["exit"] or c["n"] < cfg["min_trades"]:
            _streak(rec, "collecting" if c["n"] < cfg["min_trades"] else "live")
            continue
        better = (c["gain"] or 0) >= cfg["switch_min_gain"] and (c["t"] or 0) >= cfg["z"]
        n = _streak(rec, "better" if better else "not better")
        if better and n >= cfg["switch_after"] and (best is None or c["gain"] > cmp_[best]["gain"]):
            best = pid
    if best:
        old = policy["exit"]
        policy["exit"] = best
        g = cmp_[best]
        reason = (f"Switched on {_day(now)}: on {g['n']} {basis} it averaged {g['mean']:+.1f}% after costs, "
                  f"{g['gain']:+.1f} points better than “{exit_label(exits[old])}” (t {g['t']:.1f}), {cfg['switch_after']} reviews in a row.")
        policy["exits"][best]["reason"] = reason
        log("exit switched", best, exit_label(exits[best]), reason)

    # 4. keep the bench full: the pool first, then rules from variables with a signal, then retired rules due a retest
    have = {r["id"] for r in policy["rules"]}
    # models and quick rules have their own benches
    testing = sum(1 for r in policy["rules"] if r["status"] == "testing" and not r.get("model") and not r.get("fast"))
    room = min(cfg["add_per_review"], max(0, cfg["testing"] - testing)) if policy["last_review"] else cfg["testing"]
    for rule in list(entry_pool) + suggest_rules(var_recs, have, cfg):
        if room <= 0:
            break
        if rule["id"] in have or any(k not in VAR_KEYS or (policy["vars"].get(k) or {}).get("status") == "retired"
                                     for k, _o, _a in rule["all"]):
            continue
        r = {**rule, "status": "testing", "added": now, "since": now, "source": rule.get("source", "pool")}
        bt = backtest(path, r, live_exit, cfg)
        r["last"] = {"ts": now, "verdict": "collecting", "why": f"forward: no settled trades yet; backtest: {_fmt(summarise(bt))}",
                     "fwd": {"n": 0}, "bt": _r(summarise(bt))}
        policy["rules"].append(r)
        have.add(r["id"])
        room -= 1
        if policy["last_review"]:
            log("testing", r["id"], r["label"], f"Added for testing on {_day(now)} ({r['source']}).")
    for r in sorted((r for r in policy["rules"] if r["status"] == "retired"
                     and now - (r.get("since") or 0) >= cfg["retest_after_days"] * 86400), key=lambda r: r.get("since") or 0):
        if room <= 0:
            break
        r.update(status="testing", added=now, since=now, streak=None, reason=None)
        room -= 1
        log("testing", r["id"], r["label"], f"Back for testing on {_day(now)}: retired long enough ago to check again.")

    policy["last_review"] = now
    policy["next_review"] = now + cfg["every_days"] * 86400
    policy["log"] = ((policy.get("log") or []) + changes)[-200:]
    return policy, changes


def backtest_entries(path, rules, exits, cfg):
    """Entries the bench's rules would have made on the stored path, each with its net result under every exit
    policy, for comparing exits before the forward record is big enough. Exits that close within the hour are left
    out: one price a scan cannot price them."""
    exits = {pid: pol for pid, pol in exits.items() if pol.get("max_h", 24) >= 1}
    seen, out = set(), []
    longest = {"max_h": max(p.get("max_h", 24) for p in exits.values())}
    for r in rules:
        for pid, pol in exits.items():
            for t in backtest(path, r, longest, cfg):
                k = (t["mint"], round(t["in_ts"]))
                if k not in seen:
                    seen.add(k)
                    out.append({"mint": t["mint"], "in_ts": t["in_ts"], "out": {}})
            break                      # entries are the same for every policy only when trades do not overlap, so
                                       # take them from the first policy and price every policy on each one below
    by = defaultdict(list)
    for mint, rows in path.items():
        by[mint] = rows
    for e in out:
        rows = by[e["mint"]]
        i = next((k for k, row in enumerate(rows) if abs(row[0] - e["in_ts"]) < 1), None)
        if i is None:
            continue
        ts, _s, p0, l0 = rows[i][:4]
        pos = {"in_ts": ts, "in_price": p0, "in_liq": l0}
        for pid, pol in exits.items():
            s = new_state(p0)
            for tj, sj, pj, lj, cj, _f in rows[i + 1:]:
                if not pj:
                    continue
                guard = ("structure gate failed" if sj == "X" else
                         "liquidity pulled" if lj is not None and l0 and lj < cfg["liq_pull"] * l0 else None)
                res = step(pol, pos, s, pj, lj, cj, tj, cfg, guard)
                if res:
                    e["out"][pid] = res[0]
                    break
    return [e for e in out if e["out"]]


def add_rules(policy, rules, now, source):
    """Put rules on the bench at once, between weekly reviews: rules on variables that have only just started being
    recorded, and the models' rules, so their forward records start now rather than at the next review. A rule whose
    variables are not all known to the bench is skipped. Returns the changes, which also go to the policy's log."""
    have = {r["id"] for r in policy["rules"]}
    changes = []
    for rule in rules:
        if rule["id"] in have or any(k not in VAR_KEYS for k, _o, _a in rule.get("all") or []):
            continue
        src = rule.get("source") if rule.get("source") not in (None, "pool") else source
        r = {**rule, "status": "testing", "added": now, "since": now, "source": src,
             "last": {"ts": now, "verdict": "collecting", "fwd": {"n": 0}, "bt": {"n": 0},
                      "why": "forward: no settled trades yet; backtest: none (" + ("judged forward only" if rule.get("model")
                                                                                  else "its variables are new") + ")"}}
        policy["rules"].append(r)
        have.add(r["id"])
        changes.append({"ts": now, "what": "testing", "id": r["id"], "label": r["label"],
                        "reason": f"Added for testing on {_day(now)} ({src})."})
    policy["log"] = ((policy.get("log") or []) + changes)[-200:]
    return changes


def due(policy, now, cfg):
    return not policy or not policy.get("last_review") or now - policy["last_review"] >= cfg["every_days"] * 86400 - 1800
