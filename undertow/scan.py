"""Orchestrator: discover -> refresh -> enrich -> gate -> track -> momentum -> export.
Run:  python3 -m undertow.scan run --db undertow.db --out docs/data.json
      python3 -m undertow.scan inspect <MINT>"""
import argparse, csv, json, os, sys, time
from collections import defaultdict
from . import config as C, sources as S, gates as G, momentum as M, tgrisk, signals as SG, tracker as TR, notify, http, lab as LAB
from . import review as REV, community as COM, trade as TRD, attention as ATT, corr as CORR, minute as MIN, fast as FAST
from .store import Store, TSNAP_VARS, PATH_STATE
try:                                  # the Models tab needs numpy and the ML libraries (requirements-ml.txt)
    from . import models as MOD
except ImportError:
    MOD = None
MODELS_DIR = os.environ.get("UNDERTOW_MODELS", "state/models")

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
    """Jupiter's category lists (every launchpad and DEX, 100 tokens each) and GeckoTerminal's trending pools every
    run; GeckoTerminal's per-DEX pool lists hourly. Everything seen is kept for UNIVERSE_TTL_DAYS, so the universe
    builds up across runs. Returns the trending lists in rank order, for the attention variables."""
    seen, calls, lists = {}, 0, {}
    for path in C.JUP_LISTS:
        got = S.jup_list(path)
        for j in got:
            jcache[j["mint"]] = j
            seen.setdefault(j["mint"], {"mint": j["mint"], "pool": "", "dex": "", "name": j.get("symbol")})
        if path in ("toptrending/1h", "toptrending/6h") and got:
            lists["jup" + path.split("/")[1]] = [j["mint"] for j in got]
        calls += 1
    for dur, key in (("1h", "gt1h"), ("5m", "gt5m")):
        ranked = S.gt_trending(dur, C.ATTN["gt_pages_" + dur])
        calls += C.ATTN["gt_pages_" + dur]
        if ranked:
            lists[key] = ranked
            for m in ranked:
                seen.setdefault(m, {"mint": m, "pool": "", "dex": "", "name": None})
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
    log(f"discovery: {len(seen)} tokens ({n_jup} from Jupiter and GeckoTerminal's trending lists) from {calls} calls; "
        f"trending lists: {', '.join(f'{k} {len(v)}' for k, v in lists.items()) or 'none'}")
    return seen, lists


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


def age_h(m):
    return m["age_min"] / 60 if m.get("age_min") is not None else None


def x_handle(j, gt, d):
    return (handle_from_url((j or {}).get("twitter")) or handle_from_url((gt or {}).get("twitter"))
            or handle_from_url((d or {}).get("twitter_url")))


def site_of(j, gt, d):
    return (j or {}).get("website") or (gt or {}).get("website") or (d or {}).get("website_url")


def fetch_attention(st, want, ds_all, jup, now):
    """DEX Screener orders, X followers and website domain age for coins inside the screener or close to passing,
    each within its per-run budget, coins inside first. The three sources run in parallel threads, so their waits
    between calls overlap instead of adding up. Stores what came back in each coin's attention record."""
    from concurrent.futures import ThreadPoolExecutor
    A = C.ATTN
    recs = {t["mint"]: (json.loads(t["attn_json"]) if t.get("attn_json") else {}) for t in want}
    order = sorted(want, key=lambda t: (t["status"] != "IN", t["mint"]))
    q_ord = [t["mint"] for t in order if ATT.due(recs[t["mint"]].get("orders"), now, A["orders_ttl_h"])][:A["orders_budget"]]
    by_handle, by_domain, changed = {}, {}, set()
    for t in order:
        m = t["mint"]
        gt = json.loads(t["gt_json"]) if t.get("gt_json") else None
        j, d = jup.get(m), ds_all.get(m)
        h = x_handle(j, gt, d)
        xr = recs[m].get("x")
        ttl = A["x_ttl_h_in"] if t["status"] == "IN" else A["x_ttl_h"]
        if h and (not xr or xr.get("handle") != h or ATT.due(xr, now, ttl)):
            by_handle.setdefault(h, []).append(m)
        dom = S.domain_of(site_of(j, gt, d))
        w = recs[m].get("web") or {}
        retry = not w.get("free") and not w.get("reg") and now - (w.get("ts") or 0) >= A["web_retry_days"] * 86400
        if dom and (w.get("domain") != dom or retry):
            if dom in ATT.FREE_HOSTS:
                recs[m]["web"] = {"domain": dom, "free": 1, "ts": now}
                changed.add(m)
            else:
                by_domain.setdefault(dom, []).append(m)
    q_x, q_web = list(by_handle)[:A["x_budget"]], list(by_domain)[:A["web_budget"]]

    def loop(host, items, fn):
        out = {}
        for k in items:
            if http.down(host):
                break
            out[k] = fn(k)
        return out
    with ThreadPoolExecutor(3) as ex:
        jobs = [ex.submit(loop, "dexscreener", q_ord, S.ds_orders), ex.submit(loop, "fxtwitter", q_x, S.x_profile),
                ex.submit(loop, "rdap", q_web, S.domain_registered)]
        got_o, got_x, got_w = (f.result() for f in jobs)
    for m, o in got_o.items():
        recs[m]["orders"] = {**o, "ts": now} if o is not None else {"ts": now, "fail": 1}
        changed.add(m)
    for h, res in got_x.items():
        for m in by_handle[h]:
            recs[m]["x"] = ATT.add_x(recs[m].get("x"), h, res, now)
            changed.add(m)
    for dom, reg in got_w.items():
        for m in by_domain[dom]:
            recs[m]["web"] = {"domain": dom, "free": 0, "reg": reg, "ts": now}
            changed.add(m)
    for t in want:
        if t["mint"] in changed:
            t["attn_json"] = json.dumps(recs[t["mint"]], separators=(",", ":"))
            st.set_cols(t["mint"], attn_json=t["attn_json"])
    return {"orders": len(got_o), "orders_ok": sum(1 for v in got_o.values() if v is not None), "x": len(got_x),
            "x_ok": sum(1 for v in got_x.values() if v), "web": len(got_w), "web_ok": sum(1 for v in got_w.values() if v)}


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
def gate_features(m, d, j, tg=None):
    """The Lab variables that exist when the gates run, for rules the weekly review promoted to gates."""
    return LAB.features(d, m, j, None, None, tg, None)


