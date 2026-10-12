"""Tests for scripts/statlib.py on synthetic data and published textbook examples.

    python -m unittest discover -s tests
"""

import math
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import statlib as sl  # noqa: E402


def simulate_strata(rng, n_strata, size, beta):
    """One winner per stratum drawn from the conditional logit with a single N(0, 1) feature."""
    out = []
    for _ in range(n_strata):
        xs = [rng.gauss(0, 1) for _ in range(size)]
        w = [math.exp(beta * x) for x in xs]
        u, acc, pick = rng.random() * sum(w), 0.0, size - 1
        for k, wk in enumerate(w):
            acc += wk
            if u <= acc:
                pick = k
                break
        out.append({"X": [[x] for x in xs], "y": [1 if k == pick else 0 for k in range(size)]})
    return out


class Distributions(unittest.TestCase):
    def test_quantiles_and_tails(self):
        self.assertAlmostEqual(sl.z_for(0.95), 1.959964, places=6)
        self.assertAlmostEqual(sl.t_ppf(0.975, 10), 2.228139, places=6)
        self.assertAlmostEqual(sl.t_ppf(0.975, 1), 12.706205, places=5)
        self.assertAlmostEqual(sl.t_ppf(0.025, 3), -3.182446, places=6)
        self.assertAlmostEqual(sl.chi2_sf(3.841459, 1), 0.05, places=7)
        self.assertAlmostEqual(sl.chi2_sf(18.307038, 10), 0.05, places=7)
        self.assertAlmostEqual(sl.chi2_sf(7.814728, 3), 0.05, places=7)

    def test_wilson(self):
        lo, hi = sl.wilson(81, 263)
        self.assertAlmostEqual(lo, 0.2553, places=4)
        self.assertAlmostEqual(hi, 0.3662, places=4)
        self.assertEqual(sl.wilson(0, 10)[0], 0.0)
        self.assertIsNone(sl.wilson(0, 0))

    def test_linear_algebra(self):
        A = [[4.0, 1.0, 2.0], [1.0, 3.0, 0.5], [2.0, 0.5, 5.0]]
        x = sl.solve(A, [1.0, 2.0, 3.0])
        for row, b in zip(A, [1.0, 2.0, 3.0]):
            self.assertAlmostEqual(sum(a * v for a, v in zip(row, x)), b, places=12)
        inv = sl.inverse(A)
        for i in range(3):
            for j in range(3):
                self.assertAlmostEqual(sum(A[i][k] * inv[k][j] for k in range(3)), float(i == j), places=12)
        det = 4 * (15 - 0.25) - 1 * (5 - 1) + 2 * (0.5 - 6)
        self.assertAlmostEqual(sl.logdet(A), math.log(det), places=12)
        with self.assertRaises(ValueError):
            sl.solve([[1.0, 2.0], [2.0, 4.0]], [1.0, 1.0])


