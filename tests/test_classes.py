"""Tests for scripts/classes.py on synthetic games and event logs (never data/).

    python -m unittest discover -s tests
"""

import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import classes  # noqa: E402
import statlib  # noqa: E402

CATS = ("dev", "city", "settlement", "road", "ship")
DECK25 = {"knight": 14, "victory_point": 5, "monopoly": 2, "road_building": 2, "year_of_plenty": 2}


def is_anon(pid):
    return pid.startswith("guest-") or pid.startswith("bot-")


def ctx_for(pids, fast=True):
    return {"pids": pids, "is_anon": is_anon, "is_bot": lambda p: p.startswith("bot-"),
            "is_guest": lambda p: p.startswith("guest-"), "finishing_ranks": None, "fast": fast, "players": {}}


def make_game(gid, seats, winner, spent, G=10, scenario=None, expansion="base", trade=None, bank=None,
              dev_events=(), vp_rows=None, picks=None, robber=None, rolls=None, vp_cards=None):
    """One synthetic game: games.json entry, replays.json entry and replay_events entry.

    spent: per seat {cat: cards}. vp_rows: list of (kind, roll_index, vp list, vp_cards_held list) state rows.
    """
    n = len(seats)
    rolls = rolls if rolls is not None else 12 * n
    roll_log = [{"roll_index": t, "action_index": t, "roller": t % n + 1, "total": 8, "a_raw": [0] * n,
                 "short": [0] * n} for t in range(rolls)]
    zero = [0] * n
    first = {"action_index": 0, "roll_index": 0, "kind": "roll", "actor": 1, "vp": [2] * n, "vp_cards_held": list(zero),
             "hand": list(zero), "spent": {c: list(zero) for c in CATS}, "picked": list(zero)}
    states = [first]
    for kind, t, vp, held in vp_rows or []:
        states.append({"action_index": t + 1, "roll_index": t, "kind": kind, "actor": t % n + 1, "vp": vp,
                       "vp_cards_held": held})
    final_vp = [G if p == winner else 5 for p in seats]
    states.append({"action_index": rolls + 5, "roll_index": rolls - 1, "kind": "final", "actor": 1, "vp": final_vp,
                   "vp_cards_held": vp_cards or list(zero),
                   "spent": {c: [spent[j].get(c, 0) for j in range(n)] for c in CATS}})
    ev = {"seats": seats, "states": states, "roll_log": roll_log, "robber_events": robber or [],
          "trade_events": [], "dev_events": list(dev_events), "discard_events": [], "monopoly_events": [],
          "opening_picks": picks or [], "vp_events": [], "dev_deck": dict(DECK25)}
    game = {"id": gid, "date": "2026-01-01", "winner": winner, "n_seats": n,
            "settings": {"vp_to_win": G, "expansion": expansion, "scenario": scenario},
            "players": [{"player": p, "seat": j + 1, "vp": final_vp[j]} for j, p in enumerate(seats)]}
    trade = trade or [10] * n
    bank = bank or [5] * n
    rep = {"players": {p: {"resources_from_dice": 60, "trade_cards_given": trade[j], "trade_cards_received": trade[j],
                           "bank_cards_given": 4 * bank[j], "bank_cards_received": bank[j], "steals": 3,
                           "monopoly_cards": 0, "gold_from_dice": 0} for j, p in enumerate(seats)}}
    return game, rep, ev


def spending_world(n_games, seed, planted=None, shift=0.15):
    """Games among 5 regulars and a guest, 4 seats each. Every seat spends 40 cards drawn from the same mix
    (dev 0.25, city 0.30, settlement 0.20, road 0.20, ship 0.05), except `planted`, whose dev share is
    raised by `shift` (taken from roads and settlements)."""
    rng = random.Random(seed)
    pool = ["ana", "ben", "cat", "dan", "eve", "guest-1"]
    base = {"dev": 0.25, "city": 0.30, "settlement": 0.20, "road": 0.20, "ship": 0.05}
    games, reps, evs = [], {}, {}
    for k in range(n_games):
        seats = rng.sample(pool, 4)
        spent = []
        for p in seats:
            mix = dict(base)
            if p == planted:
                mix["dev"] += shift
                mix["settlement"] -= shift / 2
                mix["road"] -= shift / 2
            cats, w = list(mix), list(mix.values())
            draw = rng.choices(cats, weights=w, k=40)
            spent.append({c: draw.count(c) for c in CATS})
        winner = rng.choice(seats)
        g, r, e = make_game(f"g{k:03d}", seats, winner, spent)
        games.append(g)
        reps[g["id"]] = r
        evs[g["id"]] = e
    return games, reps, evs