def process(st, now, toks, budget, ds_all, jcache, policy=None, crowd=None, lists=None):
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
                    gp=json.loads(t["gp_json"]) if t.get("gp_json") else None,
                    attn=json.loads(t["attn_json"]) if t.get("attn_json") else {})

    # B. first pass: which tokens are worth the expensive checks (exit quote, trade list)?
    pre = {}
    for t in cands:
        c = ctx(t)
        hist = history_metrics(st, t["mint"], now, c["rc"])
        m = build_metrics(c["d"], c["rc"], hist, c["j"], c["exitq"], c["rpc"], c["lock"], None, rc_down, now, c["gp"])
        m["crowd"] = (crowd or {}).get(t["mint"])
        m["attn"] = ATT.features(c["attn"], now, t["mint"], c["d"], lists, age_h=age_h(m))
        m["_f"] = gate_features(m, c["d"], c["j"])
        gates = G.evaluate(m, t["status"] == "IN", policy)
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
    na = fetch_attention(st, want, ds_all, jup, now)
    st.commit()
    log(f"exit quotes: {n_q}, GoPlus checks: {n_gp}, trade lists: {len(trades)} of {len(young)} young coins near the gates")
    log(f"attention: DEX Screener orders {na['orders_ok']} of {na['orders']}, X followers {na['x_ok']} of {na['x']} "
        f"handles, website domains {na['web_ok']} of {na['web']}")

    # D. final metrics, gates, Telegram, state machine
    rows, handles = [], {}
    for t in cands:
        mint = t["mint"]
        c = ctx(t)
        d, rc, gt, j = c["d"], c["rc"], c["gt"], c["j"]
        hist = pre[mint][1]
        was_in = t["status"] == "IN"
        m = build_metrics(d, rc, hist, j, c["exitq"], c["rpc"], c["lock"], trades.get(mint), rc_down, now, c["gp"])
        m["crowd"] = (crowd or {}).get(mint)
        m["attn"] = ATT.features(c["attn"], now, mint, d, lists, age_h=age_h(m))
        m["_f"] = gate_features(m, d, j)
        gates = G.evaluate(m, was_in, policy)

        tw = x_handle(j, gt, d)
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
                       "growth_h": tgrisk.growth_per_hour(hist_tg), "kind": cnt["kind"],
                       "growth_6h": tgrisk.growth_per_hour([p for p in hist_tg if p[0] >= now - 6 * H])}
                m["attn"] = ATT.features(c["attn"], now, mint, d, lists, tgd, age_h(m))
                m["_f"] = gate_features(m, d, j, tgd)
                gates = G.evaluate(m, was_in, policy)
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
        # attention's hourly history (boosts and trending ranks), which spikes are measured against
        arec, grew = ATT.add_hourly(c["attn"], now, m["attn"])
        if grew:
            t["attn_json"] = json.dumps(arec, separators=(",", ":"))
            st.set_cols(mint, attn_json=t["attn_json"])

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
            "tg_growth": (tgd or {}).get("growth_h"), "attn": ATT.for_page(arec, m["attn"]),
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


def regime_of(rows, sol24):
    """Market-wide numbers every observation carries: SOL's 24h change and the share of candidates rising over 1h."""
    rising = [r for r in rows if (r["d"].get("chg") or {}).get("h1") is not None]
    return {"sol24": sol24, "mkt1h": sum(1 for r in rising if r["d"]["chg"]["h1"] > 0) / len(rising) if rising else None}


def observe(st, rows, now, regime):
    """Record observations for the Lab: every entry and exit as it happens, and, checking every candidate once an
    hour, the observations the Lab reads: a token's first of each day, and its first that day that passed every gate."""
    last = st.get_meta("last_obs")
    hourly = not last or now - float(last) >= C.OBS_EVERY_MIN * 60 - 120
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
        rules = LAB.rule_results(f, C.SHADOW_RULES)
        # every gate's own result, gating or not, so the weekly review can judge each gate (and a dropped one) later
        rules.update({"g:" + g["id"]: int(bool(g["ok"])) for g in r["gates"] if g["value"] is not None})
        st.add_obs(now, r["t"]["mint"], ev, state, not fails, fails, r["d"]["price"], f, rules)
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
            "website": site_of(j, gt, d), "attn": r.get("attn"),
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
                "TSNAP_FULL_H", "SNAP_BUCKETS", "MAX_CLUSTER_PCT", "GATE_ON_CLUSTER", "GP_TTL_H", "LIVE_URL", "REVIEW",
                "SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_X_LOGIN", "CALL_BASE_RATE", "ATTN", "CORR", "MODELS")
    lab, lab_rows = lab_report(st)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    symbols = st.symbols()
    write_obs_csv(os.path.join(out_dir, "observations.csv"), lab_rows, symbols)
    n_ts = write_snapshot_files(out_dir, st, symbols)
    review, trade = meta.pop("review", None), meta.pop("trade", None)
    models, corr = meta.pop("models", None), meta.pop("corr", None)
    doc = {"generated_at": now, "published_at": time.time(), "lab": lab, "review": review, "trade": trade, "models": models,
           "corr": corr, "meta": {**meta, "counts_in_by_band": counts,
           "in": sum(1 for x in toks if x["state"] in ("IN", "WATCH")), "entering": sum(1 for x in toks if x["state"] == "ENTERING"),
           "out_listed": sum(1 for x in toks if x["state"] == "OUT"), "cadence_min": C.SCAN_MINUTES, "snapshots": n_ts},
           "config": {k: getattr(C, k) for k in cfg_keys}, "slots": SLOTS,
           "bands": [b[0] for b in C.BANDS], "gate_meta": gate_meta, "tokens": toks, "tracker": trk_rows, "transitions": trans}
    with open(out_path, "w") as f:
        json.dump(clean(doc), f, separators=(",", ":"), allow_nan=False, default=lambda o: None)
    with open(os.path.join(out_dir, "version.json"), "w") as f:     # lets an open page spot a new scan cheaply
        json.dump({"generated_at": now, "published_at": doc["published_at"], "in": doc["meta"]["in"], "tracked": len(trk_rows),
                   "snapshots": n_ts}, f)
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


def gate_meta(rows):
    """Every gate this run computed: label, group, hard, and whether it is shown-only for every token (info)."""
    meta = {}
    for r in rows:
        for g in r["gates"]:
            if g["id"].startswith("lab:"):
                continue
            e = meta.setdefault(g["id"], {"label": g["label"], "group": g["group"], "hard": g["hard"], "info": True})
            if not g["info"]:
                e["info"] = False
    return meta


ATTN_SOURCE = "attention, added when its data started"


def candidate_pool():
    """Rules waiting to be tested, in order: the Lab's shadow rules first, then attention's, then the queued pool."""
    return ([{"id": r[0], "label": r[1], "key": r[2], "op": r[3], "at": r[4], "source": "Lab shadow rule"} for r in C.SHADOW_RULES]
            + [{"id": r[0], "label": r[1], "key": r[2], "op": r[3], "at": r[4], "source": ATTN_SOURCE} for r in C.ATTENTION_CANDIDATES]
            + [{"id": r[0], "label": r[1], "key": r[2], "op": r[3], "at": r[4], "source": "pool"} for r in C.CANDIDATE_POOL])


def add_attention_candidates(st, policy, now):
    """Attention's candidate gates join the gate review's bench at once, outside the weekly intake, so their record
    starts with the data; the next review judges them like every other candidate. Returns the policy."""
    if not policy:
        return policy
    have = {c["id"] for c in policy.get("candidates") or []}
    new = []
    for r in C.ATTENTION_CANDIDATES:
        if r[0] in have:
            continue
        c = {"id": r[0], "label": r[1], "key": r[2], "op": r[3], "at": r[4], "status": "testing", "added": now,
             "since": now, "source": ATTN_SOURCE}
        policy.setdefault("candidates", []).append(c)
        new.append({"ts": now, "what": "testing", "id": c["id"], "label": c["label"],
                    "reason": f"Added for testing on {REV._day(now)} ({ATTN_SOURCE})."})
    if new:
        policy["log"] = ((policy.get("log") or []) + new)[-200:]
        st.set_meta("policy", json.dumps(policy))
        st.commit()
        log(f"gate review: {len(new)} attention candidates put on the bench")
    return policy


