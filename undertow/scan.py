"""Orchestrator: discover -> refresh -> enrich -> gate -> track -> momentum -> export.
Run:  python3 -m undertow.scan run --db undertow.db --out docs/data.json
      python3 -m undertow.scan inspect <MINT>"""
import argparse, csv, json, os, sys, time
from . import config as C, sources as S, gates as G, momentum as M, tgrisk, signals as SG, tracker as TR, notify, http, lab as LAB
from .store import Store, TSNAP_VARS

H = 3600.0


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def fmt(v):
    """Readable numbers for transition reasons: 1,150 not 1.15e+03, 0.42 not 0.4213."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return str(v)
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.3g}"


# ------------------------------------------------------------------ discovery
def discover(st, now, jcache):
    """Jupiter's category lists (every launchpad and DEX, 100 tokens each) every run; GeckoTerminal's per-DEX pool
    lists hourly. Everything seen is kept for UNIVERSE_TTL_DAYS, so the universe builds up across runs."""
    seen, calls = {}, 0
    for path in C.JUP_LISTS:
        for j in S.jup_list(path):
            jcache[j["mint"]] = j
            seen.setdefault(j["mint"], {"mint": j["mint"], "pool": "", "dex": "", "name": j.get("symbol")})
        calls += 1
    n_jup = len(seen)
    last = st.get_meta("last_gt_discovery")
    if not last or now - float(last) >= C.DISCOVERY_EVERY_MIN * 60:
        for dex, pages in C.DISCOVERY_DEXES.items():
            for sort in C.DISCOVERY_SORTS:
                for pg in range(1, pages + 1):
                    pools = S.gt_pools(f"dexes/{dex}/pools?sort={sort}&page={pg}")
                    calls += 1
                    if pools is None:          # rate-limited after retries: skip this page, keep going
                        continue
                    if not pools:
                        break
                    for p in pools:
                        seen[p["mint"]] = p
        for path in ("trending_pools?page=1", "trending_pools?page=2", "new_pools?page=1"):
            for p in S.gt_pools(path) or []:
                seen.setdefault(p["mint"], p)
            calls += 1
        st.set_meta("last_gt_discovery", now)
    for p in seen.values():
        st.upsert_seen(p, now)
    st.commit()
    log(f"discovery: {len(seen)} tokens ({n_jup} from Jupiter lists) from {calls} calls")
    return seen


# ------------------------------------------------------------------ helpers
def cheap_ok(d):
    """In range on DEX Screener's numbers (with slack), and not still on a bonding curve."""
    mc, v = d.get("mcap") or 0, (d.get("vol") or {}).get("h24") or 0
    return (C.MIN_MCAP * 0.8 <= mc <= C.MAX_MCAP * 1.2 and v >= C.MIN_VOL24 * 0.6 and (d.get("liq") or 0) >= C.MIN_LIQ_USD * 0.6
            and SG.pool_kind(d.get("dex"), d.get("labels")) != "curve")


def out_of_scope(j):
    return bool(j and set(j.get("tags") or []) & C.EXCLUDE_TAGS)


def sector_of(gt):
    for c in (gt or {}).get("categories") or []:
        if c.lower() not in C.GENERIC_CATEGORIES:
            return c
    return "Other"


def handle_from_url(u):
    """First path segment of an x.com / t.me link. DEX Screener often stores a tweet or community URL here."""
    if not u:
        return None
    from urllib.parse import urlparse
    segs = [x for x in urlparse(u if "//" in u else "//" + u).path.split("/") if x]
    if not segs:
        return None
    h = segs[0].lstrip("@").lower()
    return None if h in ("i", "intent", "search", "home", "share", "hashtag", "explore", "status") else h


def history_metrics(st, mint, now, rc):
    """dev_drop, top_outflow_6h, holder_growth from our own snapshots. None until enough history exists."""
    snaps = st.snaps(mint, now - 30 * H)
    out = {"dev_drop": None, "top_outflow_6h": None, "holder_growth": None}
    if rc is None:
        return out
    ref = [s for s in snaps if s["creator_bal"] is not None and now - s["ts"] >= 3 * H]
    if ref and rc.get("creator_bal") is not None:
        prev = ref[0]["creator_bal"]
        out["dev_drop"] = max(0.0, (prev - rc["creator_bal"]) / prev) if prev > 0 else 0.0
    ref6 = [s for s in snaps if s["top20"] and s["top20"] != "{}" and 3 * H <= now - s["ts"] <= 9 * H]
    if ref6 and rc.get("supply"):
        prev = json.loads(ref6[-1]["top20"])
        cur, skip = rc.get("top20") or {}, set(rc.get("pool_owners") or [])
        floor = min(cur.values()) if cur else 0
        out["top_outflow_6h"] = sum(max(0, a - cur.get(o, floor)) for o, a in prev.items() if o not in skip) / rc["supply"] * 100
    hs = [s for s in snaps if s["holders"] and now - s["ts"] <= 8 * H]
    if len(hs) >= 2 and now - hs[0]["ts"] >= 1 * H and hs[0]["holders"] > 0:
        out["holder_growth"] = (hs[-1]["holders"] - hs[0]["holders"]) / hs[0]["holders"] / ((hs[-1]["ts"] - hs[0]["ts"]) / H)
    return out


