"""Small statistics library for the Catan stats site (pure Python standard library).

Everything build.py needs for models and intervals: conditional logit with Breslow ties
and the Firth penalty, profile likelihood intervals, game-cluster bootstrap, REML random
effects and shrinkage, Mantel-Haenszel contrasts with the player left out, Wilson,
Kaplan-Meier, sup-t bands, within-game permutation tests and the "vs the table" marker.
Matrices are lists of lists and are small (a handful of features), so plain Gaussian
elimination is fine.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from itertools import groupby
from statistics import NormalDist

LEVEL = 0.95  # one interval level site-wide
GUARDS = {"player_rows": 10, "badges": 15, "model_games": 30, "model_events": 300}
B_DESCRIPTIVE = 2000  # bootstrap draws for descriptive intervals
B_MODEL = 500  # bootstrap draws when every draw refits a model

_NORMAL = NormalDist()
_TINY = 1e-300


# ---------------------------------------------------------------------------
# Linear algebra for small dense matrices
# ---------------------------------------------------------------------------

def _eliminate(A, B):
    """Gauss-Jordan with partial pivoting on [A | B]. Returns (X with A X = B, log|det A|, sign)."""
    n = len(A)
    m = len(B[0]) if B else 0
    M = [[float(v) for v in A[i]] + [float(v) for v in B[i]] for i in range(n)]
    scale = max((abs(v) for row in A for v in row), default=0.0)
    if scale == 0.0:
        raise ValueError("singular matrix")
    logdet, sign = 0.0, 1.0
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(M[r][c]))
        if abs(M[piv][c]) <= 1e-13 * scale:
            raise ValueError("singular matrix")
        if piv != c:
            M[c], M[piv] = M[piv], M[c]
            sign = -sign
        pv = M[c][c]
        logdet += math.log(abs(pv))
        if pv < 0:
            sign = -sign
        row = M[c]
        for j in range(c, n + m):
            row[j] /= pv
        for r in range(n):
            if r != c and M[r][c] != 0.0:
                f = M[r][c]
                Mr = M[r]
                for j in range(c, n + m):
                    Mr[j] -= f * row[j]
    return [row[n:] for row in M], logdet, sign


def solve(A, b):
    """Solve A x = b for a vector b (Gauss-Jordan, partial pivoting). Raises ValueError if A is singular."""
    X, _, _ = _eliminate(A, [[v] for v in b])
    return [r[0] for r in X]


def inverse(A):
    """Inverse of a square matrix (Gauss-Jordan, partial pivoting). Raises ValueError if A is singular."""
    n = len(A)
    X, _, _ = _eliminate(A, [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)])
    return X


def logdet(A):
    """log|det A| from the pivots of Gaussian elimination. Raises ValueError if A is singular or det < 0."""
    _, ld, sign = _eliminate(A, [[] for _ in A])
    if sign < 0:
        raise ValueError("negative determinant")
    return ld


# ---------------------------------------------------------------------------
# Distributions
# ---------------------------------------------------------------------------

def norm_cdf(x):
    """Standard normal CDF (statistics.NormalDist)."""
    return _NORMAL.cdf(x)


def norm_ppf(p):
    """Standard normal quantile (statistics.NormalDist.inv_cdf)."""
    return _NORMAL.inv_cdf(p)


def z_for(level=LEVEL):
    """Two-sided normal critical value for a central interval at `level` (1.96 at 0.95)."""
    return norm_ppf(0.5 + level / 2)


def _gamma_q(a, x):
    """Regularized upper incomplete gamma Q(a, x): series below a + 1, Lentz continued fraction above."""
    if x <= 0:
        return 1.0
    lead = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1:
        ap, term = a, 1.0 / a
        total = term
        for _ in range(10000):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-16:
                break
        return max(0.0, 1.0 - total * math.exp(lead))
    b = x + 1 - a
    c, d = 1 / _TINY, 1 / b
    h = d
    for i in range(1, 10000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = d if abs(d) > _TINY else _TINY
        c = b + an / c
        c = c if abs(c) > _TINY else _TINY
        d = 1 / d
        de = d * c
        h *= de
        if abs(de - 1) < 1e-16:
            break
    return math.exp(lead) * h


def chi2_sf(x, df):
    """Chi-square upper tail P(X > x) for any df > 0, as Q(df/2, x/2)."""
    return _gamma_q(df / 2, x / 2)


def _betacf(a, b, x):
    """Continued fraction for the incomplete beta function (modified Lentz, Numerical Recipes betacf)."""
    qab, qap, qam = a + b, a + 1, a - 1
    c, d = 1.0, 1 - qab * x / qap
    d = 1 / (d if abs(d) > _TINY else _TINY)
    h = d
    for m in range(1, 10000):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > _TINY else _TINY)
        c = 1 + aa / c
        c = c if abs(c) > _TINY else _TINY
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1 + aa * d
        d = 1 / (d if abs(d) > _TINY else _TINY)
        c = 1 + aa / c
        c = c if abs(c) > _TINY else _TINY
        de = d * c
        h *= de
        if abs(de - 1) < 1e-16:
            break
    return h


def betainc(a, b, x):
    """Regularized incomplete beta I_x(a, b) by continued fraction, using the symmetry flip for x > (a+1)/(a+b+2)."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lead = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1) / (a + b + 2):
        return math.exp(lead) * _betacf(a, b, x) / a
    return 1 - math.exp(lead) * _betacf(b, a, 1 - x) / b


