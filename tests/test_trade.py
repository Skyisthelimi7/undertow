"""Buy and sell signals (undertow/trade.py) and the paper ledger the scan keeps (scan.trade_step, scan.trade_page)."""
import unittest, sys, pathlib, tempfile, os, random, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from undertow import trade as T, config as C, scan as SC
from undertow.store import Store

H = 3600
CFG = {**C.TRADE, "min_trades": 10, "var_min_n": 40, "testing": 3, "add_per_review": 1}
POL = {"tp10_8h": {"id": "tp10_8h", "tp": 10, "max_h": 8}, "hold4h": {"id": "hold4h", "max_h": 4},
       "sl20": {"id": "sl20", "sl": 20, "max_h": 24}}


def rule(rid, *conds):
    return {"id": rid, "label": rid, "all": [list(c) for c in conds], "source": "pool"}


class Features(unittest.TestCase):
    def test_path_features_from_scan_prices(self):
        now = 100 * H
        prices = [(now - 6 * H + i * 900, 1.0) for i in range(20)] + [(now - 900, 1.2)]
        f = T.path_features(prices, now, 1.5)
        self.assertAlmostEqual(f["r15"], 25.0, places=6)                 # against the scan 15 minutes ago
        self.assertAlmostEqual(f["ru6"], 50.0, places=6)                 # against the 6h low
        self.assertAlmostEqual(f["dd6"], 0.0, places=6)                  # it is the 6h high
        self.assertAlmostEqual(f["hi_h"], 0.0, places=6)
        self.assertGreater(f["vola"], 0)
        self.assertEqual(T.path_features([], now, 1.0), {})              # no history, no shape
        self.assertNotIn("r3h", T.path_features([(now - 900, 1.0)], now, 1.0))

    def test_decision_features_keep_known_numbers_only(self):
        f = T.decision_features({"c1h": 5.123456, "liq": 120000, "lp": "pump.fun", "org": None, "mc": True}, {"ru6": 3.0})
        self.assertEqual(f, {"c1h": 5.123, "liq": 120000, "ru6": 3.0})


class Rules(unittest.TestCase):
    def test_fires_needs_every_condition_and_a_value(self):
        r = rule("x", ("ru6", "<", 15), ("liq", ">=", 100_000))
        self.assertTrue(T.fires(r, {"ru6": 3, "liq": 100_000}))
        self.assertFalse(T.fires(r, {"ru6": 20, "liq": 200_000}))
        self.assertFalse(T.fires(r, {"liq": 200_000}))                      # missing never satisfies
        self.assertEqual(T.unmet(r, {"ru6": 20, "liq": 200_000}), [("ru6", "<", 15, 20)])

    def test_costs(self):
        self.assertAlmostEqual(T.cost_pct(100_000, 500, 1.0), 500 / 50_500 * 100 + 1.0)
        self.assertEqual(T.cost_pct(0, 500, 1.0), 100.0)
        # a flat price loses both sides' costs
        self.assertAlmostEqual(T.net_ret(1.0, 1e9, 1e9, {"usd": 500, "fee_pct": 1.0}), ((1 - 0.01) ** 2 - 1) * 100, places=3)