def build_metrics(ds, rc, hist, jup, exitq, rpc, lock, trades, rc_down, now, gp=None):
    """Flatten every source into one metrics dict. Each structural check has a fallback chain, so one source being
    down does not stop the screener: authorities and extensions come from the chain (RPC) first. GoPlus is a second
    opinion: it can add a trap or a higher transfer fee, never clear one the chain reported."""
    j = jup or {}
    s1 = j.get("s1h") or {}
    kind = SG.pool_kind(ds.get("dex"), ds.get("labels"))
    m = {"mcap": ds.get("mcap"), "fdv": ds.get("fdv"), "liq": ds.get("liq"), "vol24": (ds.get("vol") or {}).get("h24"),
         "vol1h": (ds.get("vol") or {}).get("h1"), "venue_kind": kind, "launchpad": j.get("launchpad"), "rc_down": rc_down}
    # structure, from the chain first
    if rpc:
        m["authority_clean"] = not rpc["mint_auth"] and not rpc["freeze_auth"]
        m["bad_ext"], m["transfer_fee"] = S.bad_extensions(rpc.get("extensions"))
    elif j.get("mint_disabled") is not None:
        m["authority_clean"] = bool(j["mint_disabled"] and j["freeze_disabled"])
    elif rc:
        m["authority_clean"] = not rc["mint_auth"] and not rc["freeze_auth"]
    if "bad_ext" not in m and rc:
        m["bad_ext"], m["transfer_fee"] = rc["bad_ext"], rc["transfer_fee"]
    if gp:
        m["gp_traps"] = list(gp.get("traps") or [])
        m["meta_mutable"] = gp.get("meta_mutable")
        if (gp.get("fee_pct") or 0) > (m.get("transfer_fee") or 0):
            m["transfer_fee"] = gp["fee_pct"]          # the higher reading, a scheduled raise included
        if "authority_clean" not in m and gp.get("mintable") is not None:
            m["authority_clean"] = not gp["mintable"] and not gp.get("freezable")
    m["lp_locked_pct"], m["lp_basis"] = SG.lp_status(rc, (lock or {}).get("locked_pct"), kind, j, ds.get("pair"))
    if rc:
        m["rugged"] = rc["rugged"]
    # holders: RugCheck when reachable, Jupiter's audit otherwise
    if rc:
        m.update(creator_pct=rc["creator_pct"], top10=rc["top10"], same_size=rc["same_size"],
                 linked_share=(rc["linked_wallets"] / rc["holders"]) if rc.get("holders") else None)
        if "cluster_pct" in rc:
            m["cluster_pct"], m["cluster_n"] = rc["cluster_pct"], rc.get("cluster_n")
        else:                                  # a RugCheck read cached before clusters were stored
            m["cluster_skip"] = "older RugCheck read"
    else:
        m["top10"] = j.get("top_holders_pct")
        m["creator_pct"] = j.get("dev_pct") if j.get("dev_pct") is not None else (0.0 if j.get("mint_disabled") is not None else None)
    # liveness and demand
    m["traders_1h"] = s1.get("traders") if jup else None
    m["sold_1h"] = s1.get("sell_vol") if jup else None
    m["organic_label"] = j.get("organic_label") if jup else None
    m["sus"] = j.get("sus") if jup else None
    ch = ds.get("chg") or {}
    seen = [(ch[k], C.CRASH_LIMITS[k]) for k in ("h1", "h6", "h24") if ch.get(k) is not None]
    if seen:
        m["crash"] = min(seen, key=lambda t: t[0] / -t[1])[0]       # the window furthest past its limit
        m["crash_breach"] = any(v < lim for v, lim in seen)
    m["exit_cost"], m["exit_measured"] = SG.exit_cost(C.ORDER_USD, ds.get("liq"), (exitq or {}).get("impact_pct"))
    # the rug study's signals
    m["lfdv"] = SG.lfdv(ds.get("liq"), m["fdv"])
    m["worst_case"] = SG.worst_case_drop(m["lfdv"], kind)
    m["age_min"] = SG.age_minutes(j, ds, now)
    bv, sv = s1.get("buy_vol"), s1.get("sell_vol")
    m["sell_share_1h"] = sv / (sv + bv) if bv is not None and sv is not None and bv + sv > 0 else None
    m["swarm"] = SG.trade_stats(trades, now) if trades is not None else {}
    holders = j.get("holders") or (rc or {}).get("holders")
    m["holders"] = holders
    flags = SG.risk_flags(m["lfdv"], m["swarm"], holders, m["age_min"], m["sell_share_1h"])
    m["risk_flags"] = flags
    m["risk"] = SG.risk_summary(flags, m["age_min"], m["fdv"])
    m.update(hist)
    return m


def spark(snaps, now):
    pts = [(s["ts"], s["mcap"]) for s in snaps if s["mcap"] and now - s["ts"] <= 24 * H]
    if len(pts) > 24:
        step = len(pts) / 24
        pts = [pts[int(i * step)] for i in range(24)] + [pts[-1]]
    return [round(v) for _, v in pts]


def entry_features(r):
    """What the token looked like when it first entered: the inputs a later calibration needs."""
    m, j = r["m"], r.get("jup") or {}
    s1 = j.get("s1h") or {}
    sw = m.get("swarm") or {}
    return {"band": G.band_of(m.get("mcap") or 0), "mcap": m.get("mcap"), "liq": m.get("liq"), "vol24": m.get("vol24"),
            "vol1h": m.get("vol1h"), "top10": m.get("top10"), "creator_pct": m.get("creator_pct"),
            "linked_share": m.get("linked_share"), "same_size": m.get("same_size"), "exit_cost": m.get("exit_cost"),
            "organic": j.get("organic"), "traders_1h": s1.get("traders"), "net_flow_1h": s1.get("net_flow"),
            "breadth_1h": r.get("breadth"), "holder_change_1h": s1.get("holder_change"), "chg1h": r.get("chg1h"),
            "momentum": (r.get("momentum") or {}).get("score"), "quality": (r.get("mq") or {}).get("label"),
            "dev_mints": j.get("dev_mints"), "tg_members": (r.get("tg") or {}).get("members"),
            "tg_bot_risk": (r.get("tg") or {}).get("bot_risk"), "launchpad": j.get("launchpad"),
            "lfdv": m.get("lfdv"), "age_min": m.get("age_min"), "risk_flags": (m.get("risk") or {}).get("count"),
            "sell_share": sw.get("sell_share_15m") if sw.get("sell_share_15m") is not None else m.get("sell_share_1h"),
            "wallets_10m": sw.get("wallets_10m"), "top5_share": sw.get("top5_share"), "holders": m.get("holders")}


