"""Derived demand, exit and momentum-quality signals. Pure functions: numbers in, numbers out."""
from . import config as C


def exit_cost_model(usd, liq_usd, fee_pct=None):
    """Cost, in %, of selling a position worth `usd` at spot into a constant-product pool holding liq_usd in
    total (half on each side): price impact usd / (y + usd), plus the pool fee."""
    if not liq_usd or liq_usd <= 0:
        return None
    y = liq_usd / 2
    return usd / (y + usd) * 100 + (C.DEFAULT_FEE_PCT if fee_pct is None else fee_pct)


def exit_cost(usd, liq_usd, quoted_impact_pct):
    """The exit-cost figure the gate uses: the worse of the pool model and Jupiter's quoted impact plus the fee.
    Taking the worse of the two is deliberate: a thin route Jupiter can see, or overstated liquidity, both count."""
    model = exit_cost_model(usd, liq_usd)
    quoted = quoted_impact_pct + C.DEFAULT_FEE_PCT if quoted_impact_pct is not None else None
    if model is None:
        return quoted, quoted is not None
    if quoted is None:
        return model, False
    return (quoted, True) if quoted > model else (model, False)


def buyer_breadth(s1h):
    """Share of the last hour's traders who ended the hour as net buyers (0-1)."""
    t, nb = (s1h or {}).get("traders"), (s1h or {}).get("net_buyers")
    return nb / t if t and nb is not None else None


def candle_stats(candles, now):
    """From ascending 5-minute candles: extension above the 6h average close, drawdown from the 24h high,
    and whether the last hour's low is above the previous hour's low."""
    if not candles or len(candles) < 12:
        return {}
    last = candles[-1][4]
    win6 = [c[4] for c in candles if c[0] >= now - 6 * 3600]
    hi24 = max(c[2] for c in candles if c[0] >= now - 24 * 3600) if any(c[0] >= now - 24 * 3600 for c in candles) else None
    lo_now = [c[3] for c in candles if c[0] >= now - 3600]
    lo_prev = [c[3] for c in candles if now - 7200 <= c[0] < now - 3600]
    return {
        "extension": last / (sum(win6) / len(win6)) - 1 if win6 else None,
        "drawdown_24h": last / hi24 - 1 if hi24 else None,
        "higher_lows": (min(lo_now) > min(lo_prev)) if lo_now and lo_prev else None,
    }


def _usd(v):
    a = abs(v)
    s = f"${a / 1e6:.1f}M" if a >= 1e6 else (f"${a / 1e3:.1f}k" if a >= 1e3 else f"${a:.0f}")
    return ("-" if v < 0 else "+") + s


def momentum_quality(chg1h, flow1h, breadth, extension):
    """Healthy: rising on net buying with most traders accumulating. Overextended: far above its recent average,
    or rising while net selling. Fading: falling on net selling. Mixed: anything else. Returns (label, reasons)."""
    if chg1h is None or flow1h is None:
        return "n/a", []
    if extension is not None and extension >= C.OVEREXTENDED:
        return "Overextended", [f"price {extension:.0%} above its 6h average"]
    if chg1h >= 15 and flow1h <= 0:
        return "Overextended", [f"up {chg1h:.0f}% in 1h while net selling ({_usd(flow1h)})"]
    why = [f"{'up' if chg1h >= 0 else 'down'} {abs(chg1h):.1f}% in 1h", f"net flow {_usd(flow1h)} in 1h"]
    if breadth is not None:
        why.append(f"{breadth:.0%} of traders net buyers")
    if chg1h > 0 and flow1h > 0 and (breadth is None or breadth >= 0.5):
        return "Healthy", why
    if chg1h < 0 and flow1h < 0:
        return "Fading", why
    return "Mixed", why


# ---- Rug-study signals ----------------------------------------------------------------------------
def pool_kind(dex_id, labels):
    """'curve' (still on a launchpad bonding curve), 'concentrated' (CLMM, DLMM, whirlpool) or 'cpmm'
    (constant-product pools: PumpSwap, Raydium AMM and CPMM, Meteora dynamic AMMs and similar)."""
    labels = set(labels or [])
    if (dex_id or "") in C.CURVE_DEX_IDS or labels & C.CURVE_LABELS:
        return "curve"
    if labels & C.CONCENTRATED_LABELS or dex_id == "orca":
        return "concentrated"
    return "cpmm"


def lfdv(liq_usd, fdv_usd):
    """Pool liquidity (both sides, USD) / fully diluted value. In a constant-product pool it is twice the pool's
    share of total supply."""
    return liq_usd / fdv_usd if liq_usd and fdv_usd and fdv_usd > 0 else None


def worst_case_drop(ratio, kind):
    """If every holder outside the pool sold into a constant-product pool, the price would end at (pool share)^2.
    Returns the fall as a fraction (0.96 = -96%); None where the formula does not apply."""
    if ratio is None or kind != "cpmm":
        return None
    share = min(ratio / 2, 1.0)
    return 1 - share * share