def t_cdf(t, df):
    """Student t CDF via the incomplete beta: P(T > |t|) = I_{df/(df+t^2)}(df/2, 1/2) / 2."""
    tail = 0.5 * betainc(df / 2, 0.5, df / (df + t * t))
    return 1 - tail if t > 0 else tail


def t_ppf(p, df):
    """Student t quantile by bisection on t_cdf (bracket doubled from the normal quantile)."""
    if not 0 < p < 1:
        raise ValueError("p must be in (0, 1)")
    if p == 0.5:
        return 0.0
    if p < 0.5:
        return -t_ppf(1 - p, df)
    lo, hi = 0.0, max(1.0, 2 * norm_ppf(p))
    while t_cdf(hi, df) < p:
        lo, hi = hi, hi * 2
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-12 * max(1.0, hi):
            break
    return (lo + hi) / 2


# ---------------------------------------------------------------------------
# Simple intervals
# ---------------------------------------------------------------------------

def wilson(k, n, level=LEVEL):
    """Wilson score interval for k successes in n trials, as (lo, hi); None when n = 0."""
    if n == 0:
        return None
    z = z_for(level)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (0.0 if k == 0 else max(0.0, centre - half), 1.0 if k == n else min(1.0, centre + half))


def t_interval(xs, level=LEVEL):
    """Mean with a t interval: mean +- t_{n-1} sd / sqrt(n). Returns (mean, lo, hi); lo, hi are None below n = 2."""
    n = len(xs)
    if n == 0:
        return None, None, None
    m = sum(xs) / n
    if n < 2:
        return m, None, None
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    half = t_ppf(0.5 + level / 2, n - 1) * sd / math.sqrt(n)
    return m, m - half, m + half


def quantile(xs, q):
    """Sample quantile with linear interpolation between order statistics (R type 7)."""
    s = sorted(xs)
    if not s:
        return None
    h = (len(s) - 1) * q
    i = math.floor(h)
    return s[i] if i + 1 >= len(s) else s[i] + (h - i) * (s[i + 1] - s[i])


def percentile_ci(values, level=LEVEL):
    """Percentile interval (type 7 quantiles at (1-level)/2 and (1+level)/2), skipping None and NaN."""
    vals = [v for v in values if v is not None and not math.isnan(v)]
    if not vals:
        return None, None
    return quantile(vals, (1 - level) / 2), quantile(vals, (1 + level) / 2)