def weekly_review(st, rows, now, policy):
    """Run the gate review when it is due (every REVIEW['every_days']); store the policy the gates read next run."""
    gmeta = gate_meta(rows)
    if not rows or not REV.due(policy, now, C.REVIEW):
        return policy, gmeta, []
    lab_rows = st.lab_rows()
    passing = sorted(LAB.populations(lab_rows)["passing"], key=lambda r: r["ts"])
    lab_vars = [LAB.analyse_variable(passing, k, "p24", C.LAB) for k in LAB.VAR_KEYS]
    # gates shown-only by design (not dropped) are tested as candidate rules instead
    judged = {g: m for g, m in gmeta.items()
              if not m["info"] or ((policy or {}).get("gates", {}).get(g) or {}).get("status") == "shown"}
    policy, changes = REV.run_review(lab_rows, policy, judged, now, C.REVIEW, candidate_pool(), lab_vars,
                                     set(LAB.VAR_KEYS) - C.NOT_GATEABLE, C.PINNED_GATES)
    st.set_meta("policy", json.dumps(policy)); st.commit()
    log(f"weekly review: {len(changes)} changes; next review {time.strftime('%d %b', time.gmtime(policy['next_review']))}")
    return policy, gmeta, changes


def base_rug_rate(st, now, days=14):
    """Share of coins that passed every gate and rugged within a day, over the last fortnight: the base rate that
    scores rug calls (None until enough have settled)."""
    rows = [r for r in st.lab_rows() if r["ts"] >= now - days * 86400]
    rg = [g for g in (LAB.rugged(r) for r in LAB.populations(rows)["passing"]) if g is not None]
    return sum(rg) / len(rg) if len(rg) >= 50 else None


# ------------------------------------------------------------------ buy and sell signals (see trade.py)
def trade_features(st, r, now, regime):
    """The variables entry rules read for one candidate: the Lab's, plus the short-term shape of its price from this
    scanner's own readings over the last day."""
    d = r["d"]
    hist = [(s["ts"], s["price"]) for s in st.snaps(r["t"]["mint"], now - 24 * H) if s["price"]]
    top = max([p for _, p in hist] + [d["price"]])
    lab_f = LAB.features(d, r["m"], r.get("jup"), r.get("mq"), r.get("momentum"), r.get("tg"),
                         {**regime, "dd24s": d["price"] / top - 1 if top else None})
    return TRD.decision_features(lab_f, TRD.path_features(hist, now, d["price"]))


def path_code(r):
    if any(g["hard"] for g in G.blocking(r["gates"])):
        return "X"
    return PATH_STATE.get(row_state(r), "O")


def seed_tpath(st, now):
    """Once, when the ledger starts: rebuild the path from the per-scan snapshots still kept (about a day and a half),
    with each coin's screener state from its transitions, so the first review has something to backtest on. Only the
    variables a snapshot holds are filled; rules on the others cannot fire on the seeded rows."""
    if st.get_meta("tpath_seeded") or st.tpath_stats()["rows"]:
        return 0
    trans = defaultdict(list)
    for r in st.db.execute("SELECT ts, mint, to_ FROM transitions ORDER BY ts"):
        trans[r["mint"]].append((r["ts"], r["to_"]))
    snaps = defaultdict(list)
    for r in st.db.execute("SELECT mint, ts, price, mcap, liq, vol24, vol1, chg1, chg6, chg24, buys1, sells1 FROM snaps "
                           "WHERE price IS NOT NULL AND ts<? ORDER BY mint, ts", (now - 60,)):
        snaps[r["mint"]].append(dict(r))
    rows = []
    for mint, ss in snaps.items():
        tr, k, state = trans.get(mint, []), 0, None
        for i, s in enumerate(ss):
            while k < len(tr) and tr[k][0] <= s["ts"] + 1:
                state, k = tr[k][1], k + 1
            code = "I" if state == "IN" else "O"
            f = None
            if code == "I":
                hist = [(x["ts"], x["price"]) for x in ss[:i] if x["ts"] >= s["ts"] - 24 * H]
                top = max([p for _, p in hist] + [s["price"]])
                mc, liq, v24 = s["mcap"], s["liq"], s["vol24"]
                lab_f = {"c1h": s["chg1"], "c6h": s["chg6"], "c24h": s["chg24"], "v1h": s["vol1"], "v24h": v24, "mc": mc, "liq": liq,
                         "liq_pct": liq / mc if liq and mc else None, "turn": v24 / mc if v24 and mc else None,
                         "v1h_24": s["vol1"] * 24 / v24 if s["vol1"] is not None and v24 else None,
                         "bs1h": s["buys1"] / s["sells1"] if s["buys1"] is not None and s["sells1"] else None,
                         "dd24s": s["price"] / top - 1 if top else None}
                f = TRD.decision_features(lab_f, TRD.path_features(hist, s["ts"], s["price"]))
            rows.append((s["ts"], mint, code, s["price"], s["liq"], s["chg1"], f))
    st.add_tpath(rows)
    st.set_meta("tpath_seeded", now)
    st.commit()
    log(f"trade ledger: path seeded with {len(rows)} rows from the per-scan snapshots")
    return len(rows)


def exit_pool_of(bank):
    """The bench's exit policies: the configured ones plus one per trained exit model (models.py)."""
    return C.EXIT_POOL + (MOD.exit_policies(bank.summary) if MOD and bank and bank.summary else [])


def loaded_exits(exits, bank):
    """The exit-model policies whose models are loaded and fresh enough to call."""
    return {pid for pid in exits if pid.startswith("x:") and bank and bank.fresh and pid in bank.exit}


def scan_step(st, ds_all, now, exits, cfg):
    """The scan's own reading of prices steps every open paper trade, before the gates are worked out: a stop or a time
    limit reached since the last reading is acted on at once. What depends on the gates (a structure gate failing, an
    exit model's call) is acted on at decision time (trade_step). Returns (trades stepped, live trades it closed as
    [(trade, result)])."""
    if not ds_all:                             # a scan that priced nothing (DEX Screener down) steps no trade
        return 0, []
    n, closed = 0, []
    for s in st.open_sigs():
        d = ds_all.get(s["mint"])
        obs = ({"price": d["price"], "liq": d.get("liq"), "c1h": (d.get("chg") or {}).get("h1")}
               if d and d.get("price") else None)
        out, sst, miss, lp, ll, done = TRD.advance(s, obs, now, exits, cfg)
        ref_out = TRD.ref_closed(s, out, exits, now)
        if s["live"] and s.get("ref_out_ts") is None and ref_out is not None and s["ref"] in out:
            closed.append((s, out[s["ref"]]))
        st.update_sig(s["id"], out, sst, miss, lp, ll, done, ref_out)
        n += 1
    st.commit()
    return n, closed


def quick_start(exits, loaded_x):
    """The exit policies every new paper trade is followed under: all on the bench, exit models only when loaded."""
    return [pid for pid in exits if not pid.startswith("x:") or pid in loaded_x]


def quick_trade_exits(exits, live_exit):
    """The exit policies a quick trade is followed under: every quick exit (2 hours or less) and the live exit, the
    scans' benchmark. The longer ones would keep a stream of quick trades open for a day each."""
    return [pid for pid, e in exits.items() if e.get("max_h", 24) <= 2 and not e.get("model")] + (
        [live_exit] if live_exit in exits and exits[live_exit].get("max_h", 24) > 2 else [])


