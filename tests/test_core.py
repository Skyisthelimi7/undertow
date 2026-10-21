import unittest, sys, pathlib, json
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from undertow import gates as G, tgrisk, momentum, sources, scan, config as C, signals as SG, tracker as TR, lab as LAB
import random


def good(**kw):
    m = dict(mcap=500_000, fdv=500_000, liq=60_000, vol24=150_000, venue_kind="cpmm", authority_clean=True, bad_ext=[],
             transfer_fee=0, lp_locked_pct=100, lp_basis="RugCheck", rugged=False, creator_pct=0.5, top10=15, same_size=1,
             linked_share=0.05, dev_drop=None, top_outflow_6h=None, crash=3, crash_breach=False, vol1h=9_000,
             traders_1h=120, sold_1h=4_000, exit_cost=2.0, organic_label="medium", sus=False, age_min=600,
             launchpad=None, risk={"count": 2, "complete": True, "calibrated": True}, cluster_pct=4.0)
    m.update(kw)
    return m


def failing(gs):
    return {g["id"] for g in G.blocking(gs)}


class Gates(unittest.TestCase):
    def test_clean_token_passes_including_warmup_gates(self):
        self.assertEqual(failing(G.evaluate(good(), False)), set())

    def test_each_rule_trips(self):
        cases = {"top10": dict(top10=30), "creator": dict(creator_pct=9), "volume": dict(vol24=10_000), "wash": dict(vol24=6_000_000),
                 "mcap": dict(mcap=10_000), "authority": dict(authority_clean=False), "lp": dict(lp_locked_pct=0),
                 "crash": dict(crash=-99, crash_breach=True), "bundle": dict(same_size=9), "devsell": dict(dev_drop=0.6),
                 "outflow": dict(top_outflow_6h=8), "linked": dict(linked_share=0.5), "extensions": dict(bad_ext=["transferHook"]),
                 "venue": dict(venue_kind="curve"), "activity": dict(vol1h=500), "traders": dict(traders_1h=10),
                 "exit": dict(exit_cost=14.0), "organic": dict(organic_label="low"), "flagged": dict(sus=True),
                 "twoway": dict(sold_1h=10), "age": dict(age_min=30), "lp": dict(lp_locked_pct=None),
                 "riskflags": dict(risk={"count": 4, "complete": True, "calibrated": True})}
        for gid, change in cases.items():
            m = good(); m.update(change)
            self.assertIn(gid, failing(G.evaluate(m, False)), gid)

    def test_exit_slack_keeps_a_token_hovering_on_the_line(self):
        m = good(); m["top10"] = 26.0
        self.assertIn("top10", failing(G.evaluate(m, False)))      # cannot enter at 26%
        self.assertNotIn("top10", failing(G.evaluate(m, True)))    # but is not evicted at 26%

    def test_unknown_blocks_entry_but_not_a_resident(self):
        m = good(); m["top10"] = None
        self.assertIn("top10", failing(G.evaluate(m, False)))
        self.assertNotIn("top10", failing(G.evaluate(m, True)))
        m = good(); m["authority_clean"] = None                    # hard gates never get the benefit of the doubt
        self.assertIn("authority", failing(G.evaluate(m, True)))

    def test_holder_gates_demoted_only_inside_the_study_range(self):
        direct = good(top10=60, creator_pct=30)
        self.assertTrue({"top10", "creator"} <= failing(G.evaluate(direct, False)))
        fresh = good(top10=60, creator_pct=30, launchpad="pump.fun")          # good() is calibrated: young and small
        gs = G.evaluate(fresh, False)
        self.assertFalse({"top10", "creator"} & failing(gs))
        self.assertTrue(all(g["info"] for g in gs if g["id"] in ("top10", "creator")))
        old = good(top10=60, creator_pct=30, launchpad="pump.fun", risk={"count": 2, "complete": True, "calibrated": False})
        self.assertTrue({"top10", "creator"} <= failing(G.evaluate(old, False)))

    def test_risk_flags_gate_only_where_the_study_applies(self):
        old = good(risk={"count": 5, "complete": True, "calibrated": False})
        self.assertNotIn("riskflags", failing(G.evaluate(old, False)))
        partial = good(risk={"count": 4, "complete": False, "calibrated": True})   # 4 already fired: fails anyway
        self.assertIn("riskflags", failing(G.evaluate(partial, False)))

    def test_source_outage_skips_only_its_own_checks(self):
        gs = G.evaluate(good(rugged=None, linked_share=None, same_size=None, rc_down=True), False)
        self.assertFalse({"rugged", "linked", "bundle"} & failing(gs))
        self.assertIn("authority", failing(G.evaluate(good(authority_clean=None, rc_down=True), False)))

    def test_wallet_cluster_shown_until_switched_on(self):
        gs = G.evaluate(good(cluster_pct=20.0), False)
        self.assertNotIn("cluster", failing(gs))                                              # shown, not gated
        cl = [g for g in gs if g["id"] == "cluster"][0]
        self.assertTrue(cl["info"]); self.assertFalse(cl["ok"])                               # but marked over the line
        C.GATE_ON_CLUSTER = True
        try:
            self.assertIn("cluster", failing(G.evaluate(good(cluster_pct=20.0), False)))
            self.assertNotIn("cluster", failing(G.evaluate(good(cluster_pct=16.0), True)))    # slack for a resident
            self.assertIn("cluster", failing(G.evaluate(good(cluster_pct=16.0), False)))      # but not for entry
            stale = good(cluster_pct=None, cluster_skip="older RugCheck read")                # cached before clusters
            self.assertNotIn("cluster", failing(G.evaluate(stale, False)))
            fresh = good(cluster_pct=40.0, launchpad="pump.fun")                              # study range: shown only
            self.assertNotIn("cluster", failing(G.evaluate(fresh, False)))
        finally:
            C.GATE_ON_CLUSTER = False

    def test_second_opinion_adds_traps_and_shows_metadata(self):
        gs = G.evaluate(good(gp_traps=["transfer fee can be raised"]), False)
        self.assertIn("extensions", failing(gs))
        ext = [g for g in gs if g["id"] == "extensions"][0]
        self.assertEqual(ext["value"], ["transfer fee can be raised"])
        self.assertIn("GoPlus", ext["rule"])
        both = [g for g in G.evaluate(good(bad_ext=["transferHook"], gp_traps=["transferHook", "x"]), False) if g["id"] == "extensions"][0]
        self.assertEqual(both["value"], ["transferHook", "x"])                                 # merged, no repeats
        clean = G.evaluate(good(gp_traps=[], meta_mutable=True), False)
        self.assertEqual(failing(clean), set())                                               # metadata never gates
        meta = [g for g in clean if g["id"] == "metadata"][0]
        self.assertTrue(meta["info"]); self.assertFalse(meta["ok"])
        only_gp = G.evaluate(good(bad_ext=None, gp_traps=["accounts start frozen"]), False)    # chain unread, GoPlus has it
        self.assertIn("extensions", failing(only_gp))

    def test_bands(self):
        self.assertEqual(G.band_of(20_000), "20k-100k"); self.assertEqual(G.band_of(19_999_999), "10m-20m")
        self.assertIsNone(G.band_of(19_999)); self.assertIsNone(G.band_of(20_000_000))


