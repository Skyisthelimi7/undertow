"""The weekly gate review: which gates earn their place, which candidate rules should become gates, and which
variables to test next. Pure functions; scan.run calls run_review() once every REVIEW["every_days"] days.

Evidence comes from the Lab's observations: one row per token-day, with every gate's result, every variable, and what
the price did over the next 24 hours. Two outcomes are read from them, both as the rug study defined them: rugged
(fell 80% below the observed price before ever trading 50% above it, within a day) and reached +50% within a day.

A gate is judged on the coins it alone blocked, against the coins that passed every gate: did they rug more often?
  protects   they rugged clearly more often (at least min_diff more, z at least z)
  costs      they rugged no more often but reached +50% clearly more often, or they rugged clearly less often:
             the gate removes the better coins
  no effect  both sides have at least min_flat settled coins and the rug rates are within flat_diff (|z| < flat_z)
  unclear    enough coins, none of the above
  collecting fewer than min_group settled coins on either side
A candidate rule is judged the same way on coins that passed every gate, split by the rule: the coins it would have
removed against the ones it would have kept ("would protect", "would cost", "no effect").

Changes need the same verdict in drop_after (or promote_after) reviews in a row, so a week's noise cannot move a
gate. At most max_drops gates are dropped and max_promotions rules promoted per review. Only the rug-risk and holder
gates can be dropped: the structure gates block a mechanism (a live mint authority, a liquidity pull), which a rug
rate cannot judge, and the scope gates define which coins are assessed at all. A dropped gate is still computed and
shown, so later reviews can restore it; a retired candidate makes room for the next variable to test."""
import math, time
from . import lab as LAB

OPS = {">=": lambda a, b: a >= b, ">": lambda a, b: a > b, "<=": lambda a, b: a <= b, "<": lambda a, b: a < b}
REVIEWABLE_GROUPS = ("risk", "holders")
H = 3600


def _day(ts):
    return time.strftime("%d %b %Y", time.gmtime(ts))


def pct(x):
    return "n/a" if x is None else f"{x * 100:.0f}%"


def _mean(xs):
    return sum(xs) / len(xs) if xs else None


def up50(r):
    """Reached 1.5x the observed price within 24h: True, False, or None while undecided."""
    if r.get("up50_ts") is not None:
        return True
    return False if r.get("done") else None


def group(rows):
    rug = [g for g in (LAB.rugged(r) for r in rows) if g is not None]
    up = [u for u in (up50(r) for r in rows) if u is not None]
    p24 = [r["p24"] for r in rows if r.get("p24") is not None]
    return {"n": len(rows), "n_rug": len(rug), "rug": _mean([1 if g else 0 for g in rug]),
            "n_up": len(up), "up50": _mean([1 if u else 0 for u in up]), "med24": LAB._median(p24)}