def start_minutes(st, now, ds_all, lists, exits, loaded_x):
    """Record the scan's reading of the watched coins as their minute at the scan, then start the minute sampler with
    the minute ledger (fast.py). Quick rules may buy only coins that passed every gate at the previous scan, whose
    gates were known throughout; a previous scan more than stale_scan_min minutes old lets nothing be bought."""
    fc = C.FAST
    watch = st.watch_list(now - fc["watch_recent_h"] * H)[:fc["max_coins"]]
    gt5 = lists.get("gt5m")
    scan_ticks = [t for t in (MIN.tick_of(ds_all.get(m), m, now, ATT.rank_score(gt5, m, 20) if gt5 is not None else None)
                              for m in watch) if t]
    st.add_ticks(scan_ticks)
    st.commit()
    prev_ts, eligible = st.scan_passing(now)
    if prev_ts is None or now - prev_ts > fc["stale_scan_min"] * 60:
        eligible = {}
    policy = json.loads(st.get_meta("trade_policy") or "null") or {}
    rules = policy.get("rules") or []
    book = FAST.Book(st.open_sigs(), exits, rules, eligible, st.fast_last([r["id"] for r in rules if r.get("fast")]),
                     st.live_open_mints(), MIN.Ads(st.feeds(now - 25 * H)),
                     {m: (ds_all.get(m) or {}).get("symbol") for m in watch}, C.TRADE, fc,
                     quick_trade_exits(exits, policy.get("exit") or C.DEFAULT_EXIT))
    book.warm(st.ticks(now - MIN.WINDOW, now))
    sampler = FAST.Sampler(watch, book, fc["every_s"], fc["slow_every"], fc["max_coins"],
                           send=lambda kind, sig, info: notify.minute(kind, sig, info, exits))
    sampler.eligible_from = prev_ts
    sampler.start()
    log(f"minute sampler: {len(watch)} coins watched, {len(scan_ticks)} priced at the scan; quick rules may buy "
        f"{len(eligible)} coins (passing every gate at the previous scan); {len(book.rules)} quick rules on the bench")
    return sampler


def finish_minutes(st, sampler, t_dec):
    """Stop the sampler and write what the minute ledger did: the readings, the feeds, every trade it stepped and every
    quick trade it opened. Returns a summary for the Buy & sell tab."""
    if sampler is None:
        return None
    sampler.stop()
    book = sampler.book
    st.add_ticks(sampler.ticks)
    st.add_feeds(sampler.feeds)
    n_new = 0
    if book is not None:
        for sigs in book.by_mint.values():
            for s in sigs:
                if s.get("id") is not None and s["id"] in book.changed:
                    st.update_sig(s["id"], s["out"], s["st"], s["miss"], s["last_price"], s["last_liq"], s["done"],
                                  s["ref_out_ts"])
        for s in book.new:
            s["id"] = st.insert_sig(s)
            n_new += 1
    st.commit()
    info = {"rounds": sampler.rounds, "errors": sampler.errors, "coins": len(sampler.mints), "ticks": len(sampler.ticks),
            "feeds": len(sampler.feeds), "gt_ok": sampler.gt_ok, "gt_tries": sampler.gt_tries,
            "from": sampler.started, "to": sampler.stopped, "eligible": len(book.eligible) if book else 0,
            "eligible_from": getattr(sampler, "eligible_from", None),
            "steps": book.steps if book else 0, "closed": book.closed if book else 0, "opened": n_new}
    log(f"minute ledger: {sampler.rounds} rounds, {len(sampler.ticks)} readings of {len(sampler.mints)} coins"
        f" ({sampler.errors} failed rounds), GeckoTerminal 5-min trending {sampler.gt_ok} of {sampler.gt_tries}; "
        f"{info['steps']} trade steps, {info['closed']} closed, {n_new} quick trades opened")
    return info


def scan_minute_features(st, mints, by, now):
    """The short-window variables at the scan for the given coins: their minutes from the hour before, ending with the
    scan's own reading (stored at the scan, or read from the scan's record when the coin is not watched)."""
    mints = list(mints)
    if not mints:
        return {}
    hist = defaultdict(list)
    for t in st.ticks(now - MIN.WINDOW, now, mints):
        hist[t["mint"]].append(t)
    ads = MIN.Ads(st.feeds(now - 25 * H))
    out = {}
    for m in mints:
        rows = hist.get(m) or []
        cur = rows[-1] if rows and abs(rows[-1]["ts"] - now) < 1 else MIN.tick_of(by[m]["d"], m, now)
        if not cur:
            continue
        coin = MIN.Coin()
        for t in rows:
            if t is not cur:
                coin.add(t)
        coin.add(cur)
        out[m] = {k: v for k, v in MIN.features(coin, cur, ads.at(m, now)).items() if k in MIN.KEYS}
    return out