class ConditionalLogit(unittest.TestCase):
    def test_recovers_planted_beta(self):
        rng = random.Random(1)
        strata = simulate_strata(rng, 400, 4, 0.5)
        fit = sl.cond_logit(strata, firth=False)
        self.assertTrue(fit["converged"])
        self.assertLess(abs(fit["beta"][0] - 0.5), 3 * fit["se"][0])

    def test_two_features_and_exploded_orders(self):
        # Full finishing orders drawn from Plackett-Luce (Gumbel trick), refit through exploded strata.
        rng = random.Random(2)
        beta = [0.6, -0.4]
        strata = []
        for _ in range(300):
            X = [[rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(4)]
            util = [beta[0] * x[0] + beta[1] * x[1] - math.log(-math.log(rng.random())) for x in X]
            order = sorted(range(4), key=lambda i: -util[i])
            ranks = [order.index(i) + 1 for i in range(4)]
            strata.extend(sl.exploded_strata(X, ranks))
        self.assertEqual(len(strata), 900)  # 3 informative stages per game of 4
        fit = sl.cond_logit(strata, firth=False)
        for b, est, se in zip(beta, fit["beta"], fit["se"]):
            self.assertLess(abs(est - b), 3 * se)

    def test_exploded_strata_ties_and_depth(self):
        X = [[1.0], [2.0], [3.0], [4.0]]
        s = sl.exploded_strata(X, [1, 2, 2, None])
        self.assertEqual([st["y"] for st in s], [[1, 0, 0, 0], [1, 1, 0]])
        self.assertEqual(len(sl.exploded_strata(X, [1, 2, 3, 4], depth=1)), 1)

    def test_breslow_ties_hand_calculation(self):
        # One stratum, x = 0, 1, 2, the first two tied as chosen (d = 2).
        # l(b) = b - 2 log(1 + e^b + e^2b); the score is zero where 3u^2 + u - 1 = 0, u = e^b.
        strata = [{"X": [[0], [1], [2]], "y": [1, 1, 0]}]
        b = 0.3
        self.assertAlmostEqual(sl.cond_logit_loglik(strata, [b]),
                               b - 2 * math.log(1 + math.exp(b) + math.exp(2 * b)), places=12)
        fit = sl.cond_logit(strata, firth=False)
        u = (math.sqrt(13) - 1) / 6
        self.assertAlmostEqual(fit["beta"][0], math.log(u), places=8)
        p = [1 / (1 + u + u * u), u / (1 + u + u * u), u * u / (1 + u + u * u)]
        m = p[1] + 2 * p[2]
        info = 2 * (p[1] + 4 * p[2] - m * m)
        self.assertAlmostEqual(fit["se"][0], 1 / math.sqrt(info), places=8)
        # Counts: an alternative chosen twice is the same as two tied copies of it.
        twice = sl.cond_logit([{"X": [[0], [1], [2]], "y": [0, 2, 0]}], firth=False)
        self.assertAlmostEqual(sl.cond_logit_loglik([{"X": [[0], [1], [2]], "y": [0, 2, 0]}], [b]),
                               2 * b - 2 * math.log(1 + math.exp(b) + math.exp(2 * b)), places=12)
        self.assertTrue(twice["converged"])

    def test_firth_under_separation(self):
        # 30 pairs, the higher x always wins: ML runs off to infinity; Firth is log(2n + 1) (add 1/2 to each cell).
        n = 30
        strata = [{"X": [[1.0], [0.0]], "y": [1, 0]}] * n
        ml = sl.cond_logit(strata, firth=False)
        self.assertTrue(not ml["converged"] or ml["beta"][0] > 20)
        fit = sl.cond_logit(strata, firth=True)
        self.assertTrue(fit["converged"])
        self.assertAlmostEqual(fit["beta"][0], math.log(2 * n + 1), places=7)
        lo, hi = sl.profile_ci(strata, 0, firth=True, fit=fit)
        self.assertTrue(0 < lo < fit["beta"][0] < hi < math.inf)
        lo_ml, hi_ml = sl.profile_ci(strata, 0, firth=False)
        self.assertEqual(hi_ml, math.inf)
        self.assertTrue(math.isfinite(lo_ml))

    def test_firth_close_to_ml_on_plentiful_data(self):
        strata = simulate_strata(random.Random(3), 2000, 3, 0.4)
        ml = sl.cond_logit(strata, firth=False)
        fi = sl.cond_logit(strata, firth=True)
        self.assertLess(abs(fi["beta"][0] - ml["beta"][0]), 0.1 * ml["se"][0])
        self.assertLess(abs(fi["beta"][0]), abs(ml["beta"][0]))  # Firth shrinks slightly toward 0

    def test_profile_ci_with_nuisance_parameter(self):
        # With two features, the profile interval for b_0 must sit at 2 (lmax - lprof) = z^2 on both sides.
        rng = random.Random(4)
        strata = []
        for _ in range(150):
            X = [[rng.gauss(0, 1), rng.gauss(0, 1)] for _ in range(3)]
            w = [math.exp(0.5 * x[0] + 0.3 * x[1]) for x in X]
            u, acc, pick = rng.random() * sum(w), 0.0, 2
            for k, wk in enumerate(w):
                acc += wk
                if u <= acc:
                    pick = k
                    break
            strata.append({"X": X, "y": [1 if k == pick else 0 for k in range(3)]})
        fit = sl.cond_logit(strata, firth=True)
        lo, hi = sl.profile_ci(strata, 0, fit=fit)
        self.assertLess(lo, fit["beta"][0])
        self.assertGreater(hi, fit["beta"][0])
        for end in (lo, hi):
            # Re-maximize b_1 by brute force over a fine grid to confirm the profile value.
            best = max(sl.cond_logit_loglik(strata, [end, fit["beta"][1] + k / 2000], firth=True)
                       for k in range(-1000, 1001))
            self.assertAlmostEqual(2 * (fit["loglik_penalized"] - best), sl.z_for(0.95) ** 2, places=3)

    def test_profile_ci_coverage(self):
        rng = random.Random(5)
        beta, hits, sims = 0.5, 0, 200
        for _ in range(sims):
            strata = simulate_strata(rng, 40, 3, beta)
            lo, hi = sl.profile_ci(strata, 0, firth=True)
            hits += lo <= beta <= hi
        self.assertGreaterEqual(hits / sims, 0.90)
        self.assertLessEqual(hits / sims, 0.99)


class Resampling(unittest.TestCase):
    def test_seeded_bootstrap_is_reproducible(self):
        games = [random.Random(6).gauss(0, 1) + i for i in range(20)]

        def stat(gs):
            return sum(gs) / len(gs)

        a = sl.cluster_bootstrap(games, stat, B=200, seed=11)
        b = sl.cluster_bootstrap(games, stat, B=200, seed=11)
        c = sl.cluster_bootstrap(games, stat, B=200, seed=12)
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        lo, hi = sl.percentile_ci(a)
        self.assertLess(lo, stat(games))
        self.assertGreater(hi, stat(games))

    def test_bca_close_to_t_interval_for_normal_mean(self):
        rng = random.Random(13)
        xs = [rng.gauss(10, 2) for _ in range(40)]

        def mean(v):
            return sum(v) / len(v)

        m, lo_t, hi_t = sl.t_interval(xs)
        se = (hi_t - m) / sl.t_ppf(0.975, 39)
        lo, hi = sl.bca_ci(xs, mean, B=2000, seed=1)
        self.assertLess(abs(lo - lo_t), 0.15 * se)
        self.assertLess(abs(hi - hi_t), 0.15 * se)
        self.assertEqual((lo, hi), sl.bca_ci(xs, mean, B=2000, seed=1))

    def test_bca_corrects_for_skew(self):
        # Mean of a right-skewed sample: BCa moves both endpoints right of the plain percentile interval.
        rng = random.Random(14)
        xs = [rng.expovariate(1.0) ** 2 for _ in range(30)]

        def mean(v):
            return sum(v) / len(v)

        lo_p, hi_p = sl.percentile_ci(sl.cluster_bootstrap(xs, mean, B=2000, seed=2))
        lo, hi = sl.bca_ci(xs, mean, B=2000, seed=2)
        self.assertGreater(lo, lo_p)
        self.assertGreater(hi, hi_p)

    def test_percentile_ci_type7(self):
        lo, hi = sl.percentile_ci(list(range(101)), 0.9)
        self.assertAlmostEqual(lo, 5.0, places=12)
        self.assertAlmostEqual(hi, 95.0, places=12)
        self.assertAlmostEqual(sl.quantile([1, 2, 3, 4], 0.5), 2.5)
        self.assertEqual(sl.percentile_ci([None, float("nan")]), (None, None))

    def test_sup_t_band_covers_level_share_of_curves(self):
        rng = random.Random(7)
        curves = [[rng.gauss(0, 1 + t / 10) for t in range(15)] for _ in range(1000)]
        band = sl.sup_t_band(curves, 0.95)
        inside = sum(all(lo <= v <= hi for v, lo, hi in zip(c, band["lo"], band["hi"])) for c in curves)
        self.assertAlmostEqual(inside / len(curves), 0.95, delta=0.005)
        self.assertGreater(band["crit"], sl.z_for(0.95))  # simultaneous is wider than pointwise

    def test_perm_test(self):
        rng = random.Random(8)
        feats, winners = [], []
        for _ in range(60):
            x = [rng.gauss(0, 1) for _ in range(4)]
            w = max(range(4), key=lambda i: x[i] + rng.gauss(0, 0.5))
            feats.append(x)
            winners.append([1 if i == w else 0 for i in range(4)])

        def stat(ws):
            return sum(sum(xi * wi for xi, wi in zip(x, w)) for x, w in zip(feats, ws))

        r1 = sl.perm_test(winners, stat, B=2000, seed=1)
        r2 = sl.perm_test(winners, stat, B=2000, seed=1)
        self.assertEqual(r1["p"], r2["p"])
        self.assertLess(r1["p"], 0.01)
        self.assertLess(r1["lo"], r1["null_mean"])
        self.assertGreater(r1["hi"], r1["null_mean"])
        self.assertEqual(winners[0], [1 if i == max(range(4), key=lambda i: winners[0][i]) else 0
                                      for i in range(4)])  # input left unshuffled


class MetaAnalysis(unittest.TestCase):
    # BCG vaccine trials (Colditz et al. 1994), log relative risks; metafor rma(method="REML") gives
    # tau^2 = 0.3132, mu = -0.7145 (SE 0.1798), Q(df = 12) = 152.2330.
    BCG = [(4, 119, 11, 128), (6, 300, 29, 274), (3, 228, 11, 209), (62, 13536, 248, 12619),
           (33, 5036, 47, 5761), (180, 1361, 372, 1079), (8, 2537, 10, 619), (505, 87886, 499, 87892),
           (29, 7470, 45, 7232), (17, 1699, 65, 1600), (186, 50448, 141, 27197), (5, 2493, 3, 2338),
           (27, 16886, 29, 17825)]

    def test_reml_matches_metafor_bcg(self):
        y = [math.log((a / (a + b)) / (c / (c + d))) for a, b, c, d in self.BCG]
        se = [math.sqrt(1 / a - 1 / (a + b) + 1 / c - 1 / (c + d)) for a, b, c, d in self.BCG]
        r = sl.reml_tau2(y, se)
        self.assertAlmostEqual(r["tau2"], 0.3132, places=4)
        self.assertAlmostEqual(r["mu"], -0.7145, places=4)
        self.assertAlmostEqual(r["se_mu"], 0.1798, places=4)
        self.assertAlmostEqual(r["Q"], 152.2330, places=3)
        self.assertLess(r["p"], 1e-20)

    def test_reml_zero_on_homogeneous_data(self):
        r = sl.reml_tau2([0.10, 0.12, 0.08, 0.11, 0.09], [0.2] * 5)
        self.assertEqual(r["tau2"], 0.0)
        self.assertGreater(r["p"], 0.9)
        self.assertAlmostEqual(r["mu"], 0.10, places=12)
        shrunk = sl.shrink([0.1, 0.3], [0.2, 0.2], r["tau2"], r["mu"])
        self.assertEqual([t for t, _ in shrunk], [r["mu"], r["mu"]])

    def test_shrink_and_ratio(self):
        (t1, s1), (t2, s2) = sl.shrink([1.0, 1.0], [0.5, 1.0], 0.25, 0.0)
        self.assertAlmostEqual(t1, 0.5)  # B = 0.25 / (0.25 + 0.25)
        self.assertAlmostEqual(t2, 0.2)  # B = 0.25 / (0.25 + 1)
        self.assertAlmostEqual(s1, math.sqrt(0.5) * 0.5)
        lr, se = sl.shrink_ratio(9.5, 4.5)
        self.assertAlmostEqual(lr, math.log(2))
        self.assertAlmostEqual(se, 1 / math.sqrt(10))


class MantelHaenszel(unittest.TestCase):
    def test_risk_difference_hand_calculation(self):
        strata = [(3, 10, 10, 40), (6, 20, 6, 30)]
        r = sl.mh_risk_difference(strata)
        # w = 10*40/50 = 8 and 20*30/50 = 12; differences 0.30 - 0.25 and 0.30 - 0.20.
        self.assertAlmostEqual(r["rd"], (8 * 0.05 + 12 * 0.10) / 20, places=12)
        # Sato: P = (100*10 - 1600*3 + 400*30/2)/2500 = 0.88 and (400*6 - 900*6 + 600*10/2)/2500 = 0;
        # Q = (3*30 + 10*7)/100 = 1.6 and (6*24 + 6*14)/100 = 2.28; Var = (0.08*0.88 + 3.88) / 20^2.
        self.assertAlmostEqual(r["se"], math.sqrt((0.08 * 0.88 + 3.88) / 400), places=12)
        # One large stratum reduces to the usual binomial variance p1 q1 / n1 + p0 q0 / n0.
        one = sl.mh_risk_difference([(3, 10, 10, 40)])
        self.assertAlmostEqual(one["se"] ** 2, 0.3 * 0.7 / 10 + 0.25 * 0.75 / 40, places=12)
        self.assertIsNone(sl.mh_risk_difference([(0, 0, 3, 10)]))

    def test_rate_ratio_hand_calculation(self):
        # Spec 1.4: one seat (t1 = 1) against the other n - 1 seats.
        strata = [(6, 1, 9, 3), (2, 1, 10, 2)]
        r = sl.mh_rate_ratio(strata)
        R = 6 * 3 / 4 + 2 * 2 / 3
        S = 9 / 4 + 10 / 3
        self.assertAlmostEqual(r["rr"], R / S, places=12)
        var = (1 * 3 * 15 / 16 + 1 * 2 * 12 / 9) / (R * S)
        self.assertAlmostEqual(r["log_se"], math.sqrt(var), places=12)
        self.assertAlmostEqual(math.sqrt(r["lo"] * r["hi"]), r["rr"], places=12)


class Survival(unittest.TestCase):
    def test_kaplan_meier_6mp(self):
        # 6-MP arm of Freireich et al. (1963); values as printed by R survfit(conf.type = "log-log").
        times = [6, 6, 6, 6, 7, 9, 10, 10, 11, 13, 16, 17, 19, 20, 22, 23, 25, 32, 32, 34, 35]
        events = [1, 1, 1, 0, 1, 0, 1, 0, 0, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0, 0, 0]
        expect = [  # time, n_risk, events, surv, se, lo, hi
            (6, 21, 3, 0.8571, 0.0764, 0.6197, 0.9516),
            (7, 17, 1, 0.8067, 0.0869, 0.5631, 0.9228),
            (10, 15, 1, 0.7529, 0.0963, 0.5032, 0.8894),
            (13, 12, 1, 0.6902, 0.1068, 0.4316, 0.8491),
            (16, 11, 1, 0.6275, 0.1141, 0.3675, 0.8049),
            (22, 7, 1, 0.5378, 0.1282, 0.2678, 0.7468),
            (23, 6, 1, 0.4482, 0.1346, 0.1881, 0.6801),
        ]
        rows = sl.kaplan_meier(times, events)
        self.assertEqual(len(rows), len(expect))
        for row, (t, n, d, s, se, lo, hi) in zip(rows, expect):
            self.assertEqual((row["time"], row["n_risk"], row["events"]), (t, n, d))
            for key, v in (("surv", s), ("se", se), ("lo", lo), ("hi", hi)):
                self.assertAlmostEqual(row[key], v, places=4)

    def test_kaplan_meier_to_zero(self):
        rows = sl.kaplan_meier([1, 2, 3], [1, 0, 1])
        self.assertAlmostEqual(rows[0]["surv"], 2 / 3)
        self.assertEqual(rows[-1]["surv"], 0.0)
        self.assertIsNone(rows[-1]["lo"])


class TableMarker(unittest.TestCase):
    def test_planted_player_is_clear_and_table_player_is_not(self):
        rng = random.Random(9)
        games = []
        for g in range(60):
            seats = {"hi": rng.gauss(1, 1), "even": rng.gauss(0, 1), "x": rng.gauss(0, 1)}
            seats[f"guest-{g}"] = rng.gauss(0, 1)  # guests count at the table but never get many games
            games.append(seats)
        out = sl.within_game_sd_marker(games)
        self.assertTrue(out["hi"]["clear"])
        self.assertGreater(out["hi"]["lo"], 0)
        self.assertAlmostEqual(out["hi"]["delta"], 1.0, delta=0.3)
        self.assertLess(out["hi"]["lo"], out["hi"]["delta"])
        self.assertAlmostEqual(out["hi"]["lo"], out["hi"]["d_lo"] / out["hi"]["s_x"])  # lo, hi in SD units
        self.assertFalse(out["even"]["clear"])
        self.assertLess(out["even"]["lo"], 0)
        self.assertGreater(out["even"]["hi"], 0)
        self.assertFalse(out["guest-0"]["clear"])  # one game, below the guard
        self.assertEqual(out["hi"]["games"], 60)

    def test_hand_example(self):
        # Two games of three: d for "a" is 3 - 1 = 2 and 4 - 2 = 2; s_X^2 = sum of squared centered values / (2 + 2).
        games = [{"a": 3, "b": 1, "c": 1}, {"a": 4, "b": 2, "c": 2}]
        out = sl.within_game_sd_marker(games, min_games=0)
        ss = 2 * ((3 - 5 / 3) ** 2 + 2 * (1 - 5 / 3) ** 2)
        s_x = math.sqrt(ss / 4)
        self.assertAlmostEqual(out["a"]["mean_d"], 2.0)
        self.assertAlmostEqual(out["a"]["delta"], 2.0 / s_x)
        self.assertAlmostEqual(out["b"]["mean_d"], -1.0)
        self.assertTrue(out["a"]["clear"])  # sd of d is 0 here, so the interval is the point 2


if __name__ == "__main__":
    unittest.main()