class NewSources(unittest.TestCase):
    def test_largest_cluster(self):
        self.assertEqual(sources._largest_cluster(None, 1000), (None, None))      # not mapped
        self.assertEqual(sources._largest_cluster([], 1000), (0.0, 0))            # mapped, none found
        nets = [{"size": 5, "tokenAmount": 300, "currentHolding": 50}, {"size": 3, "tokenAmount": 120, "currentHolding": 120},
                {"size": 2, "tokenAmount": 90}]
        self.assertEqual(sources._largest_cluster(nets, 1000), (12.0, 3))        # held now, not ever received
        self.assertEqual(sources._largest_cluster([{"size": 8665, "currentHolding": 1588}], 1000), (None, None))  # >100%

    def test_goplus_parse(self):
        sample = {"code": 1, "result": {"M": {
            "mintable": {"authority": [], "status": "0"}, "freezable": {"authority": [], "status": "0"},
            "closable": {"authority": [], "status": "0"}, "balance_mutable_authority": {"authority": [], "status": "0"},
            "metadata_mutable": {"metadata_upgrade_authority": [{"address": "A"}], "status": "1"},
            "transfer_fee": {"current_fee_rate": {"fee_rate": "0.0269"}, "scheduled_fee_rate": [{"epoch": "624", "fee_rate": "0.042"}]},
            "transfer_fee_upgradable": {"authority": [{"address": "B"}], "status": "1"}, "transfer_hook": [],
            "transfer_hook_upgradable": {"authority": [], "status": "0"}, "default_account_state": "1",
            "default_account_state_upgradable": {"authority": [], "status": "0"}, "non_transferable": "0",
            "trusted_token": 0, "holder_count": "58153", "dex": [{"burn_percent": 99.7}, {"burn_percent": None}]}}}
        orig = sources.fetch
        try:
            sources.fetch = lambda *a, **k: sample
            g = sources.gp_report("M")
            sources.fetch = lambda *a, **k: {"code": 1, "result": {}}
            self.assertIsNone(sources.gp_report("M"))
            sources.fetch = lambda *a, **k: None
            self.assertIsNone(sources.gp_report("M"))
        finally:
            sources.fetch = orig
        self.assertEqual((g["mintable"], g["freezable"], g["meta_mutable"]), (False, False, True))
        self.assertEqual(g["traps"], ["transfer fee can be raised"])
        self.assertEqual(g["fee_pct"], 4.2)                                       # the scheduled raise counts
        self.assertEqual((g["holders"], g["lp_burn_max"]), (58153, 99.7))

    def test_new_lab_variables_and_shadow_rules(self):
        f = LAB.features({"mcap": 1}, {"cluster_pct": 18.0, "meta_mutable": True}, {"dev_mints": 40})
        self.assertEqual((f["clu"], f["metamut"], f["devm"]), (18.0, 1, 40))
        res = LAB.rule_results(f, C.SHADOW_RULES)
        self.assertEqual((res["cluster_15"], res["meta_locked"], res["dev_launches_10"]), (0, 0, 0))
        self.assertNotIn("metamut", LAB.features({}, {}, {}))                    # unknown stays unknown
        self.assertEqual(LAB.rule_results(LAB.features({}, {"meta_mutable": False}, {}), C.SHADOW_RULES)["meta_locked"], 1)


class Telegram(unittest.TestCase):
    def test_parse(self):
        import re
        m = sources._TG.search("1 370 members, 170 online")
        self.assertEqual(int(re.sub(r"\D", "", m.group(1))), 1370)
        self.assertEqual(int(re.sub(r"\D", "", m.group(3))), 170)

    def test_risk_signals(self):
        s, why = tgrisk.bot_risk(9000, 20, 1500, [(0, 8000), (1, 8100), (2, 8200), (3, 8300), (4, 9000)])
        self.assertGreaterEqual(s, 70); self.assertTrue(why)
        s, why = tgrisk.bot_risk(1400, 170, 1300, [(0, 1380), (1, 1390), (2, 1395), (3, 1398), (4, 1400)])
        self.assertEqual(s, 0)
        self.assertEqual(tgrisk.bot_risk(None, None, None, []), (None, []))


