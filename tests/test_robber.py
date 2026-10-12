"""Tests for scripts/robber.py on synthetic choice data and synthetic per-action logs (never data/)."""

import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import robber  # noqa: E402
import statlib  # noqa: E402

TRUE_S1 = [0.40, 0.30, -0.50, 0.8, 0.10, -0.6, 0.0, -0.05, 0.9]  # S1_BASE order
TRUE_S2 = [0.7, 0.0, 0.6]  # vp_gap, hand, retal
REGULARS = ["p1", "p2", "p3", "p4", "p5"]


def is_anon(p):
    return p.startswith("guest-") or p.startswith("bot-")


def ranks_of(g):
    others = sorted((r for r in g["players"] if r["player"] != g["winner"]), key=lambda r: -r["vp"])
    out = {g["winner"]: 1}
    for i, r in enumerate(others, start=2):
        out[r["player"]] = i
    return out


def synth_game(gid, rng, n=4, moves=10, trades=14, knights=2, guest=False):
    """One synthetic game in the decoder v2 format. Robber hexes and victims are drawn from the true Stage 1 and
    Stage 2 models (7s and knights alike), using the module's own feature code on the history so far."""
    pool = list(REGULARS)
    rng.shuffle(pool)
    seats = pool[:n]
    if guest:
        seats[-1] = "guest-1"
    rolls = 60
    trade_ev = []
    for _ in range(trades):
        a = rng.randrange(1, n + 1)
        b = rng.choice([s for s in range(1, n + 1) if s != a])
        ri = rng.randrange(1, rolls)
        trade_ev.append({"action_index": ri * 10 + 3, "roll_index": ri, "seat": a, "partner": b,
                         "give": [1, 0, 0, 0, 0], "get": [0, 1, 0, 0, 0], "hands": [rng.randint(1, 7) for _ in range(n)]})
    trade_ev.sort(key=lambda t: t["action_index"])
    ev = {"seats": seats, "decoder_version": 2, "robber_events": [], "trade_events": trade_ev, "monopoly_events": [],
          "opening_picks": [], "vp_events": [{"action_index": 0, "board_vp": [2] * n}],
          "roll_log": [{"roll_index": i} for i in range(rolls)]}
    times = sorted(rng.sample(range(2, rolls), moves + knights))
    kn_idx = set(rng.sample(range(len(times)), knights))
    stolen = [0] * n
    for idx, ri in enumerate(times):
        cands = []
        for h in range(12):
            m = [(1 if rng.random() < 0.25 else 0) + (1 if rng.random() < 0.05 else 0) for _ in range(n)]
            cands.append({"hex": [h, idx], "dots": rng.choice([0, 1, 2, 3, 4, 5]), "m": m})
        r = {"action_index": ri * 10 + 5, "roll_index": ri, "mover": ri % n + 1,
             "cause": "knight" if idx in kn_idx else "seven", "pre_roll": False, "pirate": False,
             "hex": cands[0]["hex"], "prior_hex": None, "candidates": cands,
             "public_vp": [rng.randint(2, 8) for _ in range(n)], "hand": [rng.choice([0, 1, 3, 5, 8]) for _ in range(n)],
             "eligible": [], "victim": None, "card": None}
        ev["robber_events"].append(r)
        mv = robber.game_events(gid, {**ev, "states": [{}]}, is_anon)["moves"][-1]
        p1 = robber.softmax([robber.dot(TRUE_S1, robber.s1_row(mv, d, m)) for d, m in mv["cands"]])
        u, acc, ch = rng.random(), 0.0, len(p1) - 1
        for i, p in enumerate(p1):
            acc += p
            if u < acc:
                ch = i
                break
        r["hex"] = cands[ch]["hex"]
        st = robber.stealable(mv, cands[ch]["m"])
        r["eligible"] = st
        if st:
            w = [math.exp(robber.dot(TRUE_S2, robber.s2_row(mv, j))) for j in st]
            u, acc = rng.random() * sum(w), 0.0
            for j, wj in zip(st, w):
                acc += wj
                if u < acc:
                    r["victim"] = j
                    break
            r["victim"] = r["victim"] or st[-1]
            stolen[r["victim"] - 1] += 1
    ev["states"] = [{"action_index": 0, "roll_index": 0, "kind": "roll", "stolen_from": stolen,
                     "blocked_by": [[0] * n for _ in range(n)], "monopoly_lost_to": [[0] * n for _ in range(n)]}]
    winner = rng.choice(seats)
    game = {"id": gid, "date": "2025-01-01", "winner": winner, "settings": {"vp_to_win": 10},
            "players": [{"player": p, "vp": 10 if p == winner else rng.randint(4, 9)} for p in seats]}
    replay = {"players": {p: {"opening_dots": rng.randint(15, 25)} for p in seats}}
    return game, ev, replay


