"""Tests for scripts/momentum.py on synthetic per-action logs (never data/)."""

import random
import statistics
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import momentum  # noqa: E402

DOTS = {s: 6 - abs(s - 7) for s in range(2, 13)}
DOTS[7] = 0


def roll2d6(rng):
    return rng.randint(1, 6) + rng.randint(1, 6)


def fair_game(gid, rng, n=4, rounds=12):
    """A game with fixed random pips per seat, fair dice and a uniformly random winner (so D = 0)."""
    pips = [[rng.choice([0, 0, 1, 1, 2]) if s != 7 else 0 for s in range(2, 13)] for _ in range(n)]
    seats = [f"p{i}" for i in range(n)]
    T = rounds * n
    states, roll_log = [], []
    for t in range(T):
        tot = roll2d6(rng)
        row = {"action_index": t, "roll_index": t, "kind": "roll", "actor": t % n + 1}
        if t == 0:
            row.update({"vp": [2] * n, "vp_cards_held": [0] * n, "pips_gross": pips, "pips_blocked": [[0] * 11] * n})
        states.append(row)
        roll_log.append({"roll_index": t, "action_index": t, "roller": t % n + 1, "total": tot,
                         "a_raw": [pips[i][tot - 2] for i in range(n)], "short": [0] * n})
    winner = rng.choice(seats)
    ev = {"seats": seats, "states": states, "roll_log": roll_log, "vp_events": [], "dev_events": []}
    game = {"id": gid, "winner": winner, "settings": {"vp_to_win": 10},
            "players": [{"player": p, "vp": 10 if p == winner else 6} for p in seats]}
    return game, ev


class LuckTest(unittest.TestCase):
    def test_z_has_unit_sd_on_fair_dice(self):
        rng = random.Random(7)
        zs = []
        for k in range(200):
            g, ev = fair_game(f"g{k}", rng)
            for r in momentum.luck_rows([g], {g["id"]: ev}):
                zs += [L / v ** 0.5 for L, v in zip(r["L"], r["Vtot"]) if v > 0]
        self.assertLess(abs(statistics.pstdev(zs) - 1), 0.05)
        self.assertLess(abs(statistics.mean(zs)), 0.08)

    def test_snowball_recovers_zero_with_nominal_coverage(self):
        rng = random.Random(8)
        cover, reps = 0, 30
        for rep in range(reps):
            games = [fair_game(f"r{rep}g{k}", rng) for k in range(80)]
            rows = momentum.luck_rows([g for g, _ in games], {g["id"]: ev for g, ev in games})
            s = momentum.snowball(rows)
            cover += s["D_ci"][0] <= 0 <= s["D_ci"][1]
        self.assertGreaterEqual(cover / reps, 0.83)


def vp_row(k, actor, own_turn, bvp, changes=None, action="settlement", phase="turn"):
    return {"action_index": k, "roll_index": k, "own_turn": own_turn, "phase": phase, "actor": actor,
            "action": action, "changes": changes or [], "board_vp": bvp}


class PlayOfTheGameTest(unittest.TestCase):
    seats = ["ana", "ben", "cat"]

    def ev(self, rows):
        return {"seats": self.seats, "vp_events": rows}

    def test_longest_road_steal_is_the_play(self):
        rows = [
            vp_row(0, 1, 0, [2, 2, 2], phase="setup"),
            vp_row(10, 2, 3, [2, 5, 2]),                                   # ben goes up 3
            vp_row(20, 1, 4, [3, 5, 2]),                                   # ana settlement: M -3 -> -2
            vp_row(21, 1, 4, [5, 3, 2], [{"type": "longest_road_taken", "seat": 1, "from": 2}], "road"),  # Longest Road from ben
            vp_row(30, 2, 5, [5, 4, 2]),
            vp_row(40, 1, 6, [7, 4, 2], action="city"),                    # ana's turn 6: M +1 to +3, a smaller swing
            vp_row(50, 1, 9, [10, 4, 2], action="city"),                   # final turn
        ]
        play = momentum.play_of_the_game(self.ev(rows), 1)
        self.assertEqual(play["pick"]["swing"], 5)  # M from -3 before turn 4 to +2 after
        self.assertTrue(play["pick"]["crossed"])
        self.assertEqual(play["pick"]["best_action"]["what"][0], {"type": "longest_road_taken", "from": "ben"})

    def test_swing_given_back_is_not_picked(self):
        rows = [
            vp_row(10, 1, 3, [6, 2, 2], action="city"),        # +4 swing ...
            vp_row(20, 2, 3, [6, 7, 2]),                       # ... given back: M falls to -1
            vp_row(30, 1, 4, [8, 7, 2], action="city"),        # +2 swing, durable
            vp_row(40, 1, 6, [10, 7, 2], action="city"),       # final turn
        ]
        play = momentum.play_of_the_game(self.ev(rows), 1)
        self.assertEqual(play["pick"]["swing"], 2)
        self.assertEqual(play["given_back"]["swing"], 4)

    def test_walk_off_and_reveal(self):
        rows = [vp_row(10, 2, 3, [2, 4, 2]), vp_row(20, 1, 5, [5, 4, 2], action="city")]  # ahead only on the final turn
        self.assertEqual(momentum.go_ahead(self.ev(rows), 1)["kind"], "walk_off")
        rows = [vp_row(10, 2, 3, [2, 4, 2]), vp_row(20, 1, 5, [4, 4, 2], action="city"),
                {"action_index": 21, "roll_index": 20, "own_turn": 0, "phase": "end", "actor": None, "action": "reveal",
                 "changes": [], "board_vp": [10, 4, 2]}]
        self.assertEqual(momentum.go_ahead(self.ev(rows), 1)["kind"], "reveal")
        rows = [vp_row(10, 1, 3, [4, 2, 2]), vp_row(20, 1, 5, [10, 2, 2])]
        self.assertEqual(momentum.go_ahead(self.ev(rows), 1)["kind"], "led")

    def test_three_way_tie_is_co_plays(self):
        rows = [vp_row(0, 1, 0, [3, 2, 2], phase="setup"), vp_row(1, 1, 1, [5, 2, 2]), vp_row(2, 2, 1, [5, 3, 2]),
                vp_row(3, 1, 2, [7, 3, 2]), vp_row(4, 2, 2, [7, 4, 2]), vp_row(5, 1, 3, [9, 4, 2]),
                vp_row(6, 1, 4, [10, 4, 2])]
        play = momentum.play_of_the_game(self.ev(rows), 1)
        # Turns 1, 2 and 3 each move M by +2 while ana already leads, and none is given back.
        self.assertEqual(play["pick"]["own_turn"], 1)
        self.assertEqual(len(play["co_plays"]), 2)

    def test_small_swings_have_no_standout(self):
        rows = [vp_row(1, 1, 1, [3, 2, 2]), vp_row(2, 1, 2, [4, 2, 2]), vp_row(3, 1, 3, [10, 2, 2])]
        self.assertIsNone(momentum.play_of_the_game(self.ev(rows), 1)["pick"])


if __name__ == "__main__":
    unittest.main()