# ---------------------------------------------------------------------------
# Conditional logit (Breslow ties, Firth penalty) and profile intervals
# ---------------------------------------------------------------------------

def _prep(strata):
    """Validate strata and drop those that carry no information (fewer than 2 alternatives or nothing chosen)."""
    out = []
    for s in strata:
        X = [[float(v) for v in x] for x in s["X"]]
        y = [float(v) for v in s["y"]]
        if len(X) != len(y):
            raise ValueError("each stratum needs one y per row of X")
        d = sum(y)
        if len(X) >= 2 and d > 0:
            out.append((X, y, d))
    if not out:
        raise ValueError("no informative strata")
    return out


def _evaluate(prep, beta, firth):
    """Log-likelihood, penalized log-likelihood, (modified) score and Fisher information at beta.

    Breslow: l = sum_s [sum_k y_k x_k.b - d_s log sum_k exp(x_k.b)], I = sum_s d_s Cov_p(x).
    Firth score adds 0.5 tr(I^-1 dI/db_r) = 0.5 sum_s d_s sum_k p_k c_kr (c_k' I^-1 c_k), c_k = x_k - E_p x.
    """
    k = len(beta)
    ll = 0.0
    U = [0.0] * k
    I = [[0.0] * k for _ in range(k)]
    keep = []
    for X, y, d in prep:
        eta = [sum(b * v for b, v in zip(beta, x)) for x in X]
        top = max(eta)
        e = [math.exp(v - top) for v in eta]
        tot = sum(e)
        p = [v / tot for v in e]
        ll += sum(yk * ek for yk, ek in zip(y, eta)) - d * (top + math.log(tot))
        m = [sum(p[a] * X[a][r] for a in range(len(X))) for r in range(k)]
        C = [[x[r] - m[r] for r in range(k)] for x in X]
        for a, c in enumerate(C):
            ra = y[a] - d * p[a]
            wa = d * p[a]
            for r in range(k):
                U[r] += ra * c[r]
                wr = wa * c[r]
                Ir = I[r]
                for s in range(r + 1):
                    Ir[s] += wr * c[s]
        if firth:
            keep.append((d, p, C))
    for r in range(k):
        for s in range(r):
            I[s][r] = I[r][s]
    if not firth:
        return ll, ll, U, I
    Iinv = inverse(I)
    pen = 0.5 * logdet(I)
    for d, p, C in keep:
        for a, c in enumerate(C):
            q = sum(c[r] * sum(Iinv[r][s] * c[s] for s in range(k)) for r in range(k))
            f = 0.5 * d * p[a] * q
            for r in range(k):
                U[r] += f * c[r]
    return ll, ll + pen, U, I


def _newton(prep, beta, firth, free, max_iter=100, tol=1e-9, max_step=5.0):
    """Fisher-scoring ascent on the (penalized) log-likelihood over the coordinates in `free`.

    Step = I_ff^-1 U*_f, capped at max_step per coordinate and halved until l* does not drop. Because I is
    positive definite this is always an ascent direction; without Firth it is exact Newton for clogit.
    """
    beta = list(beta)
    ll, lp, U, I = _evaluate(prep, beta, firth)
    if not free:
        return beta, ll, lp, U, I, True, 0
    for it in range(1, max_iter + 1):
        try:
            step = solve([[I[r][s] for s in free] for r in free], [U[r] for r in free])
        except ValueError:
            return beta, ll, lp, U, I, False, it
        big = max(abs(v) for v in step)
        if big > max_step:
            step = [v * max_step / big for v in step]
        t = 1.0
        while True:
            trial = list(beta)
            for r, v in zip(free, step):
                trial[r] += t * v
            try:
                res = _evaluate(prep, trial, firth)
            except (ValueError, OverflowError):
                res = None
            if res is not None and res[1] >= lp - 1e-10 * (1 + abs(lp)):
                break
            t /= 2
            if t < 1e-10:
                return beta, ll, lp, U, I, max(abs(U[r]) for r in free) < 1e-6, it
        beta = trial
        ll, lp, U, I = res
        if max(abs(t * v) for v in step) < tol:
            return beta, ll, lp, U, I, True, it
    return beta, ll, lp, U, I, False, max_iter