class SpendingTest(unittest.TestCase):
    def setUp(self):
        classes._FACTS.clear()
        classes._VIEW_MEMO.clear()

    def test_mh_recovers_planted_share(self):
        games, reps, evs = spending_world(300, seed=5, planted="ana", shift=0.10)
        recs = classes._recs(games, reps, evs)
        rd = classes.axis_value(recs, "ana", "dev")
        self.assertAlmostEqual(rd, 0.10, delta=0.02)
        self.assertAlmostEqual(classes.axis_value(recs, "ben", "dev"), -0.10 / 5, delta=0.02)
        # the three spending shares sum to 1, so their RDs sum to 0 with the same weights
        tot = sum(classes.axis_value(recs, "ana", a) for a in ("dev", "city", "expansion"))
        self.assertAlmostEqual(tot, 0.0, places=9)

    def test_mh_hand_example(self):
        # Two games, player A vs the rest: (y, N, y_rest, N_rest) = (5, 10, 6, 30) and (2, 10, 10, 20).
        # w = 10*30/40 = 7.5 and 10*20/30 = 6.667; RD = (7.5*(0.5-0.2) + 6.667*(0.2-0.5)) / 14.167 = 0.01765
        sp1 = [{"dev": 5, "road": 5}, {"dev": 2, "road": 8}, {"dev": 2, "road": 8}, {"dev": 2, "road": 8}]
        sp2 = [{"dev": 2, "road": 8}, {"dev": 5, "road": 5}, {"dev": 5, "road": 5}]
        g1 = make_game("h1", ["A", "b1", "b2", "b3"], "A", sp1)
        g2 = make_game("h2", ["A", "b1", "b2"], "b1", sp2)
        recs = classes._recs([g1[0], g2[0]], {"h1": g1[1], "h2": g2[1]}, {"h1": g1[2], "h2": g2[2]})
        expect = (7.5 * 0.3 + (200 / 30) * (-0.3)) / (7.5 + 200 / 30)
        self.assertAlmostEqual(classes.axis_value(recs, "A", "dev"), expect, places=9)
        # losses only: just game h2
        self.assertAlmostEqual(classes.axis_value(recs[1:], "A", "dev"), -0.3, places=9)

    def test_planted_dev_share_passes_gate_and_earns_badge(self):
        games, reps, evs = spending_world(120, seed=7, planted="ana", shift=0.15)
        out = classes.compute_all(games, reps, evs, ctx_for(["ana", "ben", "cat", "dan", "eve"]))
        dev = next(a for a in out["axes"] if a["key"] == "dev")
        self.assertTrue(dev["gate"])
        self.assertGreater(dev["tau2"], 0)
        self.assertLess(dev["p"], 0.10)
        names = [b["name"] for b in out["badges"]["ana"]["badges"]]
        self.assertIn("Scientist", names)
        self.assertLessEqual(len(out["badges"]["ana"]["badges"]), classes.MAX_BADGES)
        b = next(b for b in out["badges"]["ana"]["badges"] if b["name"] == "Scientist")
        self.assertGreater(b["ci"][0], 0)
        self.assertGreater(b["stability"], 0.5)
        for p in ("ben", "cat", "dan", "eve"):
            self.assertNotIn("Scientist", [x["name"] for x in out["badges"][p]["badges"]])
        self.assertNotIn("guest-1", out["badges"])

    def test_homogeneous_table_has_no_badges(self):
        games, reps, evs = spending_world(120, seed=8, planted=None)
        out = classes.compute_all(games, reps, evs, ctx_for(["ana", "ben", "cat", "dan", "eve"]))
        for p in ("ana", "ben", "cat", "dan", "eve"):
            self.assertTrue(out["badges"][p]["eligible"])
            self.assertEqual(out["badges"][p]["badges"], [], p)

    def test_badge_needs_15_games(self):
        games, reps, evs = spending_world(14, seed=9, planted="ana", shift=0.3)
        out = classes.compute_all(games, reps, evs, ctx_for(["ana", "ben", "cat", "dan", "eve"]))
        for row in out["badges"].values():
            self.assertFalse(row["eligible"])
            self.assertEqual(row["badges"], [])

    def test_shrinkage_pulls_toward_mean(self):
        y, se = [0.1, -0.05, 0.0, 0.02], [0.02, 0.02, 0.05, 0.03]
        fit, th = classes._shrink_set(y, se)
        for yi, (t, _) in zip(y, th):
            self.assertLessEqual(abs(t - fit["mu"]), abs(yi - fit["mu"]) + 1e-12)


