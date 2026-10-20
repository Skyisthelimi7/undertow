"""Pure functions: metrics in, gate results out. No network, no database.

Every gate has a kind and a group:
  kind  'hard'  one failure removes a token at once
        'soft'  two failed scans in a row remove it
        'info'  computed and shown, never gating
  group 'structure' (can the coin trap you), 'scope' (is it in range and alive), 'risk' (rug-risk checks),
        'holders' (holder-structure checks: shown, not gated, for launchpad graduates inside the rug study's range,
        where it found they do not predict rugs; gating everywhere else)."""
from . import config as C


def band_of(mcap):
    for name, lo, hi in C.BANDS:
        if lo <= mcap < hi:
            return name
    return None


# History-based detectors have no data in a token's first hours. Unknown counts as a pass for them (shown as
# "warming up"), otherwise nothing could enter until a day of snapshots exists. Preventive gates never get this pass.
WARMUP = {"devsell", "outflow"}
GROUP_ORDER = ("structure", "scope", "risk", "holders")


def _g(gid, label, ok, kind, group, value, rule):
    return {"id": gid, "label": label, "ok": bool(ok), "hard": kind == "hard", "info": kind == "info",
            "group": group, "value": value, "rule": rule}


def evaluate(m, was_in):
    """m: flat metrics dict (None = unknown). was_in: token currently inside, so looser exit limits apply.
    An unknown value fails a gate for a token trying to enter, but is carried for one already in, so a transient
    API failure does not evict it. A check whose only source is down this run is marked 'not checked' and passes."""
    s = C.EXIT_SLACK if was_in else {"mcap_low": 1, "mcap_high": 1, "vol": 1, "liq": 1, "top10": 0, "creator": 0,
                                     "linked": 0, "cluster": 0}
    gates = []

    def add(kind, group, gid, label, val, test, rule, skipped=None):
        if val is None and skipped:
            gates.append(_g(gid, label, True, kind, group, None, f"{rule} (not checked: {skipped})"))
        elif val is None:
            warm = gid in WARMUP and kind == "soft"
            ok = False if kind == "hard" else (True if kind == "info" else (was_in or warm))
            gates.append(_g(gid, label, ok, kind, group, None, rule + (" (warming up)" if warm else " (no data)")))
        else:
            gates.append(_g(gid, label, test(val), kind, group, val, rule))

    rc_down = "RugCheck unavailable" if m.get("rc_down") else None

    # ---- structure: can the coin trap you ------------------------------------------------------------
    add("hard", "structure", "venue", "Trading on a DEX pool", m.get("venue_kind"), lambda v: v != "curve",
        "not still on a launchpad bonding curve")
    add("hard", "structure", "authority", "Mint and freeze revoked", m.get("authority_clean"), lambda v: v is True,
        "both authorities null, read from the chain")
    ext, gpt = m.get("bad_ext"), m.get("gp_traps")       # chain (or RugCheck) and GoPlus: either one flagging fails
    traps = None if ext is None and gpt is None else list(dict.fromkeys((ext or []) + (gpt or [])))
    add("hard", "structure", "extensions", "No trap extensions", traps,
        lambda v: not v and (m.get("transfer_fee") or 0) <= C.MAX_TRANSFER_FEE_PCT,
        "no permanent delegate, live transfer hook, pause, frozen-by-default or non-transferable, and no authority "
        "that could switch one on; fee ≤ %g%%%s" % (C.MAX_TRANSFER_FEE_PCT, "; checked on chain and by GoPlus" if gpt is not None else ""))
    add("info", "structure", "metadata", "Name and image locked", m.get("meta_mutable"), lambda v: v is False,
        "metadata can't be changed (GoPlus); shown, not gated: many established coins keep it changeable")
    add("hard", "structure", "lp", "Liquidity can't be pulled", m.get("lp_locked_pct"), lambda v: v >= C.MIN_LP_LOCKED_PCT,
        f"LP burned or locked ≥ {C.MIN_LP_LOCKED_PCT:g}% ({m.get('lp_basis') or 'unverified'})")
    add("hard", "structure", "rugged", "Not flagged rugged", m.get("rugged"), lambda v: v is False,
        "RugCheck rugged flag false", skipped=rc_down)

    # ---- scope: in range and alive (not safety checks) ----------------------------------------------
    mc = m.get("mcap")
    add("soft", "scope", "mcap", "In your market-cap range", mc,
        lambda v: C.MIN_MCAP * s["mcap_low"] <= v <= C.MAX_MCAP * s["mcap_high"], f"{C.MIN_MCAP:,.0f} to {C.MAX_MCAP:,.0f} USD")
    add("soft", "scope", "volume", "Alive: 24h volume", m.get("vol24"), lambda v: v >= C.MIN_VOL24 * s["vol"], f"≥ {C.MIN_VOL24:,.0f} USD")
    add("soft", "scope", "activity", "Still trading", m.get("vol1h"), lambda v: v >= C.MIN_VOL1H * s["vol"], f"≥ {C.MIN_VOL1H:,.0f} USD in the last hour")
    add("soft", "scope", "traders", "Enough traders", m.get("traders_1h"), lambda v: v >= C.MIN_TRADERS_1H * s["vol"],
        f"≥ {C.MIN_TRADERS_1H} wallets trading in the last hour")
    add("soft", "scope", "twoway", "Two-way trading", m.get("sold_1h"), lambda v: v >= C.MIN_SOLD_1H,
        f"≥ {C.MIN_SOLD_1H} USD sold in the last hour (buy-only flow is a farm pattern)")

    # ---- risk: the rug-risk checks ------------------------------------------------------------------
    add("soft", "risk", "age", "Out of its first hour", m.get("age_min"), lambda v: v >= C.MIN_AGE_MIN,
        f"≥ {C.MIN_AGE_MIN} minutes since it reached a DEX (74% of rugs finish within the first hour)")
    rs = m.get("risk")
    if rs is None:
        add("soft", "risk", "riskflags", "Rug-risk flags", None, None, f"≤ {C.MAX_RISK_FLAGS} of the study's 6 red flags")
    elif rs["calibrated"]:
        val = rs["count"] if (rs["complete"] or rs["count"] > C.MAX_RISK_FLAGS) else None
        add("soft", "risk", "riskflags", "Rug-risk flags", val, lambda v: v <= C.MAX_RISK_FLAGS,
            f"≤ {C.MAX_RISK_FLAGS} of the study's 6 red flags (it measured coins under a day old and under $1m)")
    else:
        add("info", "risk", "riskflags", "Rug-risk flags", rs["count"], lambda v: True,
            "shown only: the study's rates do not cover coins over a day old or above $1m")
    liq_floor = max(C.MIN_LIQ_USD, C.MIN_LIQ_PCT_MCAP * (mc or 0))
    add("soft", "risk", "liquidity", "Liquidity", m.get("liq"), lambda v: v >= liq_floor * s["liq"],
        f"≥ max({C.MIN_LIQ_USD:,.0f} USD, {C.MIN_LIQ_PCT_MCAP:.0%} of mcap)")
    add("soft", "risk", "exit", "Exit cost", m.get("exit_cost"), lambda v: v <= C.MAX_EXIT_COST_PCT,
        f"selling a {C.ORDER_USD:,.0f} USD position costs ≤ {C.MAX_EXIT_COST_PCT:g}% (impact and fees)")
    v2m = (m["vol24"] / mc) if m.get("vol24") is not None and mc else None
    add("soft", "risk", "wash", "Volume plausible", v2m, lambda v: v <= C.MAX_VOL_TO_MCAP, f"24h volume ≤ {C.MAX_VOL_TO_MCAP:g}× market cap")
    add("soft", "risk", "organic", "Organic trading", m.get("organic_label"), lambda v: v != "low", "Jupiter organic score not 'low'")
    add("soft", "risk", "flagged", "Not flagged by Jupiter", m.get("sus"), lambda v: v is False, "Jupiter audit does not mark it suspicious")
    add("soft", "risk", "crash", "Not in free fall", m.get("crash"), lambda v: not m.get("crash_breach"),
        "price change > %s in 1h, %s in 6h, %s in 24h" % tuple("%g%%" % C.CRASH_LIMITS[k] for k in ("h1", "h6", "h24")))
    add("soft", "risk", "devsell", "Developer not selling", m.get("dev_drop"), lambda v: v < C.DEV_SELL_DROP,
        f"deployer balance down < {C.DEV_SELL_DROP:.0%} in 24h")
    add("soft", "risk", "outflow", "No top-holder exit", m.get("top_outflow_6h"), lambda v: v < C.TOP_OUTFLOW_PCT_6H,
        f"top holders' outflow < {C.TOP_OUTFLOW_PCT_6H:g}% of supply in 6h")
    if m.get("tg_bot_risk") is not None:
        add("soft", "risk", "telegram", "Telegram looks organic", m["tg_bot_risk"], lambda v: v <= C.MAX_TG_BOT_RISK,
            f"bot-risk ≤ {C.MAX_TG_BOT_RISK}")

    # ---- holder structure: shown for fresh launchpad graduates (the study's range), gating everywhere else ----
    fresh = bool(m.get("launchpad") and (m.get("risk") or {}).get("calibrated"))
    kind = "info" if (fresh and not C.HOLDER_GATES_FOR_LAUNCHPADS) else "soft"
    why = " (shown: no rug signal among fresh launchpad graduates in the study)" if kind == "info" else ""
    add(kind, "holders", "top10", "Top 10 holders", m.get("top10"), lambda v: v <= C.MAX_TOP10_PCT + s["top10"],
        f"≤ {C.MAX_TOP10_PCT:g}% ex pools, lockers, burn, CEX{why}")
    add(kind, "holders", "creator", "Developer holding", m.get("creator_pct"), lambda v: v <= C.MAX_CREATOR_PCT + s["creator"],
        f"≤ {C.MAX_CREATOR_PCT:g}% of supply{why}")
    add(kind, "holders", "linked", "Linked wallets", m.get("linked_share"), lambda v: v <= C.MAX_LINKED_HOLDER_SHARE + s["linked"],
        f"transfer-linked wallets ≤ {C.MAX_LINKED_HOLDER_SHARE:.0%} of holders{why}", skipped=rc_down)
    add(kind, "holders", "bundle", "Bundle signature", m.get("same_size"), lambda v: v <= C.MAX_SAME_SIZE_HOLDERS,
        f"≤ {C.MAX_SAME_SIZE_HOLDERS} near-identical balances in top holders{why}", skipped=rc_down)
    add(kind, "holders", "cluster", "Largest wallet cluster", m.get("cluster_pct"),
        lambda v: v <= C.MAX_CLUSTER_PCT + s["cluster"],
        f"wallets linked by transfers hold ≤ {C.MAX_CLUSTER_PCT:g}% of supply as one group{why}",
        skipped=rc_down or m.get("cluster_skip"))
    return gates


def blocking(gates):
    """Failures that count: hard and soft gates, never 'info'."""
    return [g for g in gates if not g["ok"] and not g["info"]]
