"""Luck and momentum from the per-action logs (stats proposal 1.3, 1.6, 1.9; Phase 4, Phase 7 items 4 and 5).

Per game: the production engine, cumulative game-centered dice luck with its variance, board VP after every
turn, the dev card timeline, play of the game and the go-ahead play. Pooled: the snowball test and its
mechanism, production share by game decile, game-centered luck per player, luck-adjusted wins and where
lucky cards leak.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

from openskill.models import PlackettLuce

import series
import statlib

KEY = "momentum"
CACHE = Path(__file__).resolve().parent.parent / ".cache"
W_RATE = 3  # Level | Rate window, in rounds (answer Q6)
EARLY, MID = (1, 4), (5, 8)  # luck windows in rounds (answer Q7)
SIM_BAND = 2.241  # simultaneous 95% band for a random walk observed at every step (flat band rule)
LEAK_KINDS = ("discarded", "monopoly", "shortage", "stolen")


def r2(x):
    return None if x is None else round(x, 2)


def r3(x):
    return None if x is None else round(x, 3)


def r4(x):
    return None if x is None else round(x, 4)


# ---------------------------------------------------------------------------
# One game
# ---------------------------------------------------------------------------

def game_series(ev):
    """Per seat, per roll: expected cards E (robber on), gross expected (robber off), cards owed by the
    dice before the shortage rule (A_raw) and the variance of A_raw."""
    rolls = series.at_rolls(ev)
    n = len(ev["seats"])
    E = [[series.expected_cards(r, i) for r in rolls] for i in range(n)]
    Eg = [[series.gross_expected(r, i) for r in rolls] for i in range(n)]
    V = [[series.roll_variance(r, i) for r in rolls] for i in range(n)]
    A = [[rl["a_raw"][i] for rl in ev["roll_log"]] for i in range(n)]
    return E, Eg, A, V


def window_luck(E, A, n, rounds):
    """L_i(W) = sum over rolls in rounds lo..hi (1-based, round r = rolls (r-1)n .. rn-1) of A_raw - E."""
    lo, hi = rounds
    a, b = (lo - 1) * n, (hi * n if hi is not None else len(E[0]))
    return [sum(A[i][t] - E[i][t] for t in range(a, min(b, len(E[0])))) for i in range(n)]


def turn_units(vp_events):
    """vp_events grouped into units: consecutive rows by the same actor in the same (own_turn, phase)."""
    units = []
    for k, e in enumerate(vp_events):
        key = (e.get("actor"), e.get("own_turn"), e.get("phase"))
        if units and units[-1]["key"] == key:
            units[-1]["rows"].append(k)
        else:
            units.append({"key": key, "rows": [k]})
    return units


def describe(e, seats):
    """Short labels for what one vp_events row did, naming the seat a title was taken from."""
    out = []
    for c in e.get("changes") or []:
        t = c["type"]
        if t == "longest_road_taken":
            out.append({"type": t, "from": seats[c["from"] - 1] if c.get("from") else None})
        elif t == "largest_army_taken":
            out.append({"type": t, "from": seats[c["from"] - 1] if c.get("from") else None})
        elif t == "island_bonus":
            out.append({"type": t, "vp": c.get("vp")})
        elif t in ("settlement", "city", "longest_road_lost"):
            out.append({"type": t})
    return out


def play_of_the_game(ev, winner_seat):
    """Whole-turn play of the game (answer Q17), with the best single action inside it as detail.

    M(x) = winner's board VP minus the best other seat's board VP after each vp_events row. Units are the
    winner's own turns after setup and before the start of their final turn (the unit holding the winning
    action). Swing s = M after the unit's last row minus M before its first row. Durable: M never falls back
    to M(before) or lower after the unit and before the final turn. Pick the largest durable swing; ties
    prefer a unit that crossed into the lead; 2 or 3 ties are co-plays with the earliest starred; 4 or more
    is "no single standout". Shown only if s >= 2."""
    seats = ev["seats"]
    vpe = [e for e in ev["vp_events"] if e.get("action") != "reveal"]
    w = winner_seat - 1
    M = [e["board_vp"][w] - max(v for j, v in enumerate(e["board_vp"]) if j != w) for e in vpe]
    before = lambda k: M[k - 1] if k > 0 else 0
    units = [u for u in turn_units(vpe) if u["key"][0] == winner_seat]
    if not units:
        return None
    final = units[-1]
    final_start = final["rows"][0]
    cand = []
    for u in units[:-1]:
        if u["key"][2] == "setup":
            continue
        a, b = u["rows"][0], u["rows"][-1]
        s = M[b] - before(a)
        later = M[b + 1:final_start]
        durable = all(m > before(a) for m in later)
        best_k = max(u["rows"], key=lambda k: (M[k] - before(k), -k))
        cand.append({"start": a, "end": b, "swing": s, "durable": durable, "crossed": before(a) <= 0 < M[b],
                     "roll_index": vpe[b]["roll_index"], "own_turn": u["key"][1],
                     "from": before(a), "to": M[b],
                     "actions": [{"action": vpe[k]["action"], "swing": M[k] - before(k), "what": describe(vpe[k], seats)}
                                 for k in u["rows"]],
                     "best_action": {"action": vpe[best_k]["action"], "swing": M[best_k] - before(best_k),
                                     "what": describe(vpe[best_k], seats)}})
    durable = [c for c in cand if c["durable"]]
    out = {"threshold": 2}
    given_back = [c for c in cand if not c["durable"]]
    top = max((c["swing"] for c in durable), default=None)
    if top is None or top < 2:
        out["pick"] = None
    else:
        ties = [c for c in durable if c["swing"] == top]
        crossed = [c for c in ties if c["crossed"]]
        if crossed:
            ties = crossed
        if len(ties) >= 4:
            out["pick"] = None
            out["no_standout_ties"] = len(ties)
        else:
            out["pick"] = ties[0]
            out["co_plays"] = ties[1:]
    if given_back:
        gb = max(given_back, key=lambda c: c["swing"])
        if top is None or gb["swing"] > top:
            out["given_back"] = {k: gb[k] for k in ("swing", "roll_index", "own_turn", "from", "to")}
    return out


def go_ahead(ev, winner_seat):
    """The last action that took M from <= 0 to > 0 on board VP, the final reveal of VP cards counting as
    its own pseudo-event. Class: "led" (for good before the final turn), "walk_off" (inside the final
    turn) or "reveal" (hidden VP cards decided it)."""
    vpe = ev["vp_events"]
    w = winner_seat - 1
    M = [e["board_vp"][w] - max(v for j, v in enumerate(e["board_vp"]) if j != w) for e in vpe]
    last = None
    for k in range(len(M)):
        prev = M[k - 1] if k else 0
        if prev <= 0 < M[k]:
            last = k
    if last is None:
        return None
    units = [u for u in turn_units([e for e in vpe if e.get("action") != "reveal"]) if u["key"][0] == winner_seat]
    final_start = units[-1]["rows"][0] if units else len(vpe)
    e = vpe[last]
    kind = "reveal" if e.get("action") == "reveal" else "walk_off" if last >= final_start else "led"
    return {"kind": kind, "roll_index": e["roll_index"], "action": e.get("action"),
            "gap_before": (M[last - 1] if last else 0)}


def one_game(game, ev):
    """Everything the game page draws for one game."""
    n = len(ev["seats"])
    E, Eg, A, V = game_series(ev)
    T = len(E[0])
    ends = series.at_turn_ends(ev)
    first = series.at_rolls(ev)[0]
    bvp = [series.board_vp(first)] + [series.board_vp(r) for r in ends]
    tvp = [first["vp"]] + [r["vp"] for r in ends]
    cumL, cumV = [], []
    for i in range(n):
        l = v = 0.0
        cl, cv = [], []
        for t in range(T):
            l += A[i][t] - E[i][t]
            v += V[i][t]
            cl.append(r2(l))
            cv.append(r2(v))
        cumL.append(cl)
        cumV.append(cv)
    winner_seat = ev["seats"].index(game["winner"]) + 1
    devs = [{"t": d["roll_index"], "s": d["seat"], "a": d["action"], "pre": d.get("pre_roll", False),
             **({"c": d["card"]} if d["action"] == "play" else {})} for d in ev["dev_events"]]
    return {
        "seats": ev["seats"], "n": n, "rolls": T,
        # n x expected cards per roll = expected cards per round
        "engine": [[r2(n * x) for x in E[i]] for i in range(n)],
        "engine_gross": [[r2(n * x) for x in Eg[i]] for i in range(n)],
        "luck": cumL, "luck_var": cumV, "sim_band": SIM_BAND,
        "board_vp": [[row[i] for row in bvp] for i in range(n)],
        "true_vp": [[row[i] for row in tvp] for i in range(n)],
        "dev": devs,
        "play": play_of_the_game(ev, winner_seat),
        "go_ahead": go_ahead(ev, winner_seat),
    }


# ---------------------------------------------------------------------------
# Pooled
# ---------------------------------------------------------------------------

def luck_rows(games, events):
    """Per decoded game: seats, window luck (rounds 1-4, 5-8, 9 to end), whole-game luck and its variance."""
    out = []
    for g in games:
        ev = events.get(g["id"])
        if not ev:
            continue
        n = len(ev["seats"])
        E, _, A, V = game_series(ev)
        T = len(E[0])
        out.append({
            "game": g["id"], "n": n, "T": T, "seats": ev["seats"], "winner": g["winner"],
            "win_idx": ev["seats"].index(g["winner"]),
            "full_rounds": T // n,
            "L1": window_luck(E, A, n, EARLY), "L2": window_luck(E, A, n, MID), "L3": window_luck(E, A, n, (9, None)),
            "L18": window_luck(E, A, n, (1, 8)),
            "L": [sum(A[i][t] - E[i][t] for t in range(T)) for i in range(n)],
            "Vtot": [sum(V[i]) for i in range(n)],
            "vp": {r["player"]: r.get("vp") for r in g["players"]},
            "ev": ev, "E": E, "A": A,
        })
    return out


def pre_game_mu(games, is_anon, is_bot):
    """Pre-game mu for every member seat from one chronological openskill pass over all games (the same
    model as the ratings: Plackett-Luce, guests at the prior every game, bots left out)."""
    model = PlackettLuce()
    ratings, out = {}, {}
    for g in games:
        order = [r["player"] for r in g["players"] if not is_bot(r["player"])]
        cur = {p: model.rating() if is_anon(p) else ratings.get(p, model.rating()) for p in order}
        out[g["id"]] = {p: cur[p].mu for p in order}
        vps = {r["player"]: r["vp"] for r in g["players"]}
        others = sorted((p for p in order if p != g["winner"]), key=lambda p: -vps[p])
        ranks, prev, prank = {g["winner"]: 1}, None, None
        for i, p in enumerate(others, start=2):
            ranks[p] = prank if vps[p] == prev else i
            prev, prank = vps[p], ranks[p]
        new = model.rate([[cur[p]] for p in order], ranks=[ranks[p] for p in order])
        for p, t in zip(order, new):
            if not is_anon(p):
                ratings[p] = t[0]
    return out


def snowball(rows, mu=None, level=statlib.LEVEL):
    """Conditional logit, Firth: P(i wins) prop. to exp(b1 L(rounds 1-4) + b2 L(5-8) + b3 L(9-end)), fit as
    exp(D L1 + b2 (L1 + L2) + b3 L3) so the first coefficient is D = b1 - b2 and gets a profile interval.
    Games with fewer than 8 full rounds are dropped (none in our data)."""
    use = [r for r in rows if r["full_rounds"] >= 8]
    def feats(r, i):
        f = [r["L1"][i], r["L1"][i] + r["L2"][i], r["L3"][i]]
        if mu is not None:
            f.append(mu[r["game"]].get(r["seats"][i], 25.0))
        return f
    strata = [{"X": [feats(r, i) for i in range(r["n"])], "y": [int(i == r["win_idx"]) for i in range(r["n"])]}
              for r in use]
    fit = statlib.cond_logit(strata, firth=True)
    lo, hi = statlib.profile_ci(strata, 0, level=level, firth=True, fit=fit)
    D, b2, b3 = fit["beta"][:3]
    se_D = fit["se"][0]
    return {"games": len(use), "D": r4(D), "D_se": r4(se_D), "D_ci": [r4(lo), r4(hi)],
            "b1": r4(D + b2), "b2": r4(b2), "b3": r4(b3), "b3_se": r4(fit["se"][2]),
            "detectable_80": r3((statlib.norm_ppf(0.5 + level / 2) + statlib.norm_ppf(0.8)) * se_D) if se_D else None,
            "detected": lo > 0 or hi < 0}


def snowball_ranked(rows):
    """Sensitivity: the same three windows in an exploded logit over the full finishing order (Breslow ties)."""
    strata = []
    for r in rows:
        if r["full_rounds"] < 8:
            continue
        vp = [r["vp"].get(p) for p in r["seats"]]
        ranks = []
        for i in range(r["n"]):
            if i == r["win_idx"]:
                ranks.append(1)
            elif vp[i] is None:
                ranks.append(None)
            else:
                ranks.append(2 + sum(1 for j in range(r["n"]) if j != r["win_idx"] and vp[j] is not None and vp[j] > vp[i]))
        X = [[r["L1"][i], r["L1"][i] + r["L2"][i], r["L3"][i]] for i in range(r["n"])]
        strata += statlib.exploded_strata(X, ranks)
    fit = statlib.cond_logit(strata, firth=False)
    return {"D": r4(fit["beta"][0]), "D_se": r4(fit["se"][0])}


def centered(vals):
    m = sum(vals) / len(vals)
    return [v - m for v in vals]


def ols_slope(xs, ys):
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else None


MECH_BINS = [(5, 8), (9, 12), (13, 16), (17, 20)]


def mechanism_units(rows, games_by_id):
    """Per game, per seat: x = game-centered L(rounds 1-4), and within-game centered outcomes averaged over the
    turn ends in each round bin: capacity C (gross expected cards per round), robber drag (gross minus net
    expected cards per round) and board VP share (board VP / target). A finished game carries its final state
    forward, so survivorship drops out. Also the summed expected cards over rounds 5-8 (return) and capacity
    at the end of rounds 5 and 8 (compounding)."""
    units = []
    for r in rows:
        n, ev = r["n"], r["ev"]
        G = (games_by_id[r["game"]].get("settings") or {}).get("vp_to_win") or max(v for v in r["vp"].values() if v is not None)
        ends = series.at_turn_ends(ev)
        def state_at(t):
            return ends[min(t, len(ends) - 1)]
        x = centered(r["L1"])
        u = {"x": x, "finished": {}, "bins": {}}
        for lo, hi in MECH_BINS:
            cap, drag, share = [0.0] * n, [0.0] * n, [0.0] * n
            ts = [rr * n - 1 for rr in range(lo, hi + 1)]  # end of each round in the bin
            for t in ts:
                row = state_at(t)
                bv = series.board_vp(row)
                for i in range(n):
                    g_ = n * series.gross_expected(row, i)
                    cap[i] += g_ / len(ts)
                    drag[i] += (g_ - n * series.expected_cards(row, i)) / len(ts)
                    share[i] += bv[i] / G / len(ts)
            u["bins"][f"{lo}-{hi}"] = {"C": centered(cap), "drag": centered(drag), "share": centered(share)}
            u["finished"][f"{lo}-{hi}"] = r["T"] <= (hi * n - 1)
        ret = [sum(r["E"][i][t] for t in range(4 * n, min(8 * n, r["T"]))) for i in range(n)]
        u["return"] = centered(ret)
        c5 = centered([n * series.gross_expected(state_at(5 * n - 1), i) for i in range(n)])
        c8 = centered([n * series.gross_expected(state_at(8 * n - 1), i) for i in range(n)])
        u["c5"], u["c8"] = c5, c8
        units.append(u)
    return units


def mechanism(units, B, seed=11):
    """Pooled OLS slopes on x over all seats of all games, with 95% game-cluster bootstrap intervals."""
    def fit(us):
        xs = [x for u in us for x in u["x"]]
        out = {}
        for b in MECH_BINS:
            k = f"{b[0]}-{b[1]}"
            for o in ("C", "drag", "share"):
                out[f"{o}|{k}"] = ols_slope(xs, [y for u in us for y in u["bins"][k][o]])
        out["return"] = ols_slope(xs, [y for u in us for y in u["return"]])
        b5 = ols_slope(xs, [y for u in us for y in u["c5"]])
        b8 = ols_slope(xs, [y for u in us for y in u["c8"]])
        out["compounding"] = None if b5 is None or b8 is None else b8 - b5
        return out
    est = fit(units)
    boots = statlib.cluster_bootstrap(units, fit, B=B, seed=seed)
    res = {}
    for k, v in est.items():
        lo, hi = statlib.percentile_ci([b[k] for b in boots if b[k] is not None])
        res[k] = {"slope": r4(v), "ci": [r4(lo), r4(hi)]}
    res["finished_share"] = {f"{a}-{b}": r3(sum(u["finished"][f"{a}-{b}"] for u in units) / len(units)) for a, b in MECH_BINS}
    res["games"] = len(units)
    return res


def leaks(rows, B, seed=12):
    """Slopes on game-centered L(rounds 1-4) of cards lost in rounds 5 and later, by kind: 7-discards,
    monopoly, bank shortage (cards the dice owed but the bank could not pay) and steals."""
    units = []
    for r in rows:
        ev, n = r["ev"], r["n"]
        ends = series.at_turn_ends(ev)
        if len(ends) < 4 * n:
            continue
        a, z = ends[4 * n - 1], ends[-1]
        lost = {
            "discarded": [z["discarded"][i] - a["discarded"][i] for i in range(n)],
            "monopoly": [sum(z["monopoly_lost_to"][i]) - sum(a["monopoly_lost_to"][i]) for i in range(n)],
            "stolen": [z["stolen_from"][i] - a["stolen_from"][i] for i in range(n)],
            "shortage": [sum(rl["short"][i] for rl in ev["roll_log"][4 * n:]) for i in range(n)],
        }
        units.append({"x": centered(r["L1"]), **{k: centered(v) for k, v in lost.items()}})
    def fit(us):
        xs = [x for u in us for x in u["x"]]
        return {k: ols_slope(xs, [y for u in us for y in u[k]]) for k in LEAK_KINDS}
    est = fit(units)
    boots = statlib.cluster_bootstrap(units, fit, B=B, seed=seed)
    out = {}
    for k in LEAK_KINDS:
        lo, hi = statlib.percentile_ci([b[k] for b in boots if b[k] is not None])
        out[k] = {"slope": r4(est[k]), "ci": [r4(lo), r4(hi)]}
    out["games"] = len(units)
    return out


def deciles(rows, pids, min_games, B, seed=13):
    """Production share R_q(t) = n E_q(t) / sum_j E_j(t) (averages exactly 1 over the table), by game decile
    d = ceil(10 t / T) with t the 1-based roll. Per player: equal-weight mean over games of the decile means,
    a 95% sup-t simultaneous band from a game-cluster bootstrap, and Delta = mean over games of (mean R in
    deciles 8-10 minus mean R in deciles 1-3) with a bootstrap interval."""
    per = defaultdict(list)
    for r in rows:
        T, n = r["T"], r["n"]
        tot = [sum(r["E"][j][t] for j in range(n)) for t in range(T)]
        for i, pid in enumerate(r["seats"]):
            if pid not in pids:
                continue
            bins = defaultdict(list)
            for t in range(T):
                if tot[t] > 0:
                    bins[math.ceil(10 * (t + 1) / T)].append(n * r["E"][i][t] / tot[t])
            if len(bins) == 10:
                per[pid].append([sum(bins[d]) / len(bins[d]) for d in range(1, 11)])
    out = {}
    for k, pid in enumerate(pids):
        curves = per.get(pid, [])
        if len(curves) < min_games:
            continue
        mean_curve = lambda cs: [sum(c[d] for c in cs) / len(cs) for d in range(10)]
        delta = lambda cs: sum(sum(c[7:]) / 3 - sum(c[:3]) / 3 for c in cs) / len(cs)
        boots = statlib.cluster_bootstrap(curves, lambda cs: (mean_curve(cs), delta(cs)), B=B, seed=seed + k)
        band = statlib.sup_t_band([b[0] for b in boots], center=mean_curve(curves))
        dlo, dhi = statlib.percentile_ci([b[1] for b in boots])
        sizes = defaultdict(int)
        out[pid] = {"games": len(curves), "mean": [r3(x) for x in mean_curve(curves)],
                    "lo": [r3(x) for x in band["lo"]], "hi": [r3(x) for x in band["hi"]],
                    "delta": r3(delta(curves)), "delta_ci": [r3(dlo), r3(dhi)]}
        for r in rows:
            if pid in r["seats"]:
                sizes[r["n"]] += 1
        out[pid]["sizes"] = dict(sorted(sizes.items()))
    return out


def luck_by_player(rows, pids, min_games):
    """Game-centered dice luck: L^c = L - mean over the table of L, per game, in cards. Per player: mean
    L^c with its empirical SE (sd / sqrt(games)), a t interval, and the pooled z = sum L / sqrt(sum V)."""
    per = defaultdict(lambda: {"Lc": [], "L": 0.0, "V": 0.0})
    for r in rows:
        lc = centered(r["L"])
        for i, pid in enumerate(r["seats"]):
            if pid in pids:
                d = per[pid]
                d["Lc"].append(lc[i])
                d["L"] += r["L"][i]
                d["V"] += r["Vtot"][i]
    out = {}
    for pid, d in per.items():
        g = len(d["Lc"])
        m, lo, hi = statlib.t_interval(d["Lc"])
        sd = math.sqrt(sum((x - m) ** 2 for x in d["Lc"]) / (g - 1)) if g > 1 else None
        out[pid] = {"games": g, "mean": r2(m), "lo": r2(lo), "hi": r2(hi), "se": r3(sd / math.sqrt(g)) if sd else None,
                    "sd": r3(sd), "z": r3(d["L"] / math.sqrt(d["V"])) if d["V"] else None, "shown": g >= min_games}
    return out


def luck_adjusted_wins(rows, pids, min_games):
    """p_ig from a leave-one-game-out conditional logit (Firth) on L(rounds 1-8). Wins above luck
    W_i = sum (won - p); luck part = sum (p - 1/n); SE = sqrt(sum p (1 - p))."""
    use = [r for r in rows if r["full_rounds"] >= 8]
    strata = [{"X": [[r["L18"][i]] for i in range(r["n"])], "y": [int(i == r["win_idx"]) for i in range(r["n"])]}
              for r in use]
    full = statlib.cond_logit(strata, firth=True)
    acc = defaultdict(lambda: {"W": 0.0, "luck": 0.0, "var": 0.0, "games": 0, "wins": 0, "exp": 0.0})
    for k, r in enumerate(use):
        b = statlib.cond_logit(strata[:k] + strata[k + 1:], firth=True, start=full["beta"])["beta"][0]
        ex = [math.exp(b * r["L18"][i]) for i in range(r["n"])]
        s = sum(ex)
        for i, pid in enumerate(r["seats"]):
            if pid not in pids:
                continue
            p = ex[i] / s
            a = acc[pid]
            won = int(i == r["win_idx"])
            a["W"] += won - p
            a["luck"] += p - 1 / r["n"]
            a["var"] += p * (1 - p)
            a["games"] += 1
            a["wins"] += won
            a["exp"] += p
    out = {"b": r4(full["beta"][0]), "b_se": r4(full["se"][0]), "players": {}}
    for pid, a in acc.items():
        if a["games"] >= min_games:
            out["players"][pid] = {"games": a["games"], "wins": a["wins"], "luck_expected": r2(a["exp"]),
                                   "above_luck": r2(a["W"]), "luck_part": r2(a["luck"]), "se": r2(math.sqrt(a["var"]))}
    return out


def play_tally(per_game, games_by_id):
    """Tie-weighted counts of play-of-the-game types (the best single action's main change), New Shores vs other."""
    tally = defaultdict(lambda: defaultdict(float))
    for gid, pg in per_game.items():
        play = pg.get("play") or {}
        picks = ([play["pick"]] + play.get("co_plays", [])) if play.get("pick") else []
        scen = (games_by_id[gid].get("settings") or {}).get("scenario")
        grp = "New Shores" if scen == "new_shores" else "Other"
        for c in picks:
            what = c["best_action"]["what"]
            kind = next((w["type"] for w in what if w["type"] in ("longest_road_taken", "largest_army_taken", "island_bonus")),
                        what[0]["type"] if what else c["best_action"]["action"])
            tally[grp][kind] += 1 / len(picks)
    return {g: {k: r2(v) for k, v in d.items()} for g, d in tally.items()}


# ---------------------------------------------------------------------------
# Module entry points
# ---------------------------------------------------------------------------

def _hash(games, events):
    h = hashlib.sha256()
    h.update(json.dumps([(g["id"], g["winner"], [(r["player"], r.get("vp")) for r in g["players"]]) for g in games]).encode())
    for gid in sorted(events):
        h.update(json.dumps(events[gid]["roll_log"]).encode())
        h.update(json.dumps(events[gid]["states"][:1]).encode())
    return h.hexdigest()[:16]


def compute_all(games, replays, events, ctx):
    if not events:
        return None
    by_id = {g["id"]: g for g in games}
    per_game = {g["id"]: one_game(g, events[g["id"]]) for g in games if g["id"] in events}
    rows = luck_rows(games, events)
    fast = ctx.get("fast")
    B = 200 if fast else statlib.B_DESCRIPTIVE
    key = _hash(games, events) + ("-fast" if fast else "")
    cache = CACHE / f"{KEY}-{key}.json"
    pooled = None
    if not fast and cache.exists():
        pooled = json.loads(cache.read_text())
    if pooled is None:
        pooled = {}
        if len(rows) >= statlib.GUARDS["model_games"]:
            mu = pre_game_mu(games, ctx["is_anon"], ctx["is_bot"])
            pooled["snowball"] = snowball(rows)
            pooled["snowball"]["sensitivity"] = [
                {"name": "3 and 4 seat games only", **snowball([r for r in rows if r["n"] <= 4])},
                {"name": "Adding pre-game skill (mu)", **snowball(rows, mu=mu)},
                {"name": "Full finishing order (exploded logit)", **snowball_ranked(rows)},
            ]
            pooled["mechanism"] = mechanism(mechanism_units(rows, by_id), B)
            pooled["leaks"] = leaks(rows, B)
        if not fast:
            CACHE.mkdir(exist_ok=True)
            cache.write_text(json.dumps(pooled))
    gross_luck = {"final_round": final_round_luck(rows)}
    return {"games": per_game, "w_rate": W_RATE, "early": EARLY, "mid": MID, **pooled, **gross_luck,
            "play_tally": play_tally(per_game, by_id)}


def final_round_luck(rows):
    """Mean luck over the last round, winner vs everyone else: the stopping effect inside b3."""
    w, o = [], []
    for r in rows:
        n = r["n"]
        last = window_luck(r["E"], r["A"], n, (r["T"] // n, None)) if r["T"] >= n else None
        if last is None:
            continue
        for i in range(n):
            (w if i == r["win_idx"] else o).append(last[i])
    return {"winner": r2(sum(w) / len(w)) if w else None, "others": r2(sum(o) / len(o)) if o else None}


def compute_view(games, replays, events, ctx, all_result):
    if not all_result:
        return None
    rows = luck_rows(games, events)
    pids = set(ctx["pids"])
    G = statlib.GUARDS
    B = 200 if ctx.get("fast") else statlib.B_DESCRIPTIVE
    out = {"games": len(rows), "luck": luck_by_player(rows, pids, G["player_rows"]),
           "deciles": deciles(rows, pids, G["player_rows"], B)}
    if len(rows) >= G["model_games"]:
        out["luck_adjusted"] = luck_adjusted_wins(rows, pids, G["player_rows"])
        out["luck_adjusted"]["source"] = "this view"
    elif all_result.get("snowball"):
        out["luck_adjusted"] = None
    return out