class ComebackTest(unittest.TestCase):
    def setUp(self):
        classes._FACTS.clear()

    def test_t_star_gap_and_vp_cards(self):
        # G = 10, line G - 3 = 7. Seat 2 reaches 7 board VP at roll 5 while the winner (seat 1) has 4 board VP
        # (5 VP, 1 VP card held). Gap 3, d = 0.3. The winner holds 2 VP cards at the finish.
        rows = [("end_turn", 2, [3, 5, 2], [0, 0, 0]), ("end_turn", 5, [5, 7, 3], [1, 0, 0]),
                ("end_turn", 8, [8, 8, 3], [1, 0, 0])]
        g, r, e = make_game("c1", ["w", "x", "y"], "w", [{}, {}, {}], G=10, vp_rows=rows, vp_cards=[2, 0, 0])
        f = classes.facts(g, e, r)
        cb = f["comeback"]
        self.assertEqual(cb["t_roll"], 5)
        self.assertEqual(cb["gap"], 3)
        self.assertAlmostEqual(cb["d"], 0.3)
        self.assertEqual(cb["leaders"], ["x"])
        self.assertEqual(cb["vp_cards"], 2)
        res = classes.comebacks([f])
        self.assertEqual(res["counts"], {"d20": 1, "gap2": 1, "gap3": 1, "gap4": 0})
        self.assertEqual(res["record"], ["c1"])

    def test_first_to_c_ties_split(self):
        # c = 0.5, G = 10: line 6. At roll 4 seats 1 and 2 both reach 6 board VP: each counts 1/2.
        rows = [("end_turn", 2, [4, 5, 2], [0, 0, 0]), ("end_turn", 4, [6, 6, 3], [0, 0, 0])]
        g, r, e = make_game("c2", ["w", "x", "y"], "w", [{}, {}, {}], G=10, vp_rows=rows)
        f = classes.facts(g, e, r)
        self.assertEqual(f["first_to"][0.5], {0: 0.5, 1: 0.5})
        ctx = ctx_for(["w", "x", "y"])
        out = classes.first_to([f] * 10, ctx, 0.5)
        self.assertEqual(out["group"]["p"], 0.5)
        self.assertEqual(out["players"]["w"]["conv"], 1.0)
        self.assertEqual(out["players"]["x"]["conv"], 0.0)
        self.assertAlmostEqual(out["players"]["w"]["base"], 1 / 3, places=3)
        lo, hi = statlib.wilson(5, 5)
        self.assertAlmostEqual(out["players"]["w"]["conv_ci"][0], round(lo, 3))

    def test_first_to_ignores_hidden_vp(self):
        # Line 8 (c = 0.75, G = 10). Seat 1 has 8 VP but 2 are VP cards: board VP 6, so seat 2 at 8 is first.
        rows = [("end_turn", 3, [8, 7, 2], [2, 0, 0]), ("end_turn", 6, [8, 8, 2], [2, 0, 0])]
        g, r, e = make_game("c3", ["w", "x", "y"], "w", [{}, {}, {}], G=10, vp_rows=rows, vp_cards=[2, 0, 0])
        f = classes.facts(g, e, r)
        self.assertEqual(f["first_to"][0.75], {1: 1.0})


