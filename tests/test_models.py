"""The Models tab (undertow/models.py, train.py), attention (attention.py) and correlations (corr.py)."""
import unittest, sys, pathlib, tempfile, os, json, math, random
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from undertow import attention as A, corr as CR, trade as T, config as C

try:
    import numpy as np
    from undertow import models as MOD
    import sklearn  # noqa: F401
    HAVE_ML = True
except ImportError:
    HAVE_ML = False

H = 3600


def synthetic_path(n_coins=40, hours=60, seed=1, signal=0.6):
    """Coins scanned every 15 minutes. The price drifts with a hidden state the variable 'nf1h_liq' reveals (with
    noise), so a model has something real to find; every other variable is noise."""
    rng = random.Random(seed)
    path, t0 = {}, 1_800_000_000.0
    for c in range(n_coins):
        mint, p, rows = f"C{c:03d}", 1.0, []
        drift = 0.0
        for k in range(hours * 4):
            ts = t0 + k * 900 + c          # coins scanned a second apart, as a scan would
            if k % 8 == 0:
                drift = rng.gauss(0, 0.012)
            p *= math.exp(drift + rng.gauss(0, 0.02))
            f = {"nf1h_liq": drift * signal * 10 + rng.gauss(0, 0.05), "liq": 150_000 + rng.random() * 50_000,
                 "mc": p * 1e6, "ru6": rng.random() * 30, "vola": rng.random() * 4, "c1h": rng.gauss(0, 5),
                 "gtr": rng.choice([0, 0, 0, 12, 30]), "bst": rng.choice([0, 0, 1]), "org": rng.random() * 100}
            rows.append((ts, "I", p, f["liq"], f["c1h"], f))
        path[mint] = rows
    return path


class Attention(unittest.TestCase):
    def test_ranks_spikes_and_growth(self):
        now = 1_000_000.0
        lists = {"gt1h": ["A", "B"], "jup1h": ["B"], "gt5m": []}
        st = {"hist": [[now - 2 * H, 0, 0, 0], [now - H, 2, 0, 0]],
              "x": {"handle": "a", "followers": 1100, "read_ts": now, "ts": now,
                    "h": [[now - 24 * H, 1000], [now - 6 * H, 1050], [now - H, 1090], [now, 1100]]},
              "orders": {"ads": 1, "profile": 1, "cto": 0, "ad_last": now - H, "ts": now - 600},
              "web": {"domain": "example.com", "free": 0, "reg": now - 40 * 86400, "ts": now}}
        f = A.features(st, now, "A", {"boosts": 5, "n_links": 3}, lists, {"members": 200, "online": 10, "growth_6h": 0.01})
        self.assertEqual(f["gtr"], 40)                     # first on the 1h list
        self.assertEqual(f["jtr"], 0)                      # listed list, not on it
        self.assertNotIn("gtr5", f)                        # an empty list is unknown, not "not trending"
        self.assertEqual(f["bst_d1h"], 3)                  # 2 an hour ago, 5 now
        self.assertEqual(f["trend_new"], 1)                # on the list now, not an hour ago
        self.assertEqual((f["ads"], f["dsp"], f["cto"], f["ad_new"]), (1, 1, 0, 1))
        self.assertAlmostEqual(f["xfg"], ((1100 / 1050) ** (1 / 6) - 1) * 100, places=6)
        self.assertGreater(f["xf_spike"], 0)               # last hour faster than the day
        self.assertAlmostEqual(f["tgg"], 1.0)
        self.assertAlmostEqual(f["tgo"], 0.05)
        self.assertAlmostEqual(f["web_age"], 40.0, places=3)
        self.assertEqual(f["web_free"], 0)
        self.assertNotIn("web_new", f)                     # needs the coin's age
        old = A.features(st, now, "A", {}, lists, age_h=24)
        self.assertEqual(old["web_new"], 0)                # a 40-day-old domain on a day-old coin predates it
        st["web"]["reg"] = now - 5 * 86400
        self.assertEqual(A.features(st, now, "A", {}, lists, age_h=24)["web_new"], 1)
        st["web"] = {"domain": "github.com", "free": 0, "reg": now - 9000 * 86400, "ts": now}
        g = A.features(st, now, "A", {}, lists, age_h=24)
        self.assertEqual(g["web_free"], 1)                 # a host added to the free list after the reading
        self.assertNotIn("web_age", g)

    def test_hourly_history_and_x_readings(self):
        st, ok = A.add_hourly({}, 1000.0, {"bst": 1, "gtr": 0, "jtr": 5})
        self.assertTrue(ok)
        st, ok = A.add_hourly(st, 1000.0 + 600, {"bst": 2})
        self.assertFalse(ok)                               # under 55 minutes since the last reading
        x = A.add_x(None, "h", {"followers": 10, "tweets": 3}, 0.0)
        x = A.add_x(x, "h", None, 3600.0)                  # a failed read keeps the last count, marked
        self.assertEqual((x["followers"], x["fail"], len(x["h"])), (10, 1, 1))
        x = A.add_x(x, "other", {"followers": 5}, 7200.0)  # a new handle starts afresh
        self.assertEqual(len(x["h"]), 1)
        self.assertIn("vercel.app", A.FREE_HOSTS)

    def test_lab_and_trade_know_the_attention_variables(self):
        from undertow import lab as LAB
        self.assertTrue(set(A.KEYS) <= set(LAB.VAR_KEYS))
        self.assertTrue(set(A.KEYS) <= set(T.VAR_KEYS))
        f = LAB.features({"mcap": 1}, {"attn": {"gtr": 12, "bogus": 1}}, {})
        self.assertEqual(f["gtr"], 12)
        self.assertNotIn("bogus", f)
        for r in C.ATTENTION_RULES + C.SELL_WARNINGS:      # every condition reads a variable the bench knows
            self.assertTrue(all(k in T.VAR_KEYS for k, _o, _a in r["all"]), r["id"])
        self.assertTrue(all(r[2] in LAB.VAR_KEYS for r in C.ATTENTION_CANDIDATES))