def cond_logit(strata, firth=True, ties="breslow", start=None, max_iter=100):
    """Conditional (multinomial choice) logit stratified by group, Breslow ties, optional Firth penalty.

    strata: list of {"X": one feature vector per alternative, "y": 0/1 or counts chosen}; more than one
    chosen in a stratum is handled by the Breslow approximation. Fit: Fisher scoring with step halving on
    l*(b) = l(b) + 0.5 log|I(b)| (Firth 1993) or on l(b). SE = sqrt(diag I^-1) at the estimate.
    """
    if ties != "breslow":
        raise ValueError("only Breslow ties are implemented")
    prep = _prep(strata)
    k = len(prep[0][0][0])
    beta0 = list(start) if start is not None else [0.0] * k
    beta, ll, lp, U, I, ok, it = _newton(prep, beta0, firth, list(range(k)), max_iter=max_iter)
    try:
        cov = inverse(I)
        se = [math.sqrt(cov[r][r]) if cov[r][r] > 0 else None for r in range(k)]
    except ValueError:
        cov, se = None, [None] * k
    return {"beta": beta, "se": se, "cov": cov, "loglik": ll, "loglik_penalized": lp, "converged": ok,
            "iterations": it, "firth": firth, "n_strata": len(prep), "n_events": sum(d for _, _, d in prep)}


def cond_logit_loglik(strata, beta, firth=False):
    """(Penalized) Breslow conditional log-likelihood at a given beta, for checks and plots."""
    ll, lp, _, _ = _evaluate(_prep(strata), list(beta), firth)
    return lp if firth else ll


def profile_ci(strata, j, level=LEVEL, firth=True, fit=None, tol=1e-7):
    """Profile (penalized) likelihood interval for coefficient j.

    Solves 2 (l*max - l*prof(b_j)) = chi2_1 quantile (z^2) on each side by Illinois regula falsi, with the
    other coefficients re-maximized at each b_j (warm started). A side that never crosses within |b| < 50
    is returned as -inf or inf (possible only without Firth under separation).
    """
    prep = _prep(strata)
    if fit is None:
        fit = cond_logit(strata, firth=firth)
    k = len(fit["beta"])
    free = [r for r in range(k) if r != j]
    bhat = fit["beta"][j]
    target = fit["loglik_penalized"] - z_for(level) ** 2 / 2
    width = fit["se"][j] if fit["se"][j] else 0.5

    def g(b, start):
        beta = list(start)
        beta[j] = b
        beta, _, lp, _, _, _, _ = _newton(prep, beta, firth, free)
        return lp - target, beta

    ends = []
    for side in (-1, 1):
        start = list(fit["beta"])
        a, fa = bhat, fit["loglik_penalized"] - target
        b = bhat + side * 2 * width
        fb, start = g(b, start)
        while fb > 0:
            if abs(b) > 50:
                break
            a, fa = b, fb
            b = bhat + 2 * (b - bhat)
            fb, start = g(b, start)
        if fb > 0:
            ends.append(side * math.inf)
            continue
        for _ in range(200):
            c = b - fb * (b - a) / (fb - fa)
            fc, start = g(c, start)
            if fc * fb < 0:
                a, fa = b, fb
            else:
                fa /= 2
            b, fb = c, fc
            if abs(fc) < 1e-10 or abs(b - a) < tol:
                break
        ends.append(b)
    return ends[0], ends[1]


