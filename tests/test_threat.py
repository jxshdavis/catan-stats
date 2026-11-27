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


def model_data(n_games, beta, seed=0, n=4, states=1, shift=None):
    """Games as threat.fit_model sees them: turn ends with feature rows and a stage, the winner drawn from the
    conditional logit with weights beta + shift (stage - 0.5) on the raw features (shift 0 when None)."""
    rng = random.Random(seed)
    shift = shift or [0.0] * K
    out = []
    for g in range(n_games):
        ends = []
        for _ in range(states):
            ends.append({"X": [[rng.gauss(0, 1) for _ in range(K)] for _ in range(n)], "stage": rng.random()})
        last, c = ends[-1]["X"], ends[-1]["stage"] - 0.5
        win = draw(rng, [math.exp(sum((b + s * c) * x for b, s, x in zip(beta, shift, row))) for row in last])
        out.append({"game": f"g{g:03d}", "n": n, "win": win, "ends": ends})
    return out


def state(ai, ri, kind, actor, n, **f):
    row = {"action_index": ai, "roll_index": ri, "kind": kind, "actor": actor}
    row.update(f)
    return row


def base_fields(n):
    return {"vp": [2] * n, "vp_cards_held": [0] * n, "hand": [0] * n,
            "pips_gross": [[0] * 11 for _ in range(n)], "pips_blocked": [[0] * 11 for _ in range(n)],
            "road_length": [1] * n, "longest_road": None, "largest_army": None, "reach": [0] * n,
            "res_pips": [[0] * 6 for _ in range(n)], "ports": [[] for _ in range(n)], "reach_gold": [0] * n,
            "reach_island": [0] * n, "reach_port": [0] * n}


F = {name: k for k, name in enumerate(threat.FEATS)}


class Features(unittest.TestCase):
    def test_closeness(self):
        # No holder: need 5 segments (cap 4), so 1 short scores 3 and 5 or more short scores 0.
        self.assertEqual(threat.closeness([4, 1, 0], None, 5, 4), [3, 0, 0])
        # Holder seat 1 at 6: the others need 7; the holder gets the cap.
        self.assertEqual(threat.closeness([6, 5, 3], 1, 5, 4), [4, 2, 0])
        self.assertEqual(threat.closeness([0, 2, 3], 3, 3, 3), [0, 1, 3])

    def test_state_rows_carry_forward_and_dev_counts(self):
        n = 3
        # Seat 1: 10 dots of wheat, 5 of ore and 4 of gold; a 3:1 port and the wheat port (type 4).
        res = [[0, 0, 0, 10, 5, 4], [0] * 6, [3, 0, 0, 0, 0, 0]]
        first = state(10, 0, "roll", 1, n, **{**base_fields(n), "res_pips": res, "ports": [[0, 4], [], [2]],
                                               "vp": [3, 2, 4], "vp_cards_held": [0, 0, 1], "hand": [1, 2, 3],
                                               "reach": [7, 0, 2], "reach_gold": [3, 0, 0], "reach_island": [0, 2, 0],
                                               "reach_port": [1, 0, 2]})
        ev = {"seats": ["a", "b", "c"], "states": [first, state(20, 0, "end_turn", 1, n, hand=[0, 2, 3]),
                                                   state(30, 1, "roll", 2, n, largest_army=2)],
              "dev_events": [{"action_index": 12, "seat": 2, "action": "buy", "card": "knight"},
                             {"action_index": 14, "seat": 2, "action": "buy", "card": "knight"},
                             {"action_index": 25, "seat": 2, "action": "play", "card": "knight"}]}
        rows = threat.state_rows(ev)
        self.assertEqual(len(rows), 3)
        col = lambda r, name: [x[F[name]] for x in rows[r]["X"]]
        self.assertEqual(col(0, "board_vp"), [3, 2, 3])  # board VP drops the held VP card
        self.assertAlmostEqual(col(0, "income")[0], 15 / 36)      # the five resources, gold left out
        self.assertAlmostEqual(col(0, "income_gold")[0], 4 / 36)
        self.assertEqual(col(0, "reach"), [4, 0, 2])              # reach without its gold part
        self.assertEqual(col(0, "reach_gold"), [3, 0, 0])
        self.assertEqual(col(0, "reach_island"), [0, 2, 0])
        self.assertEqual(col(0, "reach_port"), [1, 0, 2])
        self.assertEqual(col(0, "port_31"), [1, 0, 0])
        # A 2:1 port counts for the income in its resource: seat 1 wheat 10/36; seat 3 holds brick, makes none.
        self.assertAlmostEqual(col(0, "port_21")[0], 10 / 36)
        self.assertEqual(col(0, "port_21")[1:], [0, 0])
        self.assertEqual(col(1, "dev_held"), [0, 2, 0])  # two bought by action 20
        self.assertEqual(col(1, "hand"), [0, 2, 3])      # hand carried from the end_turn row
        self.assertEqual(col(2, "dev_held"), [0, 1, 0])  # one played
        # Seat 2 holds Largest Army with 1 knight: the others need 2, so 0 knights is 2 short (3 - 2 = 1).
        self.assertEqual(col(2, "army_close"), [1, 3, 1])