class Exits(unittest.TestCase):
    cfg = {"usd": 500, "fee_pct": 0.0}

    def run_path(self, pol, prices, c1h=None, guard_at=None):
        pos, st = {"in_ts": 0, "in_price": 1.0, "in_liq": 1e12}, T.new_state(1.0)
        for i, p in enumerate(prices, 1):
            r = T.step(pol, pos, st, p, 1e12, (c1h or {}).get(i), i * 900, self.cfg, "structure gate failed" if guard_at == i else None)
            if r:
                return round(r[0], 3), r[2], i
        return None

    def test_each_exit(self):
        self.assertEqual(self.run_path({"tp": 10, "max_h": 8}, [1.05, 1.12]), (12.0, "target", 2))
        self.assertEqual(self.run_path({"sl": 20, "max_h": 8}, [0.9, 0.7]), (-30.0, "stop", 2))     # fills at the scan price
        self.assertEqual(self.run_path({"trail": 25, "arm": 20, "max_h": 24}, [1.3, 1.5, 1.1])[1:], ("trailing stop", 3))
        self.assertIsNone(self.run_path({"trail": 25, "arm": 60, "max_h": 24}, [1.3, 1.5, 1.1]))          # never armed
        self.assertEqual(self.run_path({"cool": 30, "cool_drop": 5, "max_h": 24}, [1.2, 1.4, 1.35, 1.2])[1:], ("cooled off", 4))
        self.assertEqual(self.run_path({"fade": 20, "max_h": 24}, [1, 1, 1, 0.9, 0.85], c1h={4: -10, 5: -25})[1:], ("fading", 5))
        self.assertEqual(self.run_path({"max_h": 1}, [1, 1, 1, 1.02])[1:], ("time", 4))
        self.assertEqual(self.run_path({"tp": 10, "max_h": 8}, [1.0, 1.0], guard_at=2)[1:], ("structure gate failed", 2))

    def test_levels(self):
        lv = T.levels({"tp": 10, "sl": 20, "trail": 25, "arm": 20, "max_h": 8}, {"in_ts": 0, "in_price": 2.0}, 2.6)
        self.assertAlmostEqual(lv["stop"], 1.6)
        self.assertAlmostEqual(lv["target"], 2.2)
        self.assertAlmostEqual(lv["trail"], 1.95)
        self.assertEqual(lv["until"], 8 * H)
        self.assertFalse(T.levels({"trail": 25, "arm": 50, "max_h": 8}, {"in_ts": 0, "in_price": 2.0}, 2.6)["trail_armed"])


class Advance(unittest.TestCase):
    def sig(self):
        return {"in_ts": 0, "in_price": 1.0, "in_liq": 100_000, "out": {}, "st": T.start_states(1.0, POL), "miss": 0}

    def test_every_policy_is_followed_until_it_decides(self):
        s = self.sig()
        out, st, miss, lp, ll, done = T.advance(s, {"price": 1.2, "liq": 100_000, "c1h": 5}, 900, POL, C.TRADE)
        self.assertIn("tp10_8h", out)                                     # target hit at once
        self.assertEqual(set(st), {"hold4h", "sl20"})
        self.assertFalse(done)
        s.update(out=out, st=st)
        out, st, *_rest, done = T.advance(s, {"price": 0.7, "liq": 100_000, "c1h": -30}, 2 * 900, POL, C.TRADE)
        self.assertIn("sl20", out)
        s.update(out=out, st=st)
        out, st, *_rest, done = T.advance(s, {"price": 0.7, "liq": 100_000}, 5 * H, POL, C.TRADE)
        self.assertTrue(done)
        self.assertEqual(out["hold4h"][2], "time")

    def test_guards(self):
        s = self.sig()
        out, *_r = T.advance(s, {"price": 1.0, "liq": 40_000}, 900, POL, C.TRADE)         # half the pool gone
        self.assertTrue(all(o[2] == "liquidity pulled" for o in out.values()))
        out, *_r = T.advance(self.sig(), {"price": 1.0, "liq": 100_000, "hard": True}, 900, POL, C.TRADE)
        self.assertTrue(all(o[2] == "structure gate failed" for o in out.values()))
        s = self.sig()
        for k in range(C.TRADE["max_miss"] - 1):                          # unpriced: wait a few scans first
            out, st, miss, lp, ll, done = T.advance(s, None, (k + 1) * 900, POL, C.TRADE)
            self.assertFalse(out)
            s.update(miss=miss)
        out, st, miss, lp, ll, done = T.advance(s, None, 3 * 900, POL, C.TRADE)
        self.assertTrue(done and all(o[2] == "no market data" for o in out.values()))

    def test_a_policy_dropped_from_the_bench_is_no_longer_followed(self):
        s = self.sig()
        out, st, *_r, done = T.advance(s, {"price": 1.0, "liq": 100_000}, 900, {"hold4h": POL["hold4h"]}, C.TRADE)
        self.assertEqual(set(st), {"hold4h"})


def make_path(n_coins=30, hours=60, step=900, seed=3, drift=0.0):
    """Coins passing every gate, one reading per scan, prices as a random walk; feature 'x' is the coin's number mod 2."""
    rnd, path = random.Random(seed), {}
    for c in range(n_coins):
        p, rows = 1.0, []
        for k in range(int(hours * H / step)):
            p *= 1 + rnd.gauss(drift, 0.02)
            rows.append((k * step, "I", p, 200_000, 0.0, {"org": 100 * (c % 2), "ru6": rnd.uniform(0, 40), "liq": 200_000}))
        path[f"M{c}"] = rows
    return path