def exploded_strata(X, ranks, depth=None):
    """Exploded logit (Plackett-Luce) strata from one finishing order: stage t chooses place t among those left.

    X: feature vector per player; ranks: 1 = first, equal ranks are ties (Breslow), None = unranked (kept in
    every choice set, never chosen). depth limits the number of stages. Stages with fewer than 2 alternatives
    or where everyone left is chosen are skipped.
    """
    left = list(range(len(X)))
    places = sorted({r for r in ranks if r is not None})
    out = []
    for r in places:
        if depth is not None and len(out) >= depth:
            break
        chosen = {i for i in left if ranks[i] == r}
        if len(left) >= 2 and len(chosen) < len(left):
            out.append({"X": [X[i] for i in left], "y": [1 if i in chosen else 0 for i in left]})
        left = [i for i in left if i not in chosen]
    return out


# ---------------------------------------------------------------------------
# Resampling
# ---------------------------------------------------------------------------

def cluster_bootstrap(clusters, stat_fn, B=B_DESCRIPTIVE, seed=0):
    """Nonparametric cluster bootstrap: draw len(clusters) clusters (games) with replacement, B times.

    Deterministic for a given seed (random.Random(seed)). stat_fn gets the resampled list and may return
    any value, including None for a failed refit. Returns the list of B stats.
    """
    rng = random.Random(seed)
    n = len(clusters)
    return [stat_fn([clusters[rng.randrange(n)] for _ in range(n)]) for _ in range(B)]


def bca_ci(xs, stat_fn, B=B_DESCRIPTIVE, seed=0, level=LEVEL):
    """BCa bootstrap interval (Efron 1987) for stat_fn of an iid sample, as (lo, hi).

    z0 = Phi^-1(share of resamples below the estimate, ties counted half); acceleration
    a = sum (m - t_(i))^3 / (6 [sum (m - t_(i))^2]^1.5) from the jackknife; endpoints are type 7 quantiles at
    Phi(z0 + (z0 + z_q) / (1 - a (z0 + z_q))). Resamples come from random.Random(seed).
    """
    n = len(xs)
    est = stat_fn(list(xs))
    boot = cluster_bootstrap(list(xs), stat_fn, B=B, seed=seed)
    below = sum(1 for t in boot if t < est) + 0.5 * sum(1 for t in boot if t == est)
    share = min(max(below / B, 0.5 / B), 1 - 0.5 / B)
    z0 = norm_ppf(share)
    jack = [stat_fn(list(xs[:i]) + list(xs[i + 1:])) for i in range(n)] if n > 2 else []
    m = sum(jack) / len(jack) if jack else 0.0
    num = sum((m - t) ** 3 for t in jack)
    den = sum((m - t) ** 2 for t in jack)
    a = num / (6 * den ** 1.5) if den > 0 else 0.0
    ends = []
    for q in ((1 - level) / 2, (1 + level) / 2):
        zq = norm_ppf(q)
        ends.append(quantile(boot, norm_cdf(z0 + (z0 + zq) / (1 - a * (z0 + zq)))))
    return ends[0], ends[1]


def sup_t_band(boot_curves, level=LEVEL, center=None):
    """Simultaneous sup-t band from bootstrap curves (all the same length, no gaps).

    sd_t = bootstrap SD at each point; crit = level quantile over draws of max_t |c_b(t) - mean_t| / sd_t;
    band = center (default the bootstrap mean) +- crit sd_t. Points with sd_t = 0 are skipped in the max.
    """
    B = len(boot_curves)
    T = len(boot_curves[0])
    mean_t = [sum(c[t] for c in boot_curves) / B for t in range(T)]
    sd_t = [math.sqrt(sum((c[t] - mean_t[t]) ** 2 for c in boot_curves) / (B - 1)) for t in range(T)]
    devs = [max((abs(c[t] - mean_t[t]) / sd_t[t] for t in range(T) if sd_t[t] > 0), default=0.0)
            for c in boot_curves]
    crit = quantile(devs, level)
    est = list(center) if center is not None else mean_t
    return {"lo": [e - crit * s for e, s in zip(est, sd_t)], "hi": [e + crit * s for e, s in zip(est, sd_t)],
            "crit": crit, "sd": sd_t}


