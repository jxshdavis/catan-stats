"""Tests for scripts/insights.py on synthetic games (never data/).

    python -m unittest discover -s tests
"""

import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import insights  # noqa: E402


def opening_games(b, n_games, seed, seats=4):
    """Games where the winner is drawn from exp(b x) on random opening dots; x is centered dots."""
    rng = random.Random(seed)
    games, replays = [], {}
    players = ["ana", "ben", "cat", "dan", "eve"]
    for k in range(n_games):
        pids = rng.sample(players, seats)
        dots = {p: rng.randint(14, 30) for p in pids}
        m = sum(dots.values()) / seats
        w = [math.exp(b * (dots[p] - m)) for p in pids]
        u, acc, winner = rng.random() * sum(w), 0.0, pids[-1]
        for p, wt in zip(pids, w):
            acc += wt
            if u <= acc:
                winner = p
                break
        gid = f"g{k:03d}"
        games.append({"id": gid, "date": "2026-01-01", "winner": winner,
                      "players": [{"player": p, "seat": i + 1, "vp": 10 if p == winner else 6} for i, p in enumerate(pids)]})
        replays[gid] = {"players": {p: {"opening_dots": dots[p]} for p in pids}}
    return games, replays


class OpeningTest(unittest.TestCase):
    def test_planted_effect_is_recovered(self):
        games, reps = opening_games(0.25, 400, seed=3)
        e = insights.opening_effect(insights.opening_data(games, reps))
        self.assertGreater(e["ci"][0], 0)
        self.assertLess(abs(e["b"] - 0.25), 3 * e["se"])
        self.assertAlmostEqual(e["curve"][4]["p"], 0.25, places=3)  # d = 0 is an even table

    def test_planted_null(self):
        games, reps = opening_games(0.0, 300, seed=4)
        e = insights.opening_effect(insights.opening_data(games, reps))
        self.assertLess(e["ci"][0], 0)
        self.assertGreater(e["ci"][1], 0)

    def test_best_opener_counts_ties(self):
        games = [{"id": "g", "winner": "a", "players": [{"player": p, "seat": i + 1, "vp": 5} for i, p in enumerate("abc")]}]
        reps = {"g": {"players": {"a": {"opening_dots": 20}, "b": {"opening_dots": 20}, "c": {"opening_dots": 10}}}}
        out = insights.best_opener(insights.opening_data(games, reps), draws=200)
        self.assertEqual(out["buckets"][0]["observed"], 0.5)  # a shares the max with b
        self.assertAlmostEqual(out["buckets"][0]["expected"], 1 / 3, places=3)


def marker_games(n_games, seed):
    """ana sits 1 SD above the table on 'steals', ben sits at the table; within-game noise SD is 1."""
    rng = random.Random(seed)
    per_game = []
    for _ in range(n_games):
        g = {"ana": 5 + 1.0 + rng.gauss(0, 1), "ben": 5 + rng.gauss(0, 1),
             "guest-1": 5 + rng.gauss(0, 1), "bot-1": 5 + rng.gauss(0, 1)}
        per_game.append(g)
    return per_game


class MarkerTest(unittest.TestCase):
    def test_planted_one_sd_is_colored_and_table_is_gray(self):
        res = insights.statlib.within_game_sd_marker(marker_games(80, seed=5), min_games=10)
        self.assertTrue(res["ana"]["clear"])
        self.assertGreater(res["ana"]["delta"], 0.7)
        self.assertLess(res["ana"]["delta"], 1.4)
        self.assertFalse(res["ben"]["clear"])

    def test_markers_need_ten_games(self):
        games = [{"id": f"g{k}", "winner": "ana", "players": [
            {"player": "ana", "vp": 10, "vp_breakdown": {"settlements": 10}},
            {"player": "ben", "vp": 4, "vp_breakdown": {"settlements": 4}},
            {"player": "cat", "vp": 4, "vp_breakdown": {"settlements": 4}}]} for k in range(9)]
        out = insights.table_markers(games, {}, ["ana", "ben"], 10, build.finishing_ranks)
        self.assertEqual(out["ana"], {})
        out = insights.table_markers(games + [dict(games[0], id="g9")], {}, ["ana"], 10, build.finishing_ranks)
        self.assertTrue(out["ana"]["wins"]["clear"])  # 10 wins of 10 against 3.3 expected
        self.assertEqual(out["ana"]["vp"]["good"], 1)