def age_minutes(jup, ds, now):
    """Minutes since the coin started trading on a DEX: graduation for launchpad coins, first pool otherwise."""
    import calendar, time as _t
    for key in ("graduated_at", "first_pool_at"):
        v = (jup or {}).get(key)
        if v:
            try:
                return (now - calendar.timegm(_t.strptime(v[:19], "%Y-%m-%dT%H:%M:%S"))) / 60
            except ValueError:
                pass
    created = (ds or {}).get("created")
    return (now - created / 1000) / 60 if created else None


def trade_stats(trades, now):
    """From newest-first [ts, kind, usd, wallet] trades: distinct wallets in the last 10 minutes, the top-5 buyers'
    share of buy volume in that window, and sells as a share of USD volume over the last 15 minutes. The free feed
    holds the last 300 trades; when those span less than 10 minutes the wallet count is scaled up and marked estimated."""
    if trades is None:
        return {}
    if not trades:
        return {"wallets_10m": 0, "wallets_est": False, "top5_share": None, "sell_share_15m": None, "trades_10m": 0}
    span = now - min(t[0] for t in trades)
    w10 = [t for t in trades if t[0] >= now - 600]
    w15 = [t for t in trades if t[0] >= now - 900]
    complete = len(trades) < 300 or span >= 600
    wallets = len({t[3] for t in w10 if t[3]})
    if not complete and span > 0:
        wallets = round(wallets * 600 / span)
    buys = {}
    for _ts, kind, usd, w in w10:
        if kind == "buy" and w:
            buys[w] = buys.get(w, 0) + (usd or 0)
    total = sum(buys.values())
    sv = sum(t[2] or 0 for t in w15 if t[1] == "sell")
    bv = sum(t[2] or 0 for t in w15 if t[1] == "buy")
    return {"wallets_10m": wallets, "wallets_est": not complete,
            "top5_share": sum(sorted(buys.values(), reverse=True)[:5]) / total if total > 0 else None,
            "sell_share_15m": sv / (sv + bv) if sv + bv > 0 else None, "trades_10m": len(w10)}


def risk_flags(ratio, ts, holders, age_min, sell_share_1h):
    """The study's six red flags. Each fired is True, False, or None when its input is missing. Sell share uses the
    last 15 minutes of trades when available, else the last hour from Jupiter."""
    R = C.RISK_FLAGS
    ts = ts or {}
    sell = ts.get("sell_share_15m") if ts.get("sell_share_15m") is not None else sell_share_1h
    rows = [("lfdv", "Liquidity below 0.97× FDV", ratio, lambda v: v < R["lfdv"]),
            ("wallets", "Over 98 wallets traded in 10 minutes", ts.get("wallets_10m"), lambda v: v > R["wallets_10m"]),
            ("sells", "Sells under 33% of recent volume", sell, lambda v: v < R["sell_share"]),
            ("young", "Younger than 4.6 minutes", age_min, lambda v: v < R["age_min"]),
            ("holders", "Over 103 holders", holders, lambda v: v > R["holders"]),
            ("top5", "Top-5 buyers under 21% of buying", ts.get("top5_share"), lambda v: v < R["top5_share"])]
    return [{"id": i, "label": l, "value": v, "fired": None if v is None else bool(t(v))} for i, l, v, t in rows]


def risk_summary(flags, age_min, fdv):
    """Count of fired flags, and the study's historical rates for that count when the coin sits inside what the
    study measured (under a day old, under $1m FDV). Outside it the count is shown without rates."""
    known = [f for f in flags if f["fired"] is not None]
    n = sum(1 for f in known if f["fired"])
    inside = age_min is not None and age_min < C.CALIBRATED_MAX_AGE_H * 60 and fdv is not None and fdv < C.CALIBRATED_MAX_FDV
    complete = len(known) == len(flags)
    return {"count": n, "known": len(known), "complete": complete, "calibrated": inside,
            "rug_rate": C.RUG_RATE_BY_FLAGS.get(n) if inside and complete else None,
            "doubled_rate": C.DOUBLED_RATE_BY_FLAGS.get(n) if inside and complete else None}


def lp_status(rc, gt_lock, kind, jup, pair):
    """(locked or burned %, basis) for the pool the screener prices (DEX Screener's pair). A launchpad that burns or
    locks its graduation pool's LP by design settles it; then RugCheck's figure for that same pool, then
    GeckoTerminal's, then RugCheck's deepest pool (older cached reports only). Otherwise unverified."""
    j = jup or {}
    lp = j.get("launchpad")
    grad = bool(pair and j.get("graduated_pool") == pair and kind == "cpmm")
    if grad and lp in C.LP_LOCKED_BY_DESIGN:
        return 100.0, f"{lp} graduation pool"
    by_pool = (rc or {}).get("lp_by_pool") or {}
    if by_pool.get(pair) is not None:
        return by_pool[pair], "RugCheck"
    if gt_lock is not None:
        return gt_lock, "GeckoTerminal"
    if rc and rc.get("lp_locked_pct") is not None and not by_pool:
        return rc["lp_locked_pct"], "RugCheck, deepest pool"
    if grad:
        return None, f"{lp or 'launchpad'} graduation pool, lock not confirmed"
    return None, "concentrated pool, providers can withdraw" if kind == "concentrated" else "unverified"
