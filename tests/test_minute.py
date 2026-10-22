"""The minute layer: the short-window variables (undertow/minute.py), the minute ledger and the sampler
(undertow/fast.py), the scan's side of them (scan.scan_step, start_minutes, finish_minutes, trade_step), and the
minute-horizon correlations (corr.analyse_fast)."""
import unittest, sys, pathlib, tempfile, os, json, time, math, random, urllib.error
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from undertow import minute as MIN, fast as FAST, trade as T, config as C, scan as SC, corr as CORR, sources as S, http
from undertow.store import Store

H = 3600
QUICK = {e["id"]: e for e in C.EXIT_POOL if e.get("max_h", 24) <= 2}


def tick(ts, mint, price, **kw):
    t = {"ts": ts, "mint": mint, "price": price, "liq": 2e5, "mc": price * 1e6, "v5": 1000.0, "v1h": 12000.0, "b5": 10,
         "s5": 10, "c5": 0.0, "c1h": 0.0, "bst": 0, "gtr5": None}
    t.update(kw)
    return t


class Variables(unittest.TestCase):
    def test_short_window_variables(self):
        c, t0 = MIN.Coin(), 10_000.0
        rows = [tick(t0 + i * 60, "A", 1.0 + 0.01 * i, gtr5=(i if i % 2 == 0 else None), bst=(0 if i < 20 else 30))
                for i in range(31)]
        for r in rows:
            c.add(r)
        cur = {**rows[-1], "c5": 4.0, "v5": 3000.0, "v1h": 12000.0, "b5": 30, "s5": 10}
        f = MIN.features(c, cur, {"imp": 5000})
        self.assertAlmostEqual(f["m1"], (1.30 / 1.29 - 1) * 100, places=3)
        self.assertEqual(f["m5"], 4.0)                                     # DEX Screener's own 5-minute change
        self.assertAlmostEqual(f["m15"], (1.30 / 1.15 - 1) * 100, places=3)
        self.assertAlmostEqual(f["m30"], (1.30 / 1.00 - 1) * 100, places=3)
        self.assertAlmostEqual(f["up30"], 30.0, places=3)
        self.assertAlmostEqual(f["dn30"], 0.0, places=6)
        self.assertAlmostEqual(f["v5x"], 3.0)                               # 5 minutes at 3x the hour's pace
        self.assertAlmostEqual(f["bs5"], 3.0)
        self.assertEqual(f["gtr5_d15"], 30 - 14)                           # trending score now against 15 min ago
        self.assertEqual(f["bst_d15"], 30)
        self.assertEqual(f["ad_imp"], 5000)

    def test_too_few_minutes_leave_the_window_variables_out(self):
        c = MIN.Coin()
        for i in range(5):
            c.add(tick(100.0 + i * 60, "A", 1.0))
        f = MIN.features(c, tick(400.0, "A", 1.0))
        self.assertNotIn("up30", f)
        self.assertNotIn("m15", f)

    def test_ads_count_each_ad_once_from_when_it_was_seen(self):
        a = MIN.Ads([(100.0, "A", "ads", None, None, 1000, 90.0), (160.0, "A", "ads", None, None, 1000, 90.0),
                     (170.0, "A", "ads", None, None, 4000, 150.0), (170.0, "A", "boosts", 10, 10, None, 150.0)])
        self.assertIsNone(a.at("A", 99.0))                                  # nothing seen yet
        self.assertEqual(a.at("A", 165.0), {"imp": 1000})
        self.assertEqual(a.at("A", 200.0), {"imp": 5000})
        self.assertIsNone(a.at("A", 90.0 + 25 * H))                         # older than a day
        self.assertIsNone(a.at("B", 200.0))

    def test_random_draw_is_fixed_and_near_its_share(self):
        self.assertEqual(MIN.draw("A", 1234.0, "r", 0.5), MIN.draw("A", 1250.0, "r", 0.5))   # same minute
        hits = sum(MIN.draw(f"M{i}", 60.0 * i, "fast_random", 0.02) for i in range(20_000))
        self.assertTrue(250 < hits < 550)

    def test_tick_from_a_dex_screener_record(self):
        d = {"price": 2.0, "liq": 5e4, "mcap": 2e6, "vol": {"m5": 10.0, "h1": 100.0}, "chg": {"m5": 1.0, "h1": 2.0},
             "buys5": 3, "sells5": 1, "boosts": 20}
        t = MIN.tick_of(d, "A", 50.0, 18)
        self.assertEqual((t["price"], t["mc"], t["v5"], t["b5"], t["bst"], t["gtr5"]), (2.0, 2e6, 10.0, 3, 20, 18))
        self.assertIsNone(MIN.tick_of({"price": None}, "A", 50.0))


