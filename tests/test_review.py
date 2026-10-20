"""The weekly gate review (undertow/review.py) and how the gates read its decisions (undertow/gates.py)."""
import unittest, sys, pathlib, random
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from undertow import review as R, gates as G, config as C
from test_core import good, failing

DAY = 86400
GATES = ("top10", "linked", "creator", "lp", "mcap")
META = {"top10": {"label": "Top 10 holders", "group": "holders", "hard": False, "info": False},
        "linked": {"label": "Linked wallets", "group": "holders", "hard": False, "info": False},
        "creator": {"label": "Developer holding", "group": "holders", "hard": False, "info": False},
        "lp": {"label": "Liquidity can't be pulled", "group": "structure", "hard": True, "info": False},
        "mcap": {"label": "In your market-cap range", "group": "scope", "hard": False, "info": False}}
CFG = {**C.REVIEW, "testing": 3, "add_per_review": 1}


def obs(i, day, fail=None, rug=False, f=None):
    """One settled observation of token i on a day. fail: the one gate it failed (or None)."""
    ts = day * DAY + 3600
    rules = {"g:" + g: int(g != fail) for g in GATES}
    return {"mint": f"M{i}", "ts": ts, "ev": "hourly", "fails": [fail] if fail else [], "rules": rules,
            "f": f or {}, "passed": not fail, "done": 1, "dn80_ts": ts + 3600 if rug else None, "up50_ts": None,
            "p24": 0.1 if rug else 1.1}


def cohort(start, n, fail, rug_rate, day0=0, days=10, f=None, seed=1):
    rnd = random.Random(seed)
    k = round(n * rug_rate)
    flags = [True] * k + [False] * (n - k)
    rnd.shuffle(flags)
    return [obs(start + j, day0 + j % days, fail, flags[j], f(j, flags[j]) if f else None) for j in range(n)]


class Judge(unittest.TestCase):
    def ev(self, rb, nb, rp, np_, ub=0.2, up=0.2):
        g = lambda r, n, u: {"n": n, "n_rug": n, "rug": r, "n_up": n, "up50": u, "med24": 1.0}
        return {"blocked": g(rb, nb, ub), "passed": g(rp, np_, up)}

    def test_verdicts(self):
        self.assertEqual(R.judge(self.ev(.5, 10, .1, 200), CFG)[0], "collecting")
        self.assertEqual(R.judge(self.ev(.5, 60, .1, 200), CFG)[0], "protects")
        self.assertEqual(R.judge(self.ev(.1, 150, .1, 150), CFG)[0], "no effect")
        self.assertEqual(R.judge(self.ev(.1, 150, .1, 150, ub=.5, up=.2), CFG)[0], "costs")    # it removes the risers
        self.assertEqual(R.judge(self.ev(.02, 200, .2, 200), CFG)[0], "costs")                 # its coins rug less
        self.assertEqual(R.judge(self.ev(.14, 60, .1, 60), CFG)[0], "unclear")
        why = R.judge(self.ev(.5, 60, .1, 200), CFG)[1]
        self.assertIn("50% of the time (n=60)", why)


