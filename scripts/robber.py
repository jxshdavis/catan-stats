"""Robber model, relationship network, overpunishment and trade and rob (spec 1.2, 1.5, 1.8, 2E;
Phase 5 and Phase 7 items 6, 7 and 9).

Everything here reads data/replay_events.json (decoder v2). Seats in the logs are 1-based; ev["seats"][s - 1]
is the player id in seat s. Guests and bots never get a row, but they stay in every choice set.

Shared robber model (spec 2E), fit once on all games and cached by a data hash in .cache/robber-<hash>.json:
  Stage 1, hex choice. One stratum per land robber move (pirate moves are left out and only counted). The
    alternatives are the legal hexes the decoder lists (land including the desert, not fog, not the robber's
    current hex). Income of seat j on hex h = dots(h) * m_j(h) in pips (settlement 1, city 2 per corner).
    Opponents O = every seat but the mover; the leader set L = opponents at the maximum public VP (ties all
    count). Features, all per candidate hex:
      x1 lead_inc   income of leaders            x2 other_inc  income of non-leader opponents
      x3 own_inc    the mover's own income       x4 n_steal    opponents with a building and >= 1 card
      x5 max_hand   largest stealable hand       x5' log_hand  sum of log(1 + hand) over stealable opponents
      x0 empty_inc  income of empty-handed opponents
      x2v gap_inc   sum over non-leaders of income * (leader VP - their VP)
      x6 retal      touches an opponent who stole from the mover in the last n_g rolls
    7s and knights are fit separately (Josh, Q10): two independent conditional logits, so every coefficient,
    including the own-income one that the spec's x7 = x3 * knight would have carried, differs by cause.
  Stage 2, victim choice. One stratum per land move with at least 2 eligible victims on the chosen hex;
    features: public VP minus the opponents' maximum, hand size, and "stole from the mover in the last n_g
    rolls". Also fit separately for 7s and knights.
  E is always computed with leave-one-mover-out coefficients: for each regular, the model is refit without that
  player's moves and their moves are predicted from that fit; all guest and bot moves form one left-out group.

The trade partner preference model, the partner discount and its sensitivity rows, the cards ledger, the
three-part pair balance with a null band, grudge terms, roller premium, board contention and the early
excess win model are described on their functions.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path

from openskill.models import PlackettLuce

import statlib

KEY = "robber"
MODEL_VERSION = 4  # bump to invalidate the cache when the model or features change
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"

S1_BASE = ["lead_inc", "other_inc", "own_inc", "n_steal", "max_hand", "log_hand", "empty_inc", "gap_inc", "retal"]
S1_LABELS = {
    "lead_inc": "Leader's income on the hex (per pip)",
    "other_inc": "Another opponent's income (per pip)",
    "own_inc": "Own income on the hex (per pip)",
    "n_steal": "Opponents with cards to steal (each)",
    "max_hand": "Largest stealable hand (per card)",
    "log_hand": "Sum of log(1 + hand) over stealable opponents",
    "empty_inc": "Income of empty-handed opponents (per pip)",
    "gap_inc": "Non-leader income times VP behind the leader (per pip-VP)",
    "retal": "Touches someone who robbed the mover in the last round",
    "partner_inc": "Recent trade partner's income (extra, per pip)",
    "other_x_partner": "Other opponents' income when a partner exists (extra, per pip)",
}
S2_FEATS = ["vp_gap", "hand", "retal"]
S2_LABELS = {"vp_gap": "Public VP relative to the leading opponent (per VP)", "hand": "Hand size (per card)",
             "retal": "Robbed the mover in the last round"}
CAUSES = ("seven", "knight")
SIGMA_GRID = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.5, 2.0]
EDGE_COLOR, EDGE_GREY = 10, 5  # shared games for a colored edge, and for a grey edge with counts only
INFLUENCE = 0.40  # flag an edge when one game supplies more than this share of O
TERMS_MIN_TRADES, TERMS_MIN_GAMES = 20, 10
EARLY_MIN_GAMES = 40

_STATE = {}  # per-event predictions from compute_all, reused by compute_view (never written to stats.json)


def r2(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(x, 2)


def r3(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(x, 3)


def r4(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(x, 4)


# ---------------------------------------------------------------------------
# Conditional logit with an optional ridge penalty (one choice per stratum)
# ---------------------------------------------------------------------------

def _sparse(strata):
    """Each alternative as (indices, values) of its nonzero features, so one-hot designs stay cheap."""
    out = []
    for X, c in strata:
        alts = []
        for x in X:
            idx = [j for j, v in enumerate(x) if v]
            alts.append((idx, [float(x[j]) for j in idx]))
        nz = sorted({j for idx, _ in alts for j in idx})
        out.append((alts, c, nz))
    return out


def _clogit_eval(prep, beta, ridge):
    """Penalized log-likelihood, gradient and negative Hessian. prep: _sparse(strata).
    l = sum_s [x_c.b - log sum_k exp(x_k.b)] - sum_j ridge_j b_j^2 / 2;
    -H = sum_s [sum_k p_k x_k x_k' - m m'] + diag(ridge), m = sum_k p_k x_k."""
    k = len(beta)
    ll = 0.0
    g = [0.0] * k
    H = [[0.0] * k for _ in range(k)]
    for alts, c, nz in prep:
        eta = [sum(beta[j] * v for j, v in zip(idx, vals)) for idx, vals in alts]
        top = max(eta)
        e = [math.exp(v - top) for v in eta]
        tot = sum(e)
        ll += eta[c] - top - math.log(tot)
        m = {}
        for (idx, vals), ea in zip(alts, e):
            pa = ea / tot
            if pa < 1e-15:
                continue
            for a_, (r, vr) in enumerate(zip(idx, vals)):
                m[r] = m.get(r, 0.0) + pa * vr
                w = pa * vr
                Hr = H[r]
                for s_, vs in zip(idx[:a_ + 1], vals[:a_ + 1]):
                    Hr[s_] += w * vs
        for j, v in zip(*alts[c]):
            g[j] += v
        for r in nz:
            mr = m.get(r, 0.0)
            if not mr:
                continue
            g[r] -= mr
            Hr = H[r]
            for s_ in nz:
                if s_ > r:
                    break
                ms = m.get(s_, 0.0)
                if ms:
                    Hr[s_] -= mr * ms
    # Indices within an alternative are increasing, so only H[r][s] with s <= r was filled.
    for r in range(k):
        for s_ in range(r):
            H[s_][r] = H[r][s_]
    if ridge:
        for j, lam in enumerate(ridge):
            if lam:
                ll -= 0.5 * lam * beta[j] ** 2
                g[j] -= lam * beta[j]
                H[j][j] += lam
    return ll, g, H


def clogit(strata, k, ridge=None, start=None, max_iter=60, tol=1e-8):
    """Newton-Raphson with step halving for the (ridge-penalized) conditional logit. Returns beta, se, cov
    (inverse of the penalized negative Hessian), loglik (penalized when ridge is given), the unpenalized
    loglik, the negative Hessian and the number of strata. Strata with a single alternative are dropped."""
    strata = [s for s in strata if len(s[0]) >= 2]
    if not strata:
        return None
    # A feature that never varies within a stratum is not identified; it stays at 0 (SE None) unless penalized.
    free = [j for j in range(k) if (ridge and ridge[j]) or any(len({x[j] for x in X}) > 1 for X, _ in strata)]
    beta = list(start) if start else [0.0] * k
    for j in range(k):
        if j not in free:
            beta[j] = 0.0
    prep = _sparse(strata)
    ll, g, H = _clogit_eval(prep, beta, ridge)
    ok = False
    for _ in range(max_iter):
        Hf = [[H[r][s] for s in free] for r in free]
        try:
            sub = statlib.solve(Hf, [g[r] for r in free])
        except ValueError:
            # Near-separation (a coefficient running off to infinity): damp with a tiny ridge for this step.
            try:
                sub = statlib.solve([[v + (1e-4 if i == j else 0.0) for j, v in enumerate(row)] for i, row in enumerate(Hf)],
                                    [g[r] for r in free])
            except ValueError:
                break
        step = [0.0] * k
        for j, v in zip(free, sub):
            step[j] = v
        big = max(abs(v) for v in step)
        if big > 5:
            step = [v * 5 / big for v in step]
        t = 1.0
        while True:
            trial = [b + t * v for b, v in zip(beta, step)]
            res = _clogit_eval(prep, trial, ridge)
            if res[0] >= ll - 1e-10 * (1 + abs(ll)):
                break
            t /= 2
            if t < 1e-8:
                res = None
                break
        if res is None:
            ok = max(abs(v) for v in g) < 1e-5
            break
        beta = trial
        ll, g, H = res
        if max(abs(t * v) for v in step) < tol:
            ok = True
            break
    try:
        cf = statlib.inverse([[H[r][s] + (0.0 if ok else 1e-8) for s in free] for r in free])
        cov = [[0.0] * k for _ in range(k)]
        for a, r in enumerate(free):
            for b, s_ in enumerate(free):
                cov[r][s_] = cf[a][b]
        se = [math.sqrt(cov[j][j]) if j in free and cov[j][j] > 0 else None for j in range(k)]
    except ValueError:
        cov, se = None, [None] * k
    pen = 0.5 * sum(lam * b * b for lam, b in zip(ridge, beta)) if ridge else 0.0
    return {"beta": beta, "se": se, "cov": cov, "loglik": ll, "loglik_raw": ll + pen, "H": H,
            "converged": ok, "n": len(strata)}


def softmax(eta):
    top = max(eta)
    e = [math.exp(v - top) for v in eta]
    t = sum(e)
    return [v / t for v in e]


def dot(b, x):
    return sum(u * v for u, v in zip(b, x))


# ---------------------------------------------------------------------------
# Intervals for ratios and linear combinations
# ---------------------------------------------------------------------------

def lincomb(beta, cov, w):
    """Estimate and SE of w'beta."""
    est = dot(w, beta)
    var = sum(w[i] * w[j] * cov[i][j] for i in range(len(w)) for j in range(len(w)) if w[i] and w[j])
    return est, math.sqrt(max(var, 0.0))