class Misc(unittest.TestCase):
    def test_handle_parsing(self):
        f = scan.handle_from_url
        self.assertEqual(f("https://x.com/Foo_Bar/status/123"), "foo_bar")
        self.assertEqual(f("https://twitter.com/foo"), "foo")
        self.assertIsNone(f("https://x.com/i/communities/99")); self.assertIsNone(f("https://x.com/status/5")); self.assertIsNone(f(None))

    def test_same_size_cluster(self):
        self.assertEqual(sources._max_same_size([100, 101, 100.5, 5000, 7]), 3)
        self.assertEqual(sources._max_same_size([]), 0)

    def test_momentum_needs_enough_tokens(self):
        rows = [dict(chg1h=i, chg6h=i, vol_accel=i, flow_pct=i / 10) for i in range(8)]
        momentum.score_all(rows)
        self.assertEqual(rows[-1]["momentum"]["label"], "Heating"); self.assertEqual(rows[0]["momentum"]["label"], "Cooling")
        few = [dict(chg1h=1, chg6h=1, vol_accel=1, flow_pct=.5)]
        momentum.score_all(few); self.assertIsNone(few[0]["momentum"]["score"])


class Signals(unittest.TestCase):
    def test_exit_cost_model(self):
        # $500 into a pool with $20k a side: impact 500/20500 = 2.44%, plus the 0.3% default fee
        self.assertAlmostEqual(SG.exit_cost_model(500, 40_000), 500 / 20_500 * 100 + C.DEFAULT_FEE_PCT, places=6)
        self.assertIsNone(SG.exit_cost_model(500, 0))

    def test_exit_cost_takes_the_worse_of_model_and_quote(self):
        model = SG.exit_cost_model(500, 40_000)
        self.assertEqual(SG.exit_cost(500, 40_000, None), (model, False))
        self.assertEqual(SG.exit_cost(500, 40_000, 0.5), (model, False))                      # quote better: model binds
        self.assertEqual(SG.exit_cost(500, 40_000, 6.0), (6.0 + C.DEFAULT_FEE_PCT, True))     # thinner route: quote binds
        self.assertEqual(SG.exit_cost(500, 0, None), (None, False))

    def test_momentum_quality(self):
        self.assertEqual(SG.momentum_quality(5, 3_000, 0.6, 0.1)[0], "Healthy")
        self.assertEqual(SG.momentum_quality(5, 3_000, 0.6, 0.8)[0], "Overextended")    # far above its 6h average
        self.assertEqual(SG.momentum_quality(30, -2_000, 0.4, 0.2)[0], "Overextended")   # rising on net selling
        self.assertEqual(SG.momentum_quality(-4, -1_000, 0.3, 0.0)[0], "Fading")
        self.assertEqual(SG.momentum_quality(-4, 1_000, 0.6, 0.0)[0], "Mixed")
        self.assertEqual(SG.momentum_quality(None, 1_000, 0.6, 0.0)[0], "n/a")

    def test_candle_stats(self):
        now = 100_000
        c = [[now - 7200 + i * 300, 1, 1.0 + (0.2 if i == 3 else 0), 0.9, 1.0, 10] for i in range(24)]
        s = SG.candle_stats(c, now)
        self.assertAlmostEqual(s["drawdown_24h"], 1.0 / 1.2 - 1)
        self.assertFalse(s["higher_lows"])                       # flat lows are not higher lows
        self.assertAlmostEqual(s["extension"], 0.0)