class Review(unittest.TestCase):
    def rows(self):
        # top10 and linked block coins that rug no more often than passing ones; creator's blocked coins rug far more
        return (cohort(0, 150, None, .10) + cohort(1000, 150, "top10", .10, seed=2) + cohort(2000, 150, "linked", .10, seed=3)
                + cohort(3000, 60, "creator", .50, seed=4) + cohort(4000, 150, "lp", .10, seed=5))

    def test_a_gate_is_dropped_only_after_two_reviews_agree_and_one_at_a_time(self):
        rows, now = self.rows(), 12 * DAY
        pol, ch = R.run_review(rows, None, META, now, CFG, [])
        self.assertEqual(pol["gates"]["top10"]["last"]["verdict"], "no effect")
        self.assertEqual(pol["gates"]["creator"]["last"]["verdict"], "protects")
        self.assertFalse([c for c in ch if c["what"] == "dropped"])                   # one review is not enough
        pol, ch = R.run_review(rows, pol, META, now + 7 * DAY, CFG, [])
        dropped = [c["id"] for c in ch if c["what"] == "dropped"]
        self.assertEqual(len(dropped), 1)                                              # at most one per review
        gid = dropped[0]
        self.assertIn(gid, ("top10", "linked"))
        self.assertEqual(pol["gates"][gid]["status"], "shown")
        self.assertIn("made no difference to rugs", pol["gates"][gid]["reason"])
        self.assertEqual(pol["gates"]["creator"]["status"], "gate")
        self.assertEqual(pol["gates"]["lp"]["status"], "gate")                         # structure: never dropped
        self.assertFalse(pol["gates"]["lp"]["reviewable"])
        self.assertFalse(pol["gates"]["mcap"]["reviewable"])                           # scope: never dropped
        pol, ch = R.run_review(rows, pol, META, now + 14 * DAY, CFG, [])
        self.assertEqual({g for g in ("top10", "linked") if pol["gates"][g]["status"] == "shown"}, {"top10", "linked"})
        self.assertEqual(len(pol["log"]), 2)

    def test_a_dropped_gate_comes_back_when_it_protects(self):
        rows, now = self.rows(), 12 * DAY
        pol = R.new_policy()
        pol["gates"]["creator"] = {"status": "shown", "since": 0, "short": "dropped", "streak": {"verdict": "protects", "n": 1}}
        pol["last_review"] = now - 7 * DAY
        pol, ch = R.run_review(rows, pol, META, now, CFG, [])
        self.assertEqual(pol["gates"]["creator"]["status"], "gate")
        self.assertEqual([c["what"] for c in ch if c["id"] == "creator"], ["restored"])

    def test_candidates_are_promoted_retired_and_replaced(self):
        # among coins that pass every gate, a developer holding over 1% rugs far more often; age does nothing
        rnd = random.Random(7)
        rows = []
        for j in range(400):
            hi = j % 3 == 0
            rug = rnd.random() < (.40 if hi else .06)
            rows.append(obs(j, j % 10, None, rug, {"dev": 3.0 if hi else 0.2, "age": rnd.choice([1, 12]),
                                                     "cfl": 1 if hi else 0}))
        pool = [{"id": "dev_1", "label": "Developer holds at most 1%", "key": "dev", "op": "<=", "at": 1.0},
                {"id": "age_6h", "label": "On a DEX for at least 6 hours", "key": "age", "op": ">=", "at": 6},
                {"id": "crowd_flags_0", "label": "No bad crowd tags", "key": "cfl", "op": "<=", "at": 0},
                {"id": "next_one", "label": "Waiting in the pool", "key": "age", "op": ">=", "at": 24}]
        gateable = {"dev", "age"}
        now = 12 * DAY
        pol, _ = R.run_review(rows, None, META, now, CFG, pool, gateable=gateable)
        self.assertEqual([c["id"] for c in pol["candidates"]], ["dev_1", "age_6h", "crowd_flags_0"])   # bench of 3
        by = {c["id"]: c for c in pol["candidates"]}
        self.assertEqual(by["dev_1"]["last"]["verdict"], "would protect")
        self.assertEqual(by["crowd_flags_0"]["last"]["verdict"], "would protect")
        self.assertFalse(by["crowd_flags_0"]["gateable"])
        pol, ch = R.run_review(rows, pol, META, now + 7 * DAY, CFG, pool, gateable=gateable)
        by = {c["id"]: c for c in pol["candidates"]}
        self.assertEqual(by["dev_1"]["status"], "promoted")
        self.assertEqual(by["crowd_flags_0"]["status"], "testing")      # the crowd is tested, never promoted
        self.assertIn(by["age_6h"]["status"], ("testing", "retired"))
        if by["age_6h"]["last"]["verdict"] == "no effect":
            self.assertEqual(by["age_6h"]["status"], "retired")
        self.assertIn("lab:dev_1", R.active_gates(pol, META))
        self.assertIn("next_one", by)                                     # the bench was topped up from the pool
        # the promoted rule is now judged on the coins that passed everything else, so it can still be removed later
        pol, _ = R.run_review(rows, pol, META, now + 14 * DAY, CFG, pool, gateable=gateable)
        by = {c["id"]: c for c in pol["candidates"]}
        self.assertEqual(by["dev_1"]["last"]["verdict"], "would protect")
        self.assertGreater(by["dev_1"]["last"]["blocked"]["n_rug"], 100)

    def test_due_and_page_view(self):
        self.assertTrue(R.due(None, 0, CFG))
        pol, _ = R.run_review(self.rows(), None, META, 12 * DAY, CFG, [])
        self.assertFalse(R.due(pol, 12 * DAY + 3 * DAY, CFG))
        self.assertTrue(R.due(pol, 19 * DAY, CFG))
        page = R.for_page(pol, META)
        self.assertEqual({g["id"] for g in page["gates"]}, set(META))
        self.assertEqual(page["next_review"], 19 * DAY)

    def test_old_rows_without_every_gate_result_fall_back_to_the_blocking_list(self):
        r = {"fails": ["top10"], "rules": {}}
        self.assertTrue(R.gate_failed(r, "top10"))
        self.assertFalse(R.gate_failed(r, "creator"))
        self.assertFalse(R.gate_failed({"fails": [], "rules": {"g:top10": 1}}, "top10"))


class GatesReadThePolicy(unittest.TestCase):
    def test_dropped_soft_gate_is_shown_not_gated(self):
        pol = {"gates": {"top10": {"status": "shown", "short": "dropped 27 Oct 2026: made no difference to rugs"},
                         "authority": {"status": "shown"}}}
        m = good(top10=40, authority_clean=False)
        gs = {g["id"]: g for g in G.evaluate(m, False, pol)}
        self.assertTrue(gs["top10"]["info"])
        self.assertIn("not gated: dropped 27 Oct 2026", gs["top10"]["rule"])
        self.assertNotIn("top10", failing(list(gs.values())))
        self.assertIn("authority", failing(list(gs.values())))       # a hard gate cannot be dropped this way

    def test_promoted_rule_gates_on_its_value_and_never_on_a_missing_one(self):
        pol = {"candidates": [{"id": "dev_1", "label": "Developer holds at most 1%", "key": "dev", "op": "<=", "at": 1.0,
                               "status": "promoted"},
                              {"id": "age_6h", "label": "Age", "key": "age", "op": ">=", "at": 6, "status": "testing"}]}
        m = good(); m["_f"] = {"dev": 3.0, "age": 1}
        self.assertIn("lab:dev_1", failing(G.evaluate(m, False, pol)))
        self.assertNotIn("lab:age_6h", {g["id"] for g in G.evaluate(m, False, pol)})   # testing rules do not gate
        m["_f"] = {"dev": 0.5}
        self.assertNotIn("lab:dev_1", failing(G.evaluate(m, False, pol)))
        m["_f"] = {}
        g = [g for g in G.evaluate(m, False, pol) if g["id"] == "lab:dev_1"][0]
        self.assertTrue(g["ok"])
        self.assertIn("not checked", g["rule"])

    def test_crowd_variables_can_never_become_gates(self):
        for k in ("crs", "crn", "cvn", "cfl"):
            self.assertIn(k, C.NOT_GATEABLE)
        crowd = [r for r in C.CANDIDATE_POOL if r[2] in ("crs", "crn", "cvn", "cfl")]
        self.assertTrue(crowd)


if __name__ == "__main__":
    unittest.main()
