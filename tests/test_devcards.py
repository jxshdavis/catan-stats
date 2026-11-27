"""Tests for scripts/devcards.py on synthetic games (never data/).

    python -m unittest discover -s tests
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import devcards  # noqa: E402


def game(gid, winner="a"):
    """A 3-seat game: a buys a knight and a VP card, b buys a monopoly and plays it and the knight goes unplayed
    until a plays it before rolling. a ends with Largest Army."""
    g = {"id": gid, "date": "2026-01-0" + gid[-1], "winner": winner, "players": [{"player": p} for p in "abc"]}
    ev = {
        "seats": ["a", "b", "c"],
        "dev_deck": {"knight": 14, "victory_point": 5, "road_building": 2, "year_of_plenty": 2, "monopoly": 2},
        "states": [{"roll_index": 0, "spent": {"dev": [0, 0, 0], "road": [0, 0, 0]}},
                   {"roll_index": 30, "spent": {"dev": [6, 3, 0], "road": [6, 3, 4]}, "vp_cards_held": [1, 0, 0]}],
        "dev_events": [
            {"seat": 1, "action": "buy", "card": "knight", "roll_index": 3, "own_turn": 2},
            {"seat": 2, "action": "buy", "card": "monopoly", "roll_index": 12, "own_turn": 4},
            {"seat": 2, "action": "play", "card": "monopoly", "roll_index": 15, "own_turn": 5, "pre_roll": False},
            {"seat": 1, "action": "play", "card": "knight", "roll_index": 18, "own_turn": 6, "pre_roll": True},
            {"seat": 1, "action": "buy", "card": "victory_point", "roll_index": 30, "own_turn": 10},
        ],
        "vp_events": [{"roll_index": 24, "changes": [{"type": "largest_army_taken", "seat": 1}]}],
        "monopoly_events": [{"seat": 2, "resource": "ore", "taken": [2, 0, 3], "roll_index": 15}],
    }
    rp = {"players": {"a": {"resources_from_dice": 30}, "b": {"resources_from_dice": 20}, "c": {"resources_from_dice": 10}}}
    return g, ev, rp


class CollectTests(unittest.TestCase):
    def setUp(self):
        g, ev, rp = game("g1")
        self.buys, self.plays, self.pgs, self.gms, self.monos = devcards.collect([g], {"g1": rp}, {"g1": ev})

    def test_buys_and_winning_turn(self):
        self.assertEqual([b["card"] for b in self.buys], ["knight", "monopoly", "victory_point"])
        self.assertEqual([b["wt"] for b in self.buys], [False, False, True])  # a won on the last roll

    def test_hold_and_pre_roll(self):
        hold = {p["card"]: p["hold"] for p in self.plays}
        self.assertEqual(hold, {"monopoly": 1, "knight": 4})
        self.assertTrue(next(p for p in self.plays if p["card"] == "knight")["pre"])

    def test_seat_rows(self):
        a, b, c = self.pgs
        self.assertEqual((a["buys"], a["vp"], a["kn_played"], a["la"], a["first"]), (2, 1, 1, True, 2))
        self.assertAlmostEqual(a["dev_share"], 0.5)
        self.assertAlmostEqual(a["prod"], 1.5)  # 30 of 60 cards at a 3-seat table
        self.assertEqual(b["mono_take"], 5)
        self.assertIsNone(c["first"])
        self.assertEqual(self.gms[0]["winner_vp_cards"], 1)
        self.assertEqual(self.gms[0]["la_final"], "a")

    def test_unplayed_counts_action_cards_only(self):
        self.assertEqual([r["unplayed"] for r in self.pgs], [0, 0, 0])


class SmallDataTests(unittest.TestCase):
    def test_too_few_games_returns_count_only(self):
        g, ev, rp = game("g1")
        out = devcards.compute_all([g], {"g1": rp}, {"g1": ev}, {"pids": ["a", "b", "c"], "fast": True})
        self.assertEqual(out, {"games": 1})

    def test_wae(self):
        rows = [{"win": True, "n": 4}, {"win": False, "n": 4}]
        self.assertAlmostEqual(devcards.wae(rows), 0.25)


if __name__ == "__main__":
    unittest.main()
