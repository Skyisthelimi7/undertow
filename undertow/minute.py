"""Minute data for quick trades: the short-window variables quick entry and exit rules read, worked out from one
reading a minute per coin (fast.py takes the readings). Pure functions."""
import hashlib
from collections import deque

H = 3600
# key, label, unit: the short-window variables, in the Lab's units
VARIABLES = [
    ("m1", "Price change since the last minute", "chg"), ("m5", "Price change, 5 min (DEX Screener)", "chg"),
    ("m15", "Price change, 15 min", "chg"), ("m30", "Price change, 30 min", "chg"),
    ("up30", "Rise from its 30-min low", "chg"), ("dn30", "Price vs its 30-min high", "chg"),
    ("v5x", "Volume pace: last 5 min vs the hour's average", "x"),
    ("bs5", "Buys ÷ sells, 5 min (trade counts)", "ratio"),
    ("gtr5_d15", "Change in GeckoTerminal 5-min trending score over 15 min", "n"),
    ("bst_d15", "DEX Screener boosts bought in the last 15 min", "n"),
    ("ad_imp", "DEX Screener ad impressions listed in its ads feed, last 24h", "n"),
]
KEYS = tuple(v[0] for v in VARIABLES)
WINDOW = 65 * 60                   # how much of each coin's minute history the features read
TICK_COLS = ("ts", "mint", "price", "liq", "mc", "v5", "v1h", "b5", "s5", "c5", "c1h", "bst", "gtr5")


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v


def tick_of(d, mint, ts, gtr5=None):
    """One minute reading from a DEX Screener token record (sources.ds_tokens), or None when it has no price."""
    if not d or not d.get("price"):
        return None
    vol, chg = d.get("vol") or {}, d.get("chg") or {}
    return {"ts": ts, "mint": mint, "price": d["price"], "liq": d.get("liq"), "mc": d.get("mcap"), "v5": vol.get("m5"),
            "v1h": vol.get("h1"), "b5": d.get("buys5"), "s5": d.get("sells5"), "c5": chg.get("m5"), "c1h": chg.get("h1"),
            "bst": d.get("boosts") or 0, "gtr5": gtr5}


def draw(mint, ts, salt, share):
    """A random control's pick at one minute: a fixed hash of the coin, the minute and the rule, true for about
    `share` of readings (the same draw whenever the minute is replayed)."""
    h = int(hashlib.md5(f"{mint}|{int(ts // 60)}|{salt}".encode()).hexdigest()[:8], 16)
    return h / 0xFFFFFFFF < share


class Coin:
    """One coin's recent minutes: (ts, price, gtr5, bst) readings for the last WINDOW seconds."""

    def __init__(self):
        self.q = deque()

    def add(self, t):
        self.q.append((t["ts"], t["price"], t.get("gtr5"), t.get("bst")))
        while self.q and t["ts"] - self.q[0][0] > WINDOW:
            self.q.popleft()

    def _at(self, ts, col, tol=3 * 60):
        """The reading nearest ts (within tol seconds) in column col, among those not after ts."""
        best = None
        for row in self.q:
            if row[0] > ts + 1:
                break
            if row[col] is not None and abs(row[0] - ts) <= tol:
                best = row[col]
        return best


def features(coin, t, ads=None):
    """The short-window variables for one coin at one minute. coin: its Coin with t already added; t: this minute's
    reading; ads: {"imp": impressions in the last 24h} from DEX Screener's ads feed."""
    f, ts, p = {}, t["ts"], t.get("price")
    if not p:
        return f
    q = coin.q
    if len(q) >= 2 and ts - q[-2][0] <= 3 * 60 and q[-2][1]:
        f["m1"] = (p / q[-2][1] - 1) * 100
    if _num(t.get("c5")):
        f["m5"] = t["c5"]
    for key, mins in (("m15", 15), ("m30", 30)):
        then = coin._at(ts - mins * 60, 1)
        if then:
            f[key] = (p / then - 1) * 100
    last30 = [r[1] for r in q if ts - r[0] <= 30 * 60 and r[1]]
    if len(last30) >= 10:                              # at least ten minutes of the half hour seen
        f["up30"] = (p / min(last30) - 1) * 100
        f["dn30"] = (p / max(last30) - 1) * 100
    if _num(t.get("v5")) and t.get("v1h"):
        f["v5x"] = t["v5"] * 12 / t["v1h"]
    if t.get("b5") is not None and t.get("s5") is not None and (t["b5"] or t["s5"]):
        f["bs5"] = t["b5"] / max(t["s5"], 1)
    if t.get("gtr5") is not None:
        before = coin._at(ts - 15 * 60, 2)
        if before is not None:
            f["gtr5_d15"] = t["gtr5"] - before
    if t.get("bst") is not None:
        before = coin._at(ts - 15 * 60, 3)
        if before is not None:
            f["bst_d15"] = max(0, t["bst"] - before)
    if ads and ads.get("imp") is not None:
        f["ad_imp"] = ads["imp"]
    if _num(t.get("liq")):
        f["liq"] = t["liq"]
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in f.items()}


class Ads:
    """DEX Screener's ads feed by coin: each ad once (by its start time), with the impressions the feed lists for it
    and when this scanner first saw it, so a reading only counts ads already seen by then."""

    def __init__(self, feeds=()):
        self.by = {}
        self.add(feeds)

    def add(self, feeds):
        for f_ts, m, kind, _amount, _total, impressions, at in feeds:
            if kind != "ads" or not m:
                continue
            ads = self.by.setdefault(m, {})
            key = at or f_ts
            seen, imp = ads.get(key, (f_ts, None))
            ads[key] = (min(seen, f_ts), impressions if impressions is not None else imp)

    def at(self, mint, ts):
        """{"imp": impressions of the coin's ads that started in the 24 hours before ts} or None (no ad seen)."""
        ads = self.by.get(mint)
        if not ads:
            return None
        live = [imp or 0 for key, (seen, imp) in ads.items() if seen <= ts and ts - key <= 24 * H]
        return {"imp": sum(live)} if live else None