class StudySignals(unittest.TestCase):
    def test_lfdv_and_worst_case_match_the_study(self):
        # constant-product pool holding x of supply S: L/FDV = 2x/S and a full sell-off ends at (x/S)^2 of the price
        self.assertAlmostEqual(SG.lfdv(17_300, 41_900), 0.4129, places=3)          # a pump.fun graduation pool
        self.assertAlmostEqual(SG.worst_case_drop(0.9, "cpmm"), 1 - 0.45 ** 2)       # -80%
        self.assertAlmostEqual(SG.worst_case_drop(1.0, "cpmm"), 0.75)
        self.assertAlmostEqual(SG.worst_case_drop(1.4, "cpmm"), 1 - 0.7 ** 2)       # -51%
        self.assertIsNone(SG.worst_case_drop(0.5, "concentrated"))

    def test_pool_kind(self):
        self.assertEqual(SG.pool_kind("pumpfun", None), "curve")
        self.assertEqual(SG.pool_kind("meteora", ["DBC"]), "curve")
        self.assertEqual(SG.pool_kind("raydium", ["CLMM"]), "concentrated")
        self.assertEqual(SG.pool_kind("meteora", ["DLMM"]), "concentrated")
        self.assertEqual(SG.pool_kind("raydium", ["CPMM"]), "cpmm")
        self.assertEqual(SG.pool_kind("pumpswap", None), "cpmm")

    def test_trade_stats(self):
        now = 10_000
        tr = [[now - 30 * i, "buy" if i % 3 else "sell", 100.0, f"w{i}"] for i in range(40)]   # 40 trades over 20 min
        s = SG.trade_stats(tr, now)
        self.assertEqual(s["wallets_10m"], 21)               # trades at 0..600 s inclusive: i = 0..20
        self.assertFalse(s["wallets_est"])
        self.assertAlmostEqual(s["top5_share"], 5 / 14)       # 14 equal buyers in the window
        self.assertAlmostEqual(s["sell_share_15m"], 11 / 31)
        self.assertEqual(SG.trade_stats([], now)["wallets_10m"], 0)
        self.assertEqual(SG.trade_stats(None, now), {})

    def test_risk_flags_and_calibration(self):
        flags = SG.risk_flags(0.5, {"wallets_10m": 120, "top5_share": 0.15, "sell_share_15m": 0.2}, 500, 90, None)
        self.assertEqual([f["fired"] for f in flags], [True, True, True, False, True, True])
        inside = SG.risk_summary(flags, 90, 300_000)
        self.assertEqual((inside["count"], inside["calibrated"], inside["rug_rate"]), (5, True, 56.4))
        outside = SG.risk_summary(flags, 3 * 24 * 60, 300_000)
        self.assertEqual((outside["calibrated"], outside["rug_rate"]), (False, None))

    def test_bad_extensions(self):
        bad, fee = sources.bad_extensions({"transferHook": {"programId": None}, "defaultAccountState": {"accountState": "initialized"},
                                           "transferFeeConfig": {"newerTransferFee": {"transferFeeBasisPoints": 100}}})
        self.assertEqual((bad, fee), ([], 1.0))
        bad, _ = sources.bad_extensions({"permanentDelegate": {"delegate": "x"}, "pausableConfig": {"paused": False},
                                         "defaultAccountState": {"accountState": "frozen"}, "transferHook": {"programId": "p"}})
        self.assertEqual(set(bad), {"permanentDelegate", "pausableConfig", "defaultAccountState", "transferHook"})

    def test_lp_status_chain(self):
        pump = {"graduated_pool": "P", "launchpad": "pump.fun"}
        # a launchpad that burns its graduation pool's LP settles it, even when RugCheck's deepest pool says 0
        self.assertEqual(SG.lp_status({"lp_locked_pct": 0}, None, "cpmm", pump, "P")[0], 100.0)
        # otherwise RugCheck's figure for the priced pool, then GeckoTerminal, then RugCheck's deepest pool
        self.assertEqual(SG.lp_status({"lp_by_pool": {"P": 100, "Q": 0}}, 5.0, "cpmm", None, "P"), (100, "RugCheck"))
        self.assertEqual(SG.lp_status({"lp_by_pool": {"Q": 100}}, 7.0, "cpmm", None, "P"), (7.0, "GeckoTerminal"))
        self.assertEqual(SG.lp_status({"lp_locked_pct": 100}, None, "cpmm", None, "P")[1], "RugCheck, deepest pool")
        self.assertEqual(SG.lp_status(None, 99.9, "cpmm", None, "P"), (99.9, "GeckoTerminal"))
        # Meteora DBC can leave LP claimable: its graduation pool needs a lock figure
        dbc = {"graduated_pool": "P", "launchpad": "met-dbc"}
        self.assertIsNone(SG.lp_status(None, None, "cpmm", dbc, "P")[0])
        self.assertEqual(SG.lp_status(None, 100.0, "cpmm", dbc, "P")[0], 100.0)
        self.assertEqual(SG.lp_status(None, None, "cpmm", {"graduated_pool": "Q", "launchpad": "pump.fun"}, "P")[0], None)
        self.assertIn("withdraw", SG.lp_status(None, None, "concentrated", None, "P")[1])


class Metrics(unittest.TestCase):
    def test_build_metrics_tolerates_partial_sources(self):
        """Live data arrives with holes: Jupiter stats without a buy or sell figure, no RugCheck, no trades."""
        ds = {"mcap": 80_000, "fdv": 80_000, "liq": 30_000, "vol": {"h24": 50_000, "h1": 3_000}, "dex": "pumpswap",
              "labels": [], "pair": "P", "chg": {"h1": -5.0}}
        jup = {"launchpad": "pump.fun", "graduated_pool": "P", "mint_disabled": True, "freeze_disabled": True,
               "holders": 300, "s1h": {"traders": 40, "sell_vol": 900.0}}
        hist = {"dev_drop": None, "top_outflow_6h": None, "holder_growth": None}
        m = scan.build_metrics(ds, None, hist, jup, None, None, None, None, True, 1_000_000)
        self.assertIsNone(m["sell_share_1h"])
        self.assertEqual(m["lp_basis"], "pump.fun graduation pool")
        self.assertTrue(m["authority_clean"])
        self.assertFalse(m["risk"]["complete"])
        G.evaluate(m, False)                       # must not raise on the partial record

    def test_goplus_is_a_second_opinion_that_only_adds(self):
        ds = {"mcap": 500_000, "fdv": 500_000, "liq": 60_000, "vol": {"h24": 90_000, "h1": 4_000}, "dex": "raydium",
              "labels": [], "pair": "P", "chg": {}}
        hist = {"dev_drop": None, "top_outflow_6h": None, "holder_growth": None}
        rpc = {"mint_auth": None, "freeze_auth": None, "extensions": {}}
        gp = {"mintable": True, "freezable": False, "traps": ["transfer fee can be raised"], "fee_pct": 4.2, "meta_mutable": True}
        m = scan.build_metrics(ds, None, hist, None, None, rpc, None, None, False, 1_000_000, gp)
        self.assertTrue(m["authority_clean"])                 # the chain read wins for authorities
        self.assertEqual(m["gp_traps"], ["transfer fee can be raised"])
        self.assertEqual(m["transfer_fee"], 4.2)              # the higher fee reading
        self.assertTrue(m["meta_mutable"])
        only = scan.build_metrics(ds, None, hist, None, None, None, None, None, False, 1_000_000, gp)
        self.assertFalse(only["authority_clean"])             # no other source: GoPlus decides
        rc = {"creator_pct": 1.0, "top10": 12.0, "same_size": 1, "linked_wallets": 5, "holders": 500, "rugged": False,
              "bad_ext": [], "transfer_fee": 0, "mint_auth": None, "freeze_auth": None}
        old = scan.build_metrics(ds, rc, hist, None, None, rpc, None, None, False, 1_000_000)
        self.assertEqual(old.get("cluster_skip"), "older RugCheck read")
        rc.update(cluster_pct=7.5, cluster_n=12)
        new = scan.build_metrics(ds, rc, hist, None, None, rpc, None, None, False, 1_000_000)
        self.assertEqual((new["cluster_pct"], new["cluster_n"]), (7.5, 12))


    def test_packed_gates_round_trip(self):
        rows = [{"gates": G.evaluate(good(), False)},
                {"gates": G.evaluate(good(lp_basis="GeckoTerminal", launchpad="pump.fun", top10=60), False)},
                {"gates": G.evaluate(good(rugged=None, rc_down=True), True)}]
        meta, pack = scan.pack_gates(rows)
        for r in rows:
            for g in r["gates"]:
                p, c = pack(g), meta[g["id"]]
                back = {"id": p["id"], "ok": p["ok"], "value": p["v"], "hard": p["k"] == "h", "info": p["k"] == "i",
                        "group": c["group"], "label": c["label"], "rule": p.get("r") or c["rule"]}
                self.assertEqual(back, g)