def fieller(beta, cov, wn, wd, level=statlib.LEVEL):
    """Ratio R = (wn'b) / (wd'b) with its Fieller interval: the set of R with
    (n - R d)^2 <= z^2 (Vnn - 2 R Vnd + R^2 Vdd). None ends when the denominator is not clearly away from 0."""
    z = statlib.z_for(level)
    n, _ = lincomb(beta, cov, wn)
    d, _ = lincomb(beta, cov, wd)
    k = len(beta)
    q = lambda a, b: sum(a[i] * b[j] * cov[i][j] for i in range(k) for j in range(k) if a[i] and b[j])
    vnn, vdd, vnd = q(wn, wn), q(wd, wd), q(wn, wd)
    est = n / d if d else None
    A = d * d - z * z * vdd
    B = -2 * (n * d - z * z * vnd)
    C = n * n - z * z * vnn
    disc = B * B - 4 * A * C
    if A <= 0 or disc < 0:
        return est, None, None
    lo = (-B - math.sqrt(disc)) / (2 * A)
    hi = (-B + math.sqrt(disc)) / (2 * A)
    return est, lo, hi


def shrink_set(items, level=statlib.LEVEL):
    """Normal-normal shrinkage of log((O + 0.5) / (E + 0.5)) over a set of units (statlib.shrink_ratio, REML tau^2).
    items: {key: (O, E)}. Returns ({key: {...}}, meta) with the shrunk ratio exp(theta) and exp(theta +- z sd), where
    sd^2 = B se^2 + (1 - B)^2 se_mu^2 also carries the uncertainty in the group mean.
    The Q gate is open when Cochran's Q rejects homogeneity at 1 - level."""
    keys = [k for k, (O, E) in items.items() if E is not None]
    if not keys:
        return {}, None
    ys, ses = zip(*(statlib.shrink_ratio(*items[k]) for k in keys))
    z = statlib.z_for(level)
    if len(keys) >= 2:
        re = statlib.reml_tau2(list(ys), list(ses))
        tau2, mu, se_mu = re["tau2"], re["mu"], re["se_mu"]
        meta = {"tau2": r4(tau2), "mu": r4(mu), "group_ratio": r3(math.exp(mu)), "Q": r3(re["Q"]), "df": re["df"],
                "p": r4(re["p"]), "gate_open": re["p"] is not None and re["p"] < 1 - level, "k": len(keys)}
    else:
        tau2, mu, se_mu = 1e6, ys[0], 0.0
        meta = {"tau2": None, "mu": r4(mu), "group_ratio": r3(math.exp(mu)), "Q": None, "df": 0, "p": None,
                "gate_open": False, "k": 1}
    out = {}
    for k, y, s, (th, sd) in zip(keys, ys, ses, statlib.shrink(list(ys), list(ses), tau2, mu)):
        # Add the uncertainty in mu (Morris 1983): Var = B s^2 + (1 - B)^2 se_mu^2, B = tau^2 / (tau^2 + s^2).
        Bk = tau2 / (tau2 + s * s)
        sd = math.sqrt(sd * sd + (1 - Bk) ** 2 * se_mu ** 2)
        O, E = items[k]
        out[k] = {"O": O, "E": r2(E), "ratio": r3((O + 0.5) / (E + 0.5)), "raw_lo": r3(math.exp(y - z * s)),
                  "raw_hi": r3(math.exp(y + z * s)), "shrunk": r3(math.exp(th)), "lo": r3(math.exp(th - z * sd)),
                  "hi": r3(math.exp(th + z * sd))}
    return out, meta


# ---------------------------------------------------------------------------
# Event extraction
# ---------------------------------------------------------------------------

def is_anon_default(pid):
    return isinstance(pid, str) and (pid.startswith("guest-") or pid.startswith("bot-"))


def _vp_at(vp_events, n):
    """Function action_index -> public VP per seat just before that action (from vp_events.board_vp)."""
    idx = [r["action_index"] for r in vp_events]
    vals = [r["board_vp"] for r in vp_events]

    def at(a):
        lo, hi = 0, len(idx)
        while lo < hi:
            mid = (lo + hi) // 2
            if idx[mid] < a:
                lo = mid + 1
            else:
                hi = mid
        return vals[lo - 1] if lo > 0 else [0] * n
    return at


def game_events(gid, ev, is_anon=is_anon_default, game=None):
    """Everything the models need from one game: land robber moves (with candidate incomes and windows),
    player trades, and per-seat totals. n_g is the seat count from the replay."""
    seats = ev["seats"]
    n = len(seats)
    steals = [(r["action_index"], r["roll_index"], r["mover"], r["victim"]) for r in ev["robber_events"]
              if r["victim"] is not None]
    trades = [t for t in ev["trade_events"] if t.get("partner")]
    pid = lambda s: seats[s - 1]
    grp = lambda s: "other" if is_anon(pid(s)) else pid(s)
    moves = []
    for r in ev["robber_events"]:
        if r["pirate"]:
            continue
        a, ri, ai = r["mover"], r["roll_index"], r["action_index"]
        opp = [s for s in range(1, n + 1) if s != a]
        pv, hand = r["public_vp"], r["hand"]
        vmax = max(pv[s - 1] for s in opp)
        lead = {s for s in opp if pv[s - 1] == vmax}
        robbed_me = {m for (a2, r2_, m, v) in steals if v == a and a2 < ai and r2_ > ri - n}
        recent, own_turn, their_turn, lag_any, sofar = set(), set(), set(), set(), defaultdict(int)
        for t in trades:
            if t["action_index"] >= ai or a not in (t["seat"], t["partner"]):
                continue
            j = t["partner"] if t["seat"] == a else t["seat"]
            sofar[j] += 1
            if t["roll_index"] > ri - 2 * n:
                recent.add(j)
                (own_turn if t["seat"] == a else their_turn).add(j)
            elif t["roll_index"] > ri - 4 * n:
                lag_any.add(j)
        cands = [(c["dots"], c["m"]) for c in r["candidates"]]
        chosen = next(i for i, c in enumerate(r["candidates"]) if c["hex"] == r["hex"])
        moves.append({
            "gid": gid, "n": n, "mover": a, "mover_pid": pid(a), "group": grp(a), "cause": r["cause"],
            "ri": ri, "ai": ai, "pv": pv, "hand": hand, "opp": opp, "lead": lead, "vmax": vmax,
            "robbed_me": robbed_me, "recent": recent - lead, "own_turn": own_turn - lead,
            "their_turn": their_turn - lead, "lag": (lag_any - recent) - lead,
            "sofar": {j: k for j, k in sofar.items() if j not in lead},
            "cands": cands, "chosen": chosen, "victim": r["victim"], "eligible": r["eligible"],
        })
    final = {}
    for row in ev["states"]:
        final.update(row)
    vp_at = _vp_at(ev.get("vp_events") or [], n)
    tr = []
    for t in trades:
        tr.append({"ai": t["action_index"], "ri": t["roll_index"], "seat": t["seat"], "partner": t["partner"],
                   "give": t["give"], "get": t["get"], "hands": t["hands"], "pv": vp_at(t["action_index"])})
    return {"gid": gid, "n": n, "seats": seats, "rolls": len(ev["roll_log"]), "moves": moves, "trades": tr,
            "steals": steals, "final": final, "robber_events": ev["robber_events"],
            "monopoly": ev.get("monopoly_events") or [], "picks": ev.get("opening_picks") or [],
            "vp_events": ev.get("vp_events") or [], "game": game}