class Backtest(unittest.TestCase):
    def test_trades_are_sequential_with_a_cooldown_and_only_matured_entries_count(self):
        path = {"A": [(k * 900, "I", 1.0 + 0.0001 * k, 1e9, 0.0, {"org": 1}) for k in range(200)]}
        tr = T.backtest(path, rule("all", ("org", ">=", 0)), {"max_h": 4}, {**C.TRADE, "reentry_h": 8})
        self.assertGreater(len(tr), 3)
        gaps = [b["in_ts"] - a["in_ts"] for a, b in zip(tr, tr[1:])]
        self.assertTrue(all(g >= 8 * H for g in gaps))                    # at most one entry every 8h
        end = 199 * 900
        self.assertTrue(all(t["in_ts"] <= end - 5 * H for t in tr))        # entries within max_h + 1h of the end are left out

    def test_early_winners_near_the_end_are_not_kept_while_slow_losers_are_dropped(self):
        # every entry hits +10% one scan later, but the policy allows 24h: entries in the last 25h must not count
        path = {"A": [(k * 900, "I", 1.0 if k % 2 == 0 else 1.2, 1e9, 0.0, {"org": 1}) for k in range(160)]}
        tr = T.backtest(path, rule("all", ("org", ">=", 0)), {"tp": 10, "max_h": 24}, {**C.TRADE, "reentry_h": 0})
        self.assertTrue(all(t["in_ts"] <= 159 * 900 - 25 * H for t in tr))

    def test_summary_clusters_by_coin(self):
        same = [{"mint": "A", "ret": 5.0, "in_ts": i} for i in range(20)] + [{"mint": "B", "ret": -5.0, "in_ts": i} for i in range(20)]
        s = T.summarise(same)
        self.assertEqual((s["n"], s["coins"]), (40, 2))
        self.assertAlmostEqual(s["mean"], 0.0)
        many = [{"mint": f"C{i}", "ret": 2.0 + (i % 3), "in_ts": i} for i in range(40)]
        self.assertGreater(T.summarise(many)["t"], 5)


class Judging(unittest.TestCase):
    def test_rule_verdicts(self):
        fw = lambda m, n=40, t=3.0: {"n": n, "coins": n, "win": 0.6, "mean": m, "t": t}
        self.assertEqual(T.judge_rule(fw(3.0), {"n": 0}, CFG)[0], "earns")
        self.assertEqual(T.judge_rule(fw(3.0), fw(-1.0), CFG)[0], "unclear")    # backtest disagrees
        self.assertEqual(T.judge_rule(fw(-0.5, t=-0.3), {"n": 0}, CFG)[0], "loses")
        self.assertEqual(T.judge_rule(fw(3.0, n=5), {"n": 0}, CFG)[0], "collecting")
        self.assertEqual(T.judge_rule({"n": 0}, fw(-5.0, n=40, t=-3), CFG)[0], "loses")   # a clearly losing backtest
        self.assertEqual(T.judge_rule({"n": 0}, fw(-5.0, n=40, t=-3), CFG, live=True)[0], "collecting")

    def test_a_warning_holds_when_the_state_did_clearly_worse(self):
        rnd, path = random.Random(5), {}
        for c in range(40):
            rows, p = [], 1.0
            for k in range(100):
                hot = k % 20 == 0
                rows.append((k * 900, "I", p, 1e6, 0.0, {"ru6": 50 if hot else 5}))
                p *= (0.985 if (k % 20) < 16 else 1.0) if k % 20 < 16 else 1.0
                p *= 1 + rnd.gauss(0, 0.002)
            path[f"M{c}"] = rows
        w = {"id": "pushed", "all": [["ru6", ">=", 30]]}
        rec = T.judge_warning(T.outcomes(path, CFG), w, {**CFG, "min_trades": 10, "warn_gap": 2.0, "z": 2.0})
        self.assertEqual(rec["verdict"], "holds")
        self.assertLess(rec["gap"], -2)
        self.assertEqual(T.judge_warning([], w, CFG)["verdict"], "collecting")

    def test_variables_with_a_steady_relationship_signal(self):
        path = {}
        for c in range(40):
            rows = []
            for k in range(60):
                x = (c * 7 + k) % 10
                rows.append((k * 900, "I", 1.0 + 0.001 * x * (k % 2), 1e9, 0.0, {"ru6": x}))
            path[f"M{c}"] = rows
        # the price 4h later is lower for high ru6 readings: build it so returns fall as ru6 rises
        for m, rows in path.items():
            out, p = [], 1.0
            for k, (ts, s, _p, l, c1, f) in enumerate(rows):
                out.append((ts, s, p, l, c1, f))
                p *= 1 - 0.002 * f["ru6"] + 0.009
            path[m] = out
        v = T.judge_var(T.outcomes(path, CFG), "ru6", {**CFG, "var_min_n": 40})
        self.assertEqual(v["verdict"], "signal")
        self.assertEqual(v["better"], "low")
        self.assertEqual(len(v["fifths"]), 5)