def trade_step(st, rows, ds_all, now, regime, bank=None, sampler=None, t_dec=None):
    """The paper ledger at decision time, once the gates are known: write what the minute ledger did since the scan's
    price reading (finish_minutes), record the path, act on the scan's decisions about open trades (a structure gate
    failed; an exit model says sell) at the latest price, run the weekly review when due, then let the bench's rules
    and the entry models buy coins that pass every gate. Returns (policy, features by coin, changes, model picks
    {model: {mint: score}}, exit-model sells {(sig, policy)}, the minute layer's summary, live trades closed at
    decision time). t_dec: when the gates became known (the scan's own time when not given)."""
    cfg = C.TRADE
    exit_pool = exit_pool_of(bank)
    exits = {e["id"]: e for e in exit_pool}
    loaded_x = loaded_exits(exits, bank)
    t_dec = max(now, t_dec or now)
    try:
        minute = finish_minutes(st, sampler, t_dec)
    except Exception as e:                     # the minute layer must never stop a scan
        log(f"minute ledger: not written ({type(e).__name__}: {e})")
        minute = None
        if sampler is not None:
            sampler.stop()
    policy = json.loads(st.get_meta("trade_policy") or "null")
    seed_tpath(st, now)
    by = {r["t"]["mint"]: r for r in rows}
    open_sigs = st.open_sigs()
    follow = st.tpath_recent(now - cfg["follow_h"] * H) | {s["mint"] for s in open_sigs}
    feats, path = {}, []
    for mint, r in by.items():
        code, d = path_code(r), r["d"]
        if code not in ("I", "W") and mint not in follow:
            continue
        f = trade_features(st, r, now, regime) if code == "I" and d.get("price") else None
        if f:
            feats[mint] = f
        path.append([now, mint, code, d.get("price"), d.get("liq"), (d.get("chg") or {}).get("h1"), f])
    try:
        mfeat = scan_minute_features(st, feats, by, now)
    except Exception as e:
        log(f"minute variables at the scan: skipped ({type(e).__name__}: {e})")
        mfeat = {}
    for mint, mf in mfeat.items():
        feats[mint].update({k: LAB._r(v) for k, v in mf.items()})
    for mint in follow - set(by):              # left the candidates: followed on price alone
        d = ds_all.get(mint)
        if d and d.get("price"):
            path.append([now, mint, "G", d["price"], d.get("liq"), (d.get("chg") or {}).get("h1"), None])
    st.add_tpath([tuple(p) for p in path])

    # the scan's decisions about open trades, acted on now at each trade's latest price: a structure gate failed this
    # scan, or an exit model says selling now beats holding (for every open trade still undecided under its policy)
    hard = {p[1] for p in path if p[2] == "X"}
    sells = set()
    if loaded_x and ds_all:
        items = []
        for s in open_sigs:
            if not s.get("last_price"):
                continue
            c1h = ((ds_all.get(s["mint"]) or {}).get("chg") or {}).get("h1")
            for pid, pst in (s["st"] or {}).items():
                if pid in loaded_x:
                    state = MOD.trade_state(s["in_ts"], s["in_price"], s["in_liq"], (pst or {}).get("peak"),
                                            s["last_price"], s.get("last_liq"), t_dec)
                    items.append((s["id"], pid, MOD.exit_row(feats.get(s["mint"]), c1h, state)))
        _probs, sells = bank.exit_calls(items, C.MODELS["exit_thr"])
    sell_by = defaultdict(dict)
    for sid, pid in sells:
        sell_by[sid][pid] = True
    closed_dec = []
    for s in open_sigs:
        if s["mint"] not in hard and s["id"] not in sell_by:
            continue
        obs = {"price": s.get("last_price") or s["in_price"], "liq": s.get("last_liq"), "c1h": None,
               "hard": s["mint"] in hard, "xm": sell_by.get(s["id"], {})}
        out, sst, miss, lp, ll, done = TRD.advance(s, obs, t_dec, exits, cfg, tick=True)
        ref_out = TRD.ref_closed(s, out, exits, t_dec)
        if s["live"] and s.get("ref_out_ts") is None and ref_out is not None and s["ref"] in out:
            closed_dec.append((s, out[s["ref"]]))
        st.update_sig(s["id"], out, sst, s.get("miss") or 0, lp, ll, done, ref_out)

    changes = []
    if TRD.due(policy, now, cfg):
        fwd = defaultdict(list)
        for s in st.sigs():
            fwd[s["rule"]].append({"mint": s["mint"], "in_ts": s["in_ts"], "live": s["live"],
                                   "out": {pid: o[0] for pid, o in (s["out"] or {}).items()}})
        policy, changes = TRD.run_review(policy, st.tpath(now - cfg["path_days"] * 86400), fwd, now, cfg,
                                         C.ENTRY_POOL, exit_pool, C.DEFAULT_EXIT, C.SELL_WARNINGS)
        st.set_meta("trade_policy", json.dumps(policy))
        log(f"trade review: {len(changes)} changes; live exit {policy['exit']}; "
            f"{sum(1 for x in policy['rules'] if x['status'] == 'live')} live rules")

    picks, opened = {}, 0
    if policy:
        # rules on new data (attention, the minute data) and the models' rules join the bench at once (trade.add_rules)
        added = TRD.add_rules(policy, C.ATTENTION_RULES, now, ATTN_SOURCE)
        added += TRD.add_rules(policy, [r for r in C.FAST_RULES if r["exit"] in exits], now, "quick rule, minute data")
        if MOD and bank and (bank.summary or {}).get("status") == "ok":
            added += TRD.add_rules(policy, MOD.rules_for(bank.summary), now, "model")
        if added:
            changes = changes + added
            st.set_meta("trade_policy", json.dumps(policy))
            log(f"trade bench: {len(added)} rules added for testing")
        if bank and bank.fresh and feats:
            recent = st.tpath(now - (C.MODELS["seq_steps"] + 2) * 1800)      # the LSTM reads each coin's last scans
            seqs = {m: (recent[m], len(recent[m]) - 1) for m in feats if m in recent}
            picks = bank.fired(bank.entry_scores(feats, seqs), feats, now, C.MODELS["top_share"])
        start_all = quick_start(exits, loaded_x)
        start_model = sorted({policy["exit"] if policy["exit"] in exits else C.DEFAULT_EXIT} | loaded_x)
        busy, held = st.busy_rules(now, cfg["reentry_h"]), st.live_open_mints()
        for mint, f in feats.items():
            d = by[mint]["d"]
            for rule in policy["rules"]:
                if rule["status"] not in ("testing", "live") or rule.get("fast") or (rule["id"], mint) in busy:
                    continue
                mid = rule.get("model")
                if (mint not in picks.get(mid, {})) if mid else not TRD.fires(rule, f):
                    continue
                live = rule["status"] == "live" and mint not in held
                keep = {k: f.get(k) for k in TRD.SHOWN_AT_ENTRY + [c[0] for c in rule["all"]] if f.get(k) is not None}
                if mid:                        # what the model saw: its score, its threshold, when it was trained
                    meta = (bank.entry.get(mid) or ({},))[0]
                    keep.update(sc=LAB._r(picks[mid][mint]), thr=LAB._r(meta.get("thr")), mv=round(bank.summary["trained_at"]))
                st.add_sig(rule["id"], mint, d.get("symbol") or by[mint]["t"]["symbol"], now, d["price"], d.get("liq"),
                           d.get("mcap"), keep, policy["exit"], live, TRD.start_states(d["price"], start_model if mid else start_all))
                opened += 1
                if live:
                    held.add(mint)
    st.prune_tpath(now - cfg["path_days"] * 86400)
    st.prune_sigs(now - cfg["keep_days"] * 86400, now - C.MODELS["keep_trade_days"] * 86400)
    st.prune_ticks(now - C.FAST["keep_h"] * H, now - C.FAST["feed_keep_days"] * 86400)
    st.commit()
    log(f"trade ledger: {len(path)} path rows, {len(open_sigs)} open paper trades, {len(hard & {s['mint'] for s in open_sigs})} "
        f"coins failing a structure gate, {opened} opened at the scan"
        + (f"; models: {sum(len(v) for v in picks.values())} picks from {len(picks)} models, {len(sells)} exit-model sells"
           if bank and bank.fresh else ""))
    return policy, feats, changes, picks, sells, minute, closed_dec