def race_game(rows, winner="ana", target=10):
    """A game whose timeline has one snapshot per roll: rows[t] = {pid: vp} after roll t's turn."""
    pids = list(rows[0])
    game = {"id": "g", "winner": winner, "settings": {"vp_to_win": target},
            "players": [{"player": p, "vp": rows[-1][p]} for p in pids]}
    timeline = {"turn": list(range(len(rows))), "vp": {p: [r[p] for r in rows] for p in pids}}
    return game, timeline


class ClosenessTest(unittest.TestCase):
    def test_planted_runner_up_and_lead_changes(self):
        # ben leads, then ana, then ben, then ana (3 changes), with a tie in between that is not a change.
        # At s- ben has 9 of 10, so he needed 1 VP. ana's final turn jumps from 8 to 10: a come-from-behind
        # finish that adds no lead change, because the final turn is after s-.
        rows = [
            {"ana": 2, "ben": 2, "cat": 2},
            {"ana": 2, "ben": 3, "cat": 2},   # ben leads
            {"ana": 4, "ben": 3, "cat": 2},   # ana: change 1
            {"ana": 4, "ben": 4, "cat": 2},   # tie: no change
            {"ana": 4, "ben": 5, "cat": 3},   # ben: change 2
            {"ana": 6, "ben": 5, "cat": 3},   # ana: change 3
            {"ana": 6, "ben": 7, "cat": 3},   # ben: change 4
            {"ana": 8, "ben": 9, "cat": 3},   # s-: ben still leads
            {"ana": 10, "ben": 9, "cat": 3},  # ana's final turn
        ]
        game, tl = race_game(rows)
        parts = insights.closeness_parts(game, tl)
        self.assertEqual(parts["A"], 1)
        self.assertEqual(parts["lead_changes"], 4)
        self.assertEqual(parts["s_minus"], 7)
        # C: snapshots from the first with someone at >= 5 VP (t = 4) to s- (t = 7): gaps 1, 1, 1, 1 over 8.
        self.assertAlmostEqual(parts["C"], 1 / 8)

    def test_three_changes_and_final_turn_adds_none(self):
        rows = [
            {"ana": 2, "ben": 2},
            {"ana": 3, "ben": 2},   # ana leads
            {"ana": 3, "ben": 4},   # ben: change 1
            {"ana": 5, "ben": 4},   # ana: change 2
            {"ana": 5, "ben": 9},   # ben: change 3; s-
            {"ana": 10, "ben": 9},  # ana wins from behind on the final turn
        ]
        game, tl = race_game(rows)
        parts = insights.closeness_parts(game, tl)
        self.assertEqual(parts["lead_changes"], 3)
        self.assertEqual(parts["A"], 1)

    def test_tier_and_index(self):
        games, reps = [], {}
        for k in range(8):  # ben trails by k throughout, so g0 is the closest and g7 the most one-sided
            g, tl = race_game([{"ana": 2, "ben": 2}, {"ana": 7, "ben": 7 - k}, {"ana": 9, "ben": 9 - k},
                               {"ana": 10, "ben": 9 - k}])
            g = dict(g, id=f"g{k}")
            games.append(g)
            reps[g["id"]] = {"timeline": tl}
        out = insights.closeness(games, reps, lambda g: 2)
        tier = [gid for gid, r in out["games"].items() if r["closest_tier"]]
        self.assertIn("g0", tier)
        self.assertTrue(out["games"]["g7"]["one_sided_tier"])
        self.assertGreater(out["games"]["g0"]["index"], out["games"]["g7"]["index"])