# ---------------------------------------------------------------------------
# Design matrices
# ---------------------------------------------------------------------------

def stealable(mv, m):
    return [j for j in mv["opp"] if m[j - 1] > 0 and mv["hand"][j - 1] > 0]


def s1_row(mv, dots, m, variant="base", noret=False, movers4=()):
    """Stage 1 features of one candidate hex for one move. variant adds the partner terms."""
    inc = [dots * mj for mj in m]
    a, lead, pv, hand = mv["mover"], mv["lead"], mv["pv"], mv["hand"]
    x1 = x2 = x0 = gap = 0.0
    for j in mv["opp"]:
        v = inc[j - 1]
        if not v:
            continue
        if j in lead:
            x1 += v
        else:
            x2 += v
            gap += v * (mv["vmax"] - pv[j - 1])
        if hand[j - 1] == 0:
            x0 += v
    st = stealable(mv, m)
    row = [x1, x2, inc[a - 1], float(len(st)), float(max((hand[j - 1] for j in st), default=0)),
           sum(math.log1p(hand[j - 1]) for j in st), x0, gap,
           0.0 if noret else float(any(m[j - 1] > 0 for j in mv["robbed_me"]))]
    if variant == "base":
        return row
    if variant == "partner":
        p = sum(inc[j - 1] for j in mv["recent"])
        return row + [p, x2 if mv["recent"] else 0.0]
    if variant == "lag":
        p = sum(inc[j - 1] for j in mv["lag"])
        return row + [p, x2 if mv["lag"] else 0.0]
    if variant == "turn":
        return row + [sum(inc[j - 1] for j in mv["own_turn"]), sum(inc[j - 1] for j in mv["their_turn"]),
                      x2 if mv["recent"] else 0.0]
    if variant == "sofar":
        p = sum(inc[j - 1] * k for j, k in mv["sofar"].items())
        return row + [p, x2 if mv["sofar"] else 0.0]
    if variant == "mover":
        p = sum(inc[j - 1] for j in mv["recent"])
        idx = movers4.index(mv["mover_pid"]) if mv["mover_pid"] in movers4 else len(movers4)
        extra = [0.0] * (len(movers4) + 1)
        extra[idx] = p
        return row + extra + [x2 if mv["recent"] else 0.0]
    raise ValueError(variant)


def s1_stratum(mv, variant="base", noret=False, movers4=()):
    return [s1_row(mv, d, m, variant, noret, movers4) for d, m in mv["cands"]], mv["chosen"]


def s2_row(mv, j, noret=False):
    return [float(mv["pv"][j - 1] - mv["vmax"]), float(mv["hand"][j - 1]),
            0.0 if noret else float(j in mv["robbed_me"])]


def s2_stratum(mv):
    el = mv["eligible"]
    if len(el) < 2 or mv["victim"] is None:
        return None
    return [s2_row(mv, j) for j in el], el.index(mv["victim"])


# ---------------------------------------------------------------------------
# Fitting the shared robber model (with leave-one-mover-out refits)
# ---------------------------------------------------------------------------

def _fit_pack(fit):
    if fit is None:
        return None
    return {"beta": fit["beta"], "se": fit["se"], "cov": fit["cov"], "loglik": fit["loglik"], "n": fit["n"],
            "converged": fit["converged"]}


def fit_with_lomo(moves, build, k):
    """Full fit plus one refit per mover group with that group's moves left out (warm-started at the full fit)."""
    strata = [(build(mv), mv["group"]) for mv in moves]
    strata = [(s, g) for s, g in strata if s is not None]
    full = clogit([s for s, _ in strata], k)
    lomo = {}
    for g in sorted({g for _, g in strata}):
        sub = [s for s, gg in strata if gg != g]
        f = clogit(sub, k, start=full["beta"]) if sub else None
        lomo[g] = f["beta"] if f else full["beta"]
    return {"full": _fit_pack(full), "lomo": lomo}


def fit_models(moves, fast=False):
    """All fits that need caching: Stage 1 and 2 by cause with LOMO, and the partner model variants."""
    out = {"stage1": {}, "stage2": {}, "partner": {}}
    for cause in CAUSES:
        mv = [m for m in moves if m["cause"] == cause]
        out["stage1"][cause] = fit_with_lomo(mv, lambda m: s1_stratum(m), len(S1_BASE))
        out["stage2"][cause] = fit_with_lomo(mv, s2_stratum, len(S2_FEATS))
    sev = [m for m in moves if m["cause"] == "seven"]
    kn = [m for m in moves if m["cause"] == "knight"]
    k0 = len(S1_BASE)
    start = lambda extra: out["stage1"]["seven"]["full"]["beta"] + [0.0] * extra
    counts = defaultdict(int)
    for m in moves:
        if m["group"] != "other":
            counts[m["group"]] += 1
    movers4 = tuple(sorted(counts, key=lambda p: -counts[p])[:4])
    P = out["partner"]
    P["main"] = _fit_pack(clogit([s1_stratum(m, "partner") for m in sev], k0 + 2, start=start(2)))
    P["four_plus"] = _fit_pack(clogit([s1_stratum(m, "partner") for m in sev if m["n"] >= 4], k0 + 2, start=start(2)))
    P["turn"] = _fit_pack(clogit([s1_stratum(m, "turn") for m in sev], k0 + 3, start=start(3)))
    P["lag"] = _fit_pack(clogit([s1_stratum(m, "lag") for m in sev], k0 + 2, start=start(2)))
    P["sofar"] = _fit_pack(clogit([s1_stratum(m, "sofar") for m in sev], k0 + 2, start=start(2)))
    P["mover"] = _fit_pack(clogit([s1_stratum(m, "mover", movers4=movers4) for m in sev], k0 + len(movers4) + 2,
                                  start=start(len(movers4) + 2)))
    P["movers4"] = list(movers4)
    kstart = out["stage1"]["knight"]["full"]["beta"] + [0.0, 0.0]
    P["knight"] = _fit_pack(clogit([s1_stratum(m, "partner") for m in kn], k0 + 2, start=kstart))
    return out


# ---------------------------------------------------------------------------
# Predictions per move
# ---------------------------------------------------------------------------

def predict_move(mv, b1, b2, noret=False):
    """Stage 1 hex probabilities, P(chosen hex touches j), and P(victim = j) = sum_h P1(h) P2(j | stealable(h)),
    where P2 is 1 for a single stealable opponent and the Stage 2 softmax over two or more."""
    rows = [s1_row(mv, d, m, noret=noret) for d, m in mv["cands"]]
    p1 = softmax([dot(b1, x) for x in rows])
    n = mv["n"]
    touch = [0.0] * n
    vic = [0.0] * n
    w2 = {j: math.exp(dot(b2, s2_row(mv, j, noret))) for j in mv["opp"]}
    for p, (d, m) in zip(p1, mv["cands"]):
        for j in mv["opp"]:
            if m[j - 1] > 0:
                touch[j - 1] += p
        st = stealable(mv, m)
        if st:
            tot = sum(w2[j] for j in st)
            for j in st:
                vic[j - 1] += p * w2[j] / tot
    p2 = None
    if len(mv["eligible"]) >= 2:
        tot = sum(w2[j] for j in mv["eligible"])
        p2 = {j: w2[j] / tot for j in mv["eligible"]}
    return {"touch": touch, "victim": vic, "p2": p2, "p1": p1}


def predict_all(moves, fits):
    """LOMO predictions (full and with the retaliation terms set to 0) for every land move."""
    out = []
    for mv in moves:
        f1 = fits["stage1"][mv["cause"]]
        f2 = fits["stage2"][mv["cause"]]
        b1 = f1["lomo"].get(mv["group"], f1["full"]["beta"])
        b2 = f2["lomo"].get(mv["group"], f2["full"]["beta"]) if f2["full"] else [0.0] * len(S2_FEATS)
        full = predict_move(mv, b1, b2)
        nor = predict_move(mv, b1, b2, noret=True)
        out.append({"touch": full["touch"], "victim": full["victim"], "p2": full["p2"],
                    "victim_noret": nor["victim"]})
    return out


# ---------------------------------------------------------------------------
# Group results: coefficients, leader tax, partner discount
# ---------------------------------------------------------------------------