class DraftTest(unittest.TestCase):
    def test_midrank(self):
        vals = [5, 8, 8, 10, 3]
        self.assertAlmostEqual(classes.midrank(8, vals), (2 + 1) / 5)
        self.assertAlmostEqual(classes.midrank(10, vals), 4.5 / 5)
        self.assertAlmostEqual(classes.midrank(3, vals), 0.5 / 5)

    def test_start_region_and_restriction(self):
        # Main island: hexes (0,0), (1,0), (0,1); a separate island at (4,0); a desert strip hex (2,0) with 0 dots.
        cands = [{"hex": [0, 1], "dots": 4, "m": []}, {"hex": [1, 0], "dots": 3, "m": []},
                 {"hex": [2, 0], "dots": 0, "m": []}, {"hex": [3, 0], "dots": 2, "m": []},
                 {"hex": [6, 0], "dots": 5, "m": []}]
        ev = {"robber_events": [{"pirate": False, "candidates": cands, "prior_hex": [0, 0]}]}
        # With the desert as land, (0,0)-(1,0)-(2,0)-(3,0) connect: 5 hexes vs 1.
        self.assertEqual(classes.start_region(ev, False), {(0, 0), (0, 1), (1, 0), (2, 0), (3, 0)})
        # Through the Desert: the desert separates; the mainland is (0,0), (1,0), (0,1).
        self.assertEqual(classes.start_region(ev, True), {(0, 0), (0, 1), (1, 0)})
        # Pirate moves are ignored.
        self.assertIsNone(classes.start_region({"robber_events": [{"pirate": True, "candidates": None}]}, False))

    def test_draft_picks_restricts_legal_corners(self):
        region = {(0, 0)}
        on = (1, 0, 0)    # corner of hex (0,0) (sum 1: touches (0,0), (1,-1)... via corner - e_i)
        self.assertIn((0, 0), classes.corner_hexes(on))
        off = (5, 0, -4)  # far away
        self.assertNotIn((0, 0), classes.corner_hexes(off))
        cands = [{"hex": [0, 0], "dots": 5, "m": []}, {"hex": [1, 0], "dots": 3, "m": []},
                 {"hex": [5, -1], "dots": 5, "m": []}]
        ev = {"seats": ["a", "b"], "robber_events": [{"pirate": False, "candidates": cands, "prior_hex": None}],
              "opening_picks": [{"order": 0, "seat": 1, "pick": 1, "corner": list(on), "pips": 5,
                                 "legal": [list(on) + [5], list(off) + [12]]}]}
        game = {"settings": {"scenario": "new_shores", "expansion": "seafarers"}}
        picks, dropped = classes.draft_picks(game, ev)
        self.assertEqual(dropped, 1)
        self.assertEqual(picks[0]["b"], 5)
        self.assertTrue(picks[0]["top"])
        self.assertEqual(region & set(classes.corner_hexes(on)), {(0, 0)})
        # Base game: no restriction, so the 12-pip corner counts and the pick is not the top.
        picks, dropped = classes.draft_picks({"settings": {"scenario": None, "expansion": "base"}}, ev)
        self.assertEqual(dropped, 0)
        self.assertEqual(picks[0]["b"], 12)
        self.assertFalse(picks[0]["top"])
        self.assertAlmostEqual(picks[0]["pct"], 0.25)

    def test_scope(self):
        mk = lambda e, s: {"settings": {"expansion": e, "scenario": s}}
        self.assertTrue(classes.in_draft_scope(mk("base", None)))
        self.assertTrue(classes.in_draft_scope(mk("seafarers", "new_shores")))
        self.assertTrue(classes.in_draft_scope(mk("seafarers", "through_the_desert")))
        self.assertFalse(classes.in_draft_scope(mk("seafarers", "four_islands")))
        self.assertFalse(classes.in_draft_scope(mk("seafarers", "fog_islands")))