class Lab(unittest.TestCase):
    CFG = {"min_n": 60, "min_test": 30, "min_keep": 0.3, "min_auc_gap": 0.08, "min_lift": 0.08, "z": 2.5}

    def test_outcomes_fill_at_each_horizon_within_tolerance(self):
        H, tol = 3600, 40 * 60
        o = {"ts": 0, "price": 1.0}
        for t, p in ((20 * 60, 1.6), (H + 10 * 60, 1.2), (6 * H + 50 * 60, 0.9), (24 * H + 5 * 60, 0.15)):
            o.update(LAB.step(o, p, t, tol))
        self.assertEqual(o["p1"], 1.2)
        self.assertIsNone(o.get("p6"))                 # first price after +6h came 50 min late: left empty
        self.assertEqual(o["p24"], 0.15)
        self.assertEqual((o["hi"], o["lo"]), (1.6, 0.15))
        self.assertIsNotNone(o["up50_ts"]); self.assertIsNotNone(o["dn80_ts"])
        self.assertFalse(LAB.rugged(o))                # it traded 50% above entry before falling to 0.2x
        o.update(LAB.step(o, 0.1, 25 * H, tol))
        self.assertEqual(o.get("done"), 1)

    def test_exit_rules_use_first_crossings(self):
        H, tol = 3600, 40 * 60
        o = {"ts": 0, "price": 1.0}
        for t, p in ((1200, 1.25), (2 * H, 0.65), (24 * H + 600, 0.9)):
            o.update(LAB.step(o, p, t, tol))
        self.assertEqual(set(o["cross"]), {"u10", "u20", "d10", "d20", "d30"})
        self.assertEqual(LAB.exit_result(o, 20, 30), 0.2)          # +20% came before the stop
        self.assertEqual(LAB.exit_result(o, 30, 30), -0.3)         # +30% never came; the -30% stop did
        self.assertAlmostEqual(LAB.exit_result(o, 50, None), -0.1) # no stop: held to +24h
        same = {"cross": {"u20": 5, "d20": 5}, "p24": 1.0}
        self.assertEqual(LAB.exit_result(same, 20, 20), -0.2)      # same run: assume the stop first
        ex = LAB.exit_rules([o])
        self.assertEqual(ex["n"], 1)
        self.assertAlmostEqual(ex["hold"]["mean"], -0.1)
        self.assertEqual(ex["rules"][0]["mean"], 0.2)

    def test_rugged_label(self):
        self.assertTrue(LAB.rugged({"dn80_ts": 5, "up50_ts": None}))
        self.assertTrue(LAB.rugged({"dn80_ts": 5, "up50_ts": 9}))
        self.assertFalse(LAB.rugged({"dn80_ts": 9, "up50_ts": 5}))
        self.assertIsNone(LAB.rugged({}))
        self.assertFalse(LAB.rugged({"done": 1}))

    def test_auc_and_rank_correlation(self):
        a, se = LAB.auc([1, 2, 3, 4], [False, False, True, True])
        self.assertEqual(a, 1.0)
        self.assertEqual(LAB.auc([1, 2, 3, 4], [True, True, False, False])[0], 0.0)
        self.assertEqual(LAB.auc([1, 1, 1, 1], [True, False, True, False])[0], 0.5)
        self.assertAlmostEqual(LAB.spearman([1, 2, 3, 4], [10, 20, 30, 40]), 1.0)
        self.assertAlmostEqual(LAB.spearman([1, 2, 3, 4], [4, 3, 2, 1]), -1.0)

    def test_features_derive_ratios_and_skip_missing(self):
        d = {"mcap": 100_000, "liq": 20_000, "vol": {"h1": 5_000, "h6": 30_000, "h24": 60_000}, "chg": {"h1": 4.0},
             "buys1": 30, "sells1": 20}
        j = {"s1h": {"net_flow": 2_000.0, "traders": 50, "net_buyers": 30}, "launchpad": "pump.fun"}
        f = LAB.features(d, {"age_min": 120}, j)
        self.assertEqual((f["liq_pct"], f["turn"], f["v1h_24"], f["v6h_24"], f["bs1h"]), (0.2, 0.6, 2.0, 2.0, 1.5))
        self.assertEqual((f["nf1h_liq"], f["brd1h"], f["age"], f["lp"]), (0.1, 0.6, 2.0, "pump.fun"))
        self.assertNotIn("c24h", f)
        rules = [("a", "", "v1h", ">=", 10_000), ("b", "", "c1h", ">", 0), ("c", "", "c24h", "<=", 100)]
        self.assertEqual(LAB.rule_results(f, rules), {"a": 0, "b": 1})

    def _rows(self, n, signal):
        rnd = random.Random(7)
        rows = []
        for i in range(n):
            v = rnd.random()
            up = rnd.random() < (0.25 + 0.5 * v if signal else 0.45)
            x = 1 + rnd.random() if up else rnd.random()
            rows.append({"ts": i, "mint": f"m{i}", "ev": "entry", "passed": 1, "f": {"v1h": v * 10_000},
                         "rules": {"r": 1 if v > 0.5 else 0}, "p24": x, "p6": x})
        return rows

    def test_variable_verdicts_need_signal_and_sample(self):
        self.assertEqual(LAB.analyse_variable(self._rows(400, True), "v1h", "p24", self.CFG)["verdict"], "works")
        self.assertIn(LAB.analyse_variable(self._rows(400, False), "v1h", "p24", self.CFG)["verdict"], ("none", "weak"))
        self.assertEqual(LAB.analyse_variable(self._rows(40, True), "v1h", "p24", self.CFG)["verdict"], "collecting")
        v = LAB.analyse_variable(self._rows(400, True), "v1h", "p24", self.CFG)
        self.assertEqual(v["cut"]["op"], ">=")
        self.assertGreater(v["auc"], 0.6)
        self.assertEqual(len(v["fifths"]), 5)

    def test_rule_verdicts(self):
        rule = ("r", "label", "v1h", ">=", 5_000)
        self.assertEqual(LAB.analyse_rule(self._rows(400, True), rule, "p24", self.CFG)["verdict"], "helps")
        self.assertEqual(LAB.analyse_rule(self._rows(400, False), rule, "p24", self.CFG)["verdict"], "none")

    def test_populations_count_a_token_once_a_day(self):
        rows = [{"ts": 10, "mint": "a", "ev": "hourly", "passed": 0}, {"ts": 3610, "mint": "a", "ev": "hourly", "passed": 1},
                {"ts": 7210, "mint": "a", "ev": "entry", "passed": 1}, {"ts": 86400 + 5, "mint": "a", "ev": "hourly", "passed": 1}]
        p = LAB.populations(rows)
        self.assertEqual(len(p["entries"]), 1)
        self.assertEqual([r["ts"] for r in p["all"]], [10, 86405])
        self.assertEqual([r["ts"] for r in p["passing"]], [3610, 86405])