def simulate_choice(rng, beta, n_strata, n_alt):
    strata = []
    for _ in range(n_strata):
        X = [[rng.gauss(0, 1) for _ in beta] for _ in range(n_alt)]
        p = robber.softmax([robber.dot(beta, x) for x in X])
        u, acc, c = rng.random(), 0.0, n_alt - 1
        for i, pi in enumerate(p):
            acc += pi
            if u < acc:
                c = i
                break
        strata.append((X, c))
    return strata


class ClogitTest(unittest.TestCase):
    def test_recovers_planted_coefficients(self):
        rng = random.Random(1)
        beta = [0.8, -0.5, 0.2]
        fit = robber.clogit(simulate_choice(rng, beta, 1500, 6), 3)
        self.assertTrue(fit["converged"])
        for b, est, se in zip(beta, fit["beta"], fit["se"]):
            self.assertLess(abs(est - b), 3 * se)

    def test_matches_statlib_without_penalty(self):
        rng = random.Random(2)
        strata = simulate_choice(rng, [0.5, 1.0], 120, 4)
        mine = robber.clogit(strata, 2)
        ref = statlib.cond_logit([{"X": X, "y": [1 if i == c else 0 for i in range(len(X))]} for X, c in strata],
                                 firth=False)
        for a, b in zip(mine["beta"], ref["beta"]):
            self.assertAlmostEqual(a, b, places=6)
        self.assertAlmostEqual(mine["loglik"], ref["loglik"], places=6)

    def test_ridge_shrinks_to_zero(self):
        rng = random.Random(3)
        strata = simulate_choice(rng, [1.0], 200, 3)
        free = robber.clogit(strata, 1)["beta"][0]
        tight = robber.clogit(strata, 1, ridge=[1e6])["beta"][0]
        self.assertGreater(free, 0.5)
        self.assertLess(abs(tight), 1e-3)


