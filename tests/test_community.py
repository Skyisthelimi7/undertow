"""Rug calls: pricing, settling and points (undertow/community.py), with Supabase replaced by a stub."""
import unittest, sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from undertow import community as CM, config as C

H = 3600


def fresh(side="rug"):
    return {"id": 1, "mint": "M", "side": side, "created_at": CM.iso(0), "price_at_call": None, "priced_at": None,
            "seen_at": None, "hi": None, "lo": None, "up50_at": None, "dn80_at": None}


def play(side, scans, r=0.1):
    """Run one call through a series of scans: [(seconds after the call, price or None)]."""
    c = fresh(side)
    for t, p in scans:
        c.update(CM.step_call(c, p, t, r))
    return c


class Calls(unittest.TestCase):
    def test_priced_at_the_first_scan_after_the_call(self):
        c = fresh()
        self.assertEqual(CM.step_call(c, None, 600, .1), {})                     # no price yet: wait
        ch = CM.step_call(c, 2.0, 1200, .1)
        self.assertEqual((ch["price_at_call"], ch["hi"], ch["lo"]), (2.0, 1.0, 1.0))
        self.assertEqual(ch["priced_at"], CM.iso(1200))

    def test_a_call_never_priced_within_a_day_is_void(self):
        ch = CM.step_call(fresh(), None, 24 * H + 60, .1)
        self.assertEqual((ch["outcome"], ch["points"]), ("void", 0))

    def test_rug_scores_for_rug_calls_and_against_hold_calls(self):
        path = [(1200, 1.0), (3 * H, 0.15), (20 * H, 0.1), (24 * H + 1200, 0.1)]
        c = play("rug", path)
        self.assertEqual(c["outcome"], "rug")
        self.assertAlmostEqual(c["points"], 9.0)                                  # (1 - 0.1) / 0.1
        self.assertAlmostEqual(c["lo"], 0.1)
        self.assertAlmostEqual(play("hold", path)["points"], -9.0)

    def test_up_50_first_means_it_held_even_if_it_crashed_later(self):
        path = [(1200, 1.0), (2 * H, 1.6), (5 * H, 0.1), (20 * H, 0.1), (24 * H + 1200, 0.1)]
        c = play("rug", path)
        self.assertEqual((c["outcome"], c["points"]), ("held", -1.0))
        self.assertAlmostEqual(c["hi"], 1.6)
        self.assertEqual(play("hold", path)["points"], 1.0)

    def test_losing_sight_voids_a_call_but_a_rug_already_seen_still_counts(self):
        c = play("hold", [(1200, 1.0), (10 * H, 1.1), (24 * H + 1200, None)])
        self.assertEqual((c["outcome"], c["points"]), ("void", 0))
        c = play("rug", [(1200, 1.0), (3 * H, 0.1), (24 * H + 1200, None)])     # rugged, then delisted
        self.assertEqual(c["outcome"], "rug")

    def test_prices_after_the_day_do_not_count(self):
        c = play("rug", [(1200, 1.0), (20 * H, 0.9), (26 * H, 0.05)])         # the crash came after its day
        self.assertEqual(c["outcome"], "held")
        self.assertIsNone(c["dn80_at"])

    def test_guessing_at_the_base_rate_scores_nothing(self):
        for r in (0.05, 0.1, 0.3):
            k = (1 - CM.base_rate(r)) / CM.base_rate(r)
            self.assertAlmostEqual(r * k - (1 - r) * 1, 0)                        # always calling rug
            self.assertAlmostEqual((1 - r) * 1 - r * k, 0)                        # always calling hold

    def test_base_rate_is_clamped_and_has_a_default(self):
        self.assertEqual(CM.base_rate(None), C.CALL_BASE_RATE)
        self.assertEqual(CM.base_rate(0.001), 0.03)
        self.assertEqual(CM.base_rate(0.9), 0.5)

    def test_state_matches_the_page(self):
        self.assertEqual(CM.state_of({"state_new": "IN", "fs": 0, "ps": 0}), "IN")
        self.assertEqual(CM.state_of({"state_new": "IN", "fs": 2, "ps": 0}), "WATCH")
        self.assertEqual(CM.state_of({"state_new": "OUT", "fs": 0, "ps": 1}), "ENTERING")
        self.assertEqual(CM.state_of({"state_new": "OUT", "fs": 0, "ps": 0}), "OUT")


class Plumbing(unittest.TestCase):
    def setUp(self):
        self.real = CM._req
        self.sent = []

    def tearDown(self):
        CM._req = self.real

    def test_new_secret_keys_go_in_the_apikey_header_only(self):
        self.assertNotIn("Authorization", CM._headers("sb_secret_abc"))
        self.assertEqual(CM._headers("sb_secret_abc")["apikey"], "sb_secret_abc")
        self.assertEqual(CM._headers("eyJhbGciOi.legacy")["Authorization"], "Bearer eyJhbGciOi.legacy")

    def test_sync_lists_tokens_in_batches_and_settles(self):
        def fake(method, path, body=None, extra=None):
            self.sent.append((method, path.split("?")[0], body))
            if method == "GET":
                return [{**fresh("rug"), "id": 7, "mint": "A"}]
            return None
        CM._req = fake
        rows = [{"t": {"mint": f"T{i}", "symbol": "S"}, "d": {"price": 1.0, "symbol": "S"}, "state_new": "IN", "fs": 0, "ps": 0}
                for i in range(1200)]
        out = CM.sync(rows, {"A": {"price": 2.0}}, 1200, 0.2)
        self.assertIn("1200 tokens listed, 1 new calls priced, 0 settled", out)
        posts = [s for s in self.sent if s[0] == "POST"]
        self.assertEqual([len(s[2]) for s in posts], [500, 500, 200])
        patch = [s for s in self.sent if s[0] == "PATCH"][0]
        self.assertEqual(patch[2]["price_at_call"], 2.0)

    def test_reads_page_through_more_than_a_thousand_rows(self):
        def fake(method, path, body=None, extra=None):
            off = int(path.split("offset=")[1])
            n = max(0, 2500 - off)
            self.sent.append(path)
            return [{"mint": f"T{off + i}", "rug_calls": 0, "hold_calls": 0, "watch": 1, "avoid": 0, "tags": {}}
                    for i in range(min(1000, n))]
        CM._req = fake
        self.assertEqual(len(CM.crowd()), 2500)
        self.assertEqual(len(self.sent), 3)

    def test_sync_never_stops_the_scan(self):
        def boom(*a, **k):
            raise RuntimeError("Supabase GET /rest/v1/calls answered 401: bad key")
        CM._req = boom
        self.assertTrue(CM.sync([], {}, 0, None).startswith("skipped: "))
        self.assertEqual(CM.crowd(), {})

    def test_crowd_counts_for_the_lab(self):
        CM._req = lambda *a, **k: [{"mint": "A", "rug_calls": 3, "hold_calls": 1, "watch": 2, "avoid": 5,
                                    "tags": {"bundled": 2, "rug_suspected": 1, "cto": 4}},
                                   {"mint": "B", "rug_calls": 1, "hold_calls": 0, "watch": 0, "avoid": 0, "tags": {}}]
        got = CM.crowd()
        self.assertEqual(got["A"], {"calls": 4, "rug_share": 0.75, "net_votes": -3, "bad_tags": 3})
        self.assertIsNone(got["B"]["rug_share"])                                 # fewer than 3 calls: no share


if __name__ == "__main__":
    unittest.main()