class Outcomes(unittest.TestCase):
    def test_the_reading_four_hours_on_within_the_tolerance(self):
        rows = [(k * 900, "I" if k == 0 else "O", 1.0 + 0.1 * (k >= 16), 1e12, 0.0, {"ru6": 1} if k == 0 else None) for k in range(30)]
        o = T.outcomes({"A": rows}, {"usd": 500, "fee_pct": 0.0})
        self.assertEqual(len(o), 1)                                        # only gate-passing readings with features
        ts, mint, f, net, ch = o[0]
        self.assertAlmostEqual(ch, 10.0)
        self.assertAlmostEqual(net, 10.0, places=3)
        gap = [(0, "I", 1.0, 1e12, 0.0, {"ru6": 1}), (6 * 3600, "I", 2.0, 1e12, 0.0, {"ru6": 1})]
        self.assertEqual(T.outcomes({"A": gap}, {"usd": 500, "fee_pct": 0.0}), [])   # nothing within an hour of +4h


class Review(unittest.TestCase):
    pool = [rule("r_x1", ("org", ">=", 50)), rule("r_x0", ("org", "<", 50)), rule("r_all", ("liq", ">=", 0)), rule("r_more", ("ru6", "<", 10))]
    exits = [{"id": "hold4h", "max_h": 4}, {"id": "tp10_8h", "tp": 10, "max_h": 8}]

    def fwd(self, rid, mean, n=40, start=0, spread=1.0):
        return [{"mint": f"{rid}{i}", "in_ts": start + i * H, "out": {"hold4h": mean + spread * ((i % 3) - 1), "tp10_8h": mean - 1},
                 "live": 0} for i in range(n)]

    def test_first_review_fills_the_bench_and_sets_the_exit(self):
        pol, ch = T.run_review(None, make_path(), {}, 100 * H, CFG, self.pool, self.exits, "hold4h", C.SELL_WARNINGS)
        self.assertEqual([r["id"] for r in pol["rules"]], ["r_x1", "r_x0", "r_all"])          # testing = 3
        self.assertEqual(pol["exit"], "hold4h")
        self.assertTrue(all(r["status"] == "testing" for r in pol["rules"]))
        self.assertEqual(ch, [])
        self.assertTrue(T.due(pol, 100 * H + 7 * 86400, CFG) and not T.due(pol, 101 * H, CFG))
        self.assertEqual({w["id"] for w in pol["warnings"]}, {w["id"] for w in C.SELL_WARNINGS})

    def test_a_rule_goes_live_after_two_winning_reviews_and_a_loser_retires(self):
        now = 100 * H
        pol, _ = T.run_review(None, {}, {}, now, CFG, self.pool, self.exits, "hold4h")
        fwd = {"r_x1": self.fwd("A", 4.0, start=now), "r_x0": self.fwd("B", -3.0, start=now)}
        t1 = now + 7 * 86400
        pol, ch1 = T.run_review(pol, {}, fwd, t1, CFG, self.pool, self.exits, "hold4h")
        st = {r["id"]: r["status"] for r in pol["rules"]}
        self.assertEqual((st["r_x1"], st["r_x0"]), ("testing", "testing"))                     # one review is not enough
        pol, ch2 = T.run_review(pol, {}, fwd, t1 + 7 * 86400, CFG, self.pool, self.exits, "hold4h")
        st = {r["id"]: r for r in pol["rules"]}
        self.assertEqual(st["r_x1"]["status"], "live")
        self.assertEqual(st["r_x0"]["status"], "retired")
        self.assertIn("losing", st["r_x0"]["reason"])
        self.assertEqual(sorted(c["what"] for c in ch2), ["live", "retired", "testing"])         # r_more takes the free place
        self.assertIn("r_more", {r["id"] for r in pol["rules"]})

    def test_trades_too_young_to_have_closed_do_not_count(self):
        now = 100 * H
        pol, _ = T.run_review(None, {}, {}, now, CFG, self.pool, self.exits, "hold4h")
        t1 = now + 7 * 86400
        young = self.fwd("A", 4.0, start=t1 - 4 * H, n=40)                 # opened in the last 4 hours
        pol, _ = T.run_review(pol, {}, {"r_x1": young}, t1, CFG, self.pool, self.exits, "hold4h")
        self.assertEqual(next(r for r in pol["rules"] if r["id"] == "r_x1")["last"]["fwd"]["n"], 0)

    def test_the_exit_switches_after_two_better_reviews(self):
        now = 100 * H
        pol, _ = T.run_review(None, {}, {}, now, CFG, self.pool, self.exits, "hold4h")
        entries = [{"mint": f"E{i}", "in_ts": now + i * 600, "out": {"hold4h": -3.0 + (i % 5) * 0.1, "tp10_8h": 1.0 + (i % 4) * 0.1}, "live": 0}
                   for i in range(60)]
        t1 = now + 7 * 86400
        pol, ch = T.run_review(pol, {}, {"r_all": entries}, t1, CFG, self.pool, self.exits, "hold4h")
        self.assertEqual(pol["exit"], "hold4h")
        pol, ch = T.run_review(pol, {}, {"r_all": entries}, t1 + 7 * 86400, CFG, self.pool, self.exits, "hold4h")
        self.assertEqual(pol["exit"], "tp10_8h")
        self.assertIn("exit switched", [c["what"] for c in ch])

    def test_variables_without_a_signal_stop_seeding_rules(self):
        now, pol = 100 * H, None
        path = make_path(n_coins=40, hours=30)
        for k in range(3):
            pol, _ = T.run_review(pol, path, {}, now + k * 7 * 86400, {**CFG, "var_min_n": 40}, self.pool, self.exits, "hold4h")
        retired = [k for k, v in pol["vars"].items() if v["status"] == "retired"]
        self.assertIn("ru6", retired)                                      # random: no signal three reviews running
        for k in retired:
            self.assertEqual(pol["vars"][k]["streak"]["verdict"], "no signal")

    def test_compare_exits_waits_for_both_policies_to_close(self):
        ex = {"a": {"max_h": 4}, "b": {"max_h": 24}}
        now = 100 * H
        entries = [{"mint": f"M{i}", "in_ts": now - 10 * H, "out": {"a": 1.0, "b": 5.0}} for i in range(20)]
        c = T.compare_exits(entries, "a", CFG, ex, now)
        self.assertEqual(c["b"]["n"], 0)                                   # 24h policy not ripe after 10h
        self.assertEqual(c["a"]["n"], 20)
        old = [{**e, "in_ts": now - 30 * H} for e in entries]
        self.assertAlmostEqual(T.compare_exits(old, "a", CFG, ex, now)["b"]["gain"], 4.0)