class TickSteps(unittest.TestCase):
    def test_cooling_off_is_judged_at_scans_only(self):
        pol = {"id": "c", "cool": 20, "cool_drop": 5, "max_h": 8}
        pos, cfg = {"in_ts": 0.0, "in_price": 1.0, "in_liq": 1e12}, {"usd": 500, "fee_pct": 0.0}
        st = T.new_state(1.0)
        self.assertIsNone(T.step(pol, pos, st, 1.3, 1e12, 0, 900, cfg))      # a scan: the push, prev 1.3
        self.assertIsNone(T.step(pol, pos, st, 1.2, 1e12, 0, 960, cfg, tick=True))   # a minute's dip is not a scan's
        self.assertEqual(st["prev"], 1.3)
        self.assertEqual(T.step(pol, pos, st, 1.2, 1e12, 0, 1800, cfg)[2], "cooled off")


def book(sigs=(), rules=(), eligible=None, last=None, held=(), alert=None, exits=None):
    ex = exits or {**QUICK, "tp10_8h": {"id": "tp10_8h", "tp": 10, "max_h": 8}}
    return FAST.Book(list(sigs), ex, list(rules), eligible or {}, last or {}, held, MIN.Ads(), {"A": "AAA", "B": "BBB"},
                     C.TRADE, C.FAST, list(ex), alert)


def quick_rule(rid="fast_breakout", status="testing", **kw):
    r = next(dict(x) for x in C.FAST_RULES if x["id"] == rid)
    r.update(status=status, added=0.0, since=0.0, **kw)
    return r


class MinuteLedger(unittest.TestCase):
    def open_sig(self, sid=1, mint="A", ts=0.0, price=1.0, ref="tp10_8h", live=0, rule="r1"):
        return {"id": sid, "rule": rule, "mint": mint, "sym": mint, "in_ts": ts, "in_price": price, "in_liq": 2e5,
                "in_mc": 1e6, "f": {}, "ref": ref, "live": live, "out": {}, "st": T.start_states(price, ["tp10_8h", "q15m"]),
                "miss": 0, "last_price": price, "last_liq": 2e5, "done": 0, "ref_out_ts": None}

    def test_open_trades_are_stepped_on_every_minute(self):
        alerts = []
        b = book([self.open_sig(live=1)], alert=lambda k, s, i: alerts.append((k, i[2])))
        b.round([tick(300.0, "A", 1.05)])
        b.round([tick(360.0, "A", 1.11)])                                   # the +10% target, at this minute
        s = b.by_mint["A"][0]
        self.assertEqual(s["out"]["tp10_8h"][2], "target")
        self.assertEqual(s["out"]["tp10_8h"][3], 360.0)
        self.assertEqual(s["ref_out_ts"], 360.0)
        self.assertEqual(b.changed, {1})
        self.assertIn(("sell", "target"), alerts)                         # a live trade's sale alerts as it happens
        b.round([tick(960.0, "A", 1.11)])
        self.assertEqual(s["out"]["q15m"][2], "time")
        self.assertTrue(s["done"])

    def test_quick_rules_buy_eligible_coins_once_until_the_trade_closes(self):
        r = quick_rule("fast_breakout")                                     # m5 >= 3, v5x >= 2, bs5 >= 1.2, up30 < 25
        b = book(rules=[r], eligible={"A": {"mc": 1e6}})
        hist = [tick(1000.0 + i * 60, m, 1.0) for i in range(20) for m in ("A", "B")]
        b.warm(hist)
        hot = dict(c5=4.0, v5=3000.0, b5=30, s5=10)
        b.round([tick(2200.0, "A", 1.04, **hot), tick(2200.0, "B", 1.04, **hot)])
        self.assertEqual([(s["mint"], s["rule"], s["ref"]) for s in b.new], [("A", "fast_breakout", "q10_sl7_2h")])
        s = b.new[0]
        self.assertEqual(s["in_ts"], 2200.0)
        self.assertEqual(set(s["st"]), set(b.start))                       # followed under every exit on the bench
        self.assertEqual(s["out"], {})                                      # not stepped by the minute it bought on
        self.assertIn("v5x", s["f"])
        b.round([tick(2260.0, "A", 1.05, **hot)])
        self.assertEqual(len(b.new), 1)                                     # busy while its trade is open
        b.round([tick(2320.0, "A", 1.16, **hot)])                           # +11.5%: q10_sl7_2h takes its target
        self.assertEqual(s["out"]["q10_sl7_2h"][2], "target")
        self.assertEqual(b.last[("fast_breakout", "A")], (2200.0, False))
        b.round([tick(2380.0, "A", 1.17, **hot)])
        self.assertEqual(len(b.new), 1)                                     # closed, but within reentry_min of buying
        for ts in range(2440, 2200 + C.FAST["reentry_min"] * 60, 60):       # quiet minutes: nothing to buy
            b.round([tick(float(ts), "A", 1.17)])
        self.assertEqual(len(b.new), 1)
        b.round([tick(2200.0 + C.FAST["reentry_min"] * 60, "A", 1.18, **hot)])
        self.assertEqual(len(b.new), 2)

    def test_random_control_and_live_alerts(self):
        alerts = []
        rnd = quick_rule("fast_random", status="live")
        b = book(rules=[rnd], eligible={"A": {}}, alert=lambda k, s, i: alerts.append((k, s["mint"])))
        ts = next(t for t in (60.0 * i for i in range(50_000)) if MIN.draw("A", t, "fast_random", rnd["random"]))
        b.round([tick(ts, "A", 1.0)])
        self.assertEqual(len(b.new), 1)
        self.assertTrue(b.new[0]["live"])
        self.assertEqual(alerts, [("buy", "A")])
        self.assertIn("A", b.held)

    def test_quick_rules_skip_thin_pools_and_the_random_control_too(self):
        rnd = quick_rule("fast_random", random=1.0)
        self.assertIn(["liq", ">=", C.FAST["min_liq"]], rnd["all"])
        b = book(rules=[rnd], eligible={"A": {}, "B": {}})
        b.round([tick(60.0, "A", 1.0, liq=C.FAST["min_liq"] - 1), tick(60.0, "B", 1.0, liq=C.FAST["min_liq"])])
        self.assertEqual([s["mint"] for s in b.new], ["B"])

    def test_held_coins_open_paper_trades_only(self):
        rnd = quick_rule("fast_random", status="live")
        b = book(rules=[rnd], eligible={"A": {}}, held={"A"})
        ts = next(t for t in (60.0 * i for i in range(50_000)) if MIN.draw("A", t, "fast_random", rnd["random"]))
        b.round([tick(ts, "A", 1.0)])
        self.assertFalse(b.new[0]["live"])                                  # one live position per coin