# ------------------------------------------------------------------ main pass
def process(st, now, toks, budget, ds_all, jcache):
    events = []
    # 0. a token that was inside but is no longer priced anywhere cannot be checked, so it leaves
    for t in toks:
        if t["status"] == "IN" and t["mint"] not in ds_all:
            st.add_transition(now, t["mint"], t["symbol"], "IN", "OUT", ["no market data from DEX Screener"])
            st.set_state(t["mint"], "OUT", 0, 0, now, json.loads(t["gates_json"] or "[]"))
            st.close_entry(t["mint"], now, t.get("live_mcap"), "no market data from DEX Screener")
            st.set_cols(t["mint"], last_exit_ts=now)
            t["status"] = "OUT"

    # A. candidates, then enrichment: Jupiter (stats, launchpad, tags), chain (authorities, extensions),
    #    GeckoTerminal (LP locks), RugCheck when reachable, GeckoTerminal info (sector) for the few that matter
    cands = [t for t in toks if t["mint"] in ds_all and (cheap_ok(ds_all[t["mint"]]) or t["status"] == "IN")]
    missing = [t["mint"] for t in cands if t["mint"] not in jcache]
    if missing:
        jcache.update(S.jup_tokens(missing))     # shared with the tracker snapshot, so no token is fetched twice
    jup = jcache
    for t in cands:                     # a token re-tagged as a pegged asset leaves the screener
        if t["status"] == "IN" and out_of_scope(jup.get(t["mint"])):
            st.add_transition(now, t["mint"], t["symbol"], "IN", "OUT", ["out of scope: price-pegged asset"])
            st.set_state(t["mint"], "OUT", 0, 0, now, json.loads(t["gates_json"] or "[]"))
            st.close_entry(t["mint"], now, ds_all[t["mint"]].get("mcap"), "out of scope")
            t["status"] = "OUT"
    cands = [t for t in cands if not out_of_scope(jup.get(t["mint"]))]
    pri = lambda t: (0 if t["status"] == "IN" else 1 if t["pass_streak"] else 2 if not t["rc_ts"] else 3, t["rc_ts"] or 0)
    cands.sort(key=pri)

    stale_rpc = [t["mint"] for t in cands if not t.get("rpc_ts") or now - t["rpc_ts"] > 24 * H]
    got = S.rpc_mints(stale_rpc) if stale_rpc else {}
    for t in cands:
        if t["mint"] in got:
            t["rpc_json"], t["rpc_ts"] = json.dumps(got[t["mint"]]), now
            st.set_cols(t["mint"], rpc_json=t["rpc_json"], rpc_ts=now)
    stale_lock = [t for t in cands if not t.get("lock_ts") or now - t["lock_ts"] > 6 * H]
    locks = S.gt_pools_multi([ds_all[t["mint"]].get("pair") for t in stale_lock]) if stale_lock else {}
    for t in stale_lock:
        lk = locks.get(ds_all[t["mint"]].get("pair"))
        if lk is not None:
            t["lock_json"], t["lock_ts"] = json.dumps(lk), now
            st.set_cols(t["mint"], lock_json=t["lock_json"], lock_ts=now)

    n_rc = n_gt = 0
    rc_down = http.down("rugcheck")
    for t in cands:
        mint = t["mint"]
        ttl = C.RC_TTL_H_IN if (t["status"] == "IN" or t["pass_streak"]) else C.RC_TTL_H_OUT
        if not rc_down and n_rc < budget and (not t["rc_ts"] or now - t["rc_ts"] > ttl * H):
            rc = S.rc_report(mint)
            n_rc += 1
            if rc:
                st.set_json(mint, "rc", rc, now); t["rc_json"], t["rc_ts"] = json.dumps(rc), now
            rc_down = http.down("rugcheck")
        if (t["status"] == "IN" or t["pass_streak"]) and n_gt < C.GT_INFO_BUDGET and (not t["gt_ts"] or now - t["gt_ts"] > C.GT_INFO_TTL_H * H):
            gt = S.gt_info(mint)
            n_gt += 1
            if gt:
                st.set_json(mint, "gt", gt, now); t["gt_json"], t["gt_ts"] = json.dumps(gt), now
    st.commit()
    log(f"enriched {len(cands)} candidates: {len(jup)} Jupiter, {len(got)} chain, {len(locks)} pool locks, "
        f"{n_rc} RugCheck{' (unreachable)' if rc_down else ''}, {n_gt} GeckoTerminal info")

    def ctx(t):
        mint = t["mint"]
        return dict(d=ds_all[mint], rc=json.loads(t["rc_json"]) if t["rc_json"] else None,
                    gt=json.loads(t["gt_json"]) if t["gt_json"] else None, j=jup.get(mint),
                    exitq=json.loads(t["exit_json"]) if t.get("exit_json") else None,
                    rpc=json.loads(t["rpc_json"]) if t.get("rpc_json") else None,
                    lock=json.loads(t["lock_json"]) if t.get("lock_json") else None,
                    gp=json.loads(t["gp_json"]) if t.get("gp_json") else None)

    # B. first pass: which tokens are worth the expensive checks (exit quote, trade list)?
    pre = {}
    for t in cands:
        c = ctx(t)
        hist = history_metrics(st, t["mint"], now, c["rc"])
        m = build_metrics(c["d"], c["rc"], hist, c["j"], c["exitq"], c["rpc"], c["lock"], None, rc_down, now, c["gp"])
        gates = G.evaluate(m, t["status"] == "IN")
        close = not [g for g in G.blocking(gates) if g["id"] not in ("exit", "riskflags", "telegram")]
        pre[t["mint"]] = (c, hist, m, close)

    # C. exit quotes (hourly) for tokens inside or about to enter, and trade lists (each run) for the young, small ones
    want = [t for t in cands if t["status"] == "IN" or pre[t["mint"]][3]]
    n_q = 0
    for t in want:
        c = pre[t["mint"]][0]
        if c["j"] and (not t.get("exit_ts") or now - t["exit_ts"] > C.EXIT_QUOTE_TTL_H * H):
            q = S.jup_exit_cost(t["mint"], c["j"].get("usd_price"), c["j"].get("decimals"), C.ORDER_USD)
            n_q += 1
            if q:
                st.set_cols(t["mint"], exit_json=json.dumps(q), exit_ts=now)
                t["exit_json"], t["exit_ts"] = json.dumps(q), now
    # GoPlus's second opinion for the same tokens, read every GP_TTL_H hours within a per-run budget
    n_gp = 0
    for t in want:
        if n_gp >= C.GP_BUDGET or http.down("goplus"):
            break
        if not t.get("gp_ts") or now - t["gp_ts"] > C.GP_TTL_H * H:
            g = S.gp_report(t["mint"])
            n_gp += 1
            if g:
                st.set_cols(t["mint"], gp_json=json.dumps(g), gp_ts=now)
                t["gp_json"], t["gp_ts"] = json.dumps(g), now
    # trade lists only where the study's flags gate (young and small coins); elsewhere they would only fill the panel
    young = [t for t in want if (pre[t["mint"]][2]["risk"] or {}).get("calibrated")]
    trades = {}
    for t in sorted(young, key=lambda t: t["status"] == "IN")[:C.TRADES_BUDGET]:
        tr = S.gt_trades(ds_all[t["mint"]].get("pair"))
        if tr is not None:
            trades[t["mint"]] = tr
    st.commit()
    log(f"exit quotes: {n_q}, GoPlus checks: {n_gp}, trade lists: {len(trades)} of {len(young)} young coins near the gates")

    # D. final metrics, gates, Telegram, state machine
    rows, handles = [], {}
    for t in cands:
        mint = t["mint"]
        c = ctx(t)
        d, rc, gt, j = c["d"], c["rc"], c["gt"], c["j"]
        hist = pre[mint][1]
        was_in = t["status"] == "IN"
        m = build_metrics(d, rc, hist, j, c["exitq"], c["rpc"], c["lock"], trades.get(mint), rc_down, now, c["gp"])
        gates = G.evaluate(m, was_in)

        tw = handle_from_url((j or {}).get("twitter")) or handle_from_url((gt or {}).get("twitter")) or handle_from_url(d.get("twitter_url"))
        tgh = handle_from_url((j or {}).get("telegram")) or handle_from_url((gt or {}).get("telegram")) or handle_from_url(d.get("telegram_url"))
        tgd = None
        if tgh and (was_in or not G.blocking(gates)):
            cnt = S.tg_counts(tgh)
            if cnt and cnt["members"]:
                st.add_tg(tgh, now, cnt["members"], cnt["online"])
                hist_tg = st.tg_hist(tgh, now - 48 * H)
                risk, why = tgrisk.bot_risk(cnt["members"], cnt["online"], m.get("holders"), hist_tg)
                m["tg_bot_risk"] = risk
                tgd = {"handle": tgh, "members": cnt["members"], "online": cnt["online"], "bot_risk": risk, "why": why,
                       "growth_h": tgrisk.growth_per_hour(hist_tg), "kind": cnt["kind"]}
                gates = G.evaluate(m, was_in)
        elif tgh:
            tgd = {"handle": tgh, "members": None, "online": None, "bot_risk": None, "why": [], "growth_h": None}
        if tw:
            handles.setdefault(tw, []).append(mint)

        failing = G.blocking(gates)
        hard_fail = any(g["hard"] for g in failing)
        soft_fail = any(not g["hard"] for g in failing)
        status, ps, fs, since = t["status"], t["pass_streak"], t["fail_streak"], t["status_since"] or now
        new = status
        if was_in:
            if hard_fail:
                new = "OUT"
            elif soft_fail:
                fs += 1
                new = "OUT" if fs >= C.EXIT_SCANS else "IN"
            else:
                fs = 0
            ps = 0
        else:
            if not failing:
                ps += 1
                new = "IN" if ps >= C.ENTER_SCANS else "OUT"
            else:
                ps = 0
            fs = 0
        entered_first = False
        if new != status:
            reasons = [f'{g["label"]}: {fmt(g["value"]) if g["value"] is not None else "no data"} (needs {g["rule"]})' for g in failing] or ["all gates passed"]
            st.add_transition(now, mint, d.get("symbol") or t["symbol"], status, new, reasons)
            since = now
            trk = json.loads(t["trk_json"]) if t.get("trk_json") else None
            if new == "IN":
                ps = fs = 0
                n = (t.get("entries_n") or 0) + 1
                st.open_entry(mint, n, now, d.get("mcap"), d.get("price"))
                cols = {"entries_n": n}
                if trk is None and d.get("price") and d.get("mcap"):
                    trk = TR.start(now, d["price"], d["mcap"])
                    cols["trk_json"] = json.dumps(trk)
                    entered_first = True
                st.set_cols(mint, **cols)
                t.update(cols)
            else:
                st.close_entry(mint, now, d.get("mcap"), "; ".join(reasons)[:500])
                st.set_cols(mint, last_exit_ts=now)
                t["last_exit_ts"] = now
            since_x = (d["price"] / trk["in_price"]) if (trk and d.get("price") and not entered_first) else None
            events.append({"symbol": d.get("symbol") or t["symbol"], "mint": mint, "frm": status, "to": new,
                           "mcap": d.get("mcap"), "reasons": [f'{g["label"]} {fmt(g["value"])}' for g in failing], "since_x": since_x})
            log(f'{(d.get("symbol") or t["symbol"] or mint[:6]):>10}  {status} -> {new}  {"; ".join(reasons)[:140]}')
        st.set_state(mint, new, ps, fs, since, gates)
        t["status"] = new

        snap = {"price": d.get("price"), "mcap": d.get("mcap"), "liq": d.get("liq"), "vol24": m["vol24"],
                "vol1": (d.get("vol") or {}).get("h1"), "chg1": (d.get("chg") or {}).get("h1"), "chg6": (d.get("chg") or {}).get("h6"),
                "chg24": (d.get("chg") or {}).get("h24"), "buys24": d.get("buys24"), "sells24": d.get("sells24"),
                "buys1": d.get("buys1"), "sells1": d.get("sells1")}
        if rc and t["rc_ts"] == now:
            snap.update(holders=rc["holders"], top10=rc["top10"], creator_pct=rc["creator_pct"], creator_bal=rc["creator_bal"], top20=rc["top20"])
        st.add_snap(mint, now, snap)

        v24 = m["vol24"] or 0
        s1 = (j or {}).get("s1h") or {}
        flow1 = s1.get("net_flow")
        rows.append({
            "t": t, "d": d, "gt": gt, "rc": rc, "gp": c["gp"], "m": m, "gates": gates, "tg": tgd, "tw": tw, "state_new": new,
            "ps": ps, "fs": fs, "since": since, "hard_ok": not hard_fail, "jup": j, "exitq": c["exitq"],
            "entered_first": entered_first, "moved": (status, new),
            "chg1h": (d.get("chg") or {}).get("h1"), "chg6h": (d.get("chg") or {}).get("h6"),
            "vol_accel": ((d.get("vol") or {}).get("h1") or 0) * 24 / v24 if v24 else None,
            "flow_pct": flow1 / d["liq"] if flow1 is not None and d.get("liq") else None,
            "breadth": SG.buyer_breadth(s1), "holder_growth": s1.get("holder_change"),
            "tg_growth": (tgd or {}).get("growth_h"),
        })
    st.commit()

    # E. tracker (candles for tokens that have ever entered), momentum quality, momentum ranks
    candles = track(st, now, toks, ds_all)
    for r in rows:
        cs = SG.candle_stats(candles.get(r["t"]["mint"]), now)
        flow1 = (((r.get("jup") or {}).get("s1h")) or {}).get("net_flow")
        label, why = SG.momentum_quality(r["chg1h"], flow1, r["breadth"], cs.get("extension"))
        r["mq"] = {"label": label, "why": why, **cs}
    M.score_all([r for r in rows if r["hard_ok"]])
    for r in rows:
        r.setdefault("momentum", {"score": None, "label": "n/a", "parts": {}})
        if r["entered_first"]:
            st.set_cols(r["t"]["mint"], entry_json=json.dumps(entry_features(r)))
    st.commit()
    return rows, handles, events, {"rugcheck": "unreachable" if rc_down else "ok"}


