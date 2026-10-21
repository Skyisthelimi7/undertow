"""Attention: how much notice a coin is getting, from the free sources that expose any of it. Pure functions.

Nobody publishes visitor counts for a project's website, its X account or its DEX Screener page; only their owners can
see those. What is public, and is used here instead:
  - DEX Screener: paid boosts running now (in every pair record), ads, an enhanced profile and community takeovers
    (its orders endpoint), and how many links the coin's profile lists;
  - GeckoTerminal's trending pools, which it ranks on user engagement on its site as well as trading (the nearest free
    stand-in for page visits), over the last 5 minutes and the last hour;
  - Jupiter's trending lists over 1 and 6 hours;
  - X follower counts (through a free public mirror) and Telegram members and online counts;
  - the age of the project's website domain, from public registration records.
Spikes are measured against each coin's own recent readings: boosts and trending ranks once an hour for 48 hours, X
followers at every reading for 48 hours, Telegram members at every scan (kept by the scanner)."""
H = 3600
# key, label, unit (the Lab's units): the variables this module adds to the Lab, the gate review and Buy & sell
VARIABLES = [
    ("bst", "DEX Screener boosts running", "n"), ("bst_d1h", "DEX Screener boosts bought in the last hour", "n"),
    ("ads", "DEX Screener ads paid for", "n"), ("ad_new", "DEX Screener ad paid in the last 3h (1 = yes)", "n"),
    ("dsp", "Paid DEX Screener profile (1 = yes)", "n"), ("cto", "Community takeover on DEX Screener (1 = yes)", "n"),
    ("nlinks", "Links on its DEX Screener profile", "n"),
    ("gtr", "GeckoTerminal trending, 1h (40 = first)", "score"), ("gtr5", "GeckoTerminal trending, 5 min (20 = first)", "score"),
    ("trend_new", "Joined GeckoTerminal's 1h trending list in the last hour (1 = yes)", "n"),
    ("jtr", "Jupiter trending, 1h (100 = first)", "score"), ("jtr6", "Jupiter trending, 6h (100 = first)", "score"),
    ("xf", "X followers", "n"), ("xfg", "X follower growth, % an hour over 6h", "chg"),
    ("xf_spike", "X follower spike: last hour's growth minus the day's, points an hour", "chg"),
    ("tgg", "Telegram member growth, % an hour over 6h", "chg"), ("tgo", "Telegram members online", "share"),
    ("web_age", "Website domain age, days", "n"), ("web_free", "Website on a free host or link page (1 = yes)", "n"),
    ("web_new", "Website domain bought for the launch (1 = yes, 0 = older than the coin)", "n"),
]
KEYS = tuple(v[0] for v in VARIABLES)
HIST_KEEP = 48                      # hourly readings of boosts and trending ranks
X_KEEP_H = 48                       # X follower readings
SERIES = ("bst", "gtr", "jtr")      # the hourly series, in this order after the timestamp
# Registrable domains where anyone can put up a page for free: a page there says nothing through its domain's age.
FREE_HOSTS = {
    "vercel.app", "netlify.app", "github.io", "pages.dev", "carrd.co", "webflow.io", "wixsite.com", "wix.com",
    "framer.website", "framer.ai", "framer.app", "linktr.ee", "gitbook.io", "notion.site", "medium.com", "substack.com",
    "x.com", "twitter.com", "t.me", "telegram.me", "tiktok.com", "instagram.com", "facebook.com", "youtube.com",
    "discord.gg", "discord.com", "reddit.com", "warpcast.com", "pump.fun", "dexscreener.com", "solscan.io", "birdeye.so",
    "jup.ag", "raydium.io", "meteora.ag", "bonk.fun", "letsbonk.fun", "believe.app", "wordpress.com", "blogspot.com",
    "weebly.com", "square.site", "glitch.me", "replit.app", "onrender.com", "herokuapp.com", "firebaseapp.com",
    "web.app", "beacons.ai", "bio.link", "linkin.bio", "taplink.cc", "google.com", "telegra.ph", "mirror.xyz",
    "ipfs.io", "bit.ly", "lovable.app", "canva.site", "godaddysites.com", "mystrikingly.com", "strikingly.com",
    "jimdosite.com", "webnode.page", "site123.me", "tilda.ws", "durable.co", "zyrosite.com", "surge.sh",
    "neocities.org", "000webhostapp.com", "bolt.host", "fleek.co", "on-fleek.app", "solana.com", "github.com",
    "gitlab.com", "wikipedia.org", "wikimedia.org", "t.co", "youtu.be", "dropbox.com", "canva.com", "notion.so",
    "gitbook.com", "solana.fm", "coingecko.com", "coinmarketcap.com", "geckoterminal.com", "bags.fm", "moonshot.cc",
    "linkedin.com", "twitch.tv", "kick.com", "threads.net", "bsky.app", "farcaster.xyz", "zora.co", "opensea.io",
    "magiceden.io", "tensor.trade", "imgur.com", "giphy.com", "substack.com", "carrd.co", "about.me", "msha.ke"}
