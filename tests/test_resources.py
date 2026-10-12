"""Tests for scripts/resources.py on synthetic games (never data/).

    python -m unittest discover -s tests
"""

import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import resources  # noqa: E402


def is_anon(pid):
    return pid.startswith("guest-") or pid.startswith("bot-")


def ctx_for(pids):
    return {"pids": pids, "is_anon": is_anon, "fast": True}


def pick(seat, n, res):
    return {"seat": seat, "pick": n, "pips": sum(res), "res": list(res) + [0]}


def make_game(gid, seats, winner, opening, production=None):
    """opening: per seat two 5-lists (dots per resource under each starting settlement)."""
    picks = [pick(j + 1, k + 1, opening[j][k]) for k in range(2) for j in range(len(seats))]
    game = {"id": gid, "winner": winner, "players": [{"player": p} for p in seats]}
    ev = {"seats": seats, "opening_picks": picks}
    rep = None
    if production:
        rep = {"players": {p: {"production": dict(zip(resources.RESOURCES, production[j]))} for j, p in enumerate(seats)}}
    return game, ev, rep


def synthetic(n_games, weights, seed=0, seats=("a", "b", "c", "d")):
    """Openings drawn at random; the winner drawn from exp(sum_r w_r x_r) with x centered on the table."""
    rng = random.Random(seed)
    games, events = [], {}
    for g in range(n_games):
        opening = [[[rng.choice([0, 0, 1, 2, 3, 4, 5]) for _ in range(5)] for _ in range(2)] for _ in seats]
        tot = [[a + b for a, b in zip(*o)] for o in opening]
        m = [sum(t[k] for t in tot) / len(seats) for k in range(5)]
        u = [math.exp(sum(w * (t[k] - m[k]) for k, w in enumerate(weights))) for t in tot]
        r, acc, win = rng.random() * sum(u), 0.0, 0
        for i, x in enumerate(u):
            acc += x
            if r <= acc:
                win = i
                break
        gm, ev, _ = make_game(f"g{g}", list(seats), seats[win], opening)
        games.append(gm)
        events[gm["id"]] = ev
    return games, events


class OpeningRows(unittest.TestCase):
    def test_sums_both_settlements_and_skips_old_logs(self):
        g, ev, _ = make_game("x", ["a", "b", "c"], "b",
                             [[[1, 0, 0, 0, 0], [0, 2, 0, 0, 0]], [[0, 0, 3, 0, 0], [0, 0, 0, 4, 0]], [[0, 0, 0, 0, 5], [1, 1, 1, 1, 1]]])
        rows = resources.opening_rows([g], {"x": ev})
        self.assertEqual(rows[0]["res"], [[1, 2, 0, 0, 0], [0, 0, 3, 4, 0], [1, 1, 1, 1, 6]])
        self.assertEqual(rows[0]["win"], 1)
        for p in ev["opening_picks"]:
            del p["res"]
        self.assertEqual(resources.opening_rows([g], {"x": ev}), [])


class WinModel(unittest.TestCase):
    def test_recovers_a_resource_that_matters(self):
        games, events = synthetic(400, [0.0, 0.0, 0.0, 0.6, 0.0], seed=3)
        m = resources.win_model(resources.opening_rows(games, events))
        self.assertEqual(max(m["per"], key=lambda r: m["per"][r]["or"]), "wheat")
        self.assertGreater(m["per"]["wheat"]["or_ci"][0], 1)
        self.assertLess(m["lr"]["p"], 0.01)

    def test_equal_weights_do_not_flag_the_mix(self):
        games, events = synthetic(300, [0.2] * 5, seed=5)
        m = resources.win_model(resources.opening_rows(games, events))
        self.assertGreater(m["lr"]["p"], 0.01)
        self.assertGreater(m["total"]["or_ci"][0], 1)


class GroupTest(unittest.TestCase):
    def test_counts_and_chance_expectation(self):
        none = [[0, 0, 0, 0, 0], [0, 0, 0, 0, 0]]
        has = [[1, 1, 1, 1, 1], [0, 0, 0, 0, 0]]
        g1, e1, _ = make_game("1", ["a", "b", "c"], "a", [none, has, has])  # one seat without ore, it wins
        g2, e2, _ = make_game("2", ["a", "b", "c", "d"], "b", [none, none, has, has])  # two without, one wins
        data = resources.opening_rows([g1, g2], {"1": e1, "2": e2})
        t = resources.group_test(data, 0.0, lambda d, i: d["res"][i][4] == 0)
        self.assertEqual((t["seats"], t["wins"]), (3, 2))
        self.assertAlmostEqual(t["expected"], 1 / 3 + 2 / 4, places=3)
        self.assertAlmostEqual(t["expected_dots"], t["expected"], places=3)  # b = 0: dots carry no weight

    def test_poisson_binomial(self):
        dist = resources.poisson_binomial([0.5, 0.5])
        self.assertEqual([round(x, 6) for x in dist], [0.25, 0.5, 0.25])
        lo, hi, p = resources.pb_summary([0.5] * 20, 10)
        self.assertLessEqual(lo, 10)
        self.assertGreaterEqual(hi, 10)
        self.assertAlmostEqual(p, 1.0)


class Mix(unittest.TestCase):
    def test_shares_against_the_rest_of_the_table(self):
        units = resources.mix_units([{"a": [2, 0, 0, 0, 2], "b": [1, 1, 1, 1, 0]}, {"a": [4, 0, 0, 0, 0], "c": [0, 0, 0, 4, 0]}])
        s, t, d = resources.share_diff(units, "a")
        self.assertEqual([round(x, 3) for x in s], [0.75, 0, 0, 0, 0.25])
        self.assertEqual([round(x, 3) for x in t], [0.125, 0.125, 0.125, 0.625, 0])
        self.assertAlmostEqual(sum(d), 0)

    def test_favorite_and_view_fallback(self):
        games, events = synthetic(12, [0.0] * 5, seed=1)
        for g in games:  # player a always opens heavy on ore
            ev = events[g["id"]]
            for p in ev["opening_picks"]:
                if p["seat"] == 1:
                    p["res"] = [0, 0, 0, 0, 6, 0]
        ctx = ctx_for(["a", "b", "c", "d"])
        out = resources.compute_view(games, {}, events, ctx, {"winning": "ALL"})
        self.assertEqual(out["winning_source"], "all games")
        self.assertEqual(out["winning"], "ALL")
        fav = out["players"]["a"]["favorite"]
        self.assertEqual(fav["resource"], "ore")
        self.assertTrue(fav["clear"])
        self.assertIsNone(out["players"]["a"]["dice"])


if __name__ == "__main__":
    unittest.main()