class LabPlumbing(unittest.TestCase):
    def test_observe_update_and_report(self):
        from undertow.store import Store
        st = Store(":memory:")
        st.upsert_seen({"mint": "M", "pool": "P", "dex": "pumpswap", "name": "Moo"}, 0)
        d = {"price": 1.0, "mcap": 50_000, "liq": 12_000, "vol": {"h1": 3_000, "h6": 9_000, "h24": 30_000}, "chg": {"h1": 2.0}}
        m = good(); m.update(sell_share_1h=0.4, holders=300, risk={"count": 2, "complete": True, "calibrated": True})
        gates = G.evaluate(m, False)
        row = {"t": {"mint": "M"}, "d": d, "m": m, "jup": {"launchpad": "pump.fun"}, "mq": {"label": "Healthy"},
               "momentum": {"score": 55}, "tg": None, "gates": gates, "moved": ("OUT", "IN"), "fs": 0, "ps": 0}
        self.assertEqual(scan.observe(st, [row], 0, {"sol24": -2.0}), 1)            # the entry
        row["moved"] = ("IN", "IN")
        self.assertEqual(scan.observe(st, [row], 1200, {}), 0)                      # not an hour yet, no event
        self.assertEqual(scan.observe(st, [row], 3600, {}), 0)                      # same day as its entry: not needed
        self.assertEqual(scan.observe(st, [row], 86400 + 3600, {}), 1)              # its first observation of the next day
        self.assertEqual(scan.observe(st, [row], 86400 + 7200, {}), 0)              # ... and only the first
        for t, p in ((3600 + 600, 1.3), (6 * 3600 + 600, 0.8), (24 * 3600 + 600, 1.1), (26 * 3600, 1.1)):
            scan.update_outcomes(st, {"M": {"price": p}}, t)
        rows = st.obs_rows()
        self.assertEqual([r["ev"] for r in rows], ["entry", "hourly"])
        self.assertEqual((rows[0]["p1"], rows[0]["p6"], rows[0]["p24"], rows[0]["done"]), (1.3, 0.8, 1.1, 1))
        self.assertEqual(rows[0]["f"]["sol24"], -2.0)
        self.assertEqual(rows[0]["rules"]["v24_100k"], 0)
        self.assertEqual(rows[0]["rules"]["g:top10"], 1)                 # every gate's own result, for the review
        self.assertNotIn("g:devsell", rows[0]["rules"])                   # no value (dev_drop unknown), no result
        rep, lab_rows = scan.lab_report(st)
        self.assertEqual(rep["pops"]["entries"]["p24"]["base"]["n"], 1)
        self.assertEqual(rep["stats"]["entries"], 1)
        import tempfile, os, csv as _csv
        path = os.path.join(tempfile.mkdtemp(), "o.csv")
        scan.write_obs_csv(path, lab_rows, st.symbols())
        with open(path) as fh:
            got = list(_csv.reader(fh))
        self.assertEqual(got[1][1], "Moo")
        self.assertEqual(len(got[0]), len(got[1]))


