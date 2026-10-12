"""Tests for scripts/threat.py on synthetic games (never data/).

    python -m unittest discover -s tests
"""

import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import threat  # noqa: E402

K = len(threat.FEATS)


def is_anon(pid):
    return pid.startswith("guest-") or pid.startswith("bot-")


def draw(rng, weights):
    u, acc = rng.random() * sum(weights), 0.0
    for i, w in enumerate(weights):
        acc += w
        if u <= acc:
            return i
    return len(weights) - 1


def model_data(n_games, beta, seed=0, n=4, states=1):
    """Games as threat.fit_model sees them: turn ends with feature rows, the winner drawn from the
    conditional logit with coefficients beta on the raw features."""
    rng = random.Random(seed)
    out = []
    for g in range(n_games):
        ends = []
        for _ in range(states):
            ends.append({"X": [[rng.gauss(0, 1) for _ in range(K)] for _ in range(n)]})
        last = ends[-1]["X"]
        win = draw(rng, [math.exp(sum(b * x for b, x in zip(beta, row))) for row in last])
        out.append({"game": f"g{g:03d}", "n": n, "win": win, "ends": ends})
    return out


def state(ai, ri, kind, actor, n, **f):
    row = {"action_index": ai, "roll_index": ri, "kind": kind, "actor": actor}
    row.update(f)
    return row


def base_fields(n):
    return {"vp": [2] * n, "vp_cards_held": [0] * n, "hand": [0] * n,
            "pips_gross": [[0] * 11 for _ in range(n)], "pips_blocked": [[0] * 11 for _ in range(n)],
            "road_length": [1] * n, "longest_road": None, "largest_army": None, "reach": [0] * n}


class Features(unittest.TestCase):
    def test_closeness(self):
        # No holder: need 5 segments (cap 4), so 1 short scores 3 and 5 or more short scores 0.
        self.assertEqual(threat.closeness([4, 1, 0], None, 5, 4), [3, 0, 0])
        # Holder seat 1 at 6: the others need 7; the holder gets the cap.
        self.assertEqual(threat.closeness([6, 5, 3], 1, 5, 4), [4, 2, 0])
        self.assertEqual(threat.closeness([0, 2, 3], 3, 3, 3), [0, 1, 3])

    def test_state_rows_carry_forward_and_dev_counts(self):
        n = 3
        g = [[0] * 11 for _ in range(n)]
        g[0][4] = 2  # seat 1: two cards on a 6 (5 dots): 10/36 per roll
        first = state(10, 0, "roll", 1, n, **{**base_fields(n), "pips_gross": g, "vp": [3, 2, 4],
                                               "vp_cards_held": [0, 0, 1], "hand": [1, 2, 3], "reach": [7, 0, 2]})
        ev = {"seats": ["a", "b", "c"], "states": [first, state(20, 0, "end_turn", 1, n, hand=[0, 2, 3]),
                                                   state(30, 1, "roll", 2, n, largest_army=2)],
              "dev_events": [{"action_index": 12, "seat": 2, "action": "buy", "card": "knight"},
                             {"action_index": 14, "seat": 2, "action": "buy", "card": "knight"},
                             {"action_index": 25, "seat": 2, "action": "play", "card": "knight"}]}
        rows = threat.state_rows(ev)
        self.assertEqual(len(rows), 3)
        x0 = rows[0]["X"]
        self.assertEqual([x[0] for x in x0], [3, 2, 3])  # board VP drops the held VP card
        self.assertAlmostEqual(x0[0][1], 10 / 36)
        self.assertEqual([x[2] for x in x0], [7, 0, 2])
        self.assertEqual([x[3] for x in rows[1]["X"]], [0, 2, 0])  # two bought by action 20
        self.assertEqual([x[4] for x in rows[1]["X"]], [0, 2, 3])  # hand carried from the end_turn row
        x2 = rows[2]["X"]
        self.assertEqual([x[3] for x in x2], [0, 1, 0])  # one played
        # Seat 2 holds Largest Army with 1 knight: the others need 2, so 0 knights is 2 short (3 - 2 = 1).
        self.assertEqual([x[6] for x in x2], [1, 3, 1])


class Model(unittest.TestCase):
    def test_recovers_coefficients(self):
        beta = [0.8, 0.5, 0.0, 0.3, 0.0, -0.4, 0.2]
        data = model_data(1500, beta, seed=1)
        fit = threat.fit_model(data)
        for f, b in enumerate(beta):
            est = fit["beta"][f] / fit["scale"][f]  # back to the raw-feature scale
            self.assertAlmostEqual(est, b, delta=0.15, msg=threat.FEATS[f])
            lo, hi = fit["ci"][f]
            self.assertLess(lo, fit["beta"][f])
            self.assertGreater(hi, fit["beta"][f])

    def test_cluster_intervals_widen_with_repeated_states(self):
        # Repeating one game's state 5 times adds no information: clustered SEs should stay about the same
        # as with one state per game, while naive SEs would shrink by sqrt(5).
        beta = [0.6] + [0.0] * (K - 1)
        one = threat.fit_model(model_data(600, beta, seed=2, states=1))
        rep = model_data(600, beta, seed=2, states=1)
        for d in rep:
            d["ends"] = d["ends"] * 5
        five = threat.fit_model(rep)
        self.assertAlmostEqual(five["se"][0] / one["se"][0], 1.0, delta=0.1)

    def test_cross_fit_never_scores_a_game_with_its_own_fit(self):
        data = model_data(50, [0.5] * K, seed=3)
        fold, models = threat.cross_fit(data)
        self.assertEqual(sorted(set(fold.values())), list(range(threat.FOLDS)))
        for f, m in models.items():
            self.assertEqual(m["games"], sum(1 for d in data if fold[d["game"]] != f))