class Model(unittest.TestCase):
    def test_stage_of(self):
        X = [[3] + [0] * (K - 1), [7] + [0] * (K - 1), [5] + [0] * (K - 1)]
        self.assertAlmostEqual(threat.stage_of(X, 14), 0.5)  # the leader's board VP over the target
        X[1][F["board_vp"]] = 15
        self.assertEqual(threat.stage_of(X, 14), 1.0)  # capped

    def test_recovers_constant_coefficients(self):
        beta = [0.8, 0.5, 0.0, 0.3, 0.0, -0.4, 0.2] + [0.0] * (K - 7)
        data = model_data(1500, beta, seed=1)
        fit = threat.fit_model(data, staged=False)
        self.assertEqual(len(fit["beta"]), K)
        for f, b in enumerate(beta):
            est = fit["beta"][f] / fit["scale"][f]  # back to the raw-feature scale
            self.assertAlmostEqual(est, b, delta=0.15, msg=threat.FEATS[f])
            lo, hi = fit["ci"][f]
            self.assertLess(lo, fit["beta"][f])
            self.assertGreater(hi, fit["beta"][f])

    def test_recovers_stage_shifts_without_penalty(self):
        beta = [0.6, 0.5] + [0.0] * (K - 2)
        shift = [0.8, -0.6] + [0.0] * (K - 2)  # board VP counts more late, income less
        data = model_data(2000, beta, seed=5, shift=shift)
        fit = threat.fit_model(data, ridge=(0.0, 0.0))
        self.assertEqual(len(fit["beta"]), 2 * K)
        for f in range(2):
            for b, j in ((beta[f], f), (shift[f], K + f)):
                est, se = fit["beta"][j] / fit["scale"][f], fit["se"][j] / fit["scale"][f]
                self.assertLess(abs(est - b), 3 * se, msg=f"{threat.FEATS[f]} term {j}")

    def test_penalty_shrinks(self):
        data = model_data(300, [0.8, 0.5] + [0.0] * (K - 2), seed=6, shift=[0.8, -0.6] + [0.0] * (K - 2))
        free = threat.fit_model(data, ridge=(0.0, 0.0))
        pen = threat.fit_model(data)  # the site's penalties
        self.assertEqual(pen["ridge"], [threat.RIDGE_MAIN, threat.RIDGE_STAGE])
        for j in (0, 1, K, K + 1):
            self.assertLess(abs(pen["beta"][j]), abs(free["beta"][j]))
            self.assertGreater(pen["beta"][j] * free["beta"][j], 0)  # same sign
        heavy = threat.fit_model(data, ridge=(1e7, 1e7))
        self.assertLess(max(abs(b) for b in heavy["beta"]), 1e-3)

    def test_stage_weights(self):
        k = K
        beta = [0.0] * (2 * k)
        beta[0], beta[k] = 0.4, 0.5
        V = [[0.0] * (2 * k) for _ in range(2 * k)]
        V[0][0], V[k][k], V[0][k], V[k][0] = 0.01, 0.04, -0.005, -0.005
        w = threat.stage_weights({"beta": beta, "cov": V}, points=[0.2, 0.5, 0.8])[0]
        self.assertEqual([round(v, 6) for v in w["est"]], [0.25, 0.4, 0.55])  # main + shift (stage - 0.5)
        z = threat.statlib.z_for(threat.LEVEL)
        se = math.sqrt(0.01 + 0.09 * 0.04 + 2 * 0.3 * 0.005)  # c = -0.3: var + c^2 var + 2c cov
        self.assertAlmostEqual(w["hi"][0] - w["est"][0], z * se)

    def test_cluster_intervals_widen_with_repeated_states(self):
        # Repeating one game's state 5 times adds no information: clustered SEs should stay about the same
        # as with one state per game, while naive SEs would shrink by sqrt(5). (Unpenalized: a fixed penalty
        # weighs less against 5 times the strata, which would change the estimate itself.)
        beta = [0.6] + [0.0] * (K - 1)
        one = threat.fit_model(model_data(600, beta, seed=2, states=1), staged=False)
        rep = model_data(600, beta, seed=2, states=1)
        for d in rep:
            d["ends"] = d["ends"] * 5
        five = threat.fit_model(rep, staged=False)
        self.assertAlmostEqual(five["se"][0] / one["se"][0], 1.0, delta=0.1)

    def test_forward_check_uses_only_later_games(self):
        def end(p, pc, win):
            top = max(range(2), key=lambda i: p[i])
            return {"roll_index": 0, "p": p, "p_equal": [0.5, 0.5], "p_constant": pc, "top": top, "top_equal": 0}
        early = {"game": "2026-11-01-a", "n": 2, "win": 0, "rolls": 1, "ends": [end([0.9, 0.1], [0.5, 0.5], 0)]}
        late = {"game": "2026-12-01-a", "n": 2, "win": 0, "rolls": 1, "ends": [end([0.5, 0.5], [0.8, 0.2], 0)]}
        chk = threat.check([early, late])
        fw = chk["forward"]
        self.assertEqual(fw["games"], 1)
        self.assertAlmostEqual(fw["logloss"], round(-math.log(0.5), 3))
        self.assertAlmostEqual(fw["logloss_constant"], round(-math.log(0.8), 3))
        self.assertAlmostEqual(fw["constant_minus_fitted"]["est"], round(math.log(0.5) - math.log(0.8), 3))
        self.assertAlmostEqual(chk["logloss_constant"], round((-math.log(0.5) - math.log(0.8)) / 2, 3))
        self.assertEqual(threat.check([early])["forward"]["games"], 0)

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


