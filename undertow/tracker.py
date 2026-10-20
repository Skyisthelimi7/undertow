"""Entry tracker: what happened after a token first passed every gate. Pure functions.
A tracker is a dict: in_ts, in_price, in_mcap, ath_price, ath_ts, low_price, low_ts, candles_to, out{hours: multiple}."""
H = 3600


def start(now, price, mcap):
    return {"in_ts": now, "in_price": price, "in_mcap": mcap, "ath_price": price, "ath_ts": now,
            "low_price": price, "low_ts": now, "candles_to": None, "out": {}}


def update(trk, candles, now, live_price, hours, reach_h=24):
    """Fold 5-minute candles (ascending [ts,o,h,l,c,v]) and the live price into the tracker.
    Idempotent: replaying the same candles changes nothing. Candles that open before entry are ignored, so a
    pre-entry high never counts as the ATH. reach_h is how far back the candle source reaches."""
    t = dict(trk)
    t["out"] = dict(trk.get("out") or {})
    t0, p0 = t["in_ts"], t["in_price"]
    usable = [c for c in candles or [] if c[0] >= t0]
    day_end = t0 + 24 * H
    for ts, _o, hi, lo, cl, _v in usable:
        if hi > t["ath_price"]:
            t["ath_price"], t["ath_ts"] = hi, ts
        if lo < t["low_price"]:
            t["low_price"], t["low_ts"] = lo, ts
        if ts < day_end and p0:                              # the rug study's first-day outcome marks
            _first(t, "up50_ts", ts, hi >= 1.5 * p0)
            _first(t, "rug_ts", ts, cl <= 0.2 * p0)
            _first(t, "doubled_ts", ts, hi >= 2 * p0)
    if usable:
        t["candles_to"] = max(t["candles_to"] or 0, usable[-1][0])
    if live_price and p0 and now < t0 + 24 * H:
        _first(t, "up50_ts", now, live_price >= 1.5 * p0)
        _first(t, "rug_ts", now, live_price <= 0.2 * p0)
        _first(t, "doubled_ts", now, live_price >= 2 * p0)
    if live_price:
        if live_price > t["ath_price"]:
            t["ath_price"], t["ath_ts"] = live_price, now
        if live_price < t["low_price"]:
            t["low_price"], t["low_ts"] = live_price, now
    if candles is not None and p0:
        reach_from = now - reach_h * H
        for hrs in hours:
            key, target = str(hrs), t0 + hrs * H
            if key in t["out"] or now < target + 300:
                continue
            upto = [c for c in usable if c[0] <= target]
            if upto:
                t["out"][key] = upto[-1][4] / p0          # close of the last candle at or before the horizon
            elif t0 >= reach_from:
                t["out"][key] = 1.0                       # candles cover the whole period and none traded: unchanged
            else:
                t["out"][key] = None                      # the horizon fell in a gap longer than the candle reach
    return t


def _first(t, key, ts, hit):
    if hit and (t.get(key) is None or ts < t[key]):
        t[key] = ts


def day_outcome(trk, now):
    """The rug study's labels for the first day after entry. rug: closed 80% below entry before ever trading 50% above
    it. doubled: traded at 2x. True or False once known; None while the day is still running and nothing has fired."""
    t0 = trk["in_ts"]
    up, rug, dbl = trk.get("up50_ts"), trk.get("rug_ts"), trk.get("doubled_ts")
    over = now >= t0 + 24 * H + 300
    rugged = True if (rug is not None and (up is None or rug < up)) else (False if (over or up is not None) else None)
    doubled = True if dbl is not None else (False if over else None)
    return rugged, doubled


def summary(trk, live_price, live_mcap, now=None):
    """Multiples and market caps for display. Supply is taken from the entry (mcap / price)."""
    p0 = trk["in_price"]
    supply = trk["in_mcap"] / p0 if p0 else None
    live_mcap = live_mcap if live_mcap else (live_price * supply if live_price and supply else None)
    return {
        "in_ts": trk["in_ts"], "in_mcap": trk["in_mcap"],
        "now_mcap": live_mcap, "now_x": (live_price / p0) if live_price and p0 else None,
        "ath_mcap": trk["ath_price"] * supply if supply else None, "ath_ts": trk["ath_ts"],
        "ath_x": trk["ath_price"] / p0 if p0 else None,
        "low_x": trk["low_price"] / p0 if p0 else None, "low_ts": trk["low_ts"],
        "out": trk.get("out") or {},
        "rug_24h": day_outcome(trk, now)[0] if now else None, "doubled_24h": day_outcome(trk, now)[1] if now else None,
    }