def trade_page(st, policy, feats, rows, now, exit_pool=None, picks=None, sigs=None, minute=None):
    """What the Buy & sell tab shows. Open trades carry their exit levels so the page can flag a sell between scans."""
    if not policy:
        return None
    cfg, exit_pool, picks = C.TRADE, exit_pool or C.EXIT_POOL, picks or {}
    exits = {e["id"]: e for e in exit_pool}
    if policy["exit"] not in exits:            # a live exit model whose models are missing this scan
        policy = {**policy, "exit": C.DEFAULT_EXIT}
    by = {r["t"]["mint"]: r for r in rows}
    sigs = sigs if sigs is not None else st.sigs(now - cfg["window_days"] * 86400)
    live_ids = [r["id"] for r in policy["rules"] if r["status"] == "live"]
    rules = {r["id"]: r for r in policy["rules"]}

    def trade_row(s):
        ref = exits.get(s["ref"]) or exits[policy["exit"]]
        o = (s["out"] or {}).get(s["ref"])
        peak = ((s["st"] or {}).get(s["ref"]) or {}).get("peak") or s["in_price"]
        row = {"id": s["id"], "mint": s["mint"], "sym": s["sym"], "rule": s["rule"], "in_ts": s["in_ts"],
               "in_price": s["in_price"], "in_mc": s["in_mc"], "in_liq": s["in_liq"], "exit": s["ref"], "f": s["f"]}
        if o:
            row.update(ret=o[0], h=o[1], why=o[2], out_ts=o[3], out_price=o[4])
        else:
            last = s.get("last_price") or s["in_price"]
            row.update(last_price=last, peak=peak, now_x=last / s["in_price"],
                       now_net=LAB._r(TRD.net_ret(last / s["in_price"], s["in_liq"], s.get("last_liq"), cfg)),
                       levels=TRD.levels(ref, s, peak))
        return row

    # a live trade whose exit policy has since left the bench cannot be valued any further; it drops off the page
    live = [trade_row(s) for s in sigs if s["live"] and (s["ref"] in exits or s["ref"] in (s["out"] or {}))]
    open_live = [x for x in live if "ret" not in x]
    closed_live = sorted([x for x in live if "ret" in x], key=lambda x: -x["out_ts"])
    # the record counts a trade once every trade opened at that time has had time to close (see trade.matured)
    rec = TRD.summarise([{"mint": x["mint"], "ret": x["ret"], "in_ts": x["in_ts"], "h": x["h"]} for x in closed_live
                         if TRD.matured(x["in_ts"], exits.get(x["exit"]) or exits[policy["exit"]], now)])

    # every rule's forward record under its own exit (quick rules) or the live exit, recomputed each scan so the page is
    # current between reviews
    fwd = defaultdict(list)
    n_open = defaultdict(int)
    live_exit = exits[policy["exit"]]
    own = {r["id"]: exits.get(r.get("exit")) or live_exit for r in policy["rules"]}
    for s in sigs:
        rx = own.get(s["rule"]) or live_exit
        o = (s["out"] or {}).get(rx["id"])
        if o and TRD.matured(s["in_ts"], rx, now):
            fwd[s["rule"]].append({"mint": s["mint"], "ret": o[0], "in_ts": s["in_ts"], "h": o[1]})
        if s["ref"] not in (s["out"] or {}):
            n_open[s["rule"]] += 1
    bench = []
    for r in policy["rules"]:
        since = r.get("since") if r["status"] == "live" else r.get("added")
        fs = TRD.summarise([t for t in fwd.get(r["id"], []) if t["in_ts"] >= (since or 0)])
        bench.append({k: r.get(k) for k in ("id", "label", "all", "status", "source", "added", "since", "reason", "last",
                                            "streak", "model", "fast", "exit", "random")}
                     | {"fwd_now": TRD._r(fs), "open": n_open.get(r["id"], 0)})

    # this scan: which coins each rule (or model) fires on, and how close the coins come to the rules that matter most;
    # quick rules buy on the minute data, not at the scan
    firing = defaultdict(list)
    for mint, f in feats.items():
        for r in policy["rules"]:
            if r["status"] in ("testing", "live") and not r.get("fast") and (TRD.fires(r, f) or mint in picks.get(r.get("model"), {})):
                firing[mint].append(r["id"])

    def score(b):        # the forward record once it has 10 matured trades, else the backtest (as the page ranks them)
        f, bt = b.get("fwd_now") or {}, (b.get("last") or {}).get("bt") or {}
        return f["mean"] if f.get("n", 0) >= 10 else (bt["mean"] if bt.get("n") else None)
    lead = [i for i in live_ids if not rules[i].get("fast")] or [
        b["id"] for b in sorted((b for b in bench if b["status"] == "testing" and not b.get("model") and not b.get("fast")
                                 and score(b) is not None), key=lambda b: -score(b))[:3]]
    near = []
    for mint, f in feats.items():
        for rid in lead:
            miss = TRD.unmet(rules[rid], f)
            if len(miss) == 1:
                near.append({"mint": mint, "rule": rid, "miss": [list(m) for m in miss]})
    signals = []
    for mint, ids in firing.items():
        d = by[mint]["d"]
        signals.append({"mint": mint, "sym": d.get("symbol") or by[mint]["t"]["symbol"], "price": d.get("price"),
                        "mc": d.get("mcap"), "liq": d.get("liq"), "rules": ids, "live": any(i in live_ids for i in ids),
                        "f": {k: feats[mint].get(k) for k in TRD.SHOWN_AT_ENTRY}})

    # sell-side warnings: states that were followed by falls, judged at each review on coins passing every gate
    warn = []
    wrec = {w["id"]: w for w in policy.get("warnings") or []}
    for mint, f in feats.items():
        hit = [w["id"] for w in C.SELL_WARNINGS if TRD.fires(w, f)]
        if hit:
            d = by[mint]["d"]
            warn.append({"mint": mint, "sym": d.get("symbol") or by[mint]["t"]["symbol"], "ids": hit,
                         "f": {k: f.get(k) for k in ("ru6", "dd6", "r15", "c1h", "c6h")}})

    # every exit policy on the same settled forward trades of the scans' rules (quick trades are compared apart)
    by_rule = defaultdict(list)
    for s in sigs:
        if s["out"]:
            by_rule[s["rule"]].append({"mint": s["mint"], "in_ts": s["in_ts"], "out": {p: o[0] for p, o in s["out"].items()}})
    entries = TRD.pooled({rid: by_rule.get(rid, []) for rid, r in rules.items() if not r.get("fast")})
    cmp_ = TRD.compare_exits(entries, policy["exit"], cfg, exits, now) if entries else {}
    ex = [{"id": e["id"], "label": TRD.exit_label(e), "live": e["id"] == policy["exit"], "now": cmp_.get(e["id"]),
           "last": (policy["exits"].get(e["id"]) or {}).get("last"), "reason": (policy["exits"].get(e["id"]) or {}).get("reason"),
           "streak": (policy["exits"].get(e["id"]) or {}).get("streak"), "model": e.get("model"),
           "params": {k: v for k, v in e.items() if k not in ("id", "label", "algo")}}
          for e in exit_pool]

    labels = {k: (l, u) for k, l, u in TRD.VARIABLES}
    variables = [{"key": k, "label": labels.get(k, (k, ""))[0], "unit": labels.get(k, (k, ""))[1], **v}
                 for k, v in (policy.get("vars") or {}).items()]
    return {"cfg": {k: cfg[k] for k in ("usd", "fee_pct", "reentry_h", "min_trades", "min_edge", "z", "promote_after",
                                        "retire_after", "every_days", "path_days", "switch_after", "switch_min_gain",
                                        "var_min_rho", "warn_gap")},
            "last_review": policy.get("last_review"), "next_review": policy.get("next_review"),
            "exit": {"id": policy["exit"], "label": TRD.exit_label(exits[policy["exit"]]),
                     "params": {k: v for k, v in exits[policy["exit"]].items() if k not in ("id", "label")}},
            "live_rules": live_ids, "signals": signals, "near": near[:40], "open": open_live, "closed": closed_live[:80],
            "record": TRD._r(rec), "bench": bench, "exits": ex, "vars": variables, "warnings": warn,
            "warning_rules": [{**w, "last": (wrec.get(w["id"]) or {}).get("last")} for w in C.SELL_WARNINGS],
            "log": list(reversed(policy.get("log") or []))[:40], "path": st.tpath_stats(),
            "study": C.TRADE_STUDY, "quick": quick_page(st, policy, bench, sigs, exits, by_rule, now, minute)}