class FakeSources:
    def __init__(self, prices):
        self.prices, self.calls = prices, []

    def __enter__(self):
        self.saved = (S.ds_tokens, S.gt_trending, S.ds_feed)
        S.ds_tokens = self.ds
        S.gt_trending = lambda duration="1h", pages=2, quiet=False: self.calls.append(("gt", quiet)) or ["A"]
        S.ds_feed = lambda kind, quiet=False: self.calls.append((kind, quiet)) or (
            [{"mint": "A", "amount": None, "total": None, "impressions": 2500, "at": 50.0}] if kind == "ads" else [])
        return self

    def __exit__(self, *a):
        S.ds_tokens, S.gt_trending, S.ds_feed = self.saved

    def ds(self, mints, quiet=False, tries=3, timeout=25):
        self.calls.append(("ds", quiet))
        out = {}
        for m in mints:
            p = self.prices.get(m)
            if p:
                out[m] = {"symbol": m, "price": p() if callable(p) else p, "liq": 2e5, "mcap": 1e6,
                          "vol": {"m5": 3000.0, "h1": 12000.0}, "chg": {"m5": 4.0, "h1": 1.0}, "buys5": 30,
                          "sells5": 10, "boosts": 0}
        return out


class SamplerRound(unittest.TestCase):
    def test_a_round_reads_prices_then_the_slow_lists_every_other_round(self):
        with FakeSources({"A": 1.0, "B": 2.0}) as fs:
            sm = FAST.Sampler(["A", "B", "C"], None, every=60, slow_every=2)
            sm.round(); sm.rounds += 1; sm.round()
        self.assertEqual(len(sm.ticks), 4)                                  # C has no price
        self.assertEqual(sm.ticks[0]["gtr5"], 20)                           # first on GeckoTerminal's list
        self.assertEqual(sm.ticks[1]["gtr5"], 0)                            # read, not on it
        self.assertIsNone(sm.ticks[2]["gtr5"])                              # not read this round
        self.assertEqual(sm.gt_tries, 1)
        self.assertEqual([f[2] for f in sm.feeds], ["ads"])
        self.assertTrue(all(q for _k, q in fs.calls))                       # every call quiet: never trips the scan
        self.assertEqual(fs.calls[0][0], "ds")                              # prices first

    def test_live_alerts_leave_through_the_outbox(self):
        sent = []
        rnd = quick_rule("fast_random", status="live", random=1.0)
        b = book(rules=[rnd], eligible={"A": {}})
        with FakeSources({"A": 1.0}):
            sm = FAST.Sampler(["A"], b, every=60, slow_every=2, send=lambda k, s, i: sent.append((k, s["mint"])))
            sm.round()
            sm.stop()
            sm.round()                                                      # after stop: nothing changes
        self.assertEqual(sent, [("buy", "A")])
        self.assertEqual(len(sm.ticks), 1)

    def test_quiet_failures_do_not_count_towards_an_outage(self):
        saved = http.urllib.request.urlopen
        http.urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("down"))
        http.fails.pop("testhost", None)
        try:
            for _ in range(4):
                http.fetch("testhost", "https://example.invalid/x", tries=1, quiet=True)
            self.assertFalse(http.down("testhost"))
            for _ in range(3):
                http.fetch("testhost", "https://example.invalid/x", tries=1)
            self.assertTrue(http.down("testhost"))
        finally:
            http.urllib.request.urlopen = saved
            http.fails.pop("testhost", None)