def coef_table(fit, names, labels, level=statlib.LEVEL):
    z = statlib.z_for(level)
    rows = []
    for j, name in enumerate(names):
        b, se = fit["beta"][j], fit["se"][j]
        rows.append({"key": name, "label": labels.get(name, name), "b": r4(b), "se": r4(se),
                     "or": r3(math.exp(b)), "lo": r4(b - z * se) if se else None, "hi": r4(b + z * se) if se else None})
    return rows


def leader_block(moves, fits):
    """Leader tax: Stage 1 leader premium, the Stage 2 VP coefficient, and the base rate of placements that touch
    a public-VP leader against a uniform choice over the legal hexes."""
    hit = unif = 0.0
    for mv in moves:
        L = mv["lead"]
        tl = [any(m[j - 1] > 0 for j in L) for _, m in mv["cands"]]
        hit += tl[mv["chosen"]]
        unif += sum(tl) / len(tl)
    out = {"base_rate": r3(hit / len(moves)) if moves else None, "uniform_rate": r3(unif / len(moves)) if moves else None,
           "moves": len(moves)}
    for cause in CAUSES:
        f1 = fits["stage1"][cause]["full"]
        k = len(S1_BASE)
        e1 = [0.0] * k
        e2 = [0.0] * k
        e1[0], e2[1] = 1.0, 1.0
        ratio, lo, hi = fieller(f1["beta"], f1["cov"], e1, e2)
        f2 = fits["stage2"][cause]["full"]
        z = statlib.z_for()
        vp = None
        if f2:
            b, se = f2["beta"][0], f2["se"][0]
            vp = {"b": r4(b), "se": r4(se), "or": r3(math.exp(b)), "or_lo": r3(math.exp(b - z * se)),
                  "or_hi": r3(math.exp(b + z * se)), "n": f2["n"]}
        b1, se1 = f1["beta"][0], f1["se"][0]
        out[cause] = {"premium": r3(ratio), "premium_lo": r3(lo), "premium_hi": r3(hi),
                      "or5_lead": r3(math.exp(5 * b1)), "or5_lead_lo": r3(math.exp(5 * (b1 - z * se1))),
                      "or5_lead_hi": r3(math.exp(5 * (b1 + z * se1))), "stage2_vp": vp, "n": f1["n"]}
    return out


def partner_rho(fit, j8, j9=None, k=None):
    """rho = (b2 + b9 + b8) / (b2 + b9): partner income against the same income of another trailing opponent in
    the same move (both carry the event-level b9 shift). Fieller interval."""
    k = len(fit["beta"])
    wd = [0.0] * k
    wd[1] = 1.0
    if j9 is not None:
        wd[j9] = 1.0
    wn = list(wd)
    wn[j8] += 1.0
    est, lo, hi = fieller(fit["beta"], fit["cov"], wn, wd)
    return {"rho": r3(est), "lo": r3(lo), "hi": r3(hi), "b8": r4(fit["beta"][j8]), "se8": r4(fit["se"][j8]),
            "n": fit["n"]}


def partner_block(moves, fits):
    P = fits["partner"]
    k0 = len(S1_BASE)
    sev = [m for m in moves if m["cause"] == "seven"]
    main = P["main"]
    head = partner_rho(main, k0, k0 + 1)
    z = statlib.z_for()
    bars = []
    for label, w in (("Leader", {0: 1}), ("Other opponent", {1: 1, k0 + 1: 1}),
                     ("Recent partner", {1: 1, k0 + 1: 1, k0: 1})):
        vec = [float(w.get(i, 0)) for i in range(len(main["beta"]))]
        est, se = lincomb(main["beta"], main["cov"], vec)
        bars.append({"label": label, "w": r4(est), "lo": r4(est - z * se), "hi": r4(est + z * se)})
    rows = [{"key": "main", "name": "Headline (7s)", **head}]
    rows.append({"key": "four_plus", "name": "4 or more seats", **partner_rho(P["four_plus"], k0, k0 + 1)})
    t = P["turn"]
    rows.append({"key": "turn_own", "name": "Own-turn trades", **partner_rho(t, k0, k0 + 2)})
    rows.append({"key": "turn_their", "name": "Partner's-turn trades", **partner_rho(t, k0 + 1, k0 + 2)})
    rows.append({"key": "lag", "name": "Lag placebo, 2 to 4 rounds back", **partner_rho(P["lag"], k0, k0 + 1)})
    rows.append({"key": "sofar", "name": "Per trade so far", **partner_rho(P["sofar"], k0, k0 + 1)})
    mv4 = P["movers4"]
    for i, pid in enumerate(mv4):
        rows.append({"key": f"mover_{pid}", "pid": pid, "name": "Mover-specific weight",
                     **partner_rho(P["mover"], k0 + i, k0 + len(mv4) + 1)})
    rows.append({"key": "mover_other", "name": "Other movers",
                 **partner_rho(P["mover"], k0 + len(mv4), k0 + len(mv4) + 1)})
    if P.get("knight"):
        rows.append({"key": "knight", "name": "Knights (own fit)", **partner_rho(P["knight"], k0, k0 + 1)})
    lag = rows[4]
    just = lag["lo"] is not None and lag["hi"] is not None and lag["lo"] <= 1 <= lag["hi"]
    with_partner = sum(1 for m in sev if m["recent"])
    informative = sum(1 for m in sev if m["recent"] and any(
        any(mm[j - 1] > 0 for j in m["recent"]) for _, mm in m["cands"]))
    return {**head, "bars": bars, "sensitivity": rows, "caption": "just" if just else "trade",
            "moves_with_partner": with_partner, "informative": informative, "moves": len(sev),
            "coef": coef_table(main, S1_BASE + ["partner_inc", "other_x_partner"], S1_LABELS)}


# ---------------------------------------------------------------------------
# Trade partner preference model (spec 1.2) with grudge terms (1.8)
# ---------------------------------------------------------------------------

def trade_strata(G, is_anon, regulars):
    """One stratum per player trade: roller a picks a partner from seats with >= 1 card just before the trade
    (plus the actual partner). Features: responder identity (regulars; guests and bots pooled as the reference
    "other"), log(1 + hand), q is a public-VP leader among a's opponents, q stole from a in the last 2 rounds,
    a stole from q in the last 2 rounds, and one indicator per regular pair {a, q} (the random effect u)."""
    reg_idx = {p: i for i, p in enumerate(regulars)}
    pairs = []
    pair_idx = {}
    raw = []
    for g in G:
        seats, n = g["seats"], g["n"]
        for t in g["trades"]:
            a = t["seat"]
            hands, pv = t["hands"], t["pv"]
            opp = [s for s in range(1, n + 1) if s != a]
            vmax = max(pv[s - 1] for s in opp)
            cs = [s for s in opp if hands[s - 1] >= 1 or s == t["partner"]]
            if len(cs) < 2:
                continue
            ra = seats[a - 1]
            alts = []
            for q in cs:
                rq = seats[q - 1]
                robbed_me = any(v == a and m == q and ai < t["ai"] and ri > t["ri"] - 2 * n for ai, ri, m, v in g["steals"])
                i_robbed = any(v == q and m == a and ai < t["ai"] and ri > t["ri"] - 2 * n for ai, ri, m, v in g["steals"])
                pk = None
                if not is_anon(ra) and not is_anon(rq):
                    key = tuple(sorted((ra, rq)))
                    if key not in pair_idx:
                        pair_idx[key] = len(pairs)
                        pairs.append(key)
                    pk = pair_idx[key]
                alts.append((q, None if is_anon(rq) else reg_idx[rq], math.log1p(hands[q - 1]),
                             float(pv[q - 1] == vmax), float(robbed_me), float(i_robbed), pk))
            raw.append({"gid": g["gid"], "a": a, "ra": ra, "alts": alts,
                        "chosen": [x[0] for x in alts].index(t["partner"])})
    R, K = len(regulars), len(pairs)
    k = R + 4 + K
    strata = []
    for s in raw:
        X = []
        for q, ri_, lh, lead, rm, ir, pk in s["alts"]:
            x = [0.0] * k
            if ri_ is not None:
                x[ri_] = 1.0
            x[R], x[R + 1], x[R + 2], x[R + 3] = lh, lead, rm, ir
            if pk is not None:
                x[R + 4 + pk] = 1.0
            X.append(x)
        strata.append((X, s["chosen"]))
    return strata, raw, pairs, k


