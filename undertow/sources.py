"""One small function per free data source. Each returns plain dicts, or None on failure."""
import os, re, time
from .http import fetch
from . import config

GT = "https://api.geckoterminal.com/api/v2/networks/solana"
DS = "https://api.dexscreener.com"
RC = "https://api.rugcheck.xyz/v1"
GP = "https://api.gopluslabs.io/api/v1/solana/token_security"
SOL = "So11111111111111111111111111111111111111112"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---- GeckoTerminal: discovery, graduation flag, sector, holder count -------------------------
def gt_pools(path):
    """path e.g. 'dexes/pumpswap/pools?sort=h24_volume_usd_desc&page=3'. Returns a list of pool dicts,
    [] when the page is empty, or None when the call failed (so discovery can skip it rather than stop)."""
    d = fetch("geckoterminal", f"{GT}/{path}")
    if d is None:
        return None
    out = []
    for p in (d or {}).get("data") or []:
        a, r = p["attributes"], p["relationships"]
        base = r["base_token"]["data"]["id"].split("_", 1)[1]
        quote = r["quote_token"]["data"]["id"].split("_", 1)[1]
        if base == SOL:
            continue
        tx = (a.get("transactions") or {}).get("h24") or {}
        out.append({
            "mint": base, "quote": quote, "pool": a["address"], "dex": r["dex"]["data"]["id"],
            "name": (a.get("name") or "").split(" / ")[0], "created": a.get("pool_created_at"),
            "fdv": _f(a.get("fdv_usd")), "vol24": _f((a.get("volume_usd") or {}).get("h24")),
            "liq": _f(a.get("reserve_in_usd")),
            "buyers24": tx.get("buyers"), "sellers24": tx.get("sellers"),
            "buys24": tx.get("buys"), "sells24": tx.get("sells"),
        })
    return out


def gt_info(mint):
    d = fetch("geckoterminal", f"{GT}/tokens/{mint}/info")
    a = ((d or {}).get("data") or {}).get("attributes")
    if not a:
        return None
    lp = a.get("launchpad_details") or {}
    h = a.get("holders") or {}
    return {
        "name": a.get("name"), "symbol": a.get("symbol"),
        "graduated": bool(lp.get("completed")), "launchpad": bool(lp),
        "categories": a.get("categories") or [], "holders": h.get("count"),
        "twitter": (a.get("twitter_handle") or "").lower() or None,
        "telegram": a.get("telegram_handle") or None,
        "website": (a.get("websites") or [None])[0],
        "honeypot": a.get("is_honeypot"), "gt_score": a.get("gt_score"),
    }


# ---- DEX Screener: batch price/volume/liquidity/socials (30 tokens per call) -----------------
def ds_tokens(mints):
    out = {}
    for i in range(0, len(mints), 30):
        chunk = mints[i:i + 30]
        d = fetch("dexscreener", f"{DS}/tokens/v1/solana/{','.join(chunk)}")
        for p in d or []:
            m = p["baseToken"]["address"]
            liq = ((p.get("liquidity") or {}).get("usd")) or 0
            if m in out and liq <= out[m]["liq"]:
                continue
            info = p.get("info") or {}
            soc = {s.get("type"): s.get("url") for s in (info.get("socials") or [])}
            sites = [w.get("url") for w in (info.get("websites") or []) if w.get("url")]
            tx = p.get("txns") or {}
            out[m] = {
                "symbol": p["baseToken"].get("symbol"), "name": p["baseToken"].get("name"),
                "dex": p.get("dexId"), "pair": p.get("pairAddress"), "price": _f(p.get("priceUsd")),
                "labels": p.get("labels") or [], "quote": (p.get("quoteToken") or {}).get("symbol"),
                "mcap": p.get("marketCap") or p.get("fdv"), "fdv": p.get("fdv") or p.get("marketCap"), "liq": liq,
                "vol": p.get("volume") or {}, "chg": p.get("priceChange") or {},
                "buys24": (tx.get("h24") or {}).get("buys"), "sells24": (tx.get("h24") or {}).get("sells"),
                "buys1": (tx.get("h1") or {}).get("buys"), "sells1": (tx.get("h1") or {}).get("sells"),
                "created": p.get("pairCreatedAt"), "twitter_url": soc.get("twitter"), "telegram_url": soc.get("telegram"),
                # paid DEX Screener boosts running now (absent means none), the project's website, and how many links
                # its DEX Screener profile lists
                "boosts": (p.get("boosts") or {}).get("active") or 0, "website_url": sites[0] if sites else None,
                "n_links": len(soc) + len(sites),
            }
    return out