class Tracker(unittest.TestCase):
    def setUp(self):
        self.t0 = 1_000_000
        self.trk = TR.start(self.t0, 1.0, 50_000)

    def candles(self, rows):
        return [[self.t0 + dt, 1, hi, lo, cl, 1] for dt, hi, lo, cl in rows]

    def test_ath_ignores_pre_entry_candles_and_keeps_time(self):
        c = self.candles([(-300, 9.0, 1.0, 1.0), (300, 2.0, 0.8, 1.5), (600, 3.5, 1.4, 2.0), (900, 2.2, 1.9, 2.0)])
        t = TR.update(self.trk, c, self.t0 + 1200, 2.0, (1,))
        self.assertEqual((t["ath_price"], t["ath_ts"]), (3.5, self.t0 + 600))
        self.assertEqual((t["low_price"], t["low_ts"]), (0.8, self.t0 + 300))
        s = TR.summary(t, 2.0, None)
        self.assertEqual((s["ath_mcap"], s["now_mcap"], s["now_x"]), (175_000, 100_000, 2.0))

    def test_idempotent_and_live_price_can_set_ath(self):
        c = self.candles([(300, 2.0, 0.9, 1.5)])
        a = TR.update(self.trk, c, self.t0 + 600, 1.5, (1,))
        self.assertEqual(TR.update(a, c, self.t0 + 600, 1.5, (1,)), a)
        b = TR.update(a, None, self.t0 + 900, 4.0, (1,))
        self.assertEqual((b["ath_price"], b["ath_ts"]), (4.0, self.t0 + 900))

    def test_outcomes(self):
        c = self.candles([(300, 1.2, 0.9, 1.1), (3300, 1.9, 1.7, 1.8), (3900, 1.4, 1.2, 1.3)])
        t = TR.update(self.trk, c, self.t0 + 3600 + 600, 1.3, (1, 6))
        self.assertAlmostEqual(t["out"]["1"], 1.8)               # close of the last candle at or before +1h
        self.assertNotIn("6", t["out"])                           # not due yet
        late = TR.update(self.trk, [], self.t0 + 40 * 3600, 1.0, (1,))   # first look 40h later: +1h fell in a gap
        self.assertIsNone(late["out"]["1"])

    def test_first_day_outcomes_use_the_study_definition(self):
        rug = TR.update(self.trk, self.candles([(300, 1.2, 0.5, 0.6), (600, 0.6, 0.1, 0.15)]), self.t0 + 900, 0.15, ())
        self.assertEqual(TR.day_outcome(rug, self.t0 + 900), (True, None))           # rugged; doubling still possible
        pumped = TR.update(self.trk, self.candles([(300, 1.6, 1.0, 1.5), (600, 1.5, 0.1, 0.15)]), self.t0 + 900, 0.15, ())
        self.assertEqual(TR.day_outcome(pumped, self.t0 + 900)[0], False)            # traded +50% first: not a rug
        dbl = TR.update(self.trk, self.candles([(300, 2.5, 1.0, 2.0)]), self.t0 + 25 * 3600, 2.0, ())
        self.assertEqual(TR.day_outcome(dbl, self.t0 + 25 * 3600), (False, True))


if __name__ == "__main__":
    unittest.main()