def update_outcomes(st, ds_all, now):
    """Fold this run's prices into every open observation: +1h/+6h/+24h multiples, the 24h high and low, and the
    first times it reached 1.5x, 2x or fell to 0.2x. Closes observations older than a day."""
    tol = max(C.OBS_TOL_MIN, C.SCAN_MINUTES + 10) * 60     # an hourly scheduler must still land inside the window
    n = 0
    for o in st.open_obs():
        price = (ds_all.get(o["mint"]) or {}).get("price")
        ch = LAB.step(o, price, now, tol)
        if not ch and now - o["ts"] > 24 * H + tol:
            ch = {"done": 1}                 # no price at the end of its day: close it with what was seen
        if ch:
            st.update_obs(o["rowid"], ch)
            n += 1
    st.commit()
    return n


def observe(st, rows, now, regime):
    """Record observations for the Lab: every entry and exit as it happens, and, checking every candidate once an
    hour, the observations the Lab reads: a token's first of each day, and its first that day that passed every gate."""
    last = st.get_meta("last_obs")
    hourly = not last or now - float(last) >= C.OBS_EVERY_MIN * 60 - 120
    rising = [r for r in rows if (r["d"].get("chg") or {}).get("h1") is not None]
    regime = {**(regime or {}), "mkt1h": sum(1 for r in rising if r["d"]["chg"]["h1"] > 0) / len(rising) if rising else None}
    n = 0
    for r in rows:
        frm, to = r.get("moved") or (None, None)
        ev = "entry" if to == "IN" and frm != "IN" else ("exit" if frm == "IN" and to != "IN" else ("hourly" if hourly else None))
        if not ev or not r["d"].get("price"):
            continue
        if ev == "hourly" and not st.obs_needed(r["t"]["mint"], now, not G.blocking(r["gates"])):
            continue
        # distance from the highest price this scanner has seen in 24h: a falling-knife check for every candidate,
        # since candles are only fetched for tracked tokens
        seen = [s["price"] for s in st.snaps(r["t"]["mint"], now - 24 * H) if s["price"]]
        top = max(seen + [r["d"]["price"]])
        f = LAB.features(r["d"], r["m"], r.get("jup"), r.get("mq"), r.get("momentum"), r.get("tg"),
                         {**regime, "dd24s": r["d"]["price"] / top - 1 if top else None})
        f["band"] = G.band_of(r["d"].get("mcap") or 0)
        fails = [g["id"] for g in G.blocking(r["gates"])]
        state = ("WATCH" if r["fs"] else "IN") if to == "IN" else ("ENTERING" if r["ps"] else "OUT")
        st.add_obs(now, r["t"]["mint"], ev, state, not fails, fails, r["d"]["price"], f, LAB.rule_results(f, C.SHADOW_RULES))
        n += 1
    if hourly:
        st.set_meta("last_obs", now)
    st.thin_obs(now - C.OBS_FULL_DAYS * 86400)
    st.commit()
    return n