def ds_orders(mint):
    """What has been paid for on DEX Screener for this token: approved ads, trending-bar ads, an enhanced profile, a
    community takeover. {"ads", "trend_ads", "ad_last" (unix s), "profile", "cto"} or None on failure."""
    d = fetch("dexscreener", f"{DS}/orders/v1/solana/{mint}", tries=2)
    if d is None:
        return None
    orders = d.get("orders") if isinstance(d, dict) else d
    ok = [o for o in orders or [] if o.get("status") in ("approved", "processing")]
    ads = [o for o in ok if o.get("type") == "tokenAd"]
    paid = [(o.get("paymentTimestamp") or 0) / 1000 for o in ok if o.get("type") in ("tokenAd", "trendingBarAd")]
    return {"ads": len(ads), "trend_ads": sum(1 for o in ok if o.get("type") == "trendingBarAd"),
            "ad_last": max(paid) if paid else None, "profile": int(any(o.get("type") == "tokenProfile" for o in ok)),
            "cto": int(any(o.get("type") == "communityTakeover" for o in ok))}


# ---- Attention: trending lists, X followers, website domain age ------------------------------
def gt_trending(duration="1h", pages=2):
    """GeckoTerminal's trending pools for Solana, in rank order, as base-token mints. GeckoTerminal ranks them on user
    engagement on its site, market activity and pool security, so a rank is the nearest free stand-in for visits.
    duration: 5m, 1h, 6h or 24h. Returns None when the first page fails."""
    out = []
    for pg in range(1, pages + 1):
        d = fetch("geckoterminal", f"{GT}/trending_pools?duration={duration}&page={pg}")
        if d is None:
            return out or None
        for p in d.get("data") or []:
            base = (((p.get("relationships") or {}).get("base_token") or {}).get("data") or {}).get("id", "")
            m = base.split("_", 1)[1] if "_" in base else None
            if m and m != SOL and m not in out:
                out.append(m)
    return out


def x_profile(handle):
    """Public follower count of an X account through fxtwitter's free mirror (X's own API is paid), falling back to
    vxtwitter. {"followers", "tweets"} or None."""
    if not handle:
        return None
    d = fetch("fxtwitter", f"https://api.fxtwitter.com/{handle}", tries=2)
    u = (d or {}).get("user") if isinstance(d, dict) else None
    if u and u.get("followers") is not None:
        return {"followers": u.get("followers"), "tweets": u.get("tweets")}
    d = fetch("vxtwitter", f"https://api.vxtwitter.com/{handle}", tries=1)
    if isinstance(d, dict) and d.get("followers_count") is not None:
        return {"followers": d.get("followers_count"), "tweets": d.get("tweet_count")}
    return None


_TWO_PART = {"co.uk", "org.uk", "com.au", "co.jp", "com.br", "co.in", "co.za", "com.cn", "co.kr", "com.mx", "com.tr"}


def domain_of(url):
    """The registrable domain of a website address: 'https://app.example.co.uk/x' -> 'example.co.uk'."""
    from urllib.parse import urlparse
    if not url:
        return None
    host = (urlparse(url if "//" in url else "//" + url).hostname or "").lower().strip(".")
    parts = [p for p in host.split(".") if p]
    if len(parts) < 2:
        return None
    n = 3 if ".".join(parts[-2:]) in _TWO_PART and len(parts) >= 3 else 2
    return ".".join(parts[-n:])