# a domain registered more than this many days before the coin's first pool predates the coin: borrowed or recycled
NEW_DOMAIN_DAYS = 30


def rank_score(ranked, mint, top):
    """top for first place down to 1; 0 when the coin is not among the first `top`; None when the list is unknown."""
    if not ranked:
        return None
    if mint not in ranked:
        return 0
    i = ranked.index(mint)
    return top - i if i < top else 0


def list_scores(lists, mint):
    lists = lists or {}
    out = {"gtr": rank_score(lists.get("gt1h"), mint, 40), "gtr5": rank_score(lists.get("gt5m"), mint, 20),
           "jtr": rank_score(lists.get("jup1h"), mint, 100), "jtr6": rank_score(lists.get("jup6h"), mint, 100)}
    return {k: v for k, v in out.items() if v is not None}


def add_hourly(state, now, point):
    """Append one reading of SERIES to the coin's hourly history when the last is at least 55 minutes old. Returns
    (state, appended)."""
    st = dict(state or {})
    hist = list(st.get("hist") or [])
    if hist and now - hist[-1][0] < 55 * 60:
        return st, False
    hist.append([round(now)] + [point.get(k) for k in SERIES])
    st["hist"] = hist[-HIST_KEEP:]
    return st, True


def value_at(hist, key, t, tol=90 * 60):
    """The hourly series value at or just before time t, if that reading is within tol seconds of t."""
    col = 1 + SERIES.index(key)
    best = None
    for row in hist or []:
        if row[0] > t:
            break
        if row[col] is not None:
            best = row
    return best[col] if best and t - best[0] <= tol else None


def growth(points, t_cur, cur, hours):
    """Average growth in % an hour from the reading nearest `hours` before t_cur up to cur (read at t_cur). points:
    [(ts, value)]. None without an earlier reading between half and one and a half times that far back."""
    if cur is None or cur <= 0:
        return None
    best = None
    for ts, v in points or []:
        gap = t_cur - ts
        if v is None or v <= 0 or gap < 0.5 * hours * H or gap > 1.5 * hours * H:
            continue
        if best is None or abs(gap - hours * H) < abs(best[0] - hours * H):
            best = (gap, v)
    if not best:
        return None
    return ((cur / best[1]) ** (H / best[0]) - 1) * 100