class SurvivalTest(unittest.TestCase):
    def test_km_samples_and_fifo_knights(self):
        # Seat 1 rolls 5 times (own turns 1..5). Buys knights on turns 1 and 2, plays one on turn 4:
        # FIFO matches it to the turn-1 knight (hold 3); the turn-2 knight is censored at 5 - 2 = 3.
        dev = [{"seat": 1, "own_turn": 1, "action": "buy", "card": "knight"},
               {"seat": 1, "own_turn": 2, "action": "buy", "card": "knight"},
               {"seat": 1, "own_turn": 4, "action": "play", "card": "knight"}]
        g, r, e = make_game("k1", ["a", "b"], "a", [{}, {}], dev_events=dev, rolls=10)
        e["vp_events"] = [{"own_turn": 3, "changes": [{"type": "city", "seat": 2}]}]
        s = classes.km_samples(g, e)
        self.assertEqual(s[0]["dev"], (1, 1))
        self.assertEqual(sorted(s[0]["knights"]), [(3, 0), (3, 1)])
        self.assertEqual(s[1]["dev"], (5, 0))     # no buy: censored at 5 own turns
        self.assertEqual(s[1]["city"], (3, 1))
        self.assertEqual(s[0]["city"], (5, 0))

    def test_km_cut_and_median(self):
        times = list(range(1, 21))
        rows = classes.km_curve([(t, 1) for t in times])
        self.assertTrue(all(r["n_risk"] >= classes.KM_MIN_RISK for r in rows))
        self.assertEqual(rows[-1]["time"], 16)  # 5 at risk at t = 16, 4 at t = 17
        med, lo, hi = classes.km_median(rows)
        self.assertEqual(med, 10)  # S(10) = 0.5
        self.assertLessEqual(lo, med)
        self.assertGreaterEqual(hi, med)


class DevLuckTest(unittest.TestCase):
    def test_hand_computed(self):
        # 25-card deck (5 VP, 14 knights). Buy 1 (seat 1): VP, p = 5/25. Buy 2 (seat 2): knight, p_vp = 4/24,
        # p_knight = 14/24. Buy 3 (seat 1): knight, p_vp = 4/23, p_knight = 13/23.
        dev = [{"seat": 1, "own_turn": 1, "action": "buy", "card": "victory_point"},
               {"seat": 2, "own_turn": 1, "action": "buy", "card": "knight"},
               {"seat": 1, "own_turn": 2, "action": "buy", "card": "knight"}]
        g, r, e = make_game("d1", ["a", "b", "c"], "a", [{}, {}, {}], dev_events=dev)
        res, how = classes.dev_luck_game(e)
        self.assertEqual(how, "decoder")
        a = res["a"]
        self.assertEqual(a["vp"][0], 1)
        self.assertAlmostEqual(a["vp"][1], 5 / 25 + 4 / 23)
        self.assertAlmostEqual(a["vp"][2], (5 / 25) * (20 / 25) + (4 / 23) * (19 / 23))
        self.assertAlmostEqual(a["knight"][1], 14 / 25 + 13 / 23)
        self.assertAlmostEqual(res["b"]["knight"][1], 14 / 24)

    def test_martingale_is_unbiased(self):
        # Random shuffles of the 25-card deck: O - E averages 0 and (O - E)/sqrt(V) has variance near 1.
        rng = random.Random(3)
        deck = [k for k, v in DECK25.items() for _ in range(v)]
        zs = []
        for _ in range(3000):
            rng.shuffle(deck)
            dev = [{"seat": 1 + i % 3, "own_turn": 1, "action": "buy", "card": c} for i, c in enumerate(deck[:12])]
            res, _ = classes.dev_luck_game({"seats": ["a", "b", "c"], "dev_events": dev, "dev_deck": DECK25})
            O, E, V = res["a"]["vp"]
            zs.append((O - E) / math.sqrt(V))
        m = sum(zs) / len(zs)
        sd = math.sqrt(sum((z - m) ** 2 for z in zs) / (len(zs) - 1))
        self.assertLess(abs(m), 0.06)
        self.assertLess(abs(sd - 1), 0.06)

    def test_deck_comes_from_the_decoder(self):
        ev = {"seats": list("abcde"), "dev_events": []}
        self.assertIsNone(classes.deck_of(ev)[0])
        big = {"knight": 20, "victory_point": 5, "monopoly": 3, "road_building": 3, "year_of_plenty": 3}
        ev["dev_deck"] = big
        self.assertEqual(classes.deck_of(ev), (big, "decoder"))
        # First buy from a 34-card deck: p_vp = 5/34.
        ev["dev_events"] = [{"seat": 1, "own_turn": 1, "action": "buy", "card": "knight"}]
        res, _ = classes.dev_luck_game(ev)
        self.assertAlmostEqual(res["a"]["vp"][1], 5 / 34)