def quick_page(st, policy, bench, sigs, exits, by_rule, now, minute):
    """The Buy & sell tab's quick trades: the minute data collected, the quick rules with their forward records under
    their own exits, every quick trade of the window, and every exit policy on the same quick entries against the
    baseline quick exit."""
    cfg = C.TRADE
    quick = {b["id"]: b for b in bench if b.get("fast")}
    if not quick and not minute:
        return None
    trades = []
    for s in sorted((s for s in sigs if s["rule"] in quick), key=lambda s: -s["in_ts"])[:120]:
        o = (s["out"] or {}).get(s["ref"])
        row = {"id": s["id"], "rule": s["rule"], "sym": s["sym"], "mint": s["mint"], "in_ts": s["in_ts"],
               "in_price": s["in_price"], "in_mc": s["in_mc"], "in_liq": s["in_liq"], "exit": s["ref"], "live": bool(s["live"]),
               "f": {k: (s["f"] or {}).get(k) for k in MIN.KEYS if (s["f"] or {}).get(k) is not None}}
        if o:
            row.update(ret=o[0], h=o[1], why=o[2], out_ts=o[3])
        else:
            last = s.get("last_price") or s["in_price"]
            row.update(now_net=LAB._r(TRD.net_ret(last / s["in_price"], s["in_liq"], s.get("last_liq"), cfg)))
        trades.append(row)
    base = C.FAST["baseline_exit"] if C.FAST["baseline_exit"] in exits else next(iter(exits))
    entries = TRD.pooled({rid: by_rule.get(rid, []) for rid in quick})
    cmp_ = TRD.compare_exits(entries, base, cfg, exits, now) if entries else {}
    return {"rules": [quick[k] for k in quick], "trades": trades, "n_trades": sum(1 for s in sigs if s["rule"] in quick),
            "exits": [{"id": e["id"], "label": TRD.exit_label(e), "base": e["id"] == base, "now": cmp_.get(e["id"]),
                       "quick": e.get("max_h", 24) <= 2} for e in exits.values() if not e.get("model")],
            "base": base, "minute": minute, "ticks": st.tick_stats(), "cfg": C.FAST,
            "vars": [{"key": k, "label": l, "unit": u} for k, l, u in MIN.VARIABLES]}


ENTRY_KEYS = ("id", "slug", "algo", "family", "kind", "set", "n_vars", "n_test", "auc", "auc_sd", "train_auc", "gap",
              "accuracy", "balanced_acc", "brier", "logloss", "ic", "picks", "pick_coins", "pick_win", "pick_net", "pick_med",
              "pick_t", "base_net", "edge", "luck_one", "luck_best", "beats_luck", "thr", "leading", "train_rows",
              "train_coins", "seconds_wf", "seconds_fit", "error")
EXIT_KEYS = ("id", "slug", "algo", "family", "n_vars", "decisions", "auc", "train_auc", "gap", "accuracy", "sell_rate",
             "trades", "net", "base_net", "gain", "gain_t", "early", "thr", "leading", "seconds", "error")


def models_page(st, bank, policy, tpage, now, picks, sells, sigs=None):
    """What the Models tab shows: every model's walk-forward test, its forward paper record under the live exit, the
    exit models against the live exit on the same trades, and every model trade with its coin and time."""
    S = (bank.summary if bank else None) or {}
    out = {"available": MOD is not None, "status": S.get("status") or "waiting for the first training run",
           "study": C.ML_STUDY, "cfg": {k: C.MODELS[k] for k in ("every_h", "top_share", "exit_thr", "fold_h", "min_samples",
                                                                   "min_coins", "max_age_h", "luck_draws")},
           "sets": C.MODEL_SETS}
    if bank:
        out.update(fresh=bank.fresh, errors=bank.errors[:20], age_h=round(getattr(bank, "age_h", 0) or 0, 1))
    for k in ("trained_at", "samples", "coins", "period", "folds", "fold_sizes", "embargo_h", "base_win", "base_net",
              "base_oos_net", "base_oos_win", "label", "seconds"):
        out[k] = S.get(k)
    if not S:
        return out
    cfg = C.TRADE
    exits = {e["id"]: e for e in exit_pool_of(bank)}
    live_exit = exits.get((policy or {}).get("exit")) or exits[C.DEFAULT_EXIT]
    rules = {r["id"]: r for r in (policy or {}).get("rules") or []}
    every = sigs if sigs is not None else st.sigs(now - cfg["window_days"] * 86400)
    sigs = [s for s in every if s["rule"].startswith("m:")]
    by_rule = defaultdict(list)
    for s in sigs:
        by_rule[s["rule"]].append(s)
    entry = []
    for m in S.get("entry") or []:
        rid = MOD.rule_id(m["id"]) if MOD else "m:" + m["id"]
        r, ss = rules.get(rid) or {}, by_rule.get(rid, [])
        lid = live_exit["id"]
        done = [{"mint": s["mint"], "ret": s["out"][lid][0], "in_ts": s["in_ts"], "h": s["out"][lid][1]} for s in ss
                if (s["out"] or {}).get(lid) and TRD.matured(s["in_ts"], live_exit, now)]
        last = max(ss, key=lambda s: s["in_ts"]) if ss else None
        entry.append({k: m.get(k) for k in ENTRY_KEYS}
                     | {"rule": rid, "status": r.get("status"), "verdict": (r.get("last") or {}).get("verdict"),
                        "streak": r.get("streak"), "since": r.get("added"), "fwd": TRD._r(TRD.summarise(done)),
                        "trades": len(ss), "open": sum(1 for s in ss if lid not in (s["out"] or {})),
                        "now": len(picks.get(m["id"], {})),
                        "last_entry": {"sym": last["sym"], "mint": last["mint"], "ts": last["in_ts"],
                                       "sc": (last["f"] or {}).get("sc")} if last else None})
    cmp_ = {e["id"]: e for e in (tpage or {}).get("exits") or []}
    exit_rows = [{k: e.get(k) for k in EXIT_KEYS} | {"fwd": (cmp_.get(e["id"]) or {}).get("now"),
                                                     "live": (policy or {}).get("exit") == e["id"]}
                 for e in S.get("exit") or []]
    sell_now = defaultdict(list)
    for sid, pid in sells or ():
        sell_now[sid].append(pid)
    log_rows = []
    for s in sorted(sigs, key=lambda s: -s["in_ts"])[:200]:
        o = (s["out"] or {}).get(live_exit["id"])
        row = {"id": s["id"], "ts": s["in_ts"], "sym": s["sym"], "mint": s["mint"], "model": s["rule"][2:],
               "sc": (s["f"] or {}).get("sc"), "thr": (s["f"] or {}).get("thr"), "mv": (s["f"] or {}).get("mv"),
               "price": s["in_price"], "mc": s["in_mc"], "liq": s["in_liq"], "live": bool(s["live"])}
        if o:
            row.update(ret=o[0], h=o[1], why=o[2], out_ts=o[3])
        else:
            last = s.get("last_price") or s["in_price"]
            row.update(now_net=LAB._r(TRD.net_ret(last / s["in_price"], s["in_liq"], s.get("last_liq"), cfg)),
                       x_sell=sell_now.get(s["id"], []))
        x_out = {pid: [v[0], v[3]] for pid, v in (s["out"] or {}).items() if pid.startswith("x:")}
        if x_out:
            row["x_out"] = x_out
        log_rows.append(row)
    # every sale an exit model made, on any paper trade (rules' and models'), against the live exit on the same trade
    xlog = []
    for s in every:
        for pid, v in (s["out"] or {}).items():
            if pid.startswith("x:") and v[2] == "model said sell":
                ref = (s["out"] or {}).get(live_exit["id"])
                xlog.append({"ts": v[3], "sym": s["sym"], "mint": s["mint"], "model": pid, "rule": s["rule"], "in_ts": s["in_ts"],
                             "h": v[1], "ret": v[0], "price": v[4], "live_ret": ref[0] if ref else None})
    xlog.sort(key=lambda x: -x["ts"])
    out.update(entry=entry, exit=exit_rows, log=log_rows, exit_log=xlog[:150], exit_sells=len(xlog),
               live_exit={"id": live_exit["id"], "label": TRD.exit_label(live_exit)}, trades_total=len(sigs))
    return out