def not_candidate_reason(d, j):
    """Why a tracked token is not among this run's candidates, as gate ids (or 'nodata' when nothing prices it)."""
    if not d or not d.get("price"):
        return ["nodata"]
    if out_of_scope(j):
        return ["scope"]
    if SG.pool_kind(d.get("dex"), d.get("labels")) == "curve":
        return ["venue"]
    mc, v = d.get("mcap") or 0, (d.get("vol") or {}).get("h24") or 0
    out = []
    if not C.MIN_MCAP * 0.8 <= mc <= C.MAX_MCAP * 1.2:
        out.append("mcap")
    if v < C.MIN_VOL24 * 0.6:
        out.append("volume")
    if (d.get("liq") or 0) < C.MIN_LIQ_USD * 0.6:
        out.append("liquidity")
    return out or ["scope"]


def row_state(r):
    return ("WATCH" if r["fs"] else "IN") if r["state_new"] == "IN" else ("ENTERING" if r["ps"] else "OUT")


def snapshot_tracked(st, rows, ds_all, jcache, now):
    """Once an hour, record every tracked token's numbers, in or out of the screener, so they can be compared hour by
    hour after entry: market cap, liquidity, volume, net buying, wallets, holders, top-10 share, organic score,
    liquidity / FDV, the multiple of the entry price and the screener state. Entries are recorded as they happen."""
    by = {r["t"]["mint"]: r for r in rows}
    last = st.get_meta("last_tsnap")
    hourly = not last or now - float(last) >= C.TSNAP_EVERY_MIN * 60 - 120
    entering = {m for m, r in by.items() if r.get("entered_first")}
    todo = []
    for t in st.tracked():
        trk = json.loads(t["trk_json"])
        if t["mint"] in entering or (hourly and now - trk["in_ts"] <= C.TRACK_DAYS * 86400 + H):
            todo.append((t, trk))
    missing = [t["mint"] for t, _ in todo if t["mint"] not in jcache and t["mint"] in ds_all]
    if missing:
        jcache.update(S.jup_tokens(missing))
    n = 0
    for t, trk in todo:
        mint = t["mint"]
        d, j, r = ds_all.get(mint), jcache.get(mint) or {}, by.get(mint)
        if r:
            m, fails, state = dict(r["m"]), [g["id"] for g in G.blocking(r["gates"])], row_state(r)
        else:
            m = {"lfdv": SG.lfdv((d or {}).get("liq"), (d or {}).get("fdv") or (d or {}).get("mcap"))}
            fails = not_candidate_reason(d, j)
            state = "GONE" if fails == ["nodata"] else "OUT"
        # Jupiter's holder count and top-holder share for every token and every hour: one source through the whole
        # series, so a change in the numbers is a change in the token, not a switch between data sources
        m["holders"], m["top10"] = j.get("holders"), j.get("top_holders_pct")
        f = LAB.features(d, m, j)
        ev = "entry" if mint in entering else "hourly"
        price = (d or {}).get("price")
        x = price / trk["in_price"] if price and trk.get("in_price") else None
        st.add_tsnap(now, mint, ev, 0.0 if ev == "entry" else round((now - trk["in_ts"]) / H, 3), state, fails,
                     price, LAB._r(x), f)
        n += 1
    if hourly:
        st.set_meta("last_tsnap", now)
    st.thin_tsnap(C.TSNAP_FULL_H)
    st.commit()
    log(f"tracker snapshots: {n} recorded{'' if hourly else ' (entries only; next hourly round later)'}")
    return n


def track(st, now, toks, ds_all):
    """Update every tracked token: live price each run, 5-minute candles every run while inside the screener and
    hourly after it leaves, for TRACK_DAYS after first entry. Returns {mint: candles} for this run."""
    tracked = [t for t in toks if t.get("trk_json")]
    tracked.sort(key=lambda t: (0 if t["status"] == "IN" else 1, t.get("candles_ts") or 0))
    n, got = 0, {}
    for t in tracked:
        mint, d = t["mint"], ds_all.get(t["mint"])
        trk = json.loads(t["trk_json"])
        recent = t.get("candles_ts") and now - t["candles_ts"] < C.TRACK_REFRESH_H_OUT * H
        due = now - trk["in_ts"] <= C.TRACK_DAYS * 86400 and (t["status"] == "IN" or not recent)
        cs = None
        if due and n < C.CANDLE_BUDGET:
            cs = S.gt_candles((d or {}).get("pair") or t.get("pool"), mint)
            n += 1
            if cs is not None:
                got[mint] = cs
                st.set_cols(mint, candles_ts=now)
        trk = TR.update(trk, cs, now, (d or {}).get("price"), C.OUTCOME_HOURS)
        cols = {"trk_json": json.dumps(trk)}
        if d and d.get("price"):
            cols.update(live_price=d["price"], live_mcap=d.get("mcap"), live_ts=now)
        st.set_cols(mint, **cols)
        t.update(cols)
    st.commit()
    log(f"tracker: {len(tracked)} tracked, {n} candle calls")
    return got


# ------------------------------------------------------------------ export
TRACK_VARS = ("mc", "liq", "v1h", "v24h", "nf1h", "tr1h", "brd1h", "hold", "top10", "org", "lfdv")
# entry_features() names, for entries recorded before the hourly snapshots existed
_ENTRY_KEYS = {"mcap": "mc", "liq": "liq", "vol1h": "v1h", "vol24": "v24h", "net_flow_1h": "nf1h", "traders_1h": "tr1h",
               "breadth_1h": "brd1h", "holders": "hold", "top10": "top10", "organic": "org", "lfdv": "lfdv"}
# Hours since entry at which the page compares tokens: every hour for three days, then every six hours to day 14.
SLOTS = list(range(0, C.TSNAP_FULL_H + 1)) + list(range(C.TSNAP_FULL_H + 6, C.TRACK_DAYS * 24 + 1, 6))
_SLOT_AT = {s: i for i, s in enumerate(SLOTS)}
# The columns of the hour-by-hour comparison: at entry, +1h, +6h, +24h (each from the snapshot nearest that hour,
# within a tolerance) and the latest snapshot.
MARKS = (("entry", 0, 0.5), ("+1h", 1, 0.5), ("+6h", 6, 1.0), ("+24h", 24, 2.0))
STATE_CODE = {"IN": "I", "WATCH": "W", "ENTERING": "E", "OUT": "O", "GONE": "G"}


def slot_of(h):
    if h is None or h < -0.5:
        return None
    if h <= C.TSNAP_FULL_H + 0.5:
        return int(round(h))
    s = C.TSNAP_FULL_H + int(round((h - C.TSNAP_FULL_H) / 6)) * 6
    return s if s in _SLOT_AT else None