class DiceTest(unittest.TestCase):
    def test_fair_counts_have_no_drift(self):
        counts = {str(s): (6 - abs(s - 7)) * 10 for s in range(2, 13)}
        out = insights.dice_calibration([{"dice": {"counts": counts}}])
        self.assertEqual(out["chi2"], 0)
        self.assertEqual(out["drift"], 0)
        self.assertEqual(out["sevens"], 60)


def dice_games(n_games):
    """ana wins every game where ana's dice pay at or above par and none below; ben's dice are always exactly par
    and ben wins the rest. guest-1 and bot-1 always run cold and never win."""
    games, replays = [], {}
    for k in range(n_games):
        cold = k % 2 == 1
        winner = "ben" if cold else "ana"
        gid = f"g{k:03d}"
        seats = ["ana", "ben", "guest-1", "bot-1"]
        games.append({"id": gid, "date": "2026-01-01", "winner": winner,
                      "players": [{"player": p, "seat": i + 1, "vp": 10 if p == winner else 6} for i, p in enumerate(seats)]})
        replays[gid] = {"players": {
            "ana": {"resources_from_dice": 40 if cold else 50, "expected_from_dice": 45.0},
            "ben": {"resources_from_dice": 45, "expected_from_dice": 45.0},
            "guest-1": {"resources_from_dice": 30, "expected_from_dice": 45.0},
            "bot-1": {"resources_from_dice": 30, "expected_from_dice": 45.0}}}
    return games, replays


class ColdDiceTest(unittest.TestCase):
    def test_counts_and_typical(self):
        games, reps = dice_games(20)
        a = insights.cold_dice(games, reps, ["ana", "ben", "cal"], build.is_anon, 10)["players"]["ana"]
        self.assertEqual((a["cold"]["games"], a["cold"]["wins"]), (10, 0))
        self.assertEqual((a["par"]["games"], a["par"]["wins"]), (10, 10))
        # Everyone else on cold dice (guest and bot, 40 seats) never won, so a cold game is typically won 0 times;
        # everyone else at or above par (ben, 20 seats at 4 players) won 10 of 20.
        self.assertEqual(a["cold"]["typical"], 0)
        self.assertEqual(a["par"]["typical"], 5)
        self.assertEqual((a["cold"]["lo"], a["cold"]["hi"]), (0, 0))
        self.assertLess(a["par"]["hi"], 10)  # ten par wins is beyond what luck covers around 5
        self.assertEqual([g["cold"] for g in a["games"][:3]], [False, True, False])
        self.assertAlmostEqual(a["games"][1]["pct"], round(-5 / 45, 4))

    def test_exactly_par_is_not_cold_and_guards(self):
        games, reps = dice_games(20)
        out = insights.cold_dice(games, reps, ["ana", "ben", "cal"], build.is_anon, 10)["players"]
        b = out["ben"]
        self.assertEqual(b["cold"]["games"], 0)  # dice exactly at expectation count as par
        self.assertIsNone(b["cold"]["rate"])
        self.assertEqual((b["cold"]["typical"], b["cold"]["lo"], b["cold"]["hi"]), (0, 0, 0))
        self.assertNotIn("cal", out)  # never played
        self.assertEqual(insights.cold_dice(games[:9], reps, ["ana"], build.is_anon, 10)["players"], {})

    def test_guests_and_bots_are_never_listed(self):
        games, reps = dice_games(20)
        out = insights.cold_dice(games, reps, ["ana", "ben", "guest-1", "bot-1"], build.is_anon, 10)["players"]
        self.assertEqual(sorted(out), ["ana", "ben"])

    def test_win_band(self):
        self.assertEqual(insights.win_band([]), (0, 0))
        self.assertEqual(insights.win_band([1.0] * 4), (4, 4))
        lo, hi = insights.win_band([0.5] * 20)  # Binomial(20, 0.5): central 95% is 6 to 14
        self.assertEqual((lo, hi), (6, 14))


if __name__ == "__main__":
    unittest.main()