def trade_model(G, is_anon, regulars, level=statlib.LEVEL):
    """Fit P_t(q) ~ exp(pi_q + g1 log(1 + h_tq) + g2 L_tq + d1 robbed_me + d2 i_robbed + u_{a q}) by penalized
    Newton, u ~ N(0, sigma_u^2) on regular pairs only, for each sigma_u on a grid, and pick sigma_u by the Laplace
    marginal likelihood  l(theta^, u^) - |u^|^2 / (2 sigma^2) - 0.5 log|sigma^2 I_uu + 1|, with theta profiled
    out (the u block of the penalized negative Hessian at the joint mode)."""
    strata, raw, pairs, k = trade_strata(G, is_anon, regulars)
    if len(strata) < 30:
        return None
    R, K = len(regulars), len(pairs)
    grid, best, prev = [], None, None
    for sig in SIGMA_GRID:
        # A negligible ridge (prior SD about 30) on the popularity terms keeps them identified when no guest or
        # bot is ever a candidate (then only their differences are); u gets the N(0, sigma^2) penalty.
        ridge = [1e-3] * R + [0.0] * 4 + [(1 / sig ** 2 if sig > 0 else 1e6)] * K
        f = clogit(strata, k, ridge=ridge, start=prev)
        prev = f["beta"]
        Iuu = [[f["H"][R + 4 + i][R + 4 + j] - (ridge[R + 4 + i] if i == j else 0.0) for j in range(K)] for i in range(K)]
        if sig > 0:
            M = [[sig * sig * Iuu[i][j] + (1.0 if i == j else 0.0) for j in range(K)] for i in range(K)]
            u2 = sum(f["beta"][R + 4 + i] ** 2 for i in range(K))
            lml = f["loglik_raw"] - u2 / (2 * sig * sig) - 0.5 * statlib.logdet(M)
        else:
            lml = f["loglik_raw"]
        grid.append({"sigma": sig, "lml": r3(lml)})
        if best is None or lml > best[0]:
            best = (lml, sig, f)
    _, sig, f = best
    z = statlib.z_for(level)
    beta, cov = f["beta"], f["cov"]
    sd = lambda j: math.sqrt(cov[j][j]) if cov and cov[j][j] > 0 else None
    term = lambda j: {"b": r4(beta[j]), "se": r4(sd(j)), "or": r3(math.exp(beta[j])),
                      "or_lo": r3(math.exp(beta[j] - z * sd(j))) if sd(j) else None,
                      "or_hi": r3(math.exp(beta[j] + z * sd(j))) if sd(j) else None}
    # Expected trades per pair with u = 0, and observed.
    E = defaultdict(float)
    for s, (X, c) in zip(raw, strata):
        eta = [dot(beta[:R + 4], x[:R + 4]) for x in X]
        p = softmax(eta)
        for pr, alt in zip(p, s["alts"]):
            if alt[6] is not None:
                E[pairs[alt[6]]] += pr
    u = {}
    for i, key in enumerate(pairs):
        j = R + 4 + i
        s_ = sd(j)
        u["|".join(key)] = {"u": r4(beta[j]), "exp_u": r3(math.exp(beta[j])), "lo": r3(math.exp(beta[j] - z * s_)) if s_ else None,
                            "hi": r3(math.exp(beta[j] + z * s_)) if s_ else None, "E": r2(E[key])}
    pi_vals = beta[:R]
    pi_mean = sum(pi_vals) / R if R else 0
    return {"sigma_u": sig, "grid": grid, "n_trades": len(strata),
            "pi": {p: {"b": r4(beta[i]), "centered": r4(beta[i] - pi_mean), "se": r4(sd(i))} for i, p in enumerate(regulars)},
            "hand": term(R), "leader": term(R + 1), "robbed_me": term(R + 2), "i_robbed": term(R + 3), "u": u,
            "theta": [r4(b) for b in beta[:R + 4]], "regulars": list(regulars)}


def trade_E(G, is_anon, model):
    """Expected trades per regular pair (u = 0) in a set of games, using a fitted model's theta."""
    regs = model["regulars"]
    strata, raw, pairs, k = trade_strata(G, is_anon, regs)
    R = len(regs)
    theta = model["theta"]
    E = defaultdict(float)
    for s, (X, c) in zip(raw, strata):
        p = softmax([dot(theta, x[:R + 4]) for x in X])
        for pr, alt in zip(p, s["alts"]):
            if alt[6] is not None:
                E["|".join(pairs[alt[6]])] += pr
    return E


# ---------------------------------------------------------------------------
# Pre-game mu (spec 2D) and the early excess win model (1.5, Phase 7 item 9)
# ---------------------------------------------------------------------------

def pre_game_mu(games, is_anon, is_bot, ranks_of):
    """Pre-game mu for every seat from one chronological openskill pass over all games (Plackett-Luce over the
    finishing order; guests at the prior every game; bots left out of the update and given the prior). Only a
    skill covariate here; the leaderboard ranks by wins above expected."""
    model = PlackettLuce()
    ratings, out = {}, {}
    for g in games:
        ranks = ranks_of(g)
        order = [r["player"] for r in g["players"] if not is_bot(r["player"])]
        cur = {p: model.rating() if is_anon(p) else ratings.get(p, model.rating()) for p in order}
        out[g["id"]] = {p: cur[p].mu for p in order}
        new = model.rate([[cur[p]] for p in order], ranks=[ranks[p] for p in order])
        for p, t in zip(order, new):
            if not is_anon(p):
                ratings[p] = t[0]
    return out


def early_cut(G_ev):
    """action_index at which any seat's public VP first reaches ceil(target / 2) (or the end)."""
    g = G_ev["game"]
    target = (g.get("settings") or {}).get("vp_to_win") or max(r["vp"] for r in g["players"] if r.get("vp") is not None)
    half = math.ceil(target / 2)
    for r in G_ev["vp_events"]:
        if max(r["board_vp"]) >= half:
            return r["action_index"]
    return math.inf


def early_excess_rows(G, preds_by_move, mu, replays):
    """Per game: seats with x = early excess steals sum_e (1[victim = i] - P^(-mover)(victim = i)) over land moves
    before the cut, pre-game mu, and opening dots minus the table mean."""
    data = []
    for g in G:
        game = g["game"]
        rp = (replays.get(g["gid"]) or {}).get("players") or {}
        if not all(p in rp for p in g["seats"]):
            continue
        cut = early_cut(g)
        x = [0.0] * g["n"]
        for mv in g["moves"]:
            if mv["ai"] >= cut:
                continue
            pr = preds_by_move[id(mv)]
            for j in range(g["n"]):
                x[j] += (1.0 if mv["victim"] == j + 1 else 0.0) - pr["victim"][j]
        dots = [rp[p]["opening_dots"] for p in g["seats"]]
        md = sum(dots) / len(dots)
        mus = [mu.get(g["gid"], {}).get(p, 25.0) for p in g["seats"]]
        data.append({"gid": g["gid"], "X": [[x[j], mus[j], dots[j] - md] for j in range(g["n"])],
                     "y": [1 if p == game["winner"] else 0 for p in g["seats"]]})
    return data


def early_excess_model(data, level=statlib.LEVEL):
    """Conditional logit (Firth) for the winner: gamma on early excess steals, plus pre-game mu and centered
    opening dots. Reported as the OR per card with its profile penalized-likelihood interval."""
    strata = [{"X": d["X"], "y": d["y"]} for d in data]
    fit = statlib.cond_logit(strata, firth=True)
    lo, hi = statlib.profile_ci(strata, 0, level=level, firth=True, fit=fit)
    g = fit["beta"][0]
    return {"gamma": r4(g), "se": r4(fit["se"][0]), "lo": r4(lo), "hi": r4(hi), "or": r3(math.exp(g)),
            "or_lo": r3(math.exp(lo)), "or_hi": r3(math.exp(hi)), "b_mu": r4(fit["beta"][1]), "b_dots": r4(fit["beta"][2]),
            "games": len(strata)}


# ---------------------------------------------------------------------------
# Board contention at setup (Phase 7 item 7)
# ---------------------------------------------------------------------------

def corner_hexes(c):
    """Hexes [x, y] touching corner [x, y, z]: sum 1 -> subtract 1 from one coordinate; sum 2 -> from two."""
    x, y, z = c
    if x + y + z == 1:
        cand = [(x - 1, y, z), (x, y - 1, z), (x, y, z - 1)]
    else:
        cand = [(x - 1, y - 1, z), (x - 1, y, z - 1), (x, y - 1, z - 1)]
    return [(a, b) for a, b, _ in cand]


def hex_dots(G_ev):
    """Dots per land hex, from every robber move's candidate list (the robber's start hex appears once moved)."""
    d = {}
    for r in G_ev["robber_events"]:
        for c in r.get("candidates") or []:
            d[tuple(c["hex"])] = c["dots"]
    return d