def x_series(snaps):
    """The multiple of the entry price at each slot (hours since entry), from the snapshots nearest each slot.
    Trailing empty slots are dropped; a gap inside the series stays None."""
    best = {}
    for s in snaps:
        k = slot_of(s["h"])
        if s["x"] is None or k is None:
            continue
        gap = abs(s["h"] - k)
        if k not in best or gap < best[k][0]:
            best[k] = (gap, s["x"])
    out = [best[k][1] if k in best else None for k in SLOTS]
    while out and out[-1] is None:
        out.pop()
    return out


def marks_table(snaps, entry_f):
    """{variable: [at entry, +1h, +6h, +24h, latest]} from the hourly snapshots. A token that entered before the
    snapshots existed takes its entry column from what was recorded at entry."""
    cols = []
    for name, at, tol in MARKS:
        near = [s for s in snaps if abs(s["h"] - at) <= tol and (name != "entry" or s["ev"] in ("entry", "hourly"))]
        cols.append(min(near, key=lambda s: (s["ev"] != "entry", abs(s["h"] - at))) if near else None)
    cols.append(snaps[-1] if snaps else None)
    out = {}
    for k in TRACK_VARS:
        vals = [c.get(k) if c else None for c in cols]
        if vals[0] is None and entry_f and k != "top10":   # the entry record's top-10 came from RugCheck, not Jupiter
            vals[0] = entry_f.get(k)
        if any(v is not None for v in vals):
            out[k] = vals
    return out


def tracker_rows(st, rows, now):
    state_of = {r["t"]["mint"]: r for r in rows}
    snaps_by = {}
    for s in st.tsnaps():
        snaps_by.setdefault(s["mint"], []).append(s)
    out = []
    for t in st.tracked():
        trk = json.loads(t["trk_json"])
        s = TR.summary(trk, t.get("live_price"), t.get("live_mcap"), now)
        entry = json.loads(t["entry_json"]) if t.get("entry_json") else None
        ef = st.obs_ends(t["mint"])[0]
        if ef is None and entry:
            ef = {_ENTRY_KEYS[k]: v for k, v in entry.items() if k in _ENTRY_KEYS}
        snaps = snaps_by.get(t["mint"], [])
        r = state_of.get(t["mint"])
        state = row_state(r) if r else ("IN" if t["status"] == "IN" else "OUT")
        if state == "ENTERING":
            state = "OUT"
        out.append({"mint": t["mint"], "symbol": t["symbol"], "name": t["name"], "state": state,
                    "entries": t.get("entries_n") or 1, "last_exit_ts": t.get("last_exit_ts"),
                    "band_at_entry": G.band_of(trk["in_mcap"] or 0), "live_ts": t.get("live_ts"),
                    "in_price": trk.get("in_price"), "pair": (r["d"].get("pair") if r else None) or t.get("pool"),
                    "entry": entry, "vt": marks_table(snaps, ef), "vt_ts": snaps[-1]["ts"] if snaps else None,
                    "hx": x_series(snaps), "n_snaps": len(snaps), **s})
    out.sort(key=lambda x: -x["in_ts"])
    return out


def bucket_of(mint, n=None):
    """Which snapshot file holds a token: the sum of its address's character codes, modulo the file count.
    The page computes the same thing to fetch one file rather than all of them."""
    return sum(map(ord, mint)) % (n or C.SNAP_BUCKETS)


def write_snapshot_files(out_dir, st, symbols):
    """Hourly tracker snapshots: snapshots.csv (every row) and snap/<n>.json (per token, for the page)."""
    rows = st.tsnaps()
    iso = lambda ts: time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)) if ts else ""
    labels = {k: l for k, l, _u in LAB.VARIABLES}
    with open(os.path.join(out_dir, "snapshots.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["utc", "symbol", "mint", "event", "hours_since_entry", "state", "not_passing", "price", "x_entry"]
                   + [labels.get(k, k) for k in TSNAP_VARS])
        for s in rows:
            w.writerow([iso(s["ts"]), symbols.get(s["mint"]) or "", s["mint"], s["ev"], s["h"], s["state"],
                        (s["fails"] or "").replace(",", " "), s["price"], s["x"]] + [s[k] for k in TSNAP_VARS])
    buckets = [{} for _ in range(C.SNAP_BUCKETS)]
    cols = ["ts", "h", "st", "fails", "x"] + list(TSNAP_VARS)
    for s in rows:
        b = buckets[bucket_of(s["mint"])].setdefault(s["mint"], {"c": cols, "r": []})
        b["r"].append([int(s["ts"]), round(s["h"], 2), STATE_CODE.get(s["state"], ""), s["fails"] or "", s["x"]]
                      + [s[k] for k in TSNAP_VARS])
    os.makedirs(os.path.join(out_dir, "snap"), exist_ok=True)
    for i, b in enumerate(buckets):
        with open(os.path.join(out_dir, "snap", f"{i}.json"), "w") as f:
            json.dump(clean(b), f, separators=(",", ":"), allow_nan=False)
    return len(rows)


CSV_COLS = ["symbol", "mint", "first_entry_utc", "entry_mcap", "now_mcap", "now_x", "ath_mcap", "ath_utc", "ath_x",
            "max_drawdown_pct", "x_1h", "x_6h", "x_24h", "x_7d", "rug_24h", "doubled_24h", "entries", "state",
            "band_at_entry", "launchpad", "age_min", "lfdv", "risk_flags", "sell_share", "wallets_10m", "top5_share",
            "holders", "top10", "creator_pct", "linked_share", "exit_cost", "organic", "traders_1h", "net_flow_1h",
            "momentum", "quality", "dev_mints", "tg_members", "tg_bot_risk"]


def write_csv(path, trk_rows):
    iso = lambda ts: time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)) if ts else ""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(CSV_COLS)
        for x in trk_rows:
            e, o = x.get("entry") or {}, x.get("out") or {}
            w.writerow([x["symbol"], x["mint"], iso(x["in_ts"]), x["in_mcap"], x["now_mcap"], x["now_x"], x["ath_mcap"],
                        iso(x["ath_ts"]), x["ath_x"], (x["low_x"] - 1) * 100 if x.get("low_x") else "",
                        o.get("1"), o.get("6"), o.get("24"), o.get("168"), x.get("rug_24h"), x.get("doubled_24h"),
                        x["entries"], x["state"], x["band_at_entry"]]
                       + [e.get(k) for k in ("launchpad", "age_min", "lfdv", "risk_flags", "sell_share", "wallets_10m", "top5_share",
                                             "holders", "top10", "creator_pct", "linked_share", "exit_cost", "organic",
                                             "traders_1h", "net_flow_1h", "momentum", "quality", "dev_mints", "tg_members", "tg_bot_risk")])


def pack_gates(rows):
    """Gate labels and most rules are the same for every token: send each once in gate_meta, and per token only the
    id, result, value, kind (h hard, s soft, i info) and a rule only where it differs (lock basis, not checked)."""
    seen = {}
    for r in rows:
        for g in r["gates"]:
            e = seen.setdefault(g["id"], {"label": g["label"], "group": g["group"], "rules": {}})
            e["rules"][g["rule"]] = e["rules"].get(g["rule"], 0) + 1
    meta = {gid: {"label": e["label"], "group": e["group"], "rule": max(e["rules"], key=e["rules"].get)} for gid, e in seen.items()}

    def pack(g):
        out = {"id": g["id"], "ok": g["ok"], "v": g["value"], "k": "h" if g["hard"] else ("i" if g["info"] else "s")}
        if g["rule"] != meta[g["id"]]["rule"]:
            out["r"] = g["rule"]
        return out
    return meta, pack