def perm_test(strata, stat_fn, B=10000, seed=0, alternative="greater", level=LEVEL):
    """Within-stratum permutation test: shuffle each game's indicator list (e.g. winner 1/0 per seat) independently.

    stat_fn(strata) -> float. p = (1 + #{T_b >= T_obs}) / (B + 1) for "greater" ("less" mirrors it,
    "two-sided" uses |T - null mean|). Also returns the null mean and a central `level` band of the null.
    """
    rng = random.Random(seed)
    obs = stat_fn(strata)
    work = [list(s) for s in strata]
    null = []
    for _ in range(B):
        for s in work:
            rng.shuffle(s)
        null.append(stat_fn(work))
    m = sum(null) / B
    eps = 1e-12 * (1 + abs(obs))
    if alternative == "greater":
        hits = sum(1 for t in null if t >= obs - eps)
    elif alternative == "less":
        hits = sum(1 for t in null if t <= obs + eps)
    elif alternative == "two-sided":
        hits = sum(1 for t in null if abs(t - m) >= abs(obs - m) - eps)
    else:
        raise ValueError("alternative must be greater, less or two-sided")
    lo, hi = percentile_ci(null, level)
    return {"obs": obs, "p": (1 + hits) / (B + 1), "null_mean": m, "lo": lo, "hi": hi, "B": B, "null": null}


# ---------------------------------------------------------------------------
# Random effects and shrinkage
# ---------------------------------------------------------------------------

def _reml_ll(y, v, tau2):
    """REML log-likelihood of tau^2 up to a constant: -0.5 [sum log(v+t) + log sum w + sum w (y - mu)^2]."""
    w = [1 / (vi + tau2) for vi in v]
    sw = sum(w)
    mu = sum(wi * yi for wi, yi in zip(w, y)) / sw
    return -0.5 * (sum(math.log(vi + tau2) for vi in v) + math.log(sw) + sum(wi * (yi - mu) ** 2 for wi, yi in zip(w, y)))


def reml_tau2(y, se, tol=1e-10, max_iter=500):
    """Random-effects tau^2 by REML (Fisher scoring from the DerSimonian-Laird start, step halving, truncated at 0).

    Also returns Cochran's Q (fixed-effect weights 1/se^2) with its chi2_{k-1} p-value and the random-effects
    weighted mean mu with SE = (sum 1/(se^2 + tau^2))^-1/2.
    """
    k = len(y)
    v = [s * s for s in se]
    w0 = [1 / vi for vi in v]
    sw0 = sum(w0)
    mu0 = sum(w * yi for w, yi in zip(w0, y)) / sw0
    Q = sum(w * (yi - mu0) ** 2 for w, yi in zip(w0, y))
    df = k - 1
    p = chi2_sf(Q, df) if df > 0 else None
    c = sw0 - sum(w * w for w in w0) / sw0
    tau2 = max(0.0, (Q - df) / c) if df > 0 and c > 0 else 0.0
    converged = df == 0
    for _ in range(max_iter if df > 0 else 0):
        w = [1 / (vi + tau2) for vi in v]
        sw, sw2, sw3 = sum(w), sum(x * x for x in w), sum(x ** 3 for x in w)
        mu = sum(wi * yi for wi, yi in zip(w, y)) / sw
        score = 0.5 * (sum(wi * wi * (yi - mu) ** 2 for wi, yi in zip(w, y)) - (sw - sw2 / sw))
        info = 0.5 * (sw2 - 2 * sw3 / sw + (sw2 / sw) ** 2)
        step = score / info
        base = _reml_ll(y, v, tau2)
        new = max(0.0, tau2 + step)
        while _reml_ll(y, v, new) < base - 1e-12 and abs(new - tau2) > tol:
            new = max(0.0, (new + tau2) / 2)
        done = abs(new - tau2) < tol * (1 + tau2)
        tau2 = new
        if done:
            converged = True
            break
    w = [1 / (vi + tau2) for vi in v]
    sw = sum(w)
    mu = sum(wi * yi for wi, yi in zip(w, y)) / sw
    return {"tau2": tau2, "mu": mu, "se_mu": math.sqrt(1 / sw), "Q": Q, "df": df, "p": p, "k": k,
            "converged": converged}