def contention(G_ev):
    """C_ab = sum_h min(w_a(h), w_b(h)) at the first roll, w_q(h) = sum over q's setup settlements touching h of
    dots / 36 (no cities exist yet). Returned in dots (36 C) per seat pair, plus how many seats' opening pips
    the hex map reproduces (a check on the corner geometry)."""
    dots = hex_dots(G_ev)
    n = G_ev["n"]
    w = [defaultdict(float) for _ in range(n)]
    ok = 0
    for p in G_ev["picks"]:
        hs = corner_hexes(p["corner"])
        if sum(dots.get(h, 0) for h in hs) == p["pips"]:
            ok += 1
        for h in hs:
            w[p["seat"] - 1][h] += dots.get(h, 0)
    C = {}
    for a in range(n):
        for b in range(a + 1, n):
            C[(a + 1, b + 1)] = sum(min(w[a][h], w[b].get(h, 0)) for h in w[a])
    return C, ok, len(G_ev["picks"])


# ---------------------------------------------------------------------------
# Per-view summaries
# ---------------------------------------------------------------------------

def pair_key(a, b):
    return "|".join(sorted((a, b)))


def influence(per_game):
    tot = sum(per_game.values())
    return bool(tot and max(per_game.values()) / tot > INFLUENCE)


def summarize_view(G, preds, all_res, ctx, B, trade_fit=None, seed=31):
    """Everything per view: pair tiers, trade edges, directed robber O/E (Stage 1, Stage 2, combined steals),
    per-player targeting, cards lost, the cards ledger, pair balance with a null band, partner hit ratios,
    pirate counts, roller premium, pair terms of trade and setup contention."""
    is_anon = ctx["is_anon"]
    regs = [p for p in ctx["pids"] if any(p in g["seats"] for g in G)]
    level = statlib.LEVEL
    z = statlib.z_for(level)
    games_of = defaultdict(int)
    for g in G:
        for p in set(g["seats"]):
            if not is_anon(p):
                games_of[p] += 1
    # ---- pairs: shared games and rolls
    pairs = {}
    for g in G:
        rp = [p for p in g["seats"] if not is_anon(p)]
        for i, a in enumerate(rp):
            for b in rp[i + 1:]:
                k = pair_key(a, b)
                pr = pairs.setdefault(k, {"games": 0, "rolls": 0})
                pr["games"] += 1
                pr["rolls"] += g["rolls"]
    for k, pr in pairs.items():
        pr["tier"] = "color" if pr["games"] >= EDGE_COLOR else "grey" if pr["games"] >= EDGE_GREY else "hidden"
    # ---- trades between pairs
    trade_O = defaultdict(lambda: defaultdict(int))
    for g in G:
        for t in g["trades"]:
            a, b = g["seats"][t["seat"] - 1], g["seats"][t["partner"] - 1]
            if not is_anon(a) and not is_anon(b):
                trade_O[pair_key(a, b)][g["gid"]] += 1
    tm = trade_fit or all_res.get("trade_model")
    tE = trade_E(G, is_anon, tm) if tm else {}
    for k, pr in pairs.items():
        O = sum(trade_O[k].values())
        u = (tm or {}).get("u", {}).get(k) if tm else None
        pr["trade"] = {"O": O, "E": r2(tE.get(k)), "per100": r2(100 * O / pr["rolls"]) if pr["rolls"] else None,
                       "exp_u": u["exp_u"] if u else None, "lo": u["lo"] if u else None, "hi": u["hi"] if u else None,
                       "influence": influence(trade_O[k]) if O else False}
    # ---- directed robber O/E (land moves; LOMO E)
    st1 = defaultdict(lambda: [0, 0.0])
    st2 = defaultdict(lambda: [0, 0.0])
    stc = defaultdict(lambda: [0, 0.0])
    stc_game = defaultdict(lambda: defaultdict(int))
    tgt = defaultdict(lambda: {"O": 0, "E": 0.0, "Eu": 0.0, "Ou": 0, "pO": 0, "pE": 0.0, "Enr": 0.0})
    nr = defaultdict(float)
    full_E = defaultdict(float)
    sim_events = []
    for g in G:
        for mv in g["moves"]:
            pr = preds[id(mv)]
            a = g["seats"][mv["mover"] - 1]
            d_ch, m_ch = mv["cands"][mv["chosen"]]
            el = mv["eligible"]
            for j in mv["opp"]:
                b = g["seats"][j - 1]
                touched = m_ch[j - 1] > 0
                stole = mv["victim"] == j
                if not is_anon(b):
                    t = tgt[b]
                    t["O"] += stole
                    t["E"] += pr["victim"][j - 1]
                    t["pO"] += touched
                    t["pE"] += pr["touch"][j - 1]
                    if el and j in el:
                        t["Eu"] += 1 / len(el)
                if is_anon(a) or is_anon(b):
                    continue
                key = f"{a}>{b}"
                st1[key][0] += touched
                st1[key][1] += pr["touch"][j - 1]
                if pr["p2"] is not None and j in pr["p2"]:
                    st2[key][0] += stole
                    st2[key][1] += pr["p2"][j]
                stc[key][0] += stole
                stc[key][1] += pr["victim"][j - 1]
                if stole:
                    stc_game[key][g["gid"]] += 1
                nr[key] += pr["victim_noret"][j - 1]
                full_E[key] += pr["victim"][j - 1]
            sim_events.append((g["seats"], mv, pr))
    colored = {k for k, pr in pairs.items() if pr["tier"] == "color"}
    dir_keys = [f"{a}>{b}" for k in colored for a, b in (k.split("|"), k.split("|")[::-1])]
    shr, shr_meta = shrink_set({k: tuple(stc[k]) for k in dir_keys if k in stc})
    s1s, s1_meta = shrink_set({k: tuple(st1[k]) for k in dir_keys if k in st1})
    s2s, s2_meta = shrink_set({k: tuple(st2[k]) for k in dir_keys if k in st2 and st2[k][1] > 0})
    directed = {}
    for key in set(stc) | set(st1):
        a, b = key.split(">")
        tier = pairs.get(pair_key(a, b), {}).get("tier", "hidden")
        if tier == "hidden":
            continue
        rolls = pairs[pair_key(a, b)]["rolls"]
        d = {"tier": tier, "O": stc[key][0], "E": r2(stc[key][1]), "per100": r2(100 * stc[key][0] / rolls) if rolls else None,
             "stage1": {"O": st1[key][0], "E": r2(st1[key][1])}, "stage2": {"O": st2[key][0], "E": r2(st2[key][1])},
             "influence": influence(stc_game[key]) if stc[key][0] else False}
        if key in shr:
            d.update({k2: shr[key][k2] for k2 in ("ratio", "shrunk", "lo", "hi")})
        if key in s1s:
            d["stage1"].update({k2: s1s[key][k2] for k2 in ("ratio", "shrunk", "lo", "hi")})
        if key in s2s:
            d["stage2"].update({k2: s2s[key][k2] for k2 in ("ratio", "shrunk", "lo", "hi")})
        directed[key] = d
    # ---- per-player targeting (combined steals) with shrinkage across players with enough games
    rows_ok = [p for p in regs if games_of[p] >= statlib.GUARDS["player_rows"]]
    tshr, tmeta = shrink_set({p: (tgt[p]["O"], tgt[p]["E"]) for p in rows_ok})
    ushr, _ = shrink_set({p: (tgt[p]["O"], tgt[p]["Eu"]) for p in rows_ok})
    targeting = {}
    for p in rows_ok:
        t = tgt[p]
        targeting[p] = {**tshr[p], "games": games_of[p], "o_minus_e": r2(t["O"] - t["E"]),
                        "even": {"E": r2(t["Eu"]), "ratio": r3((t["O"] + 0.5) / (t["Eu"] + 0.5)),
                                 "shrunk": ushr[p]["shrunk"]},
                        "place": {"O": t["pO"], "E": r2(t["pE"]), "ratio": r3((t["pO"] + 0.5) / (t["pE"] + 0.5))}}
    # ---- pair balance: three exact parts and a null band from redraws of the fitted model
    balance = {}
    rng = random.Random(seed)
    for k in sorted(colored):
        a, b = k.split("|")
        ab, ba = f"{a}>{b}", f"{b}>{a}"
        O_ab, O_ba = stc[ab][0], stc[ba][0]
        part_pos = nr[ab] - nr[ba]
        part_ret = (full_E[ab] - nr[ab]) - (full_E[ba] - nr[ba])
        part_beyond = (O_ab - full_E[ab]) - (O_ba - full_E[ba])
        probs = []
        for seats, mv, pr in sim_events:
            mover = seats[mv["mover"] - 1]
            if mover == a and b in seats:
                probs.append((1, pr["victim"][seats.index(b)]))
            elif mover == b and a in seats:
                probs.append((-1, pr["victim"][seats.index(a)]))
        sims = []
        for _ in range(B):
            s = sum(sg for sg, p in probs if rng.random() < p)
            sims.append(s - (full_E[ab] - full_E[ba]))
        lo, hi = statlib.percentile_ci(sims, level)
        balance[k] = {"a": a, "b": b, "O_ab": O_ab, "O_ba": O_ba, "net": O_ab - O_ba, "position": r2(part_pos),
                      "retaliation": r2(part_ret), "beyond": r2(part_beyond), "band": [r2(lo), r2(hi)], "B": B}
    # ---- cards ledger and cards lost relative to the table
    ledger = defaultdict(lambda: [0, 0, 0])
    lost = defaultdict(lambda: {"stolen": [], "blocked": [], "monopoly": []})
    pirate = {"moves": 0, "steals": 0, "by_player": defaultdict(lambda: {"moves": 0, "stolen_from": 0})}
    for g in G:
        seats, n, fin = g["seats"], g["n"], g["final"]
        for r in g["robber_events"]:
            a = seats[r["mover"] - 1]
            if r["victim"] is not None:
                b = seats[r["victim"] - 1]
                if not is_anon(a) and not is_anon(b):
                    ledger[f"{a}>{b}"][0] += 1
            if r["pirate"]:
                pirate["moves"] += 1
                if not is_anon(a):
                    pirate["by_player"][a]["moves"] += 1
                if r["victim"] is not None:
                    pirate["steals"] += 1
                    vb = seats[r["victim"] - 1]
                    if not is_anon(vb):
                        pirate["by_player"][vb]["stolen_from"] += 1
        bb, mon = fin.get("blocked_by") or [[0] * n] * n, fin.get("monopoly_lost_to") or [[0] * n] * n
        for i in range(n):
            for t in range(n):
                if i == t:
                    continue
                a, b = seats[t], seats[i]
                if not is_anon(a) and not is_anon(b):
                    ledger[f"{a}>{b}"][1] += bb[i][t]
                    ledger[f"{a}>{b}"][2] += mon[i][t]
        xs = {"stolen": list(fin.get("stolen_from") or [0] * n),
              "blocked": [sum(bb[i][t] for t in range(n) if t != i) for i in range(n)],
              "monopoly": [sum(mon[i][t] for t in range(n) if t != i) for i in range(n)]}
        for c, vals in xs.items():
            m = sum(vals) / n
            for i, p in enumerate(seats):
                if not is_anon(p):
                    lost[p][c].append(vals[i] - m)
    ledger_out = {}
    for key, (s, bl, mo) in ledger.items():
        a, b = key.split(">")
        pr = pairs.get(pair_key(a, b))
        if not pr or pr["tier"] == "hidden" or not pr["rolls"]:
            continue
        f = 100 / pr["rolls"]
        ledger_out[key] = {"steals": s, "blocked": bl, "monopoly": mo, "per100": [r2(s * f), r2(bl * f), r2(mo * f)],
                           "total100": r2((s + bl + mo) * f)}
    cards_lost = {}
    for p in rows_ok:
        row = {"games": games_of[p]}
        for c in ("stolen", "blocked", "monopoly"):
            m, lo, hi = statlib.t_interval(lost[p][c], level)
            row[c] = {"mean": r2(m), "lo": r2(lo), "hi": r2(hi)}
        cards_lost[p] = row
    # ---- per-player partner hit ratio (gated): moves with a recent non-leader partner on some legal hex
    ph = defaultdict(lambda: {"O": 0, "E": 0.0, "n": 0, "games": set()})
    for g in G:
        for mv in g["moves"]:
            if mv["cause"] != "seven" or not mv["recent"]:
                continue
            a = g["seats"][mv["mover"] - 1]
            if is_anon(a):
                continue
            touchP = [any(m[j - 1] > 0 for j in mv["recent"]) for _, m in mv["cands"]]
            if not any(touchP) or all(touchP):
                continue
            p1 = preds[id(mv)]["p1_base"]
            h = ph[a]
            h["O"] += touchP[mv["chosen"]]
            h["E"] += sum(p for p, t in zip(p1, touchP) if t)
            h["n"] += 1
            h["games"].add(g["gid"])
    ph_ok = {p: (h["O"], h["E"]) for p, h in ph.items() if games_of[p] >= statlib.GUARDS["player_rows"] and h["n"] >= 20}
    phs, ph_meta = shrink_set(ph_ok)
    partner_hit = {p: {**phs[p], "placements": ph[p]["n"], "games": games_of[p]} for p in phs}
    partner_hit_small = {p: {"placements": h["n"], "games": games_of[p]} for p, h in ph.items()
                         if p not in phs and not is_anon(p)}
    # ---- roller premium and pair terms of trade
    premium, terms = roller_terms(G, is_anon, regs, games_of, B, seed + 1)
    # ---- setup contention
    cont = defaultdict(list)
    geo_ok = geo_n = 0
    for g in G:
        C, ok, nn = contention(g)
        geo_ok += ok
        geo_n += nn
        for (s1, s2), v in C.items():
            a, b = g["seats"][s1 - 1], g["seats"][s2 - 1]
            if not is_anon(a) and not is_anon(b):
                cont[pair_key(a, b)].append(v)
    for k, pr in pairs.items():
        if k in cont and pr["tier"] != "hidden":
            m, lo, hi = statlib.t_interval(cont[k], level)
            pr["contention"] = {"mean": r2(m), "lo": r2(lo), "hi": r2(hi)}
        if k in balance:
            pr["balance"] = balance[k]
        if k in terms:
            pr["terms"] = terms[k]
    pairs = {k: v for k, v in pairs.items() if v["tier"] != "hidden"}
    pim = (tm or {}).get("pi") or {}
    return {
        "games": len(G), "players": regs, "games_of": dict(games_of),
        "pairs": pairs, "directed": directed,
        "directed_meta": {"steals": shr_meta, "stage1": s1_meta, "stage2": s2_meta},
        "targeting": targeting, "targeting_meta": tmeta,
        "cards_lost": cards_lost, "ledger": ledger_out,
        "pirate": {"moves": pirate["moves"], "steals": pirate["steals"],
                   "by_player": {p: v for p, v in pirate["by_player"].items() if p in regs}},
        "partner_hit": partner_hit, "partner_hit_meta": ph_meta, "partner_hit_small": partner_hit_small,
        "premium": premium, "nodes": {p: {"pi": pim.get(p, {}).get("centered"), "games": games_of[p]} for p in regs},
        "contention_check": {"picks_matched": geo_ok, "picks": geo_n},
        "land_moves": sum(len(g["moves"]) for g in G),
        "trades": sum(len(g["trades"]) for g in G),
    }