class Snapshots(unittest.TestCase):
    """Hourly tracker snapshots, the page's series, and the state the scheduled task carries between runs."""
    def tracked_store(self):
        from undertow.store import Store
        st = Store(":memory:")
        st.upsert_seen({"mint": "M", "pool": "P", "dex": "pumpswap", "name": "Moo"}, 0)
        st.set_cols("M", trk_json=json.dumps(TR.start(0, 1.0, 50_000)))
        st.commit()
        return st

    DS = {"M": {"price": 1.2, "mcap": 60_000, "fdv": 60_000, "liq": 10_000, "dex": "pumpswap", "labels": [],
                "vol": {"h1": 1_000, "h6": 5_000, "h24": 10_000}, "chg": {"h1": 5.0}, "buys1": 30, "sells1": 20}}
    JUP = {"M": {"holders": 300, "top_holders_pct": 30.0, "organic": 40.0,
                 "s1h": {"net_flow": 100.0, "traders": 20, "net_buyers": 12}}}

    def test_out_of_range_token_is_snapshotted_hourly_with_why(self):
        st = self.tracked_store()
        self.assertEqual(scan.snapshot_tracked(st, [], self.DS, dict(self.JUP), 3600), 1)
        s = st.tsnaps("M")[0]
        self.assertEqual((s["ev"], s["h"], s["state"], s["fails"], s["x"]), ("hourly", 1.0, "OUT", "volume", 1.2))
        self.assertEqual((s["hold"], s["top10"], s["nf1h"], s["brd1h"], s["bs1h"], s["mc"]), (300, 30.0, 100.0, 0.6, 1.5, 60_000))
        self.assertEqual(scan.snapshot_tracked(st, [], self.DS, dict(self.JUP), 3600 + 1200), 0)   # not an hour yet
        self.assertEqual(scan.snapshot_tracked(st, [], {}, {}, 7200), 1)                           # nothing prices it
        s = st.tsnaps("M")[-1]
        self.assertEqual((s["state"], s["fails"], s["price"], s["x"]), ("GONE", "nodata", None, None))

    def test_entry_is_recorded_at_once(self):
        st = self.tracked_store()
        scan.snapshot_tracked(st, [], self.DS, dict(self.JUP), 3600)
        row = {"t": {"mint": "M"}, "d": self.DS["M"], "m": good(holders=None), "gates": G.evaluate(good(), False),
               "entered_first": True, "state_new": "IN", "fs": 0, "ps": 0}
        self.assertEqual(scan.snapshot_tracked(st, [row], self.DS, dict(self.JUP), 3700), 1)
        s = st.tsnaps("M")[-1]
        self.assertEqual((s["ev"], s["h"], s["state"], s["fails"]), ("entry", 0.0, "IN", ""))

    def test_thinning_keeps_hourly_then_six_hourly(self):
        st = self.tracked_store()
        for h in range(0, 101):
            st.add_tsnap(h * 3600, "M", "entry" if h == 0 else "hourly", float(h), "IN", [], 1.0, 1.0, {})
        st.thin_tsnap(72)
        hs = [s["h"] for s in st.tsnaps("M")]
        self.assertEqual(hs[:73], [float(h) for h in range(73)])
        self.assertEqual(len(hs) - 73, len({int((h - 72) // 6) for h in range(73, 101)}))

    def test_series_and_marks(self):
        snaps = [{"h": 0.0, "ev": "entry", "x": 1.0, "mc": 50, "hold": 100},
                 {"h": 1.05, "ev": "hourly", "x": 1.3, "mc": 65, "hold": 120},
                 {"h": 2.4, "ev": "hourly", "x": 0.9, "mc": 45, "hold": None},
                 {"h": 6.4, "ev": "hourly", "x": 0.7, "mc": 35, "hold": 90}]
        hx = scan.x_series(snaps)
        self.assertEqual(hx, [1.0, 1.3, 0.9, None, None, None, 0.7])
        vt = scan.marks_table(snaps, {"hold": 99, "top10": 20, "liq": 500})
        self.assertEqual(vt["mc"], [50, 65, 35, None, 35])
        self.assertEqual(vt["hold"], [100, 120, 90, None, 90])
        self.assertEqual(vt["liq"], [500, None, None, None, None])          # entry column from the entry record ...
        self.assertNotIn("top10", vt)                     # ... except top-10, which came from a different source there
        self.assertEqual(scan.slot_of(80.0), 78)
        self.assertEqual(scan.x_series([]), [])

    def test_snapshot_files_split_by_bucket(self):
        import tempfile, os, csv as _csv
        st = self.tracked_store()
        scan.snapshot_tracked(st, [], self.DS, dict(self.JUP), 3600)
        d = tempfile.mkdtemp()
        self.assertEqual(scan.write_snapshot_files(d, st, st.symbols()), 1)
        b = scan.bucket_of("M")
        self.assertEqual(b, ord("M") % C.SNAP_BUCKETS)
        got = json.loads(pathlib.Path(d, "snap", f"{b}.json").read_text())["M"]
        self.assertEqual(got["r"][0][:5], [3600, 1.0, "O", "volume", 1.2])
        with open(os.path.join(d, "snapshots.csv")) as fh:
            rows = list(_csv.reader(fh))
        self.assertEqual(rows[1][1], "Moo")
        self.assertEqual(len(rows[0]), len(rows[1]))

    def test_state_round_trip_and_refusal_to_start_empty(self):
        import tempfile, os, sqlite3
        from undertow import cloud
        st = self.tracked_store()
        d = tempfile.mkdtemp()
        db = os.path.join(d, "a.db")
        st.db.execute(f"VACUUM INTO '{db}'")
        cloud.pack(db, os.path.join(d, "out"))
        shards = [json.loads(pathlib.Path(d, "out", "state", f"db.{i}.json").read_text()) for i in range(cloud.SHARDS)]
        self.assertEqual([s["part"] for s in shards], [0, 1, 2])
        self.assertEqual(shards[0]["of"], 1)
        self.assertTrue(cloud.restore(os.path.join(d, "out"), os.path.join(d, "b.db")))
        con = sqlite3.connect(os.path.join(d, "b.db"))
        self.assertEqual(con.execute("SELECT symbol FROM tokens").fetchone()[0], "Moo")
        con.close()
        self.assertFalse(cloud.restore(os.path.join(d, "nothing"), os.path.join(d, "c.db")))
        with self.assertRaises(SystemExit):                      # never start from empty and overwrite the history
            cloud.cycle(os.path.join(d, "nothing"), os.path.join(d, "site"))
        self.assertTrue(cloud.bundle(os.path.join(d, "src", "bundle.json")) > 10)
        files = json.loads(pathlib.Path(d, "src", "bundle.json").read_text())["files"]
        import re
        for name in files:                                       # every path passes the scheduled task's own filter
            self.assertRegex(name, r"^((undertow|web)/[A-Za-z0-9_.-]+\.(py|css|html|js)|build_page\.py)$")

    def test_page_builds_as_a_fragment_or_a_document(self):
        import tempfile, os
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
        import build_page
        d = tempfile.mkdtemp()
        build_page.build(os.path.join(d, "f.html"), fragment=True)
        frag = pathlib.Path(d, "f.html").read_text()
        self.assertTrue(frag.startswith("<title>Undertow</title>"))
        self.assertNotIn("<html", frag[:2000])
        self.assertNotIn("supabase", frag)                               # the claude.ai copy has no community layer
        build_page.build(os.path.join(d, "p.html"))
        page = pathlib.Path(d, "p.html").read_text()
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertIn("supabase-js@2.112.3", page)                       # the GitHub page does
        self.assertIn(".cm-modal", page)
        for p_ in (frag, page):                                          # the Buy & sell tab is in every build
            self.assertIn('data-view="trade"', p_)
            self.assertIn('id="tradewrap"', p_)
            self.assertIn("function sellState", p_)
        build_page.build(os.path.join(d, "s.html"), fragment=True, split=True)       # the published page: small
        small = pathlib.Path(d, "s.html").read_text()
        self.assertLess(len(small), 12_000)
        self.assertIn('<script src="app.js">', small)
        self.assertTrue(pathlib.Path(d, "app.js").read_text().rstrip().endswith("})();"))