class HoarderTest(unittest.TestCase):
    def ev(self, hand_at_end, builds, buys=(), deck=None):
        """Seat 1 ends its turn at action 10 holding hand_at_end, then discards on a 7 at action 20."""
        n = 2
        states = [{"action_index": 1, "roll_index": 0, "kind": "roll", "actor": 1, "hand": [0, 0],
                   "hand_cards": [[0] * 5, [0] * 5]},
                  {"action_index": 10, "roll_index": 0, "kind": "end_turn", "actor": 1, "hand": [sum(hand_at_end), 0],
                   "hand_cards": [list(hand_at_end), [0] * 5]},
                  {"action_index": 15, "roll_index": 1, "kind": "end_turn", "actor": 2}]
        vp = [{"action_index": a, "changes": [{"type": k, "seat": 1}]} for a, k in builds]
        dev = [{"action_index": a, "seat": 2, "own_turn": 1, "action": "buy", "card": "knight"} for a in buys]
        return {"seats": ["p", "q"], "states": states, "vp_events": vp, "dev_events": dev,
                "discard_events": [{"action_index": 20, "roll_index": 2, "seat": 1, "cards": [1, 1, 1, 1, 0], "hand_before": 8}],
                "dev_deck": deck or dict(DECK25)}

    def test_city_affordable_on_owned_settlement(self):
        e = self.ev([0, 0, 0, 2, 3], [(0, "settlement"), (2, "settlement")])
        self.assertEqual(classes.discard_checks(e), [(1, {"city": True, "dev": False, "avoidable": True})])

    def test_city_not_avoidable_without_a_settlement_to_upgrade(self):
        # Both settlements already cities: 2 settlements - 2 cities = 0 left to upgrade.
        e = self.ev([0, 0, 0, 2, 3], [(0, "settlement"), (2, "settlement"), (5, "city"), (6, "city")])
        self.assertEqual(classes.discard_checks(e)[0][1]["city"], False)
        # A city built after that end of turn does not count against it.
        e = self.ev([0, 0, 0, 2, 3], [(0, "settlement"), (2, "settlement"), (5, "city"), (12, "city")])
        self.assertEqual(classes.discard_checks(e)[0][1]["city"], True)

    def test_dev_needs_cards_left_in_the_deck(self):
        e = self.ev([0, 0, 1, 1, 1], [(0, "settlement")])
        self.assertEqual(classes.discard_checks(e)[0][1], {"city": False, "dev": True, "avoidable": True})
        e = self.ev([0, 0, 1, 1, 1], [(0, "settlement")], buys=[3, 4], deck={"knight": 2})
        self.assertEqual(classes.discard_checks(e)[0][1]["avoidable"], False)

    def test_share_and_no_previous_turn(self):
        e = self.ev([5, 3, 0, 0, 0], [(0, "settlement")])
        e["discard_events"].append({"action_index": 12, "roll_index": 1, "seat": 2, "cards": [4, 0, 0, 0, 0], "hand_before": 8})
        checks = classes.discard_checks(e)
        self.assertEqual(checks[0][1]["avoidable"], False)
        self.assertIsNone(checks[1][1])  # seat 2 had not ended a turn before action 12
        g = {"id": "h", "settings": {}}
        out = classes.hoarder([g] * 10, {"h": e}, ctx_for(["p", "q"]))
        self.assertEqual(out["players"]["p"]["share"], 0.0)
        self.assertEqual(out["players"]["q"]["checked"], 0)
        self.assertEqual(out["discards"], 20)


if __name__ == "__main__":
    unittest.main()