def roller_terms(G, is_anon, regs, games_of, B, seed):
    """Roller premium P_a = sum G / sum R over player trades a made as roller (G = cards a gave, R = cards a got),
    against the field (every other roller's trades in the same games' pool, a left out); and pair terms of trade
    rho_{a|b} = (G/R with b) / (G/R with anyone else), shown only when each direction of the pair has at least 20
    roller trades over at least 10 shared games. 95% game-cluster bootstrap intervals."""
    per_game = []  # per game: {(roller, partner): [cards given, cards received, trades]}
    for g in G:
        agg = defaultdict(lambda: [0, 0, 0])
        for t in g["trades"]:
            a, b = g["seats"][t["seat"] - 1], g["seats"][t["partner"] - 1]
            x = agg[(a, b)]
            x[0] += sum(t["give"])
            x[1] += sum(t["get"])
            x[2] += 1
        per_game.append(dict(agg))

    def prem(sample, p):
        Gp = Rp = Gf = Rf = 0
        for rows in sample:
            for (a, b), (gv, gt, _) in rows.items():
                if a == p:
                    Gp += gv
                    Rp += gt
                else:
                    Gf += gv
                    Rf += gt
        if not Rp or not Rf or not Gf:
            return None
        return (Gp / Rp) / (Gf / Rf)

    def tot(sample, a, b):
        Gw = Rw = Go = Ro = 0
        for rows in sample:
            for (x, y), (gv, gt, _) in rows.items():
                if x != a:
                    continue
                if y == b:
                    Gw += gv
                    Rw += gt
                else:
                    Go += gv
                    Ro += gt
        if not Rw or not Ro or not Go:
            return None
        return (Gw / Rw) / (Go / Ro)

    premium = {}
    for p in regs:
        if games_of[p] < statlib.GUARDS["player_rows"]:
            continue
        n_tr = sum(v[2] for rows in per_game for (a, _), v in rows.items() if a == p)
        Gp = sum(v[0] for rows in per_game for (a, _), v in rows.items() if a == p)
        Rp = sum(v[1] for rows in per_game for (a, _), v in rows.items() if a == p)
        est = prem(per_game, p)
        if est is None:
            continue
        boot = statlib.cluster_bootstrap(per_game, lambda s: prem(s, p), B=B, seed=seed)
        lo, hi = statlib.percentile_ci(boot)
        premium[p] = {"P": r3(Gp / Rp) if Rp else None, "ratio": r3(est), "lo": r3(lo), "hi": r3(hi),
                      "trades": n_tr, "given": Gp, "received": Rp}
    field_G = sum(v[0] for rows in per_game for v in rows.values())
    field_R = sum(v[1] for rows in per_game for v in rows.values())
    premium["_field"] = {"P": r3(field_G / field_R) if field_R else None,
                         "trades": sum(v[2] for rows in per_game for v in rows.values())}
    terms = {}
    cnt = defaultdict(int)
    shared = defaultdict(set)
    flow = defaultdict(lambda: [0] * 5)
    for g in G:
        for t in g["trades"]:
            a, b = g["seats"][t["seat"] - 1], g["seats"][t["partner"] - 1]
            cnt[(a, b)] += 1
            shared[pair_key(a, b)].add(g["gid"])
            for i in range(5):
                flow[(a, b)][i] += t["give"][i]
                flow[(b, a)][i] += t["get"][i]
    for i, a in enumerate(regs):
        for b in regs[i + 1:]:
            k = pair_key(a, b)
            if is_anon(a) or is_anon(b):
                continue
            entry = {"n_ab": cnt[(a, b)], "n_ba": cnt[(b, a)], "flow_ab": flow[(a, b)], "flow_ba": flow[(b, a)]}
            if (cnt[(a, b)] >= TERMS_MIN_TRADES and cnt[(b, a)] >= TERMS_MIN_TRADES
                    and len(shared[k]) >= TERMS_MIN_GAMES):
                for x, y, tag in ((a, b, "ab"), (b, a, "ba")):
                    est = tot(per_game, x, y)
                    boot = statlib.cluster_bootstrap(per_game, lambda s: tot(s, x, y), B=B, seed=seed + 7)
                    lo, hi = statlib.percentile_ci(boot)
                    entry[tag] = {"rho": r3(est), "lo": r3(lo), "hi": r3(hi)}
            if sum(flow[(a, b)]) or sum(flow[(b, a)]):
                terms[k] = entry
    return premium, terms


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def _hash(games, events):
    h = hashlib.sha256()
    h.update(f"v{MODEL_VERSION}".encode())
    h.update(json.dumps([(g["id"], g["winner"], (g.get("settings") or {}).get("vp_to_win")) for g in games]).encode())
    for gid in sorted(events):
        ev = events[gid]
        h.update(json.dumps([ev["seats"], ev["robber_events"], ev["trade_events"]], sort_keys=True).encode())
    return h.hexdigest()[:16]