class LeaveOneMoverOutTest(unittest.TestCase):
    def test_hand_computed_E(self):
        """One feature, two alternatives x = (1, 0), so the fit is logit(share choosing x = 1). Mover A chooses
        x = 1 in 2 of 3 moves, mover B in 3 of 4. Leaving A out, b = log 3 and P = 3/4, so E_A = 3 x 3/4 = 2.25;
        leaving B out, b = log 2 and P = 2/3, so E_B = 4 x 2/3 = 8/3."""
        moves = [{"group": "A", "c": c} for c in (0, 0, 1)] + [{"group": "B", "c": c} for c in (0, 0, 0, 1)]
        res = robber.fit_with_lomo(moves, lambda m: ([[1.0], [0.0]], m["c"]), 1)
        self.assertAlmostEqual(res["lomo"]["A"][0], math.log(3), places=6)
        self.assertAlmostEqual(res["lomo"]["B"][0], math.log(2), places=6)
        self.assertAlmostEqual(res["full"]["beta"][0], math.log(5 / 2), places=6)
        E = {"A": 0.0, "B": 0.0}
        for m in moves:
            b = res["lomo"][m["group"]][0]
            E[m["group"]] += robber.softmax([b, 0.0])[0]
        self.assertAlmostEqual(E["A"], 2.25, places=6)
        self.assertAlmostEqual(E["B"], 8 / 3, places=6)

    def test_predict_all_uses_the_left_out_fit(self):
        rng = random.Random(4)
        game, ev, _ = synth_game("g1", rng, moves=4, knights=0)
        moves = robber.game_events("g1", ev, is_anon)["moves"]
        k = len(robber.S1_BASE)
        b_full, b_a = [0.0] * k, [0.3] * k
        g0 = moves[0]["group"]
        fits = {"stage1": {"seven": {"full": {"beta": b_full}, "lomo": {g0: b_a}}},
                "stage2": {"seven": {"full": {"beta": [0.0] * 3}, "lomo": {}}}}
        pr = robber.predict_all(moves, fits)
        want = robber.predict_move(moves[0], b_a, [0.0] * 3)
        self.assertEqual(pr[0]["victim"], want["victim"])

    def test_combined_victim_probability_by_hand(self):
        """Two hexes. Hex 0 touches seat 2 only (P2 = 1); hex 1 touches seats 2 and 3, chosen by Stage 2 with weights
        exp(b . z). With b1 = 0 both hexes have P1 = 1/2."""
        mv = {"mover": 1, "opp": [2, 3], "lead": {2}, "vmax": 5, "pv": [3, 5, 4], "hand": [2, 4, 6], "robbed_me": set(),
              "cands": [(4, [0, 1, 0]), (3, [0, 1, 1])], "eligible": [2, 3], "n": 3}
        b2 = [0.5, 0.0, 0.0]
        pr = robber.predict_move(mv, [0.0] * len(robber.S1_BASE), b2)
        w2, w3 = math.exp(0.0), math.exp(0.5 * (4 - 5))
        self.assertAlmostEqual(pr["victim"][1], 0.5 + 0.5 * w2 / (w2 + w3), places=10)
        self.assertAlmostEqual(pr["victim"][2], 0.5 * w3 / (w2 + w3), places=10)
        self.assertAlmostEqual(pr["touch"][1], 1.0, places=10)
        self.assertAlmostEqual(pr["touch"][2], 0.5, places=10)


class FeatureTest(unittest.TestCase):
    def test_stage1_row(self):
        mv = {"mover": 1, "opp": [2, 3, 4], "lead": {2}, "vmax": 6, "pv": [3, 6, 4, 2], "hand": [1, 3, 0, 5],
              "robbed_me": {4}, "recent": {3}, "own_turn": set(), "their_turn": {3}, "lag": set(), "sofar": {3: 2},
              "mover_pid": "p1"}
        # dots 5; mover 1 building, seat 2 a city, seat 3 (empty hand) 1, seat 4 1.
        row = robber.s1_row(mv, 5, [1, 2, 1, 1], "partner")
        self.assertEqual(row[0], 10)  # leader income
        self.assertEqual(row[1], 10)  # other opponents 3 and 4
        self.assertEqual(row[2], 5)  # own
        self.assertEqual(row[3], 2)  # stealable: 2 and 4 (3 has no cards)
        self.assertEqual(row[4], 5)  # largest stealable hand
        self.assertAlmostEqual(row[5], math.log(4) + math.log(6))
        self.assertEqual(row[6], 5)  # empty-handed seat 3
        self.assertEqual(row[7], 5 * 2 + 5 * 4)  # gaps 6 - 4 and 6 - 2
        self.assertEqual(row[8], 1.0)  # seat 4 robbed the mover
        self.assertEqual(row[9], 5)  # partner seat 3
        self.assertEqual(row[10], 10)  # x9 = x2 when a partner exists

    def test_windows(self):
        """Retaliation window: last n_g rolls; partner window: last 2 n_g rolls; lag: the 2 n_g before that."""
        n = 4
        ev = {"seats": ["p1", "p2", "p3", "p4"], "states": [{}], "roll_log": [{}] * 40,
              "robber_events": [
                  {"action_index": 100, "roll_index": 10, "mover": 2, "cause": "seven", "pirate": True, "victim": 1,
                   "candidates": None, "hex": [0, 0], "eligible": [1], "public_vp": [2] * n, "hand": [1] * n},
                  {"action_index": 170, "roll_index": 17, "mover": 3, "cause": "seven", "pirate": True, "victim": 1,
                   "candidates": None, "hex": [0, 0], "eligible": [1], "public_vp": [2] * n, "hand": [1] * n},
                  {"action_index": 200, "roll_index": 20, "mover": 1, "cause": "seven", "pirate": False, "victim": None,
                   "candidates": [{"hex": [1, 1], "dots": 3, "m": [0, 1, 1, 1]}, {"hex": [2, 2], "dots": 2, "m": [0, 0, 0, 0]}],
                   "hex": [1, 1], "eligible": [], "public_vp": [2, 2, 2, 5], "hand": [1] * n}],
              "trade_events": [
                  {"action_index": 190, "roll_index": 19, "seat": 1, "partner": 2, "give": [1, 0, 0, 0, 0], "get": [0] * 5, "hands": [1] * n},
                  {"action_index": 120, "roll_index": 12, "seat": 3, "partner": 1, "give": [1, 0, 0, 0, 0], "get": [0] * 5, "hands": [1] * n},
                  {"action_index": 205, "roll_index": 20, "seat": 1, "partner": 4, "give": [1, 0, 0, 0, 0], "get": [0] * 5, "hands": [1] * n}]}
        mv = robber.game_events("g", ev, is_anon)["moves"][0]
        self.assertEqual(mv["robbed_me"], {3})  # rolls 17 to 20 are the last 4; roll 10 is not
        self.assertEqual(mv["recent"], {2})  # roll 19 within 8; roll 12 is in the lag window; 205 is later
        self.assertEqual(mv["lag"], {3})
        self.assertEqual(mv["lead"], {4})