class Correlations(unittest.TestCase):
    def test_spearman_and_clustered_t(self):
        xs = list(range(100))
        r = CR.spearman_t(xs, [x * 2 + 1 for x in xs], [i % 10 for i in xs])
        self.assertAlmostEqual(r["rho"], 1.0, places=6)
        r = CR.spearman_t(xs, [-x for x in xs], [i % 10 for i in xs])
        self.assertAlmostEqual(r["rho"], -1.0, places=6)
        self.assertEqual(CR.ranks([3, 1, 3, 2]), [2.5, 0.0, 2.5, 1.0])

    def test_analyse_finds_the_planted_variable(self):
        path = synthetic_path(n_coins=40, hours=40, signal=1.0)
        doc = CR.analyse(path, max(r[-1][0] for r in path.values()), {**C.CORR, "min_n": 100, "min_coins": 10})
        by = {v["key"]: v for v in doc["vars"]}
        p1 = by["nf1h_liq"]["predicts"]["1"]
        self.assertGreater(p1["rho"], 0.1)                  # the planted signal shows
        self.assertGreater(abs(p1["rho"]), abs((by["org"].get("predicts") or {}).get("1", {}).get("rho") or 0))
        self.assertTrue(by["c1h"]["price_derived"])
        self.assertNotIn("together", by["c1h"])