def fake_row(mint, price, liq=200_000, hard=False, state="IN", sym=None):
    gates = [{"id": "lp", "ok": not hard, "hard": True, "info": False, "label": "lp", "group": "structure", "value": 1, "rule": ""}]
    return {"t": {"mint": mint, "symbol": sym or mint}, "d": {"symbol": sym or mint, "price": price, "mcap": price * 1e6, "liq": liq,
            "chg": {"h1": 0.0}}, "m": {}, "jup": {}, "gates": gates, "state_new": "IN" if state in ("IN", "WATCH") else "OUT",
            "fs": 1 if state == "WATCH" else 0, "ps": 0}


class Ledger(unittest.TestCase):
    """The scan's side: the path, paper trades opened by rules and stepped every scan, and the page's view."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.st = Store(os.path.join(self.dir, "t.db"))
        self._feat = SC.trade_features
        SC.trade_features = lambda st, r, now, regime: {"ru6": 5.0, "liq": r["d"]["liq"], "mc": r["d"]["mcap"]}

    def tearDown(self):
        SC.trade_features = self._feat
        self.st.close()

    def scan(self, now, prices, hard=()):
        rows = [fake_row(m, p, hard=m in hard) for m, p in prices.items()]
        ds = {m: {"price": p, "liq": 200_000, "chg": {"h1": 0.0}} for m, p in prices.items()}
        pol, feats, ch = SC.trade_step(self.st, rows, ds, now, {})
        return pol, feats, ch, rows

    def test_rules_open_trades_that_every_exit_follows(self):
        t0 = 1_000_000.0
        pol, feats, ch, rows = self.scan(t0, {})
        self.assertIsNotNone(pol)                                          # the first review ran on the first scan
        live = next(r for r in pol["rules"] if r["id"] == "unpushed_liquid")
        live["status"] = "live"
        self.st.set_meta("trade_policy", json.dumps(pol)); self.st.commit()
        pol, feats, ch, rows = self.scan(t0 + 900, {"A": 1.0, "B": 2.0})
        sigs = self.st.sigs()
        self.assertTrue(sigs)
        self.assertTrue(any(s["live"] and s["rule"] == "unpushed_liquid" for s in sigs))
        self.assertEqual(sum(1 for s in sigs if s["live"]), 2)               # one live position per coin
        self.assertTrue(all(set(s["st"]) == {e["id"] for e in C.EXIT_POOL} for s in sigs))
        # +12% on A: the +10% target exits fire at the next scan, A's live trade closes under the live exit
        pol, feats, ch, rows = self.scan(t0 + 1800, {"A": 1.12, "B": 2.0})
        a = [s for s in self.st.sigs() if s["mint"] == "A" and s["live"]][0]
        self.assertIn("tp10_8h", a["out"])
        self.assertEqual(a["out"]["tp10_8h"][2], "target")
        self.assertIsNotNone(a["ref_out_ts"])
        page = SC.trade_page(self.st, pol, feats, rows, t0 + 1800)
        self.assertEqual({x["mint"] for x in page["open"]}, {"B"})
        self.assertEqual([x["mint"] for x in page["closed"]], ["A"])
        self.assertEqual(page["record"]["n"], 0)                           # not matured: a +10% exit within 8h counts after 9h
        page = SC.trade_page(self.st, pol, feats, rows, t0 + 10 * H)
        self.assertEqual(page["record"]["n"], 1)
        self.assertTrue(page["signals"])
        self.assertIn("levels", page["open"][0])

    def test_a_structure_failure_closes_trades_at_once_and_the_path_follows_coins_that_left(self):
        t0 = 2_000_000.0
        pol, *_ = self.scan(t0, {"A": 1.0})
        pol, *_ = self.scan(t0 + 900, {"A": 1.0})
        self.assertTrue(self.st.open_sigs())
        self.scan(t0 + 1800, {"A": 0.9}, hard={"A"})
        self.assertFalse(self.st.open_sigs())
        self.assertTrue(all(o[2] == "structure gate failed" for s in self.st.sigs() for o in s["out"].values()))
        # A is no longer a candidate: still followed on price for follow_h
        SC.trade_step(self.st, [], {"A": {"price": 0.8, "liq": 1000, "chg": {"h1": -5}}}, t0 + 2700, {})
        path = self.st.tpath(0)["A"]
        self.assertEqual(path[-1][1], "G")
        self.assertEqual([r[1] for r in path[:3]], ["I", "I", "X"])

    def test_seed_rebuilds_the_path_once_from_snapshots(self):
        st, t0 = self.st, 3_000_000.0
        for k in range(10):
            st.add_snap("S", t0 + k * 900, {"price": 1 + k / 100, "mcap": 1e6, "liq": 1e5, "vol24": 1e5, "vol1": 1e4, "chg1": 1, "chg6": 2,
                                           "chg24": 3, "buys1": 10, "sells1": 5})
        st.add_transition(t0 + 3 * 900, "S", "S", "OUT", "IN", [])
        st.commit()
        n = SC.seed_tpath(st, t0 + 20 * 900)
        self.assertEqual(n, 10)
        rows = st.tpath(0)["S"]
        self.assertEqual([r[1] for r in rows], ["O"] * 3 + ["I"] * 7)
        self.assertIsNone(rows[0][5])
        self.assertAlmostEqual(rows[5][5]["bs1h"], 2.0)
        self.assertEqual(SC.seed_tpath(st, t0 + 21 * 900), 0)               # only once


if __name__ == "__main__":
    unittest.main()
