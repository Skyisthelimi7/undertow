"""The minute layer: a sampler that reads DEX Screener once a minute for the coins that matter while a scan runs, and
the minute ledger that steps every open paper trade on those readings and lets the quick rules buy (minute.py turns
the readings into the short-window variables quick rules read).

How a scan uses them (scan.py): it reads every price once (the scan's reading, which steps every open paper trade),
then starts the sampler, works out the gates for 10 to 15 minutes, and stops the sampler just before stepping the
ledger. Scans run back to back, so the minutes are nearly continuous; the gap is a run's start-up and its own price
reading, about two minutes.

Each round, for every watched coin (inside the screener, close to passing, recently passing, or holding a paper trade):
price, liquidity, market cap, 5-minute and 1-hour volume, 5-minute buys and sells, 5-minute and 1-hour price change and
paid boosts running, all from DEX Screener's pair records, which it recomputes as trades land. Every other round:
GeckoTerminal's 5-minute trending list (refreshed every 60 seconds on the free API) and DEX Screener's feeds of the
latest paid boosts and ads, with the impression counts its ads feed lists. (DEX Screener's trending score counts
visitors to its pages, but its API publishes neither the score nor the visitors.)

Everything runs in memory in the sampler's thread; the scan writes the readings and the ledger's changes to the
database afterwards, so the database is only touched from the scan's own thread. Quick rules may buy a coin only when
it passed every gate at the latest scan whose gates had been worked out by then: during a scan that is the previous
scan, since this one's gates are still being worked out. Live alerts go out from here, as the minute happens."""
import threading, time
from collections import defaultdict
from . import sources as S, attention as ATT, minute as MIN, trade as TRD


class Book:
    """The minute ledger.

    sigs: the open paper trades (store dicts), stepped in place. exits: {policy id: policy} on the bench. rules: the
    bench's rules; quick ones (testing or live, with their own exit on the bench) are checked at every minute.
    eligible: {mint: the variables of the scan that counts} for coins that passed every gate. last: {(rule, mint):
    (latest entry, still open)} (store.fast_last). held: coins with a live trade open. ads: minute.Ads. syms: {mint:
    symbol}. start: the exit policies a new quick trade is followed under. alert(kind, sig, info): live trades opened
    or closed (optional)."""

    def __init__(self, sigs, exits, rules, eligible, last, held, ads, syms, cfg, fcfg, start, alert=None):
        self.by_mint = defaultdict(list)
        for s in sigs:
            self.by_mint[s["mint"]].append(s)
        self.exits, self.cfg, self.fcfg, self.start = exits, cfg, fcfg, list(start)
        self.rules = [r for r in rules if r.get("fast") and r.get("status") in ("testing", "live") and r.get("exit") in exits]
        self.eligible, self.last, self.held = eligible, dict(last), set(held)
        self.ads, self.syms, self.alert = ads, syms, alert
        self.coins = defaultdict(MIN.Coin)
        self.changed, self.new = set(), []
        self.rounds = self.steps = self.closed = 0

    def warm(self, ticks):
        """Earlier minutes, so the short-window variables have their history; nothing is stepped or bought."""
        for t in ticks:
            self.coins[t["mint"]].add(t)

    def busy(self, rid, mint, ts):
        x = self.last.get((rid, mint))
        return bool(x) and (x[1] or ts - x[0] < self.fcfg["reentry_min"] * 60)

    def round(self, rows, feeds=()):
        """One minute: every reading steps the coin's open trades, then the quick rules look at the coin. The round's
        feed entries count from the next minute (they were read after the prices)."""
        self.rounds += 1
        for t in sorted(rows, key=lambda r: r["mint"]):
            m = t["mint"]
            coin = self.coins[m]
            coin.add(t)
            obs = {"price": t["price"], "liq": t.get("liq"), "c1h": t.get("c1h")}
            for s in self.by_mint.get(m, ()):
                if not s.get("done"):
                    self._step(s, obs, t["ts"])
            if m in self.eligible and self.rules:
                self._decide(m, t, coin)
        self.ads.add(feeds)

    def _step(self, s, obs, ts):
        out, sst, miss, lp, ll, done = TRD.advance(s, obs, ts, self.exits, self.cfg, tick=True)
        was = s.get("ref_out_ts")
        ref_out = TRD.ref_closed(s, out, self.exits, ts)
        s.update(out=out, st=sst, miss=miss, last_price=lp, last_liq=ll, done=1 if done else 0, ref_out_ts=ref_out)
        self.steps += 1
        if s.get("id") is not None:
            self.changed.add(s["id"])
        if was is None and ref_out is not None:
            self.closed += 1
            k = (s["rule"], s["mint"])
            if k in self.last:                 # a quick rule may buy the coin again once its trade has closed
                self.last[k] = (self.last[k][0], False)
            if s.get("live"):
                self.held.discard(s["mint"])
                if self.alert and s["ref"] in out:
                    self.alert("sell", s, out[s["ref"]])

    def _decide(self, m, t, coin):
        ts, f = t["ts"], None
        for r in self.rules:
            rid = r["id"]
            if self.busy(rid, m, ts):
                continue
            if f is None:
                f = {**self.eligible[m], **MIN.features(coin, t, self.ads.at(m, ts))}
            if not TRD.fires(r, f) or (r.get("random") and not MIN.draw(m, ts, rid, r["random"])):
                continue                   # a random control keeps its conditions (the pool floor) and then draws
            live = r["status"] == "live" and m not in self.held
            keys = TRD.SHOWN_AT_ENTRY + list(MIN.KEYS) + ["rug", "rug_hi"] + [c[0] for c in r.get("all") or []]
            s = {"id": None, "rule": rid, "mint": m, "sym": self.syms.get(m), "in_ts": ts, "in_price": t["price"],
                 "in_liq": t.get("liq"), "in_mc": t.get("mc"), "f": {k: f[k] for k in keys if f.get(k) is not None},
                 "ref": r["exit"], "live": 1 if live else 0, "out": {}, "st": TRD.start_states(t["price"], self.start),
                 "miss": 0, "last_price": t["price"], "last_liq": t.get("liq"), "done": 0, "ref_out_ts": None}
            self.new.append(s)
            self.by_mint[m].append(s)
            self.last[(rid, m)] = (ts, True)
            if live:
                self.held.add(m)
                if self.alert:
                    self.alert("buy", s, r)