@unittest.skipUnless(HAVE_ML, "needs numpy and scikit-learn (requirements-ml.txt)")
class Models(unittest.TestCase):
    def setUp(self):
        self.algos, self.exit_algos = MOD.ALGOS, MOD.EXIT_ALGOS
        MOD.ALGOS = [("logit", "Logistic regression", "cls"), ("ridge", "Ridge regression", "ret")]
        MOD.EXIT_ALGOS = [("logit", "Logistic regression")]
        self.dir = tempfile.mkdtemp()
        self.cfg = {**C.MODELS, "min_samples": 300, "min_coins": 10, "min_train": 150, "min_test": 50, "fold_h": 6,
                    "luck_draws": 50}
        self.pol = {"id": "tp10_8h", "tp": 10, "max_h": 8}

    def tearDown(self):
        MOD.ALGOS, MOD.EXIT_ALGOS = self.algos, self.exit_algos

    def test_samples_are_one_per_coin_hour_and_matured(self):
        path = synthetic_path(n_coins=5, hours=30)
        s = MOD.entry_samples(path, self.pol, C.TRADE)
        end = T.path_end(path)
        self.assertTrue(s)
        self.assertTrue(all(x["ts"] <= end - 9 * H for x in s))          # every label had time to close
        keys = [(x["mint"], int(x["ts"] // H)) for x in s]
        self.assertEqual(len(keys), len(set(keys)))

    def test_folds_train_only_on_trades_closed_before_the_test_window(self):
        ts = np.arange(0, 60 * H, 900.0)
        closed = ts + np.where(np.arange(len(ts)) % 3, 8 * H, 0.5 * H)     # some trades close fast, some take 8h
        fl = MOD.folds(ts, closed, {**self.cfg, "min_train": 10, "min_test": 10})
        self.assertTrue(fl)
        for tr, te in fl:
            self.assertLess(closed[tr].max(), ts[te].min())                # no training label reaches into the window
            self.assertTrue((ts[te] >= 30 * H - 1).all())                 # test windows tile the later half

    def test_train_score_and_decide(self):
        path = synthetic_path(n_coins=40, hours=70, signal=1.0)
        s = MOD.train_all(path, self.pol, C.TRADE, self.cfg, {"all": "every variable"}, self.dir, log=lambda *a: None)
        self.assertEqual(s["status"], "ok", s.get("status"))
        ent = {m["id"]: m for m in s["entry"]}
        self.assertIn("random", ent)
        lg = ent["logit.all"]
        self.assertGreater(lg["auc"], 0.55)                                 # the planted signal is found out of sample
        self.assertLess(abs(ent["random"]["auc"] - 0.5), 0.08)
        self.assertIsNotNone(lg["luck_best"])
        self.assertTrue(os.path.exists(os.path.join(self.dir, lg["file"])))
        # the scan's side: load, score, pick, and the exit model's call
        now = s["trained_at"] + 600
        bank = MOD.Bank(self.dir, now, 30)
        self.assertTrue(bank.fresh)
        self.assertIn("logit.all", bank.entry)
        feats = {"A": {"nf1h_liq": 0.5, "liq": 1e5}, "B": {"nf1h_liq": -0.5, "liq": 1e5}}
        sc = bank.entry_scores(feats, {})
        self.assertGreater(sc["logit.all"]["A"], sc["logit.all"]["B"])
        picks = bank.fired(sc, feats, now, 0.2)
        self.assertIn("random", picks)
        rules = MOD.rules_for(s)
        self.assertTrue(all(r["id"].startswith("m:") and r["model"] and r["all"] == [] for r in rules))
        self.assertFalse(T.fires(rules[0], {"anything": 1}))               # a model's rule never fires on conditions
        pols = MOD.exit_policies(s)
        if pols:
            self.assertEqual(pols[0]["tp"], 10)
            state = MOD.trade_state(now - H, 1.0, 1e5, 1.05, 1.02, 1e5, now)
            probs, sells = bank.exit_calls([(1, pols[0]["id"], MOD.exit_row({"nf1h_liq": -0.5}, -2, state))], 0.5)
            self.assertIn((1, pols[0]["id"]), probs)
        # an old model trades nothing
        self.assertFalse(MOD.Bank(self.dir, s["trained_at"] + 40 * H, 30).fresh)

    def test_collecting_until_enough_samples(self):
        s = MOD.train_all(synthetic_path(n_coins=3, hours=20), self.pol, C.TRADE, self.cfg, {"all": "x"}, self.dir,
                          log=lambda *a: None)
        self.assertTrue(s["status"].startswith("collecting"))
        self.assertFalse(MOD.Bank(self.dir, s["trained_at"], 30).fresh)


class ScanSide(unittest.TestCase):
    """fetch_attention and the ledger with models, against stubbed sources and a small trained bank."""

    def setUp(self):
        from undertow import scan as SC, sources as S
        from undertow.store import Store
        self.SC, self.S = SC, S
        self.dir = tempfile.mkdtemp()
        self.st = Store(os.path.join(self.dir, "t.db"))
        self.saved = (S.ds_orders, S.x_profile, S.domain_registered)

    def tearDown(self):
        self.S.ds_orders, self.S.x_profile, self.S.domain_registered = self.saved
        self.st.close()

    def test_fetch_attention_records_each_source_once_per_handle_and_domain(self):
        S, SC, st = self.S, self.SC, self.st
        calls = {"o": 0, "x": 0, "w": 0}
        S.ds_orders = lambda m: calls.__setitem__("o", calls["o"] + 1) or {"ads": 1, "trend_ads": 0, "ad_last": 50.0, "profile": 1, "cto": 0}
        S.x_profile = lambda h: calls.__setitem__("x", calls["x"] + 1) or {"followers": 1234, "tweets": 9}
        S.domain_registered = lambda d: calls.__setitem__("w", calls["w"] + 1) or 1_000.0
        want = []
        for i, m in enumerate(("A", "B", "C")):
            st.upsert_seen({"mint": m, "pool": "", "dex": "", "name": m}, 100.0)
            want.append({"mint": m, "status": "IN" if i == 0 else "OUT", "attn_json": None, "gt_json": None})
        st.commit()
        jup = {"A": {"twitter": "https://x.com/same", "website": "https://www.proj.io/x"},
               "B": {"twitter": "https://x.com/same", "website": "https://proj.vercel.app"},
               "C": {"twitter": None, "website": None}}
        n = SC.fetch_attention(st, want, {m: {} for m in "ABC"}, jup, 100.0)
        self.assertEqual(calls, {"o": 3, "x": 1, "w": 1})                   # one X call for a shared handle
        a = json.loads(st.get("A")["attn_json"])
        self.assertEqual((a["x"]["followers"], a["web"]["domain"], a["web"]["free"], a["orders"]["ads"]), (1234, "proj.io", 0, 1))
        b = json.loads(st.get("B")["attn_json"])
        self.assertEqual((b["web"]["domain"], b["web"]["free"]), ("vercel.app", 1))   # a free host: no lookup
        self.assertEqual(n["x_ok"], 1)
        # nothing is due again a minute later
        for t in want:
            t["attn_json"] = st.get(t["mint"])["attn_json"]
        SC.fetch_attention(st, want, {m: {} for m in "ABC"}, jup, 160.0)
        self.assertEqual(calls, {"o": 3, "x": 1, "w": 1})

    @unittest.skipUnless(HAVE_ML, "needs numpy and scikit-learn")
    def test_models_open_logged_trades_and_exit_models_follow_them(self):
        SC, st = self.SC, self.st
        algos, exit_algos = MOD.ALGOS, MOD.EXIT_ALGOS
        MOD.ALGOS, MOD.EXIT_ALGOS = [("logit", "Logistic regression", "cls")], [("logit", "Logistic regression")]
        feat = SC.trade_features
        try:
            mdir = os.path.join(self.dir, "models")
            cfg = {**C.MODELS, "min_samples": 300, "min_coins": 10, "min_train": 150, "min_test": 50, "fold_h": 6, "luck_draws": 20}
            s = MOD.train_all(synthetic_path(n_coins=30, hours=70, signal=1.0), {"id": "tp10_8h", "tp": 10, "max_h": 8},
                              C.TRADE, cfg, {"all": "every variable"}, mdir, log=lambda *a: None)
            self.assertEqual(s["status"], "ok")
            now = s["trained_at"] + 60
            bank = MOD.Bank(mdir, now, 30)
            SC.trade_features = lambda st_, r, now_, regime: {"nf1h_liq": 2.0, "liq": 2e5, "ru6": 50.0}
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
            from test_trade import fake_row
            rows = [fake_row(m, 1.0) for m in ("A", "B")]
            ds = {m: {"price": 1.0, "liq": 2e5, "chg": {"h1": 0.0}} for m in ("A", "B")}
            pol, feats, ch, picks, sells, _minute, _closed = SC.trade_step(st, rows, ds, now, {}, bank)
            self.assertTrue(any(r["id"] == "m:logit.all" for r in pol["rules"]))
            self.assertIn("A", picks.get("logit.all", {}))                    # a strong reading scores in the top fifth
            sig = [x for x in st.sigs() if x["rule"] == "m:logit.all"]
            self.assertEqual({x["mint"] for x in sig}, {"A", "B"})
            self.assertTrue(all(x["f"].get("sc") is not None and x["f"].get("thr") is not None for x in sig))
            self.assertTrue(all(set(x["st"]) == {"tp10_8h", "x:logit"} for x in sig))   # live exit and exit models only
            page = SC.trade_page(st, pol, feats, rows, now, SC.exit_pool_of(bank), picks)
            self.assertTrue(any(e["id"] == "x:logit" for e in page["exits"]))
            mp = SC.models_page(st, bank, pol, page, now, picks, sells)
            self.assertTrue(mp["log"] and mp["log"][0]["model"] == "logit.all" or any(r["model"] == "logit.all" for r in mp["log"]))
            self.assertTrue(any(e["id"] == "logit.all" and e["trades"] == 2 for e in mp["entry"]))
            # next scan: the price falls; the exit model is asked about every open model trade
            ds2 = {m: {"price": 0.97, "liq": 2e5, "chg": {"h1": -3.0}} for m in ("A", "B")}
            SC.scan_step(st, ds2, now + 900, {e["id"]: e for e in SC.exit_pool_of(bank)}, C.TRADE)
            SC.trade_step(st, [fake_row(m, 0.97) for m in ("A", "B")], ds2, now + 900, {}, bank)
            self.assertTrue(all("x:logit" in x["st"] or "x:logit" in x["out"] for x in st.sigs() if x["rule"] == "m:logit.all"))
        finally:
            MOD.ALGOS, MOD.EXIT_ALGOS = algos, exit_algos
            SC.trade_features = feat


class ExitModelStep(unittest.TestCase):
    def test_a_model_sell_only_applies_to_a_model_policy_and_the_target_still_wins(self):
        pos, cfg = {"in_ts": 0.0, "in_price": 1.0, "in_liq": 1e6}, C.TRADE
        pol = {"id": "x:rf", "tp": 10, "max_h": 8, "model": "rf"}
        self.assertEqual(T.step(pol, pos, T.new_state(1.0), 1.01, 1e6, 0, 900, cfg, None, True)[2], "model said sell")
        self.assertEqual(T.step(pol, pos, T.new_state(1.0), 1.2, 1e6, 0, 900, cfg, None, True)[2], "target")
        self.assertIsNone(T.step({"id": "tp10_8h", "tp": 10, "max_h": 8}, pos, T.new_state(1.0), 1.01, 1e6, 0, 900, cfg, None, True))
        sig = {"in_ts": 0.0, "in_price": 1.0, "in_liq": 1e6, "out": {}, "st": {"x:rf": T.new_state(1.0), "tp10_8h": T.new_state(1.0)}}
        out, st, *_ = T.advance(sig, {"price": 1.01, "liq": 1e6, "c1h": 0, "xm": {"x:rf": True}}, 900,
                                {"x:rf": pol, "tp10_8h": {"id": "tp10_8h", "tp": 10, "max_h": 8}}, cfg)
        self.assertEqual(set(out), {"x:rf"})
        self.assertEqual(set(st), {"tp10_8h"})

    def test_add_rules_skips_known_and_unknown(self):
        pol = T.new_policy(C.EXIT_POOL, C.DEFAULT_EXIT)
        ch = T.add_rules(pol, C.ATTENTION_RULES + [{"id": "bad", "label": "bad", "all": [["nope", ">", 1]]}], 100.0, "test")
        self.assertEqual(len(ch), len(C.ATTENTION_RULES))
        self.assertEqual(T.add_rules(pol, C.ATTENTION_RULES, 200.0, "test"), [])
        self.assertTrue(all(r["status"] == "testing" for r in pol["rules"]))


if __name__ == "__main__":
    unittest.main()
