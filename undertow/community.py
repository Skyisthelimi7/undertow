"""Community: rug calls, votes and crowd tags from signed-in visitors, kept in Supabase (supabase/schema.sql).

The page talks to Supabase itself with the publishable key; row-level security and the four functions in the schema
decide what a signed-in visitor may do. This module is the scanner's side, run once a scan with the secret key
(SUPABASE_SECRET_KEY, a GitHub Actions secret). It lists the tokens that can be called, prices and settles open
calls, and reads the crowd's counts so the Lab can test them like any other variable. The crowd never touches a gate.

A call is priced at the first scan after it is made, so nobody can call with hindsight, and settles 24 hours after
that price on the rug study's definition: rugged if the price fell 80% below the call price before it ever traded
50% above it. Points are set so that guessing scores nothing on average. With r the share of passing coins that
rugged within a day over the last fortnight, a right rug call scores (1 - r) / r and a wrong one -1; a right hold
call scores 1 and a wrong one -(1 - r) / r. A call whose token stopped being priced for the last stretch of its day
is void and scores nothing."""
import datetime as dt
import json, os, urllib.error, urllib.request
from . import config as C

H = 3600
OPEN_STATES = ("IN", "WATCH", "ENTERING")
TOL_S = 40 * 60                   # a price is counted toward a call's day up to this long after the day ends
PAGE = 1000                       # Supabase's default cap on rows per request


def _url():
    return (os.environ.get("SUPABASE_URL") or C.SUPABASE_URL or "").rstrip("/")


def _secret():
    return os.environ.get("SUPABASE_SECRET_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""


def enabled():
    return bool(_url() and _secret())


def _headers(key, extra=None):
    h = {"apikey": key, "Content-Type": "application/json", "Accept": "application/json",
         "User-Agent": "undertow-scanner/0.2"}
    if not key.startswith("sb_"):      # a legacy service_role key is a JWT and also goes in Authorization
        h["Authorization"] = "Bearer " + key
    h.update(extra or {})
    return h


def _req(method, path, body=None, extra=None):
    req = urllib.request.Request(_url() + path, method=method, headers=_headers(_secret(), extra),
                                 data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Supabase {method} {path.split('?')[0]} answered {e.code}: {e.read().decode()[:200]}")
    return json.loads(raw) if raw.strip() else None


def _get_all(path):
    """Every row of a GET, a page at a time: Supabase returns at most 1,000 rows per request."""
    out, off = [], 0
    while True:
        got = _req("GET", f"{path}&limit={PAGE}&offset={off}") or []
        out += got
        if len(got) < PAGE:
            return out
        off += PAGE


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


def ts(s):
    if not s:
        return None
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def state_of(r):
    """The page's state for a scanned row: IN, WATCH, ENTERING or OUT."""
    if r["state_new"] == "IN":
        return "WATCH" if r["fs"] else "IN"
    return "ENTERING" if r["ps"] else "OUT"


def step_call(c, price, now, r):
    """What changes on one open call at this scan. c: the call as Supabase returns it. price: this scan's price for
    its token (None if unpriced). r: the rug base rate. Returns the fields to update (empty if nothing changed)."""
    if c.get("price_at_call") is None:
        if price:
            return {"price_at_call": price, "priced_at": iso(now), "seen_at": iso(now), "hi": 1.0, "lo": 1.0}
        if now - ts(c["created_at"]) > 24 * H:
            return {"outcome": "void", "points": 0, "settled_at": iso(now)}
        return {}
    p0, t0 = c["price_at_call"], ts(c["priced_at"])
    ch = {}
    if price and now - t0 <= 24 * H + TOL_S:
        x = price / p0
        ch["seen_at"] = iso(now)
        if c.get("hi") is None or x > c["hi"]:
            ch["hi"] = x
        if c.get("lo") is None or x < c["lo"]:
            ch["lo"] = x
        if x >= 1.5 and not c.get("up50_at"):
            ch["up50_at"] = iso(now)
        if x <= 0.2 and not c.get("dn80_at"):
            ch["dn80_at"] = iso(now)
    if now - t0 >= 24 * H:
        seen = ts(ch.get("seen_at") or c.get("seen_at") or c["priced_at"])
        dn, up = ts(ch.get("dn80_at") or c.get("dn80_at")), ts(ch.get("up50_at") or c.get("up50_at"))
        rugged = dn is not None and (up is None or dn < up)
        if not rugged and seen < t0 + 18 * H:         # lost sight of it for the last quarter of its day
            ch.update(outcome="void", points=0, settled_at=iso(now))
            return ch
        k = (1 - r) / r
        pts = (k if rugged else -1.0) if c["side"] == "rug" else (-k if rugged else 1.0)
        ch.update(outcome="rug" if rugged else "held", base_rate=round(r, 4), points=round(pts, 2), settled_at=iso(now))
    return ch


def base_rate(r):
    return min(max(r if r is not None else C.CALL_BASE_RATE, 0.03), 0.5)


def list_tokens(rows, now):
    """Every token the screener shows, so calls, votes and tags are accepted on them (and only on them)."""
    body = [{"mint": r["t"]["mint"], "symbol": (r["d"].get("symbol") or r["t"].get("symbol") or "")[:32],
             "state": state_of(r), "price": r["d"].get("price"), "updated_at": iso(now)} for r in rows]
    for i in range(0, len(body), 500):
        _req("POST", "/rest/v1/tokens?on_conflict=mint", body[i:i + 500],
             {"Prefer": "resolution=merge-duplicates,return=minimal"})
    return len(body)


def settle(ds_all, now, rate):
    """Price new calls, follow open ones and settle those whose day is over. Returns (priced, settled)."""
    calls = _get_all("/rest/v1/calls?settled_at=is.null&select=id,mint,side,created_at,price_at_call,priced_at,"
                     "seen_at,hi,lo,up50_at,dn80_at&order=id")
    r = base_rate(rate)
    priced = settled = 0
    for c in calls:
        ch = step_call(c, (ds_all.get(c["mint"]) or {}).get("price"), now, r)
        if not ch:
            continue
        _req("PATCH", f"/rest/v1/calls?id=eq.{int(c['id'])}", ch, {"Prefer": "return=minimal"})
        priced += "price_at_call" in ch
        settled += "settled_at" in ch
    return priced, settled


def sync(rows, ds_all, now, rate):
    """The scanner's whole community step; never lets a Supabase problem stop the scan."""
    try:
        n = list_tokens(rows, now)
        priced, settled = settle(ds_all, now, rate)
        return f"{n} tokens listed, {priced} new calls priced, {settled} settled (rug base rate {base_rate(rate):.0%})"
    except Exception as e:                                  # noqa: BLE001 - reported, never fatal
        return f"skipped: {e}"


def crowd():
    """{mint: {calls, rug_share, net_votes, bad_tags}} from the public per-token counts, for the Lab."""
    try:
        got = _get_all("/rest/v1/token_crowd?select=mint,rug_calls,hold_calls,watch,avoid,tags&order=mint")
    except Exception:                                       # noqa: BLE001 - the crowd is optional
        return {}
    out = {}
    for x in got:
        rug, hold = x.get("rug_calls") or 0, x.get("hold_calls") or 0
        tags = x.get("tags") or {}
        out[x["mint"]] = {"calls": rug + hold, "rug_share": rug / (rug + hold) if rug + hold >= 3 else None,
                          "net_votes": (x.get("watch") or 0) - (x.get("avoid") or 0),
                          "bad_tags": (tags.get("bundled") or 0) + (tags.get("rug_suspected") or 0)}
    return out