def lab_report(st):
    """The Lab's analysis plus what the page needs to label it."""
    rows = st.lab_rows()
    out = LAB.analyse(rows, C.SHADOW_RULES, C.LAB)
    out["variables"] = [{"key": k, "label": l, "unit": u} for k, l, u in LAB.VARIABLES]
    out["rules"] = [{"id": r[0], "label": r[1]} for r in C.SHADOW_RULES]
    out["stats"] = st.obs_stats()
    return out, rows


def write_obs_csv(path, rows, symbols):
    """One row per analysed observation: when, what state, every variable, every shadow rule and what happened next."""
    rule_ids = [r[0] for r in C.SHADOW_RULES]
    iso = lambda ts: time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts)) if ts else ""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["utc", "symbol", "mint", "event", "state", "passed", "failing_gates", "price"] + LAB.VAR_KEYS
                   + ["launchpad", "venue", "band", "quality"] + ["rule_" + r for r in rule_ids]
                   + ["x_1h", "x_6h", "x_24h", "high_24h", "low_24h", "rugged_24h", "doubled_24h"])
        for r in rows:
            fe, ru = r["f"], r["rules"]
            w.writerow([iso(r["ts"]), symbols.get(r["mint"]) or "", r["mint"], r["ev"], r["state"], r["passed"],
                        " ".join(r["fails"]), r["price"]] + [fe.get(k, "") for k in LAB.VAR_KEYS]
                       + [fe.get("lp", ""), fe.get("kind", ""), fe.get("band", ""), fe.get("q", "")]
                       + [ru.get(k, "") for k in rule_ids]
                       + [r["p1"], r["p6"], r["p24"], r["hi"], r["lo"], LAB.rugged(r),
                          (r["x2_ts"] is not None) if (r["done"] or r["x2_ts"] is not None) else ""])


def export(st, rows, handles, now, meta, out_path):
    toks = []
    gate_meta, pack = pack_gates(rows)
    trk_rows = tracker_rows(st, rows, now)
    trk_by = {x["mint"]: x for x in trk_rows}
    for r in rows:
        t, d, m, gt, rc, j = r["t"], r["d"], r["m"], r["gt"], r["rc"], r.get("jup") or {}
        mc = d.get("mcap") or 0
        status = r["state_new"]
        state = ("WATCH" if r["fs"] else "IN") if status == "IN" else ("ENTERING" if r["ps"] else "OUT")
        tw = r["tw"]
        shared = [x for x in handles.get(tw, []) if x != t["mint"]] if tw else []
        top10 = m.get("top10")
        flows = {k: ((j.get(w) or {}).get("net_flow")) for k, w in (("h1", "s1h"), ("h6", "s6h"), ("h24", "s24h"))}
        s1, s24 = j.get("s1h") or {}, j.get("s24h") or {}
        toks.append({
            "mint": t["mint"], "symbol": d.get("symbol") or t["symbol"], "name": d.get("name") or t["name"],
            "sector": sector_of(gt), "band": G.band_of(mc), "state": state, "since": r["since"],
            "mcap": mc, "fdv": m.get("fdv"), "float_cap": mc * (1 - top10 / 100) if top10 is not None else None,
            "liq": d.get("liq"), "vol24": m.get("vol24"), "vol1h": m.get("vol1h"), "price": d.get("price"),
            "chg": {k: (d.get("chg") or {}).get(k) for k in ("m5", "h1", "h6", "h24")},
            "age_h": (m["age_min"] / 60) if m.get("age_min") is not None else None,
            "launchpad": j.get("launchpad"), "venue": {"dex": d.get("dex"), "kind": m.get("venue_kind"), "labels": d.get("labels"), "quote": d.get("quote")},
            "holders": m.get("holders"),
            "top10": top10, "creator_pct": m.get("creator_pct"), "lp_locked": m.get("lp_locked_pct"), "lp_basis": m.get("lp_basis"),
            "linked_share": m.get("linked_share"), "same_size": m.get("same_size"),
            "cluster": {"pct": m.get("cluster_pct"), "n": m.get("cluster_n")} if m.get("cluster_pct") is not None else None,
            "goplus": r.get("gp"),
            "dev_drop": m.get("dev_drop"), "top_outflow_6h": m.get("top_outflow_6h"),
            "demand": {"net_flow": flows, "traders_1h": s1.get("traders"), "net_buyers_1h": s1.get("net_buyers"),
                       "breadth_1h": r.get("breadth"), "organic_buyers_24h": s24.get("organic_buyers"),
                       "holder_change": {"h1": s1.get("holder_change"), "h24": s24.get("holder_change")},
                       "sold_1h": m.get("sold_1h"), "sell_share_1h": m.get("sell_share_1h")},
            "study": {"lfdv": m.get("lfdv"), "worst_case": m.get("worst_case"), "age_min": m.get("age_min"),
                      "swarm": m.get("swarm"), "flags": m.get("risk_flags"), "risk": m.get("risk")},
            "organic": {"score": j.get("organic"), "label": j.get("organic_label")} if j else None,
            "deployer": {"launches": j.get("dev_mints"), "graduated": j.get("dev_grads"), "holds_pct": j.get("dev_pct"),
                         "wallet": (rc or {}).get("creator") or j.get("dev")} if j or rc else None,
            "exit": {"cost_pct": m.get("exit_cost"), "from_quote": m.get("exit_measured"), "usd": C.ORDER_USD,
                     "model_pct": SG.exit_cost_model(C.ORDER_USD, d.get("liq")),
                     "quoted_impact_pct": (r.get("exitq") or {}).get("impact_pct"), "venues": (r.get("exitq") or {}).get("venues")},
            "quality": r.get("mq"),
            "rc_score": (rc or {}).get("score"), "rc_risks": (rc or {}).get("risks"),
            "x": {"handle": tw, "shared_with": len(shared)}, "tg": r["tg"],
            "website": j.get("website") or (gt or {}).get("website"),
            "momentum": r["momentum"], "gates": [pack(g) for g in r["gates"]],
            "spark": spark(st.snaps(t["mint"], now - 24 * H), now),
            "dex": d.get("dex"), "pair": d.get("pair"), "tracker": trk_by.get(t["mint"]),
        })
    toks.sort(key=lambda x: (-{"IN": 3, "WATCH": 3, "ENTERING": 2, "OUT": 1}[x["state"]], -(x["mcap"] or 0)))
    trans = [{"ts": r["ts"], "mint": r["mint"], "symbol": r["symbol"], "from": r["frm"], "to": r["to_"], "reasons": json.loads(r["reasons"])}
             for r in st.recent_transitions(80)]
    counts = {b[0]: sum(1 for x in toks if x["band"] == b[0] and x["state"] in ("IN", "WATCH")) for b in C.BANDS}
    for x in trk_rows:
        x.pop("entry", None)                       # entry features go to the CSV, not the page
    cfg_keys = ("MIN_MCAP", "MAX_MCAP", "MIN_VOL24", "MIN_LIQ_USD", "MIN_LIQ_PCT_MCAP", "MAX_VOL_TO_MCAP", "MAX_TOP10_PCT",
                "MAX_CREATOR_PCT", "MAX_LINKED_HOLDER_SHARE", "MAX_SAME_SIZE_HOLDERS", "MIN_LP_LOCKED_PCT", "DEV_SELL_DROP",
                "TOP_OUTFLOW_PCT_6H", "MAX_TG_BOT_RISK", "CRASH_LIMITS", "SCAN_MINUTES", "ENTER_SCANS", "EXIT_SCANS",
                "MAX_TRANSFER_FEE_PCT", "ORDER_USD", "MAX_EXIT_COST_PCT", "DEFAULT_FEE_PCT", "MIN_VOL1H", "MIN_TRADERS_1H",
                "OVEREXTENDED", "TRACK_DAYS", "OUTCOME_HOURS", "MIN_AGE_MIN", "MIN_SOLD_1H", "LFDV_RED", "LFDV_GREEN",
                "LFDV_THIN", "RISK_FLAGS", "RUG_RATE_BY_FLAGS", "DOUBLED_RATE_BY_FLAGS", "CALIBRATED_MAX_AGE_H",
                "CALIBRATED_MAX_FDV", "MAX_RISK_FLAGS", "HOLDER_GATES_FOR_LAUNCHPADS", "TRADES_BUDGET", "TSNAP_EVERY_MIN",
                "TSNAP_FULL_H", "SNAP_BUCKETS", "MAX_CLUSTER_PCT", "GATE_ON_CLUSTER", "GP_TTL_H", "LIVE_URL")
    lab, lab_rows = lab_report(st)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    symbols = st.symbols()
    write_obs_csv(os.path.join(out_dir, "observations.csv"), lab_rows, symbols)
    n_ts = write_snapshot_files(out_dir, st, symbols)
    doc = {"generated_at": now, "lab": lab, "meta": {**meta, "counts_in_by_band": counts,
           "in": sum(1 for x in toks if x["state"] in ("IN", "WATCH")), "entering": sum(1 for x in toks if x["state"] == "ENTERING"),
           "out_listed": sum(1 for x in toks if x["state"] == "OUT"), "cadence_min": C.SCAN_MINUTES, "snapshots": n_ts},
           "config": {k: getattr(C, k) for k in cfg_keys}, "slots": SLOTS,
           "bands": [b[0] for b in C.BANDS], "gate_meta": gate_meta, "tokens": toks, "tracker": trk_rows, "transitions": trans}
    with open(out_path, "w") as f:
        json.dump(clean(doc), f, separators=(",", ":"), allow_nan=False, default=lambda o: None)
    with open(os.path.join(out_dir, "version.json"), "w") as f:     # lets an open page spot a new scan cheaply
        json.dump({"generated_at": now, "in": doc["meta"]["in"], "tracked": len(trk_rows), "snapshots": n_ts}, f)
    log(f"wrote {out_path}: {doc['meta']['in']} in, {doc['meta']['entering']} entering, {doc['meta']['out_listed']} listed out, {len(trk_rows)} tracked")
    return doc