def _load_or_fit(games, events, moves, fast):
    key = _hash(games, events) + ("-fast" if fast else "")
    path = CACHE / f"{KEY}-{key}.json"
    if not fast and path.exists():
        try:
            return json.loads(path.read_text()), True
        except (OSError, json.JSONDecodeError):
            pass
    fits = fit_models(moves, fast)
    if not fast:
        CACHE.mkdir(exist_ok=True)
        path.write_text(json.dumps(fits))
    return fits, False


# ---------------------------------------------------------------------------
# Module entry points
# ---------------------------------------------------------------------------

def _prepare(games, events, ctx):
    is_anon = ctx.get("is_anon", is_anon_default)
    G = []
    for g in games:
        ev = events.get(g["id"])
        if ev and ev.get("decoder_version", 2) >= 2 and "robber_events" in ev:
            G.append(game_events(g["id"], ev, is_anon, game=g))
    return G


def compute_all(games, replays, events, ctx):
    if not events:
        return None
    t0 = time.time()
    fast = bool(ctx.get("fast"))
    is_anon = ctx.get("is_anon", is_anon_default)
    G = _prepare(games, events, ctx)
    moves = [mv for g in G for mv in g["moves"]]
    if len(moves) < 50:
        return None
    fits, hit = _load_or_fit(games, events, moves, fast)
    preds = {}
    for mv, pr in zip(moves, predict_all(moves, fits)):
        f1 = fits["stage1"][mv["cause"]]
        b1 = f1["lomo"].get(mv["group"], f1["full"]["beta"])
        pr["p1_base"] = softmax([dot(b1, s1_row(mv, d, m)) for d, m in mv["cands"]])
        preds[id(mv)] = pr
    regulars = [p for p in ctx["pids"] if any(p in g["seats"] for g in G)]
    tm = trade_model(G, is_anon, regulars)
    res = {
        "version": MODEL_VERSION,
        "source": "all games",
        "counts": {"games": len(G), "land_moves": len(moves),
                   "sevens": sum(1 for m in moves if m["cause"] == "seven"),
                   "knights": sum(1 for m in moves if m["cause"] == "knight"),
                   "stage2": sum(1 for m in moves if len(m["eligible"]) >= 2),
                   "pirate_moves": sum(1 for g in G for r in g["robber_events"] if r["pirate"]),
                   "player_trades": sum(len(g["trades"]) for g in G)},
        "stage1": {c: {"coef": coef_table(fits["stage1"][c]["full"], S1_BASE, S1_LABELS), "n": fits["stage1"][c]["full"]["n"],
                       "loglik": r3(fits["stage1"][c]["full"]["loglik"])} for c in CAUSES},
        "stage2": {c: ({"coef": coef_table(fits["stage2"][c]["full"], S2_FEATS, S2_LABELS), "n": fits["stage2"][c]["full"]["n"]}
                       if fits["stage2"][c]["full"] else None) for c in CAUSES},
        "lomo_groups": sorted(fits["stage1"]["seven"]["lomo"]),
        "leader": leader_block([m for m in moves if m["cause"] == "seven"], fits),
        "leader_knight_base": leader_block([m for m in moves if m["cause"] == "knight"], fits)["moves"],
        "partner": partner_block(moves, fits),
        "trade_model": tm,
    }
    # Leader base rates over all land moves, both causes.
    lb = leader_block(moves, fits)
    res["leader"]["base_rate_all"], res["leader"]["uniform_rate_all"] = lb["base_rate"], lb["uniform_rate"]
    # Early excess (exploratory), all games.
    mu = pre_game_mu(games, is_anon, ctx.get("is_bot", lambda p: str(p).startswith("bot-")), ctx["finishing_ranks"])
    data = early_excess_rows(G, preds, mu, replays)
    res["early_excess"] = early_excess_model(data) if len(data) >= EARLY_MIN_GAMES else {"needs": EARLY_MIN_GAMES, "has": len(data)}
    _STATE.clear()
    _STATE.update({"preds": preds, "G": {g["gid"]: g for g in G}, "mu": mu, "replays": replays})
    res["build"] = {"cache_hit": hit, "seconds": round(time.time() - t0, 1)}
    return res


def compute_view(games, replays, events, ctx, all_result):
    if not all_result or not _STATE:
        return None
    t0 = time.time()
    fast = bool(ctx.get("fast"))
    B = 200 if fast else statlib.B_DESCRIPTIVE
    G = [_STATE["G"][g["id"]] for g in games if g["id"] in _STATE["G"]]
    if not G:
        return None
    is_anon = ctx.get("is_anon", is_anon_default)
    n_games = len(G)
    refit = n_games >= statlib.GUARDS["model_games"] and n_games < all_result["counts"]["games"]
    tm = None
    if refit:
        regulars = [p for p in ctx["pids"] if any(p in g["seats"] for g in G)]
        tm = trade_model(G, is_anon, regulars)
    out = summarize_view(G, _STATE["preds"], all_result, ctx, B, trade_fit=tm)
    out["trade_model"] = None if not tm else {k: tm[k] for k in ("sigma_u", "hand", "leader", "robbed_me", "i_robbed", "n_trades")}
    out["trade_source"] = "this view" if (tm or n_games == all_result["counts"]["games"]) else "all games"
    out["robber_source"] = "all games"
    if n_games >= EARLY_MIN_GAMES:
        if n_games == all_result["counts"]["games"]:
            out["early_excess"] = all_result["early_excess"]
        else:
            data = early_excess_rows(G, _STATE["preds"], _STATE["mu"], _STATE["replays"])
            out["early_excess"] = early_excess_model(data) if len(data) >= EARLY_MIN_GAMES else {"needs": EARLY_MIN_GAMES, "has": len(data)}
    else:
        out["early_excess"] = {"needs": EARLY_MIN_GAMES, "has": n_games}
    out["seconds"] = round(time.time() - t0, 1)
    return out