def ztest(p1, n1, p2, n2):
    """z for the difference p1 - p2 between two proportions (pooled standard error)."""
    if p1 is None or p2 is None or not n1 or not n2:
        return None
    p = (p1 * n1 + p2 * n2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    return (p1 - p2) / se if se else None


# ------------------------------------------------------------------ gates
def gate_failed(r, gid):
    """Did this gate fail on this row? Rows since 20 Oct 2026 record every gate's result ("g:<id>" in rules);
    older rows only list the gates that blocked."""
    g = (r.get("rules") or {}).get("g:" + gid)
    if g is not None:
        return g == 0
    return gid in (r.get("fails") or [])


def failing(rows, active):
    """Each observation (oldest first) with the set of active gates it failed, worked out once per review."""
    return [(r, {a for a in active if gate_failed(r, a)})
            for r in sorted(rows, key=lambda r: r["ts"]) if r.get("ev") in ("hourly", "entry")]


def first_clean(fl, skip=None):
    """One observation per token-day: the first that failed no active gate other than `skip`. A token watched for
    hours counts once a day, as in the Lab."""
    out = {}
    for r, fs in fl:
        key = (r["mint"], int(r["ts"] // 86400))
        if key in out or (fs and fs != {skip}):
            continue
        out[key] = r
    return list(out.values())


def gate_evidence(fl, gid):
    """The coins this gate alone blocked against the coins that passed every active gate. fl: failing(rows, active).
    Works the same for a gate that is gating and for one the review dropped (it is still computed and recorded)."""
    clean = first_clean(fl, gid)
    return {"blocked": group([r for r in clean if gate_failed(r, gid)]),
            "passed": group([r for r in clean if not gate_failed(r, gid)])}


def judge(ev, cfg, words=("protects", "costs")):
    """Verdict and its reason in plain words. words: what to call the two directions (gates or candidates)."""
    b, p = ev["blocked"], ev["passed"]
    if b["n_rug"] < cfg["min_group"] or p["n_rug"] < cfg["min_group"]:
        return "collecting", (f"needs {cfg['min_group']} settled coins on each side; has {b['n_rug']} blocked "
                              f"and {p['n_rug']} passing")
    zr = ztest(b["rug"], b["n_rug"], p["rug"], p["n_rug"])
    zu = ztest(b["up50"], b["n_up"], p["up50"], p["n_up"])
    d_rug = b["rug"] - p["rug"]
    nums = (f"blocked coins rugged {pct(b['rug'])} of the time (n={b['n_rug']}) against {pct(p['rug'])} for the "
            f"rest (n={p['n_rug']}); +50% within a day: {pct(b['up50'])} against {pct(p['up50'])}")
    if d_rug >= cfg["min_diff"] and zr is not None and zr >= cfg["z"]:
        return words[0], nums
    better = zu is not None and b["up50"] - p["up50"] >= cfg["min_diff"] and zu >= cfg["z"]
    if (better and (zr is None or zr < cfg["flat_z"])) or (zr is not None and zr <= -cfg["z"] and d_rug <= -cfg["min_diff"]):
        return words[1], nums
    if (b["n_rug"] >= cfg["min_flat"] and p["n_rug"] >= cfg["min_flat"] and zr is not None
            and abs(d_rug) <= cfg["flat_diff"] and abs(zr) < cfg["flat_z"]):
        return "no effect", nums
    return "unclear", nums


# ------------------------------------------------------------------ candidate rules
def rule_evidence(rows, rule):
    """Coins that passed every gate, split by the rule: the ones it would remove against the ones it would keep. The
    rule is read from each observation's stored variables, so rows from before a promotion count too."""
    key, op, at = rule["key"], rule["op"], rule["at"]
    kept, cut = [], []
    for r in rows:
        v = (r.get("f") or {}).get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        (kept if OPS[op](v, at) else cut).append(r)
    ev = {"blocked": group(cut), "passed": group(kept)}
    n = len(kept) + len(cut)
    ev["keep"] = len(kept) / n if n else None
    return ev


def suggestions(lab_vars, have, gateable):
    """New candidate rules from the Lab: variables whose line (found on the earlier half of the data) held on the
    later half. lab_vars: the Lab's variable records for one population and horizon."""
    out = []
    for v in lab_vars or []:
        cut = v.get("cut")
        if v.get("verdict") not in ("works", "weak") or not cut or v["key"] not in gateable:
            continue
        rid = f"auto_{v['key']}"
        if rid in have:
            continue
        out.append({"id": rid, "label": f"Lab line: {v['key']} {cut['op']} {cut['at']}", "key": v["key"],
                    "op": cut["op"], "at": cut["at"], "source": "Lab suggestion"})
    return out


# ------------------------------------------------------------------ the review
def new_policy():
    return {"version": 1, "last_review": None, "next_review": None, "gates": {}, "candidates": [], "log": []}


def _streak(rec, verdict):
    s = rec.get("streak") or {}
    rec["streak"] = {"verdict": verdict, "n": s.get("n", 0) + 1 if s.get("verdict") == verdict else 1}
    return rec["streak"]["n"]


def _summ(ev, verdict, why, now):
    b, p = ev["blocked"], ev["passed"]
    out = {"ts": now, "verdict": verdict, "why": why,
           "blocked": {k: b[k] for k in ("n", "n_rug", "rug", "up50", "med24")},
           "passed": {k: p[k] for k in ("n", "n_rug", "rug", "up50", "med24")}}
    if "keep" in ev:
        out["keep"] = ev["keep"]
    return out


def active_gates(policy, gate_meta):
    """Gate ids currently gating: every computed gate that is not info and not dropped, plus promoted rules."""
    shown = {g for g, rec in (policy.get("gates") or {}).items() if rec.get("status") == "shown"}
    ids = [g for g, meta in gate_meta.items() if not meta.get("info") and g not in shown]
    ids += ["lab:" + c["id"] for c in policy.get("candidates") or [] if c.get("status") == "promoted"]
    return ids


def run_review(rows, policy, gate_meta, now, cfg, pool, lab_vars=None, gateable=(), pinned=()):
    """One review. rows: Lab observations (any order). policy: the stored policy or None. gate_meta: {gate id: {label,
    group, hard, info}} for every gate the scanner computes. pool: candidate rules waiting to be tested, in order.
    Returns (policy, changes)."""
    policy = policy or new_policy()
    active = active_gates(policy, gate_meta)
    fl = failing([r for r in rows if r["ts"] >= now - cfg["window_days"] * 86400], active)
    passing = first_clean(fl)
    changes, drops, restores, promos = [], 0, 0, 0

    def log(what, rid, label, reason):
        changes.append({"ts": now, "what": what, "id": rid, "label": label, "reason": reason})

    for gid, meta in gate_meta.items():
        rec = policy["gates"].setdefault(gid, {"status": "gate", "since": now})
        rec["label"], rec["group"] = meta.get("label", gid), meta.get("group")
        rec["reviewable"] = meta.get("group") in REVIEWABLE_GROUPS and not meta.get("hard") and gid not in pinned
        ev = gate_evidence(fl, gid)
        verdict, why = judge(ev, cfg)
        rec["last"] = _summ(ev, verdict, why, now)
        n = _streak(rec, verdict)
        if not rec["reviewable"]:
            continue
        if rec["status"] == "gate" and verdict in ("no effect", "costs") and n >= cfg["drop_after"] and drops < cfg["max_drops"]:
            what = "made no difference to rugs" if verdict == "no effect" else "removed better coins"
            rec.update(status="shown", since=now, short=f"dropped {_day(now)}: {what}",
                       reason=f"Dropped on {_day(now)} after {n} reviews in a row found it {what}: {why}.")
            drops += 1
            log("dropped", gid, rec["label"], rec["reason"])
        elif rec["status"] == "shown" and verdict == "protects" and n >= cfg["drop_after"] and restores < cfg["max_drops"]:
            rec.update(status="gate", since=now, short=None, reason=f"Restored on {_day(now)}: {why}.")
            restores += 1
            log("restored", gid, rec["label"], rec["reason"])

    def judge_rule(c):
        # a promoted rule now gates, so it is judged on the coins that passed everything else
        ev = rule_evidence(passing if c["status"] == "testing" else first_clean(fl, "lab:" + c["id"]), c)
        verdict, why = judge(ev, cfg, ("would protect", "would cost"))
        c["last"] = _summ(ev, verdict, why, now)
        c["gateable"] = c["key"] in gateable          # crowd and late-scan variables are tested, never promoted
        return verdict, why, _streak(c, verdict), ev.get("keep")

    for c in policy["candidates"]:
        if c.get("status") not in ("testing", "promoted"):
            continue
        verdict, why, n, keep = judge_rule(c)
        if c["status"] == "testing":
            if (verdict == "would protect" and n >= cfg["promote_after"] and c["key"] in gateable
                    and keep is not None and keep >= cfg["min_keep"] and promos < cfg["max_promotions"]):
                c.update(status="promoted", since=now,
                         reason=f"Promoted to a gate on {_day(now)} after {n} reviews in a row: {why}; it keeps {pct(keep)} of passing coins.")
                promos += 1
                log("promoted", c["id"], c["label"], c["reason"])
            elif verdict in ("no effect", "would cost") and n >= cfg["drop_after"]:
                c.update(status="retired", since=now,
                         reason=f"Retired on {_day(now)} after {n} reviews in a row: {'no difference' if verdict == 'no effect' else 'it would remove better coins'}; {why}.")
                log("retired", c["id"], c["label"], c["reason"])
            elif verdict == "collecting" and n >= cfg.get("stale_after", 6):
                # it removes almost no passing coin, or almost all: it cannot be judged, so it gives up its place
                c.update(status="retired", since=now,
                         reason=f"Retired on {_day(now)}: still too few coins on one side after {n} reviews ({why}).")
                log("retired", c["id"], c["label"], c["reason"])
        elif verdict in ("no effect", "would cost") and n >= cfg["drop_after"]:
            c.update(status="retired", since=now, reason=f"Removed as a gate on {_day(now)}: {why}.")
            log("dropped", "lab:" + c["id"], c["label"], c["reason"])

    # keep the testing bench full: first the queued pool, then the Lab's own suggestions, then, once both run dry,
    # rules retired long enough ago that the market may have changed. A new rule is judged at once on the stored
    # observations, so its first verdict counts toward the two in a row it needs.
    have = {c["id"] for c in policy["candidates"]}
    testing = sum(1 for c in policy["candidates"] if c.get("status") == "testing")
    room = min(cfg["add_per_review"], max(0, cfg["testing"] - testing)) if policy["last_review"] else cfg["testing"]
    for rule in list(pool) + suggestions(lab_vars, have, gateable):
        if room <= 0:
            break
        if rule["id"] in have:
            continue
        c = {**rule, "status": "testing", "added": now, "since": now, "source": rule.get("source", "pool")}
        policy["candidates"].append(c)
        judge_rule(c)
        have.add(rule["id"])
        room -= 1
        if policy["last_review"]:
            log("testing", rule["id"], rule["label"], f"Added for testing on {_day(now)} ({c['source']}).")
    stale = sorted((c for c in policy["candidates"] if c.get("status") == "retired"
                    and now - (c.get("since") or 0) >= cfg.get("retest_after_days", 56) * 86400), key=lambda c: c.get("since") or 0)
    for c in stale[:max(0, room)]:
        c.update(status="testing", since=now, streak=None, reason=None)
        judge_rule(c)
        log("testing", c["id"], c["label"], f"Back for testing on {_day(now)}: retired long enough ago to check again.")

    policy["last_review"] = now
    policy["next_review"] = now + cfg["every_days"] * 86400
    policy["log"] = (policy.get("log") or []) + changes
    policy["log"] = policy["log"][-200:]
    return policy, changes


def due(policy, now, cfg):
    return not policy or not policy.get("last_review") or now - policy["last_review"] >= cfg["every_days"] * 86400 - 1800


def for_page(policy, gate_meta):
    """What the page shows: every gate and candidate with its status, verdict and reason, and the change log."""
    if not policy:
        return None
    gates = []
    for gid, rec in policy.get("gates", {}).items():
        if gid not in gate_meta:
            continue
        gates.append({"id": gid, "label": rec.get("label"), "group": rec.get("group"), "status": rec.get("status"),
                      "reviewable": rec.get("reviewable"), "reason": rec.get("reason"), "last": rec.get("last"),
                      "streak": rec.get("streak")})
    cands = [{k: c.get(k) for k in ("id", "label", "key", "op", "at", "status", "source", "added", "since", "reason",
                                    "last", "streak", "gateable")} for c in policy.get("candidates", [])]
    return {"last_review": policy.get("last_review"), "next_review": policy.get("next_review"), "gates": gates,
            "candidates": cands, "log": list(reversed(policy.get("log") or []))[:40]}