class ScanSide(unittest.TestCase):
    """start_minutes, a real sampler thread for a few fast rounds, and trade_step writing what the minute ledger did."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.st = Store(os.path.join(self.dir, "t.db"))
        self._feat = SC.trade_features
        SC.trade_features = lambda st, r, now, regime: {"ru6": 5.0, "liq": r["d"]["liq"], "mc": r["d"]["mcap"]}
        self._fast = dict(C.FAST)

    def tearDown(self):
        SC.trade_features = self._feat
        C.FAST.clear(); C.FAST.update(self._fast)
        self.st.close()

    def test_minutes_between_scans(self):
        from test_trade import fake_row
        st, t0 = self.st, time.time() - 3 * H
        exits = {e["id"]: e for e in C.EXIT_POOL}
        for m in ("A", "B"):
            st.upsert_seen({"mint": m, "pool": "", "dex": "", "name": m}, t0)
        st.db.execute("UPDATE tokens SET status='IN'")
        st.commit()
        # scan 1: both coins pass; the bench fills (the quick rules join it) and rules buy at the scan
        rows = [fake_row(m, 1.0) for m in ("A", "B")]
        ds = {m: {"symbol": m, "price": 1.0, "liq": 2e5, "mcap": 1e6, "chg": {"h1": 0.0, "m5": 1.5}} for m in ("A", "B")}
        SC.scan_step(st, ds, t0, exits, C.TRADE)
        pol, *_ = SC.trade_step(st, rows, ds, t0, {})
        self.assertTrue(any(r.get("fast") for r in pol["rules"]))
        rnd = next(r for r in pol["rules"] if r["id"] == "fast_random")
        rnd["random"] = 1.0                                                 # buy at every minute, to see one
        st.set_meta("trade_policy", json.dumps(pol)); st.commit()
        n_open = len(st.open_sigs())
        self.assertGreater(n_open, 0)
        # scan 2, 15 minutes on: the scan's reading, then the sampler runs three fast rounds at +12%
        now = t0 + 900
        C.FAST.update(every_s=0.05)
        with FakeSources({"A": 1.12, "B": 1.0}):
            SC.scan_step(st, ds, now, exits, C.TRADE)
            sm = SC.start_minutes(st, now, {**ds, "A": {**ds["A"], "price": 1.0}}, {"gt5m": ["A"]}, exits, set())
            deadline = time.time() + 10
            while sm.rounds < 3 and time.time() < deadline:
                time.sleep(0.02)
            pol, feats, ch, picks, sells, minute, closed = SC.trade_step(st, [fake_row(m, 1.0) for m in ("A", "B")], ds,
                                                                        now, {}, None, sm, time.time())
        self.assertGreaterEqual(minute["rounds"], 3)
        self.assertGreaterEqual(minute["ticks"], 6)
        self.assertGreater(st.tick_stats()["rows"], 6)                      # the minutes and the scan's own reading
        a = [s for s in st.sigs() if s["mint"] == "A" and s["rule"] != "fast_random"]
        self.assertTrue(all(s["out"]["tp10_8h"][2] == "target" and s["out"]["tp10_8h"][3] > now for s in a))
        quick = [s for s in st.sigs() if s["rule"] == "fast_random"]
        self.assertEqual({s["mint"] for s in quick}, {"A", "B"})            # both passed at the previous scan
        self.assertTrue(all(s["in_ts"] > now for s in quick))
        self.assertEqual(minute["opened"], len(quick))
        self.assertIn("m5", feats["A"])                                     # the scan's minute variables
        # a scan rule's buy fills at decision time at the latest minute price, not at the scan's older reading
        st.db.execute("DELETE FROM tsig WHERE rule='unpushed_liquid'"); st.commit()   # free to buy again
        pol2 = json.loads(st.get_meta("trade_policy"))
        for r in pol2["rules"]:
            if r["id"] == "unpushed_liquid":
                r["all"] = []                                               # fires on every passing coin
        st.set_meta("trade_policy", json.dumps(pol2)); st.commit()
        with FakeSources({"A": 1.3, "B": 1.0}):
            later = now + 900
            SC.scan_step(st, ds, later, exits, C.TRADE)
            sm = SC.start_minutes(st, later, ds, {"gt5m": ["A"]}, exits, set())
            deadline = time.time() + 10
            while sm.rounds < 2 and time.time() < deadline:
                time.sleep(0.02)
            t_dec = time.time()
            SC.trade_step(st, [fake_row(m, 1.0) for m in ("A", "B")], ds, later, {}, None, sm, t_dec)
        bought = [s for s in st.sigs() if s["rule"] == "unpushed_liquid" and s["in_ts"] > later]
        self.assertTrue(bought)
        a = next(s for s in bought if s["mint"] == "A")
        self.assertEqual((a["in_ts"], a["in_price"]), (t_dec, 1.3))         # not the scan's 1.0
        self.assertLessEqual(a["f"]["lag"], C.FAST["fill_lag_s"])
        page = SC.trade_page(st, pol, feats, [fake_row(m, 1.0) for m in ("A", "B")], now, None, {}, None, minute)
        q = page["quick"]
        self.assertEqual(q["n_trades"], len(quick))
        self.assertTrue(all(b["id"] not in [x["id"] for x in q["rules"]] or b.get("fast") for b in page["bench"]))
        self.assertTrue(any(e["base"] for e in q["exits"]))


class Redefine(unittest.TestCase):
    def test_a_changed_quick_rule_restarts_its_record_while_under_test(self):
        pol = T.new_policy(C.EXIT_POOL, C.DEFAULT_EXIT)
        old = [{**r, "all": [c for c in r["all"] if c[0] != "liq"]} for r in C.FAST_RULES]
        T.add_rules(pol, old, 100.0, "test")
        live = next(r for r in pol["rules"] if r["id"] == "fast_momentum")
        live.update(status="live", since=150.0)
        ch = T.sync_rules(pol, C.FAST_RULES, 200.0)
        self.assertEqual(len(ch), len(C.FAST_RULES) - 1)                    # the live one keeps its definition
        r = next(r for r in pol["rules"] if r["id"] == "fast_breakout")
        self.assertIn(["liq", ">=", C.FAST["min_liq"]], r["all"])
        self.assertEqual((r["added"], r["since"], r["last"]["verdict"]), (200.0, 200.0, "collecting"))
        self.assertNotIn(["liq", ">=", C.FAST["min_liq"]], live["all"])
        self.assertEqual(T.sync_rules(pol, C.FAST_RULES, 300.0), [])         # nothing changed since

    def test_the_first_redefinition_restarts_after_the_old_definitions_last_trades(self):
        d = tempfile.mkdtemp()
        st = Store(os.path.join(d, "t.db"))
        pol = T.new_policy(C.EXIT_POOL, C.DEFAULT_EXIT)
        T.add_rules(pol, C.FAST_RULES, SC.QUICK_RESTART_TS - 800, "test")
        T.add_rules(pol, C.ATTENTION_RULES, SC.QUICK_RESTART_TS - 800, "test")
        SC.restart_quick_records_once(st, pol)
        self.assertTrue(all(r["added"] == SC.QUICK_RESTART_TS for r in pol["rules"] if r.get("fast")))
        self.assertTrue(all(r["added"] < SC.QUICK_RESTART_TS for r in pol["rules"] if not r.get("fast")))
        self.assertEqual(json.loads(st.get_meta("trade_policy"))["rules"][0]["added"], pol["rules"][0]["added"])
        for r in pol["rules"]:
            r["added"] = 1.0
        SC.restart_quick_records_once(st, pol)                              # once only
        self.assertTrue(all(r["added"] == 1.0 for r in pol["rules"]))
        st.close()


class TrainRequest(unittest.TestCase):
    def test_asks_once_when_overdue(self):
        d = tempfile.mkdtemp()
        st = Store(os.path.join(d, "t.db"))

        class B:
            summary = {"status": "collecting: x", "trained_at": 0.0}
        now = 10 * H
        SC.train_request(st, B, now, d)
        self.assertTrue(os.path.exists(os.path.join(d, "train_due")))
        SC.train_request(st, B, now + 600, d)                              # asked a few minutes ago: no file
        self.assertFalse(os.path.exists(os.path.join(d, "train_due")))
        B.summary = {"status": "ok", "trained_at": now}
        SC.train_request(st, B, now + 5 * H, d)                            # fresh enough
        self.assertFalse(os.path.exists(os.path.join(d, "train_due")))
        SC.train_request(st, B, now + 7.5 * H, d)
        self.assertTrue(os.path.exists(os.path.join(d, "train_due")))
        st.close()


class QuickExitsApart(unittest.TestCase):
    def test_quick_trades_do_not_move_the_live_exit(self):
        cfg = {**C.TRADE, "min_trades": 10, "switch_after": 1}
        ex = [{"id": "a", "max_h": 4}, {"id": "b", "max_h": 4}]
        now = 100 * H

        def fwd(rid):
            return {rid: [{"mint": f"M{i}", "in_ts": now - 30 * H + i * 60, "live": 0, "out": {"a": -5.0 + (i % 3), "b": 5.0 + (i % 5)}}
                          for i in range(40)]}
        for fast, expect in ((True, "a"), (False, "b")):
            pol = T.new_policy(ex, "a")
            pol["last_review"] = now - 7 * 86400
            pol["rules"] = [{"id": "q", "label": "q", "all": [], "status": "testing", "added": 0, "since": 0,
                             **({"fast": True, "exit": "a"} if fast else {})}]
            pol, _ = T.run_review(pol, {}, fwd("q"), now, cfg, [], ex, "a")
            self.assertEqual(pol["exit"], expect)


class MinuteCorrelations(unittest.TestCase):
    def test_a_variable_that_predicts_the_next_minutes_holds(self):
        rnd = random.Random(5)
        t0, ticks, passing = 1_000_000.0, [], []
        for k in range(60):                                                 # a scan every 15 minutes for 15 hours
            passing.append((t0 + k * 900, {f"C{i}" for i in range(40)}))
        for i in range(40):
            m, p = f"C{i}", 1.0
            pace = [1.0] * 900
            for j in range(900):                                            # one reading a minute
                if j % 37 == 0:
                    pace[j] = rnd.choice((0.5, 1.0, 3.0))
                elif j:
                    pace[j] = pace[j - 1]
            for j in range(900):
                ts = t0 + j * 60
                drift = (pace[j] - 1.0) * 0.004                             # a hot volume pace keeps lifting the price
                p *= math.exp(drift + rnd.gauss(0, 0.004))
                ticks.append({"ts": ts, "mint": m, "price": p, "liq": 2e5, "mc": p * 1e6, "v5": 1000.0 * pace[j],
                              "v1h": 12000.0, "b5": 10, "s5": 10, "c5": 0.0, "c1h": 0.0, "bst": 0, "gtr5": None})
        by = {}
        for t in ticks:
            by.setdefault(t["mint"], []).append(t)
        out = CORR.analyse_fast(sorted(by.items()), passing, [], t0 + 900 * 60, C.CORR)
        self.assertGreater(out["points"], 1000)
        v = next(x for x in out["vars"] if x["key"] == "v5x")
        self.assertEqual(v["predicts"]["15"]["verdict"], "holds")
        self.assertGreater(v["predicts"]["15"]["rho"], 0.1)
        bs = next(x for x in out["vars"] if x["key"] == "bs5")
        self.assertNotEqual((bs["predicts"].get("15") or {}).get("verdict"), "holds")   # constant: nothing to rank


if __name__ == "__main__":
    unittest.main()