def clean(o):
    """json has no NaN; swap any float nan/inf for None before dumping."""
    if isinstance(o, float) and (o != o or o in (float("inf"), float("-inf"))):
        return None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o


def backfill(st):
    """Start trackers for tokens that entered before the tracker existed."""
    for mint, ts, price, mcap, n in st.first_entry_backfill():
        st.set_cols(mint, trk_json=json.dumps(TR.start(ts, price, mcap)), entries_n=n)
    st.commit()


def run(args):
    t0 = time.time(); now = t0
    if getattr(args, "cadence", None):
        C.SCAN_MINUTES = args.cadence          # shown on the page: how often the scheduler runs this scan
    st = Store(args.db)
    backfill(st)
    jcache = {}
    if not args.no_discovery:
        discover(st, now, jcache)
    toks = st.universe(now - C.UNIVERSE_TTL_DAYS * 86400)
    log(f"universe: {len(toks)} tokens")
    ds_all = S.ds_tokens([t["mint"] for t in toks])
    log(f"dexscreener: {len(ds_all)} priced")
    n_up = update_outcomes(st, ds_all, now)
    sol = S.ds_tokens([C.SOL_MINT]).get(C.SOL_MINT) or {}
    rows, handles, events, status = process(st, now, toks, args.max_enrich, ds_all, jcache)
    n_obs = observe(st, rows, now, {"sol24": (sol.get("chg") or {}).get("h24")})
    log(f"lab: {n_obs} observations recorded, {n_up} open ones updated")
    snapshot_tracked(st, rows, ds_all, jcache, now)
    st.prune(now - C.SNAP_KEEP_H * H, now - C.TG_KEEP_DAYS * 86400); st.commit()
    meta = {"universe": len(toks), "priced": len(ds_all), "candidates": len(rows), "seconds": round(time.time() - t0),
            "sources": ["GeckoTerminal", "DEX Screener", "Jupiter", "Solana RPC", "RugCheck", "Telegram public pages"],
            "source_status": status}
    doc = export(st, rows, handles, now, meta, args.out)
    write_csv(os.path.join(os.path.dirname(os.path.abspath(args.out)), "tracker.csv"), tracker_rows(st, rows, now))
    st.close()
    notify.send(events)
    return doc


def inspect(args):
    now = time.time(); st = Store(args.db)
    st.upsert_seen({"mint": args.mint, "pool": "", "dex": "", "name": None}, now); st.commit()
    ds_all = S.ds_tokens([args.mint])
    t = st.get(args.mint)
    rows, _, _, _ = process(st, now, [t], 5, ds_all, {})
    if not rows:
        print("not priced on DEX Screener, out of range, on a bonding curve or out of scope"); return
    r = rows[0]
    m = r["m"]
    print(f'{r["d"].get("symbol")}  mcap {r["d"].get("mcap"):,.0f}  band {G.band_of(r["d"].get("mcap") or 0)}  '
          f'launchpad {m.get("launchpad")}  L/FDV {fmt(m.get("lfdv"))}  risk flags {(m.get("risk") or {}).get("count")}  quality {r["mq"]["label"]}')
    for g in r["gates"]:
        kind = "HARD" if g["hard"] else ("info" if g["info"] else "soft")
        print(f'  {"PASS" if g["ok"] else "FAIL"}  {kind}  {g["group"]:<9} {g["label"]:<26} {str(g["value"])[:18]:<18} {g["rule"]}')
    if r["tg"]:
        print("  telegram:", r["tg"])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("run"); a.add_argument("--db", default="undertow.db"); a.add_argument("--out", default="data.json")
    a.add_argument("--max-enrich", type=int, default=80); a.add_argument("--no-discovery", action="store_true")
    a.add_argument("--cadence", type=int, default=None, help="minutes between scheduled runs, shown on the page")
    b = sub.add_parser("inspect"); b.add_argument("mint"); b.add_argument("--db", default="undertow.db")
    args = ap.parse_args()
    run(args) if args.cmd == "run" else inspect(args)