def shrink(y, se, tau2, mu):
    """Normal-normal shrinkage: theta_i = mu + B_i (y_i - mu), B_i = tau^2 / (tau^2 + se_i^2), sd_i = sqrt(B_i) se_i.

    Returns a list of (theta, sd) given tau^2 and mu (their own uncertainty is not propagated).
    """
    out = []
    for yi, si in zip(y, se):
        b = tau2 / (tau2 + si * si) if tau2 + si * si > 0 else 0.0
        out.append((mu + b * (yi - mu), math.sqrt(b) * si))
    return out


def shrink_ratio(O, E):
    """Log O/E with a half-count correction and its delta-method SE: (log((O+.5)/(E+.5)), 1/sqrt(O+.5)).

    Treats O as Poisson with Var(O) ~ O + 0.5 and E (a model expectation) as fixed.
    """
    return math.log((O + 0.5) / (E + 0.5)), 1 / math.sqrt(O + 0.5)


# ---------------------------------------------------------------------------
# Mantel-Haenszel contrasts against the rest of the table
# ---------------------------------------------------------------------------

def mh_risk_difference(strata, level=LEVEL):
    """Mantel-Haenszel risk difference of a player vs the rest of the table (player excluded), stratified by game.

    strata: (y_i, N_i, y_rest, N_rest) per game. RD = sum w (y_i/N_i - y_rest/N_rest) / sum w with
    w = N_i N_rest / (N_i + N_rest). Variance: Sato, Greenland and Robins (1989), valid for sparse and large
    strata. Wald interval at `level`. Games with N_i = 0 or N_rest = 0 carry no weight and are skipped.
    """
    rows = [(float(a), float(n1), float(c), float(n0)) for a, n1, c, n0 in strata if n1 > 0 and n0 > 0]
    if not rows:
        return None
    W = sum(n1 * n0 / (n1 + n0) for _, n1, _, n0 in rows)
    rd = sum(n1 * n0 / (n1 + n0) * (a / n1 - c / n0) for a, n1, c, n0 in rows) / W
    P = sum((n1 * n1 * c - n0 * n0 * a + n1 * n0 * (n0 - n1) / 2) / (n1 + n0) ** 2 for a, n1, c, n0 in rows)
    Qs = sum((a * (n0 - c) + c * (n1 - a)) / (2 * (n1 + n0)) for a, n1, c, n0 in rows)
    var = max(0.0, (rd * P + Qs) / (W * W))
    se = math.sqrt(var)
    z = z_for(level)
    return {"rd": rd, "se": se, "lo": rd - z * se, "hi": rd + z * se, "n": len(rows)}


def mh_rate_ratio(strata, level=LEVEL):
    """Mantel-Haenszel rate ratio stratified by game, with the Greenland-Robins (1985) variance of log RR.

    strata: (a, t1, b, t0) per game: player's count a over exposure t1, rest of table's count b over t0.
    For "one seat vs the other n-1 seats" pass t1 = 1, t0 = n - 1, which gives
    RR = sum a (n-1)/n / sum b / n. Var(log RR) = sum t1 t0 (a+b) / T^2 / (R S). Wald interval on the log scale.
    """
    rows = [(float(a), float(t1), float(b), float(t0)) for a, t1, b, t0 in strata if t1 > 0 and t0 > 0]
    R = sum(a * t0 / (t1 + t0) for a, t1, b, t0 in rows)
    S = sum(b * t1 / (t1 + t0) for a, t1, b, t0 in rows)
    if R <= 0 or S <= 0:
        return None
    rr = R / S
    var = sum(t1 * t0 * (a + b) / (t1 + t0) ** 2 for a, t1, b, t0 in rows) / (R * S)
    se = math.sqrt(var)
    z = z_for(level)
    return {"rr": rr, "log_se": se, "lo": rr * math.exp(-z * se), "hi": rr * math.exp(z * se), "n": len(rows)}