class Reason(unittest.TestCase):
    """The biggest reason the top threat leads: the parts add up to the log-odds gap, and the largest one wins."""

    def setUp(self):
        rng = random.Random(3)
        self.model = {"staged": True, "scale": [rng.uniform(0.5, 2) for _ in range(K)],
                      "beta": [rng.uniform(-1, 1) for _ in range(2 * K)]}

    def row(self, X, stage):
        r = {"X": X, "stage": stage}
        r["p"] = threat.model_probs(r, self.model)
        return r

    def parts(self, r, t, s):
        c, b, sc = r["stage"] - threat.STAGE_CENTER, self.model["beta"], self.model["scale"]
        return [(r["X"][t][f] - r["X"][s][f]) / sc[f] * (b[f] + b[K + f] * c) for f in range(K)]

    def test_parts_add_up_and_largest_is_named(self):
        rng = random.Random(7)
        for _ in range(50):
            r = self.row([[rng.uniform(0, 10) for _ in range(K)] for _ in range(4)], rng.random())
            order = sorted(range(4), key=lambda i: -r["p"][i])
            t, s = order[0], order[1]
            parts = self.parts(r, t, s)
            self.assertAlmostEqual(sum(parts), math.log(r["p"][t] / r["p"][s]), places=9)
            f, a, seat, b = threat.reason(r, self.model)
            self.assertEqual(f, max(range(K), key=lambda j: parts[j]))
            self.assertEqual((seat, a, b), (s, r["X"][t][f], r["X"][s][f]))

    def test_one_feature_apart(self):
        X = [[1.0] * K for _ in range(3)]
        X[2][threat.VP_COL] = 5.0  # seat 3 differs from the rest only in board VP
        self.model["beta"][threat.VP_COL], self.model["beta"][K + threat.VP_COL] = 1.0, 0.0
        r = self.row(X, 0.5)
        self.assertEqual(threat.reason(r, self.model), (threat.VP_COL, 5.0, 0, 1.0))

    def test_tie_has_no_reason(self):
        r = self.row([[2.0] * K for _ in range(3)], 0.3)
        self.assertIsNone(threat.reason(r, self.model))

    def test_constant_model_ignores_shift(self):
        self.model = {"staged": False, "scale": [1.0] * K, "beta": [0.0] * K}
        self.model["beta"][threat.FEATS.index("hand")] = 2.0
        X = [[0.0] * K for _ in range(2)]
        X[1][threat.FEATS.index("hand")] = 3.0
        r = self.row(X, 0.9)
        self.assertEqual(threat.reason(r, self.model)[:3], (threat.FEATS.index("hand"), 3.0, 0))


if __name__ == "__main__":
    unittest.main()