def train_request(st, bank, now, folder):
    """Ask for a training run when the models are older than they should be (GitHub often runs scheduled workflows
    hours late): a file the scan workflow looks for, and a note of when it last asked so it asks once, not every
    scan. Collecting summaries are retried sooner, as each hour of history may add a walk-forward fold."""
    cfg = C.MODELS
    S = (bank.summary if bank else None) or {}
    age_h = (now - S["trained_at"]) / H if S.get("trained_at") else None
    ok = S.get("status") == "ok"
    due = age_h is None or age_h >= (cfg["every_h"] + 1 if ok else cfg["retry_collecting_h"])
    asked = float(st.get_meta("train_asked") or 0)
    path = os.path.join(folder, "train_due")
    if due and now - asked >= cfg["ask_every_h"] * H:
        with open(path, "w") as fh:
            fh.write(f"{now}\n")
        st.set_meta("train_asked", now)
        st.commit()
        log(f"models: asked for a training run (" + ("none yet" if age_h is None else f"last trained {age_h:.1f}h ago") + ")")
    elif os.path.exists(path):
        os.remove(path)


def corr_page(st, now):
    """The Correlations tab, worked out at most once every CORR["every_min"] minutes and kept in the database between."""
    last = st.get_meta("corr")
    if last:
        try:
            doc = json.loads(last)
            if now - doc.get("ts", 0) < C.CORR["every_min"] * 60 - 120:
                return doc
        except ValueError:
            pass
    t0 = time.time()
    doc = CORR.analyse(st.tpath(now - C.TRADE["path_days"] * 86400), now, C.CORR)
    keep = now - C.FAST["keep_h"] * H
    passing = st.passing_sets(keep - 2 * H)
    try:
        doc["minute"] = CORR.analyse_fast(st.ticks_by_coin(keep, set().union(*[p[1] for p in passing])), passing,
                                          st.feeds(keep - 25 * H), now, C.CORR)
    except Exception as e:
        log(f"correlations on the minute data: skipped ({type(e).__name__}: {e})")
        doc["minute"] = {"points": 0, "coins": 0, "vars": [], "error": str(e)}
    doc["seconds"] = round(time.time() - t0, 1)
    st.set_meta("corr", json.dumps(clean(doc), separators=(",", ":")))
    st.commit()
    log(f"correlations: {doc['points']} hourly readings on {doc['coins']} coins, {doc['minute']['points']} minute "
        f"readings on {doc['minute']['coins']} coins, in {doc['seconds']}s")
    return doc


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
    jcache, lists = {}, {}
    if not args.no_discovery:
        _seen, lists = discover(st, now, jcache)
    toks = st.universe(now - C.UNIVERSE_TTL_DAYS * 86400)
    log(f"universe: {len(toks)} tokens")
    ds_all = S.ds_tokens([t["mint"] for t in toks])
    log(f"dexscreener: {len(ds_all)} priced")
    bank = MOD.Bank(args.models, now, C.MODELS["max_age_h"]) if MOD and getattr(args, "models", None) else None
    if bank:
        log(f"models: {'none trained yet' if not bank.summary else bank.summary.get('status')}"
            + (f"; {len(bank.entry)} entry and {len(bank.exit)} exit models loaded, trained {bank.age_h:.1f}h ago"
               + ("" if bank.fresh else " (too old to trade)") if bank.summary and bank.summary.get('status') == 'ok' else "")
            + (f"; failed to load: {', '.join(bank.errors[:5])}" if bank.errors else ""))
    exits = {e["id"]: e for e in exit_pool_of(bank)}
    # the paper ledger's scan reading, then the minute sampler until the ledger is stepped at decision time
    n_step, closed_scan = scan_step(st, ds_all, now, exits, C.TRADE)
    notify.closes(closed_scan)
    log(f"trade ledger: {n_step} open paper trades stepped on the scan's prices, {len(closed_scan)} live ones closed")
    sampler = None
    if not getattr(args, "no_minutes", False) and ds_all:
        try:                                   # the minute layer must never stop a scan
            sampler = start_minutes(st, now, ds_all, lists, exits, loaded_exits(exits, bank))
        except Exception as e:
            log(f"minute sampler: not started ({type(e).__name__}: {e})")
    n_up = update_outcomes(st, ds_all, now)
    sol = S.ds_tokens([C.SOL_MINT]).get(C.SOL_MINT) or {}
    policy = json.loads(st.get_meta("policy") or "null")
    crowd = COM.crowd() if COM.enabled() else {}
    try:
        rows, handles, events, status = process(st, now, toks, args.max_enrich, ds_all, jcache, policy, crowd, lists)
    except BaseException:
        if sampler:
            sampler.stop()
        raise
    regime = regime_of(rows, (sol.get("chg") or {}).get("h24"))
    n_obs = observe(st, rows, now, regime)
    log(f"lab: {n_obs} observations recorded, {n_up} open ones updated")
    policy, gmeta, changes = weekly_review(st, rows, now, policy)
    policy = add_attention_candidates(st, policy, now)
    tpolicy, tfeats, tchanges, picks, sells, minute, closed_dec = trade_step(st, rows, ds_all, now, regime, bank, sampler,
                                                                             time.time())
    train_request(st, bank, now, os.path.dirname(os.path.abspath(args.db)))
    rate = base_rug_rate(st, now)
    community = COM.sync(rows, ds_all, now, rate) if COM.enabled() else "off: no SUPABASE_SECRET_KEY"
    log("community: " + community)
    snapshot_tracked(st, rows, ds_all, jcache, now)
    st.prune(now - C.SNAP_KEEP_H * H, now - C.TG_KEEP_DAYS * 86400)
    if now - float(st.get_meta("attn_pruned") or 0) >= 86400:
        log(f"attention: {st.prune_attention(now - C.ATTN['keep_days'] * 86400)} stale records thinned")
        st.set_meta("attn_pruned", now)
    st.commit()
    meta = {"universe": len(toks), "priced": len(ds_all), "candidates": len(rows), "seconds": round(time.time() - t0),
            "sources": ["GeckoTerminal", "DEX Screener", "Jupiter", "Solana RPC", "RugCheck", "Telegram public pages",
                        "fxtwitter (X followers)", "RDAP (domain records)"],
            "source_status": status, "trending": {k: len(v) for k, v in lists.items()}}
    meta["review"] = REV.for_page(policy, gmeta)
    meta["call_base_rate"] = round(COM.base_rate(rate), 4)       # what rug calls are scored against (see community.py)
    meta["call_base_rate_measured"] = rate is not None             # False: the default, until a fortnight has settled
    meta["community"] = community
    sigs = st.sigs(now - C.TRADE["window_days"] * 86400)          # read once for both tabs
    tpage = trade_page(st, tpolicy, tfeats, rows, now, exit_pool_of(bank), picks, sigs, minute)
    meta["trade"] = tpage
    meta["models"] = models_page(st, bank, tpolicy, tpage, now, picks, sells, sigs)
    meta["corr"] = corr_page(st, now)
    doc = export(st, rows, handles, now, meta, args.out)
    write_csv(os.path.join(os.path.dirname(os.path.abspath(args.out)), "tracker.csv"), tracker_rows(st, rows, now))
    st.close()
    notify.send(events)
    notify.review(changes)
    notify.trade(tchanges, tpage, now)
    notify.closes(closed_dec)
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
    a.add_argument("--models", default=MODELS_DIR, help="folder the training job (undertow.train) writes the models to")
    a.add_argument("--no-minutes", action="store_true", help="run without the minute sampler (tests, local runs)")
    b = sub.add_parser("inspect"); b.add_argument("mint"); b.add_argument("--db", default="undertow.db")
    args = ap.parse_args()
    run(args) if args.cmd == "run" else inspect(args)