class Sampler(threading.Thread):
    """Reads the watched coins every `every` seconds until stopped, handing each round to the minute ledger.
    ticks: [dict of minute.TICK_COLS]; feeds: [(ts, mint, kind, amount, total, impressions, at)]. send(kind, sig,
    info): delivers the ledger's live alerts, outside the lock so a slow message never holds up stop()."""

    def __init__(self, mints, book=None, every=60.0, slow_every=2, max_coins=240, send=None):
        super().__init__(daemon=True, name="undertow-sampler")
        self.mints = list(dict.fromkeys(mints))[:max_coins]
        self.book, self.every, self.slow_every, self.send = book, every, slow_every, send
        self.ticks, self.feeds, self.outbox = [], [], []
        if book is not None and send is not None:
            book.alert = lambda kind, sig, info: self.outbox.append((kind, dict(sig), info))
        self.rounds = self.errors = 0
        self.gt_ok = self.gt_tries = 0
        self.started = self.stopped = None
        self._halt, self._lock, self._closed = threading.Event(), threading.Lock(), False

    def run(self):
        self.started = time.time()
        while not self._halt.is_set():
            t0 = time.time()
            try:
                self.round()
            except Exception:                        # a failed round is skipped; the next one tries again
                self.errors += 1
            self.rounds += 1
            self._halt.wait(max(1.0, self.every - (time.time() - t0)))

    def round(self):
        d = S.ds_tokens(self.mints, quiet=True, tries=1, timeout=10) if self.mints else {}
        ts = time.time()                             # the prices are as of the read, not the round's start
        gt, feeds = None, []
        if self.rounds % self.slow_every == 0:
            self.gt_tries += 1
            gt = S.gt_trending("5m", 1, quiet=True)
            if gt is not None:
                self.gt_ok += 1
            for kind in ("boosts", "ads"):
                for e in S.ds_feed(kind, quiet=True) or []:
                    feeds.append((time.time(), e["mint"], kind, e.get("amount"), e.get("total"), e.get("impressions"),
                                  e.get("at")))
        rows = [t for t in (MIN.tick_of(d.get(m), m, ts, ATT.rank_score(gt, m, 20) if gt is not None else None)
                            for m in self.mints) if t]
        with self._lock:                             # nothing changes once stop() has returned
            if self._closed:
                return
            self.ticks.extend(rows)
            self.feeds.extend(feeds)
            if self.book is not None:
                try:
                    self.book.round(rows, feeds)
                except Exception:
                    self.errors += 1
            out, self.outbox = self.outbox, []
        for a in out:
            try:
                self.send(*a)
            except Exception:
                self.errors += 1

    def stop(self, wait=90):
        self._halt.set()
        if self.is_alive():
            self.join(wait)
        with self._lock:
            self._closed = True
        self.stopped = time.time()
        return self