def game(n, rolls, rollers, tops, trades, win, moves=()):
    """A scored game as the per-player functions see it. tops[t] is the top threat after roll t."""
    rows = []
    for t in range(rolls):
        p = [0.1] * n
        p[tops[t]] = 0.7
        rows.append({"action_index": 10 * t, "roll_index": t, "kind": "roll", "actor": rollers[t] + 1, "p": p,
                     "top": tops[t]})
    return {"game": "g", "n": n, "rolls": rolls, "win": win, "rows": rows, "ends": [], "seats": list("abcd"[:n]),
            "trades": [{"roll": t, "seat": s, "partner": q, "given": gv, "received": rc, "top": tops[t]}
                       for t, s, q, gv, rc in trades], "moves": list(moves)}


class Tyrant(unittest.TestCase):
    def test_ex_ante_own_and_off_turn(self):
        # 3 seats; rolls cycle 0, 1, 2. Seat 2 is the top threat throughout.
        rollers = [t % 3 for t in range(6)]
        tops = [2] * 6
        # Seat 0's own-turn trades: one with the tyrant (seat 2), one with seat 1. Off turn: one trade on seat 2's
        # turn (roll 2) with the roller.
        d = game(3, 6, rollers, tops, [(0, 0, 2, 1, 1), (3, 0, 1, 1, 1), (2, 2, 0, 1, 1)], win=1)
        O, E = threat.tyrant_units(d, 0, hindsight=False)
        self.assertEqual(O, 2)
        # Own turn: 2 trades x 1/(n-1) = 1. Off turn: 1 trade x share of other players' turns that are the
        # tyrant's (2 of 4) = 0.5.
        self.assertAlmostEqual(E, 1.5)

    def test_hindsight_weights_and_winner_excluded(self):
        rollers = [t % 3 for t in range(4)]
        d = game(3, 4, rollers, [0] * 4, [(0, 0, 1, 1, 1), (3, 0, 1, 1, 1)], win=1)
        O, E = threat.tyrant_units(d, 0, hindsight=True)
        self.assertAlmostEqual(O, 1 / 4 + 4 / 4)  # weights (roll + 1) / rolls
        self.assertAlmostEqual(E, (1 / 4 + 4 / 4) / 2)
        self.assertIsNone(threat.tyrant_units(d, 1, hindsight=True))  # the winner can't feed the winner


class Groveler(unittest.TestCase):
    def test_net_against_role_baseline(self):
        tops = [1] * 3
        d = game(3, 3, [0, 1, 2], tops, [(0, 0, 1, 3, 1), (1, 1, 0, 1, 2), (2, 2, 1, 2, 2)], win=1)
        base = threat.grovel_base([d], "a")  # leave seat 0 ("a") out: only seat 2's trade counts, as roller
        self.assertEqual(base, {True: 0.0, False: 0.0})
        # Seat 0 as roller gives 3 for 1 (+2); as partner on seat 1's turn gets 1, gives 2 (+1).
        self.assertEqual(threat.grovel_items(d, 0, base), [2, 1])
        self.assertEqual(threat.grovel_items(d, 1, base), [])  # the threat itself has no items


class Coward(unittest.TestCase):
    def test_hex_and_victim_decisions(self):
        mv1 = {"mover": 0, "tau": 2, "touch": [True, False, False], "chosen": 1, "p_hex": [0.5, 0.3, 0.2],
               "eligible": [1], "victim": 1}
        mv2 = {"mover": 0, "tau": 2, "touch": [True, True], "chosen": 0, "p_hex": [0.5, 0.5],
               "eligible": [1, 2], "victim": 2}
        d = game(3, 1, [0], [2], [], win=1, moves=[mv1, mv2])
        O, E, nh, nv = threat.coward_units(d, 0)
        # mv1: a hex decision (dodged, E 0.5); one eligible victim, so no victim decision.
        # mv2: every hex touches the threat, so no hex decision; victim: robbed the threat (E 1/2).
        self.assertEqual((nh, nv), (1, 1))
        self.assertEqual(O, 1)
        self.assertAlmostEqual(E, 1.0)

    def test_relative_interval(self):
        units = [(2, 1, 4, 4)] * 30  # twice the threat-blind rate, the table at it
        r = threat.relative_interval(units, B=200, seed=0)
        self.assertAlmostEqual(r["ratio"], 2.0)
        self.assertEqual(r["rest"], 1.0)
        self.assertTrue(r["clear"])


if __name__ == "__main__":
    unittest.main()