def domain_registered(domain):
    """When the website's domain was registered (unix seconds), from public RDAP records; None when unknown."""
    import calendar
    if not domain:
        return None
    d = fetch("rdap", f"https://rdap.org/domain/{domain}", tries=1)
    for e in (d or {}).get("events") or []:
        if e.get("eventAction") == "registration" and e.get("eventDate"):
            try:
                return calendar.timegm(time.strptime(e["eventDate"][:19], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                return None
    return None


# ---- RugCheck: authorities, holders, creator, LP, insider graph ------------------------------
def rc_report(mint):
    d = fetch("rugcheck", f"{RC}/tokens/{mint}/report", tries=2)
    if not d or "mint" not in d:
        return None
    tok = d.get("token") or {}
    supply = tok.get("supply") or 0
    ka = d.get("knownAccounts") or {}
    skip = {k for k, v in ka.items() if v.get("type") in ("AMM", "CLOB", "LOCKER", "CEX", "BURN", "PROGRAM")}
    skip |= {"1nc1nerator11111111111111111111111111111111", "11111111111111111111111111111111"}
    top = d.get("topHolders") or []
    ex = [h for h in top if h.get("owner") not in skip and h.get("address") not in skip]
    ext = d.get("token_extensions") or {}
    bad_ext = [k for k in config.DANGEROUS_EXTENSIONS if ext.get(k)]
    tf = (d.get("transferFee") or {}).get("pct") or 0
    mk = sorted(d.get("markets") or [], key=lambda m: -((m.get("lp") or {}).get("baseUSD", 0) + (m.get("lp") or {}).get("quoteUSD", 0)))
    lp_locked = ((mk[0].get("lp") or {}).get("lpLockedPct")) if mk else None
    cb = d.get("creatorBalance") or 0
    cl_pct, cl_n = _largest_cluster(d.get("insiderNetworks"), supply)
    return {
        "supply": supply, "mint_auth": tok.get("mintAuthority") or d.get("mintAuthority"),
        "freeze_auth": tok.get("freezeAuthority") or d.get("freezeAuthority"),
        "bad_ext": bad_ext, "transfer_fee": tf, "rugged": bool(d.get("rugged")),
        "creator": d.get("creator"), "creator_bal": cb, "creator_pct": (cb / supply * 100) if supply else None,
        "holders": d.get("totalHolders"), "top10": sum(h["pct"] for h in ex[:10]) if ex else None,
        "top20": {h["owner"]: h["amount"] for h in top},          # raw balances incl. pools; used for outflow
        "ex_owners": [h["owner"] for h in ex], "pool_owners": sorted(skip),
        "same_size": _max_same_size([h["amount"] for h in ex]),
        "linked_wallets": d.get("graphInsidersDetected") or 0,
        "insider_flagged_pct": sum(h["pct"] for h in top if h.get("insider")),
        "cluster_pct": cl_pct, "cluster_n": cl_n,
        "lp_locked_pct": lp_locked, "lp_by_pool": {m["pubkey"]: (m.get("lp") or {}).get("lpLockedPct") for m in mk if m.get("pubkey")},
        "risks": [(r.get("name"), r.get("level")) for r in d.get("risks") or []],
        "score": d.get("score_normalised"), "launchpad": (d.get("launchpad") or {}).get("platform"),
    }


def _largest_cluster(networks, supply):
    """The biggest group of wallets RugCheck links by token transfers, as (% of supply it holds now, wallets in it).
    This is the cluster InsightX and Bubblemaps draw as one bubble group. (None, None) when RugCheck did not map
    the networks, or when its biggest group claims more than the whole supply (seen on 20 Oct 2026: 8,665 wallets
    "holding" 159%), so the figure cannot be trusted; (0.0, 0) when it mapped them and found none."""
    if networks is None or not supply:
        return None, None
    held = lambda n: n.get("currentHolding") if n.get("currentHolding") is not None else n.get("tokenAmount") or 0
    best = max((n for n in networks if isinstance(n, dict)), key=held, default=None)
    if not best:
        return 0.0, 0
    pct = held(best) / supply * 100
    if pct > 100:
        return None, None
    return pct, best.get("size") or best.get("activeAccounts") or 0


# ---- GoPlus Security: a second opinion on the structure ----------------------------------------
def gp_report(mint):
    """GoPlus's free Solana token check (keyless, one token per call). It re-reads the structure from a second
    source: mint and freeze authority, Token-2022 traps, authorities that could switch a trap on later (raise the
    transfer fee, add a transfer hook, make new accounts start frozen, change balances) and whether the name,
    symbol and image can still be changed."""
    d = fetch("goplus", f"{GP}?contract_addresses={mint}", tries=2)
    r = (((d or {}).get("result")) or {}).get(mint)
    if not isinstance(r, dict) or not r:
        return None

    def on(key):
        v = r.get(key)
        return str(v.get("status")) == "1" if isinstance(v, dict) else None

    fee = r.get("transfer_fee") if isinstance(r.get("transfer_fee"), dict) else {}
    rates = [_f((fee.get("current_fee_rate") or {}).get("fee_rate"))]
    rates += [_f(s.get("fee_rate")) for s in fee.get("scheduled_fee_rate") or [] if isinstance(s, dict)]
    traps = []
    if on("balance_mutable_authority"):
        traps.append("balances can be changed")
    if r.get("transfer_hook"):
        traps.append("transfer hook set")
    if str(r.get("default_account_state")) == "2":
        traps.append("accounts start frozen")
    if str(r.get("non_transferable")) == "1":
        traps.append("non-transferable")
    for key, what in (("transfer_fee_upgradable", "transfer fee can be raised"),
                      ("transfer_hook_upgradable", "transfer hook can be added"),
                      ("default_account_state_upgradable", "accounts can be made to start frozen")):
        if on(key):
            traps.append(what)
    burns = [_f(x.get("burn_percent")) for x in r.get("dex") or [] if isinstance(x, dict)]
    return {
        "mintable": on("mintable"), "freezable": on("freezable"), "closable": on("closable"),
        "meta_mutable": on("metadata_mutable"), "traps": traps,
        "fee_pct": round(max([x for x in rates if x is not None], default=0) * 100, 3),
        "trusted": bool(r.get("trusted_token")), "holders": int(_f(r.get("holder_count")) or 0) or None,
        "lp_burn_max": max([b for b in burns if b is not None], default=None),
    }


def _max_same_size(amounts, tol=0.015):
    a = sorted(x for x in amounts if x)
    best = 0
    for i, x in enumerate(a):
        n = sum(1 for y in a[i:] if y <= x * (1 + tol))
        best = max(best, n)
    return best


# ---- Telegram: member and online counts from the public preview page (no key) ----------------
_TG = re.compile(r"([\d][\d\s  ]*)\s*(members|subscribers)(?:,\s*([\d\s  ]+)\s*online)?", re.I)


def tg_counts(handle_or_url):
    if not handle_or_url:
        return None
    h = handle_or_url.rstrip("/").split("/")[-1].lstrip("@")
    if not h or h.startswith("+") or h.lower() in ("joinchat",):
        return None
    html = fetch("telegram", f"https://t.me/{h}", as_json=False, tries=2)
    if not html:
        return None
    m = _TG.search(html)
    if not m:
        return None
    num = lambda s: int(re.sub(r"\D", "", s)) if s and re.search(r"\d", s) else None
    return {"handle": h, "members": num(m.group(1)), "online": num(m.group(3)), "kind": m.group(2).lower()}


# ---- Jupiter: live demand stats, organic score, deployer history, executable sell quotes -----
JUP = config.JUP_BASE


def _jh():
    key = os.environ.get("JUP_API_KEY")
    return {"x-api-key": key} if key else None


def _jstat(s):
    if not s:
        return None
    bv, sv = s.get("buyVolume"), s.get("sellVolume")
    return {"net_flow": (bv or 0) - (sv or 0) if (bv is not None or sv is not None) else None,
            "buy_vol": bv, "sell_vol": sv, "traders": s.get("numTraders"), "net_buyers": s.get("numNetBuyers"),
            "organic_buyers": s.get("numOrganicBuyers"), "holder_change": s.get("holderChange"),
            "vol_change": s.get("volumeChange"), "liq_change": s.get("liquidityChange")}


def _jparse(t):
    a = t.get("audit") or {}
    return {
        "mint": t.get("id"), "symbol": t.get("symbol"), "name": t.get("name"), "tags": t.get("tags") or [],
        "organic": t.get("organicScore"), "organic_label": t.get("organicScoreLabel"),
        "holders": t.get("holderCount"), "dev": t.get("dev"), "dev_mints": a.get("devMints"),
        "dev_grads": a.get("devMigrations"), "dev_pct": a.get("devBalancePercentage"),
        "top_holders_pct": a.get("topHoldersPercentage"),
        "mint_disabled": a.get("mintAuthorityDisabled"), "freeze_disabled": a.get("freezeAuthorityDisabled"),
        "sus": bool(a.get("isSus")), "launchpad": t.get("launchpad"), "graduated_pool": t.get("graduatedPool"),
        "graduated_at": t.get("graduatedAt"), "first_pool_at": (t.get("firstPool") or {}).get("createdAt"),
        "verified": bool(t.get("isVerified")), "decimals": t.get("decimals"), "usd_price": t.get("usdPrice"),
        "mcap": t.get("mcap"), "fdv": t.get("fdv"), "liquidity": t.get("liquidity"),
        "twitter": t.get("twitter"), "telegram": t.get("telegram"), "website": t.get("website"),
        "s5m": _jstat(t.get("stats5m")), "s1h": _jstat(t.get("stats1h")),
        "s6h": _jstat(t.get("stats6h")), "s24h": _jstat(t.get("stats24h")),
    }


def jup_tokens(mints):
    """Up to 50 mints per call. Stats windows: 5m, 1h, 6h, 24h. holder_change is a percentage."""
    out = {}
    for i in range(0, len(mints), 50):
        d = fetch("jupiter", f"{JUP}/tokens/v2/search?query={','.join(mints[i:i + 50])}", headers=_jh())
        for t in d or []:
            out[t["id"]] = _jparse(t)
    return out


def jup_list(path, limit=100):
    """A Jupiter category list such as 'toptrending/1h' or 'recent': up to 100 tokens from every launchpad and DEX."""
    d = fetch("jupiter", f"{JUP}/tokens/v2/{path}?limit={limit}", headers=_jh())
    return [_jparse(t) for t in d or [] if t.get("id")]


def jup_exit_cost(mint, usd_price, decimals, usd):
    """Jupiter's quoted price impact (in %) for selling a position worth `usd`, and the venues it routes through.
    Impact is measured against Jupiter's own mid price inside one quote, so it is not thrown off by prices moving
    between calls; fees are added separately. Measured live, quotes for the same token vary by a point or two."""
    if not usd_price or decimals is None:
        return None
    amount = int(usd / usd_price * 10 ** decimals)
    if amount <= 0:
        return None
    q = fetch("jupiter", f"{JUP}/swap/v1/quote?inputMint={mint}&outputMint={SOL}&amount={amount}&slippageBps=5000",
              headers=_jh(), tries=2)
    if not q or q.get("priceImpactPct") is None:
        return None
    return {"impact_pct": float(q["priceImpactPct"]) * 100, "usd": usd,
            "venues": [r.get("swapInfo", {}).get("label") for r in q.get("routePlan") or []]}


# ---- GeckoTerminal candles: 5-minute OHLCV for the last 24 hours (the free tier's reach) --------
def gt_candles(pool, mint):
    """Ascending [ts, open, high, low, close, volume] in USD for `mint` in `pool`. None on failure."""
    if not pool:
        return None
    d = fetch("geckoterminal", f"{GT}/pools/{pool}/ohlcv/minute?aggregate=5&limit=1000&currency=usd&token={mint}")
    lst = (((d or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list")
    if lst is None:
        return None
    return sorted(([int(c[0])] + [float(x) for x in c[1:6]] for c in lst), key=lambda c: c[0])


def gt_pools_multi(addresses):
    """Locked-liquidity percentage and fee per pool, 30 pools per call. {pool: {"locked_pct", "fee_pct"}}."""
    out = {}
    addrs = [a for a in addresses if a]
    for i in range(0, len(addrs), 30):
        d = fetch("geckoterminal", f"{GT}/pools/multi/{','.join(addrs[i:i + 30])}")
        for p in (d or {}).get("data") or []:
            a = p.get("attributes") or {}
            out[a.get("address")] = {"locked_pct": _f(a.get("locked_liquidity_percentage")), "fee_pct": _f(a.get("pool_fee_percentage"))}
    return out


def gt_trades(pool):
    """The pool's last 300 trades (24h at most), newest first: [ts, kind, usd, wallet]. None on failure."""
    import calendar
    if not pool:
        return None
    d = fetch("geckoterminal", f"{GT}/pools/{pool}/trades")
    if d is None:
        return None
    out = []
    for x in d.get("data") or []:
        a = x.get("attributes") or {}
        try:
            ts = calendar.timegm(time.strptime(a["block_timestamp"][:19], "%Y-%m-%dT%H:%M:%S"))
        except (KeyError, ValueError):
            continue
        out.append([ts, a.get("kind"), _f(a.get("volume_in_usd")) or 0.0, a.get("tx_from_address")])
    return out


# ---- Solana RPC: mint authorities and Token-2022 extensions, straight from the chain --------------
def rpc_mints(mints):
    """getMultipleAccounts (100 per call). {mint: {"program", "mint_auth", "freeze_auth", "supply", "decimals",
    "extensions": {name: state}}}. Mints the RPC does not return are left out."""
    url = os.environ.get("SOLANA_RPC_URL") or config.RPC_URL
    out = {}
    for i in range(0, len(mints), 100):
        chunk = mints[i:i + 100]
        d = fetch("rpc", url, data={"jsonrpc": "2.0", "id": 1, "method": "getMultipleAccounts",
                                    "params": [chunk, {"encoding": "jsonParsed"}]}, timeout=40)
        vals = (((d or {}).get("result") or {}).get("value")) or []
        for m, acc in zip(chunk, vals):
            try:
                info = acc["data"]["parsed"]["info"]
            except (TypeError, KeyError):
                continue
            out[m] = {"program": acc.get("owner"), "mint_auth": info.get("mintAuthority"),
                      "freeze_auth": info.get("freezeAuthority"), "supply": info.get("supply"),
                      "decimals": info.get("decimals"),
                      "extensions": {e.get("extension"): e.get("state") for e in info.get("extensions") or []}}
    return out


def bad_extensions(exts):
    """Names of Token-2022 extensions that let the issuer take, freeze or block tokens, plus the transfer fee in %."""
    bad = []
    for name in config.DANGEROUS_EXTENSIONS:
        if name not in (exts or {}):
            continue
        st = exts[name] or {}
        if name == "transferHook" and not st.get("programId"):
            continue                          # hook extension present but no hook program set
        if name == "defaultAccountState" and st.get("accountState") != "frozen":
            continue                          # new accounts start usable
        bad.append(name)
    fee = ((exts or {}).get("transferFeeConfig") or {}).get("newerTransferFee") or {}
    return bad, (fee.get("transferFeeBasisPoints") or 0) / 100