def add_x(rec, handle, reading, now):
    """Store an X reading, keeping the coin's follower readings for X_KEEP_H hours (a new handle starts afresh)."""
    rec = dict(rec or {})
    pts = list(rec.get("h") or []) if rec.get("handle") == handle else []
    out = {"handle": handle, "ts": now}
    if reading and reading.get("followers") is not None:
        pts.append([round(now), reading["followers"]])
        out.update(followers=reading["followers"], tweets=reading.get("tweets"))
    else:
        out["fail"] = 1
        if rec.get("handle") == handle and rec.get("followers") is not None:
            out.update(followers=rec["followers"], tweets=rec.get("tweets"), read_ts=rec.get("read_ts"))
    if "fail" not in out:
        out["read_ts"] = now
    out["h"] = [p for p in pts if now - p[0] <= X_KEEP_H * H]
    return out


def features(state, now, mint, d, lists, tg=None, age_h=None):
    """Attention variables for one coin at one scan. state: the coin's stored attention record (hist, orders, x, web);
    d: its DEX Screener record; lists: this scan's trending lists; tg: this scan's Telegram reading, with growth_6h
    (a fraction an hour) when the scanner has six hours of counts; age_h: hours since the coin's first pool."""
    st, d, tg = state or {}, d or {}, tg or {}
    hist = st.get("hist") or []
    f = {"bst": d.get("boosts") or 0, "nlinks": d.get("n_links")}
    f.update(list_scores(lists, mint))
    before = value_at(hist, "bst", now - H)
    if before is not None:
        f["bst_d1h"] = max(0, f["bst"] - before)
    if "gtr" in f:
        g_before = value_at(hist, "gtr", now - H)
        if g_before is not None:
            f["trend_new"] = 1 if f["gtr"] > 0 and not g_before else 0
    o = st.get("orders")
    if o and now - (o.get("ts") or 0) <= 12 * H and "ads" in o:
        f.update(ads=o.get("ads"), dsp=o.get("profile"), cto=o.get("cto"),
                 ad_new=1 if o.get("ad_last") and now - o["ad_last"] <= 3 * H else 0)
    x = st.get("x") or {}
    if x.get("followers") is not None and now - (x.get("read_ts") or 0) <= 6 * H:
        t_x, pts = x["read_ts"], [tuple(p) for p in x.get("h") or []]
        f["xf"] = x["followers"]
        f["xfg"] = growth(pts, t_x, x["followers"], 6)
        g1, g24 = growth(pts, t_x, x["followers"], 1), growth(pts, t_x, x["followers"], 24)
        if g1 is not None and g24 is not None:
            f["xf_spike"] = g1 - g24
    if tg.get("members"):                     # (the member count itself is the Lab's tgm)
        if tg.get("growth_6h") is not None:
            f["tgg"] = tg["growth_6h"] * 100
        if tg.get("online") is not None:
            f["tgo"] = tg["online"] / tg["members"]
    w = st.get("web")
    if w and w.get("domain"):
        free = bool(w.get("free")) or w["domain"] in FREE_HOSTS        # the list can grow after a domain was read
        f["web_free"] = int(free)
        if w.get("reg") and not free:
            f["web_age"] = max(0.0, (now - w["reg"]) / 86400)
            if age_h is not None:
                f["web_new"] = 1 if f["web_age"] <= age_h / 24 + NEW_DOMAIN_DAYS else 0
    return {k: v for k, v in f.items() if v is not None}


def due(rec, now, every_h):
    """Is a stored reading missing or at least every_h hours old (two minutes' slack for scan timing)?"""
    return not rec or not rec.get("ts") or now - rec["ts"] >= every_h * H - 120


def for_page(state, f):
    """What the X-ray shows: this scan's attention variables and when each source was last read."""
    st = state or {}
    o, x, w = st.get("orders") or {}, st.get("x") or {}, st.get("web") or {}
    return {**(f or {}), "orders_ts": o.get("ts"), "trend_ads": o.get("trend_ads"), "x_handle": x.get("handle"),
            "x_ts": x.get("read_ts"), "x_tweets": x.get("tweets"), "x_failed": x.get("fail"), "domain": w.get("domain"),
            "web_ts": w.get("ts"), "x_hist": [p[1] for p in (x.get("h") or [])][-24:]}