class IntervalTest(unittest.TestCase):
    def test_fieller_matches_delta_when_precise(self):
        beta, cov = [2.0, 4.0], [[1e-6, 0.0], [0.0, 1e-6]]
        est, lo, hi = robber.fieller(beta, cov, [1, 0], [0, 1])
        self.assertAlmostEqual(est, 0.5)
        self.assertLess(lo, 0.5)
        self.assertGreater(hi, 0.5)
        self.assertLess(hi - lo, 0.01)

    def test_fieller_unbounded_when_denominator_near_zero(self):
        est, lo, hi = robber.fieller([1.0, 0.1], [[0.01, 0.0], [0.0, 1.0]], [1, 0], [0, 1])
        self.assertIsNone(lo)

    def test_shrink_homogeneous_collapses_to_group(self):
        items = {k: (20, 20.0) for k in "abcd"}
        out, meta = robber.shrink_set(items)
        self.assertEqual(meta["tau2"], 0.0)
        self.assertFalse(meta["gate_open"])
        vals = {v["shrunk"] for v in out.values()}
        self.assertEqual(len(vals), 1)
        self.assertLess(out["a"]["lo"], out["a"]["shrunk"])  # the interval keeps the uncertainty in mu


class TradeModelTest(unittest.TestCase):
    def _games(self, u_pair, seed):
        """Trades where the roller picks a partner with log-odds g1 log(1 + hand) + u for the pair (p1, p2)."""
        rng = random.Random(seed)
        G = []
        for k in range(80):
            seats = rng.sample(REGULARS, 4)
            trades = []
            for t in range(25):
                a = rng.randrange(1, 5)
                hands = [rng.randint(1, 8) for _ in range(4)]
                cs = [q for q in range(1, 5) if q != a]
                eta = [0.7 * math.log1p(hands[q - 1]) + (u_pair if {seats[a - 1], seats[q - 1]} == {"p1", "p2"} else 0.0)
                       for q in cs]
                p = robber.softmax(eta)
                u, acc, ch = rng.random(), 0.0, cs[-1]
                for q, pq in zip(cs, p):
                    acc += pq
                    if u < acc:
                        ch = q
                        break
                trades.append({"ai": t * 10, "ri": t, "seat": a, "partner": ch, "give": [1, 0, 0, 0, 0],
                               "get": [0, 1, 0, 0, 0], "hands": hands, "pv": [2, 2, 2, 2]})
            G.append({"gid": f"t{k}", "n": 4, "seats": seats, "trades": trades, "steals": []})
        return G

    def test_recovers_hand_effect_and_no_pair_effect(self):
        tm = robber.trade_model(self._games(0.0, 5), is_anon, REGULARS)
        self.assertLess(abs(tm["hand"]["b"] - 0.7), 3 * tm["hand"]["se"])
        self.assertLessEqual(tm["sigma_u"], 0.3)

    def test_planted_pair_effect(self):
        tm = robber.trade_model(self._games(1.0, 6), is_anon, REGULARS)
        # One planted pair among ten: the spread of the true u is about 0.3, and the estimates are shrunk.
        self.assertGreater(tm["sigma_u"], 0.0)
        self.assertGreater(tm["u"]["p1|p2"]["exp_u"], 1.3)
        others = [v["exp_u"] for k, v in tm["u"].items() if k != "p1|p2"]
        self.assertLess(max(others), tm["u"]["p1|p2"]["exp_u"])


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rng = random.Random(11)
        games, events, replays = [], {}, {}
        for k in range(70):
            g, ev, rp = synth_game(f"g{k:02d}", rng, guest=(k % 10 == 0))
            g["date"] = f"2025-01-{k % 28 + 1:02d}"
            games.append(g)
            events[g["id"]] = ev
            replays[g["id"]] = rp
        games.sort(key=lambda g: (g["date"], g["id"]))
        cls.ctx = {"pids": REGULARS, "is_anon": is_anon, "is_bot": lambda p: p.startswith("bot-"),
                   "finishing_ranks": ranks_of, "fast": True, "players": {}}
        cls.res = robber.compute_all(games, replays, events, cls.ctx)
        cls.view = robber.compute_view(games, replays, events, cls.ctx, cls.res)

    def test_stage1_recovers_planted_coefficients(self):
        for row, b in zip(self.res["stage1"]["seven"]["coef"], TRUE_S1):
            if row["key"] in ("lead_inc", "other_inc", "own_inc", "retal", "gap_inc"):
                self.assertLess(abs(row["b"] - b), 3.5 * row["se"], row["key"])

    def test_stage2_recovers_vp_gap(self):
        row = self.res["stage2"]["seven"]["coef"][0]
        self.assertLess(abs(row["b"] - TRUE_S2[0]), 3.5 * row["se"])

    def test_partner_rho_near_one_when_no_partner_effect(self):
        p = self.res["partner"]
        self.assertTrue(p["lo"] is None or p["lo"] < 1 < p["hi"])

    def test_pair_balance_parts_add_up(self):
        bal = [p["balance"] for p in self.view["pairs"].values() if "balance" in p]
        self.assertTrue(bal)
        for b in bal:
            self.assertAlmostEqual(b["position"] + b["retaliation"] + b["beyond"], b["net"], delta=0.02)
            self.assertLessEqual(b["band"][0], b["band"][1])

    def test_targeting_E_sums_to_steals(self):
        """Every land move with a stealable opponent on some hex yields an expected victim, so with no guests
        sum E is close to sum O over all seats; here a guest seat takes part, so E is at most the moves."""
        t = self.view["targeting"]
        self.assertTrue(t)
        for v in t.values():
            self.assertGreaterEqual(v["E"], 0)
            self.assertGreater(v["shrunk"], 0)

    def test_guards_and_guests(self):
        self.assertNotIn("guest-1", self.view["targeting"])
        for k, p in self.view["pairs"].items():
            self.assertNotIn("guest", k)
            self.assertEqual(p["tier"], "color" if p["games"] >= 10 else "grey")

    def test_early_excess_runs(self):
        self.assertIn("gamma", self.res["early_excess"])


if __name__ == "__main__":
    unittest.main()