# ---------------------------------------------------------------------------
# Survival
# ---------------------------------------------------------------------------

def kaplan_meier(times, events, level=LEVEL):
    """Kaplan-Meier estimate with Greenwood SE and the log(-log) interval S^exp(+-z sqrt(G)/|log S|).

    events: truthy = event, falsy = censored (censored at t still count at risk at t). One row per distinct
    event time: time, n_risk, events, surv, se, lo, hi (se, lo, hi are None where undefined, e.g. S = 0).
    """
    z = z_for(level)
    data = sorted(zip(times, (1 if e else 0 for e in events)), key=lambda r: r[0])
    at_risk = len(data)
    S, gw = 1.0, 0.0
    rows = []
    for t, grp in groupby(data, key=lambda r: r[0]):
        grp = list(grp)
        d = sum(e for _, e in grp)
        if d:
            S *= 1 - d / at_risk
            gw = gw + d / (at_risk * (at_risk - d)) if at_risk > d else math.inf
            se = S * math.sqrt(gw) if math.isfinite(gw) else None
            lo = hi = None
            if 0 < S < 1 and math.isfinite(gw):
                s_ll = math.sqrt(gw) / abs(math.log(S))
                lo, hi = S ** math.exp(z * s_ll), S ** math.exp(-z * s_ll)
            rows.append({"time": t, "n_risk": at_risk, "events": d, "surv": S, "se": se, "lo": lo, "hi": hi})
        at_risk -= len(grp)
    return rows


# ---------------------------------------------------------------------------
# "vs the table" marker (spec 1.7)
# ---------------------------------------------------------------------------

def _per(x, s):
    return None if x is None or s <= 0 else x / s


def within_game_sd_marker(per_game, level=LEVEL, min_games=GUARDS["player_rows"]):
    """Within-game deviation from the rest of the table, in SD units, per player.

    per_game: list of {pid: value} with every seat (guests and bots too; None values are skipped).
    d_ig = x_ig - mean_{j != i} x_jg; delta_i = mean_g d_ig / s_X, where s_X^2 = sum (x_ig - mean_g x)^2 / sum (n_g - 1)
    is the pooled within-game variance over all player-games. t interval for mean d (df = n - 1); clear = the
    interval excludes 0 and the player has at least min_games games. Per pid: delta, lo, hi (interval in SD
    units), clear, games, t, s_x, and mean_d, d_lo, d_hi in the stat's own units.
    """
    ds = defaultdict(list)
    ss, dof = 0.0, 0
    for g in per_game:
        vals = {p: float(v) for p, v in g.items() if v is not None}
        n = len(vals)
        if n < 2:
            continue
        tot = sum(vals.values())
        m = tot / n
        for p, v in vals.items():
            ss += (v - m) ** 2
            ds[p].append(v - (tot - v) / (n - 1))
        dof += n - 1
    s_x = math.sqrt(ss / dof) if dof else 0.0
    out = {}
    for p, d in ds.items():
        n = len(d)
        md, lo, hi = t_interval(d, level)
        sd = math.sqrt(sum((x - md) ** 2 for x in d) / (n - 1)) if n > 1 else None
        t = md / (sd / math.sqrt(n)) if sd else None
        out[p] = {"delta": _per(md, s_x), "lo": _per(lo, s_x), "hi": _per(hi, s_x),
                  "clear": n >= max(2, min_games) and lo is not None and (lo > 0 or hi < 0),
                  "games": n, "t": t, "s_x": s_x, "mean_d": md, "d_lo": lo, "d_hi": hi}
    return out
