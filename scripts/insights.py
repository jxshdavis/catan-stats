"""Model-based and group-level stats for the site, computed by build.py.

Each function takes plain game and replay records (games.json entries and
data/replays.json entries) and returns JSON-ready dicts. The methods follow
the stats proposal; every number the site shows comes with the method text in
the "How it works" page and the info buttons.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict

import series
import statlib

DICE_FACES = list(range(2, 13))
DICE_P = {s: (6 - abs(s - 7)) / 36 for s in DICE_FACES}


def r3(x):
    return None if x is None else round(x, 3)


def r4(x):
    return None if x is None else round(x, 4)


def members(game, is_anon):
    return [r["player"] for r in game["players"] if not is_anon(r["player"])]


def target_of(game):
    return (game.get("settings") or {}).get("vp_to_win") or max(r["vp"] for r in game["players"] if r.get("vp") is not None)


# ---------------------------------------------------------------------------
# 1.10 Closest games (interim: true VP, "hindsight", until board VP exists)
# ---------------------------------------------------------------------------

def vp_by_roll(timeline):
    """Dense VP after every roll index 0..T from a change-point timeline: {pid: [v0..vT]}."""
    turns = timeline["turn"]
    T = max(turns)
    out = {}
    for pid, vals in timeline["vp"].items():
        series, j, cur = [], 0, 0
        for t in range(T + 1):
            while j < len(turns) and turns[j] <= t:
                cur = vals[j]
                j += 1
            series.append(cur)
        out[pid] = series
    return out


def closeness_parts(game, timeline):
    """The three closeness parts for one game, all ending at s-, the end_turn before the winner's final turn.

    With one roll per turn, the state after roll index t's end_turn is the dense value at t, and the
    winner's final turn is roll T, so s- is t = T - 1.
      A  = G - max over non-winners of V(s-): VP the best non-winner still needed.
      B' = changes of the strict sole leader over end_turn snapshots 0..s-, divided by (G - 2).
           A tie leaves the last sole leader in place, so only a new sole leader counts as a change.
      C  = mean over snapshots from the first one where anyone has at least G/2, to s-, of (top - second) / (G - 2).
    """
    V = vp_by_roll(timeline)
    pids = list(V)
    T = len(next(iter(V.values()))) - 1
    G = target_of(game)
    w = game["winner"]
    s = max(0, T - 1)
    others = [p for p in pids if p != w]
    best_other = max(V[p][s] for p in others)
    A = G - best_other
    within2 = sum(1 for p in others if G - V[p][s] <= 2)
    changes, last = 0, None
    for t in range(s + 1):
        vals = sorted(((V[p][t], p) for p in pids), reverse=True)
        if vals[0][0] > vals[1][0]:
            leader = vals[0][1]
            if last is not None and leader != last:
                changes += 1
            last = leader
    gaps = []
    started = False
    for t in range(s + 1):
        vals = sorted((V[p][t] for p in pids), reverse=True)
        if not started and vals[0] >= G / 2:
            started = True
        if started:
            gaps.append((vals[0] - vals[1]) / (G - 2))
    if not gaps:  # nobody reached half the target before the final turn: use s- alone
        vals = sorted((V[p][s] for p in pids), reverse=True)
        gaps = [(vals[0] - vals[1]) / (G - 2)]
    return {"A": A, "A_within2": within2, "lead_changes": changes, "B": changes / (G - 2), "C": sum(gaps) / len(gaps),
            "s_minus": s, "target": G}


def pct_ranks(values, higher_is_closer):
    """Mid-rank percentile in [0, 1] of each value, oriented so 1 is the closest game."""
    n = len(values)
    out = []
    for v in values:
        below = sum(1 for u in values if (u < v if higher_is_closer else u > v))
        ties = sum(1 for u in values if u == v)
        out.append((below + 0.5 * ties) / n)
    return out


def board_timeline(ev):
    """Board VP (VP cards held left out) as a timeline in the replays.json shape: index 0 is the board
    after setup, index t the end of the turn of roll t."""
    first = series.at_rolls(ev)[0]
    ends = series.at_turn_ends(ev)
    rows = [series.board_vp(first)] + [series.board_vp(r) for r in ends]
    return {"turn": list(range(len(rows))), "vp": {pid: [r[i] for r in rows] for i, pid in enumerate(ev["seats"])}}


def closeness(games, replays, n_seats, events=None):
    """Closeness on board VP when the per-action logs exist, with the true-VP (hindsight) version under
    "hindsight"; on true VP alone otherwise."""
    if events and all(g["id"] in events for g in games if g["id"] in replays):
        out = closeness_on(games, {g["id"]: board_timeline(events[g["id"]]) for g in games if g["id"] in events}, n_seats)
        if out:
            out["series"] = "board VP: what everyone could see"
            out["hindsight"] = closeness_on(games, {gid: r["timeline"] for gid, r in replays.items()}, n_seats)
        return out
    return closeness_on(games, {gid: r["timeline"] for gid, r in replays.items()}, n_seats)


def closeness_on(games, timelines, n_seats):
    """Closeness index I = 100 x mean of the three part percentiles (equal weights, frozen), plus the
    tier of games in the top quartile under all four composites: all three parts, and each pair of parts.
    A ties are broken by the number of opponents within 2 VP. Percentiles use every decoded game."""
    rows = []
    for g in games:
        tl = timelines.get(g["id"])
        if not tl:
            continue
        parts = closeness_parts(g, tl)
        rows.append({"game": g["id"], "n_seats": n_seats(g), **parts})
    if len(rows) < 4:
        return None
    # A with the within-2 tiebreak: fewer VP needed is closer; more opponents within 2 breaks ties.
    pA = pct_ranks([-r["A"] + r["A_within2"] / 100 for r in rows], True)
    pB = pct_ranks([r["B"] for r in rows], True)
    pC = pct_ranks([r["C"] for r in rows], False)
    comps = {
        "all": [(a + b + c) / 3 for a, b, c in zip(pA, pB, pC)],
        "no_A": [(b + c) / 2 for b, c in zip(pB, pC)],
        "no_B": [(a + c) / 2 for a, c in zip(pA, pC)],
        "no_C": [(a + b) / 2 for a, b in zip(pA, pB)],
    }
    ranks = {}
    for k, vals in comps.items():
        order = sorted(range(len(rows)), key=lambda i: -vals[i])
        rk = [0] * len(rows)
        for pos, i in enumerate(order, start=1):
            rk[i] = pos
        ranks[k] = rk
    n = len(rows)
    q = math.ceil(n / 4)
    for i, r in enumerate(rows):
        rk = [ranks[k][i] for k in comps]
        r.update({"pA": r3(pA[i]), "pB": r3(pB[i]), "pC": r3(pC[i]), "index": round(100 * comps["all"][i], 1),
                  "rank": ranks["all"][i], "rank_min": min(rk), "rank_max": max(rk),
                  "closest_tier": max(rk) <= q, "one_sided_tier": min(rk) > n - q,
                  "B": r3(r["B"]), "C": r3(r["C"])})
    # Seat-class view: percentiles within 3p, 4p and 5-6p, since more seats make the max over opponents closer.
    for cls in ("3", "4", "5-6"):
        sub = [r for r in rows if (str(r["n_seats"]) if r["n_seats"] < 5 else "5-6") == cls]
        if len(sub) < 4:
            continue
        a = pct_ranks([-r["A"] + r["A_within2"] / 100 for r in sub], True)
        b = pct_ranks([r["B"] for r in sub], True)
        c = pct_ranks([r["C"] for r in sub], False)
        for r, x, y, z in zip(sub, a, b, c):
            r["index_in_class"] = round(100 * (x + y + z) / 3, 1)
    return {"games": {r.pop("game"): r for r in rows}, "n": n, "tier_size": q,
            "series": "true VP (hindsight): includes VP cards nobody could see"}


# ---------------------------------------------------------------------------
# 1.6 Dice calibration
# ---------------------------------------------------------------------------

def dice_calibration(games):
    """Seven rate with a Wilson interval and z against 1/6; pooled chi-square on 10 df; the summed
    per-game chi-square (df = 10 per game) as a check that rolls are independent within games; and
    drift = sum((p_hat - P) f) / sum(E), the relative excess of cards a fixed board would get."""
    counts = {s: 0 for s in DICE_FACES}
    per_game_chi2, games_n = 0.0, 0
    for g in games:
        d = (g.get("dice") or {}).get("counts")
        if not d:
            continue
        c = {s: int(d[str(s)]) for s in DICE_FACES}
        n = sum(c.values())
        if not n:
            continue
        games_n += 1
        for s in DICE_FACES:
            counts[s] += c[s]
        per_game_chi2 += sum((c[s] - n * DICE_P[s]) ** 2 / (n * DICE_P[s]) for s in DICE_FACES)
    N = sum(counts.values())
    if not N:
        return None
    E7 = N / 6
    z7 = (counts[7] - E7) / math.sqrt(N * (1 / 6) * (5 / 6))
    chi2 = sum((counts[s] - N * DICE_P[s]) ** 2 / (N * DICE_P[s]) for s in DICE_FACES)
    # Drift weights each non-7 face by its dots: a board with one settlement on every number gets f(s) = dots(s).
    f = {s: (6 - abs(s - 7)) if s != 7 else 0 for s in DICE_FACES}
    drift = sum((counts[s] / N - DICE_P[s]) * f[s] for s in DICE_FACES) / sum(DICE_P[s] * f[s] for s in DICE_FACES)
    return {
        "rolls": N, "games": games_n,
        "sevens": counts[7], "sevens_expected": r3(E7), "seven_rate": r4(counts[7] / N),
        "seven_rate_ci": [r4(x) for x in statlib.wilson(counts[7], N)], "seven_z": r3(z7),
        "chi2": r3(chi2), "chi2_df": 10, "chi2_p": r4(statlib.chi2_sf(chi2, 10)),
        "per_game_chi2": r3(per_game_chi2), "per_game_df": 10 * games_n,
        "per_game_p": r4(statlib.chi2_sf(per_game_chi2, 10 * games_n)),
        "drift": r4(drift),
    }


# ---------------------------------------------------------------------------
# 1.1 Openings
# ---------------------------------------------------------------------------

def seat_rows(game, replay):
    """Every seat of a game with its opening dots, or None if any seat lacks a replay value."""
    out = []
    for r in game["players"]:
        st = (replay or {}).get("players", {}).get(r["player"])
        if st is None:
            return None
        out.append({"player": r["player"], "seat": r.get("seat"), "vp": r.get("vp"), "dots": st["opening_dots"]})
    return out


def opening_data(games, replays):
    """Per game: seats with x = opening dots minus the table mean, and the winner's index."""
    data = []
    for g in games:
        rows = seat_rows(g, replays.get(g["id"]))
        if rows is None:
            continue
        m = sum(r["dots"] for r in rows) / len(rows)
        for r in rows:
            r["x"] = r["dots"] - m
        data.append({"game": g["id"], "n": len(rows), "rows": rows, "winner": g["winner"],
                     "win_idx": next(i for i, r in enumerate(rows) if r["player"] == g["winner"])})
    return data


def winner_strata(data, feats):
    """One conditional-logit stratum per game: alternatives are the seats, the winner is chosen."""
    return [{"X": [feats(d, r) for r in d["rows"]], "y": [1 if i == d["win_idx"] else 0 for i in range(d["n"])]}
            for d in data]


def p_of_d(b, d):
    """Win chance for a player d pips above each of three equal opponents."""
    return math.exp(b * d) / (math.exp(b * d) + 3)


def opening_effect(data, level=statlib.LEVEL):
    """Conditional logit stratified by game, P(i wins g) proportional to exp(b x_ig), fit with the Firth
    penalty; the interval is the profile penalized-likelihood interval."""
    strata = winner_strata(data, lambda d, r: [r["x"]])
    fit = statlib.cond_logit(strata, firth=True)
    lo, hi = statlib.profile_ci(strata, 0, level=level, firth=True)
    b = fit["beta"][0]
    return {
        "b": r4(b), "se": r4(fit["se"][0]), "ci": [r4(lo), r4(hi)],
        "or": r3(math.exp(b)), "or_ci": [r3(math.exp(lo)), r3(math.exp(hi))],
        "curve": [{"d": d, "p": r4(p_of_d(b, d)), "lo": r4(p_of_d(lo, d)), "hi": r4(p_of_d(hi, d))}
                  for d in range(-4, 5)],
        "p2": r3(p_of_d(b, 2)), "games": len(data),
    }


def opening_robustness(data, is_anon):
    """Four refits of the opening effect, each reported as b with its SE (Firth on throughout, as for every
    winner model, except the exploded logit, which models every place and is fit by maximum likelihood)."""
    out = []
    # Each guest and bot seat counts as its own player.
    key = lambda d, r: (d["game"], r["player"]) if is_anon(r["player"]) else r["player"]
    xs = defaultdict(list)
    for d in data:
        for r in d["rows"]:
            xs[key(d, r)].append(r["x"])
    xbar = {k: sum(v) / len(v) for k, v in xs.items()}
    fit = statlib.cond_logit(winner_strata(data, lambda d, r: [r["x"] - xbar[key(d, r)], xbar[key(d, r)]]), firth=True)
    out.append({"name": "Mundlak, within player", "b": r4(fit["beta"][0]), "se": r4(fit["se"][0])})
    out.append({"name": "Mundlak, between players", "b": r4(fit["beta"][1]), "se": r4(fit["se"][1])})
    regulars = sorted({r["player"] for d in data for r in d["rows"] if not is_anon(r["player"])})
    ref = regulars[0]
    fe = [p for p in regulars if p != ref]
    fit = statlib.cond_logit(winner_strata(
        data, lambda d, r: [r["x"]] + [1.0 if r["player"] == p else 0.0 for p in fe]), firth=True)
    out.append({"name": "Player fixed effects", "b": r4(fit["beta"][0]), "se": r4(fit["se"][0])})
    seated = [d for d in data if all(r["seat"] is not None for r in d["rows"])]
    fit = statlib.cond_logit(winner_strata(
        seated, lambda d, r: [r["x"], (r["seat"] - 1) / (d["n"] - 1)]), firth=True)
    out.append({"name": "Seat term", "b": r4(fit["beta"][0]), "se": r4(fit["se"][0]), "games": len(seated)})
    strata = []
    for d in data:
        # Exploded logit: the winner is chosen from everyone, then each place from those left.
        # Seats with equal VP share a place (Breslow ties); a bot with unknown VP is left out.
        rows = [r for r in d["rows"] if r["vp"] is not None]
        winner = d["rows"][d["win_idx"]]
        places = [[winner]]
        rest = sorted((r for r in rows if r is not winner), key=lambda r: -r["vp"])
        for r in rest:
            if len(places) > 1 and places[-1][0]["vp"] == r["vp"]:
                places[-1].append(r)
            else:
                places.append([r])
        left = list(rows)
        for group in places[:-1]:
            strata.append({"X": [[r["x"]] for r in left], "y": [1 if r in group else 0 for r in left]})
            left = [r for r in left if r not in group]
    fit = statlib.cond_logit(strata, firth=False)
    out.append({"name": "Exploded logit, full finishing order", "b": r4(fit["beta"][0]), "se": r4(fit["se"][0])})
    return out


def best_opener(data, draws=10000, seed=1):
    """Wins by the best, middle and worst openers against chance. k_g = seats tied at the max opening
    dots, O_best = sum 1[winner at max] / k_g, E_best = sum 1/n_g (worst the same at the min; middle
    counts the m_g seats strictly between, E = sum m_g / n_g). Games where every seat ties are dropped.
    The null band and the one-sided p for O_best come from moving the win to a uniformly random seat
    within each game."""
    used = [d for d in data if len({r["dots"] for r in d["rows"]}) > 1]
    dropped = len(data) - len(used)

    def buckets(win):
        o = [0.0, 0.0, 0.0]
        for d, w in zip(used, win):
            dots = [r["dots"] for r in d["rows"]]
            hi, lo = max(dots), min(dots)
            v = dots[w]
            if v == hi:
                o[0] += 1 / dots.count(hi)
            elif v == lo:
                o[2] += 1 / dots.count(lo)
            else:
                o[1] += 1
        return o

    obs = buckets([d["win_idx"] for d in used])
    exp = [0.0, 0.0, 0.0]
    for d in used:
        dots = [r["dots"] for r in d["rows"]]
        hi, lo = max(dots), min(dots)
        exp[0] += 1 / d["n"]
        exp[2] += 1 / d["n"]
        exp[1] += sum(1 for v in dots if lo < v < hi) / d["n"]
    rng = random.Random(seed)
    sims = [buckets([rng.randrange(d["n"]) for d in used]) for _ in range(draws)]
    p = (1 + sum(1 for s in sims if s[0] >= obs[0] - 1e-9)) / (draws + 1)
    names = ["Best opener", "Middle", "Worst opener"]
    out = []
    for k in range(3):
        col = sorted(s[k] for s in sims)
        out.append({"label": names[k], "observed": r3(obs[k]), "expected": r3(exp[k]),
                    "lo": r3(col[int(0.025 * draws)]), "hi": r3(col[int(0.975 * draws) - 1])})
    return {"buckets": out, "p_best": r4(p), "games": len(used), "dropped_all_tied": dropped, "draws": draws}


def opening_by_player(data, is_anon, min_games):
    """Raw = mean over a player's games of x. Draft-adjusted = mean of (x - c), where c is the mean x in the
    same (player count, seat) cell over the other games (leave this game out), for 3 and 4 seat games only;
    5 and 6 seat games stay raw and are counted. t intervals."""
    cell = defaultdict(list)
    for d in data:
        for r in d["rows"]:
            if r["seat"] is not None and d["n"] in (3, 4):
                cell[(d["n"], r["seat"])].append((d["game"], r["x"]))
    per = defaultdict(lambda: {"raw": [], "adj": [], "unadjusted_games": 0})
    for d in data:
        for r in d["rows"]:
            if is_anon(r["player"]):
                continue
            p = per[r["player"]]
            p["raw"].append(r["x"])
            others = [x for gid, x in cell.get((d["n"], r["seat"]), []) if gid != d["game"]]
            if d["n"] in (3, 4) and others:
                p["adj"].append(r["x"] - sum(others) / len(others))
            else:
                p["adj"].append(r["x"])
                p["unadjusted_games"] += 1
    out = {}
    for pid, p in per.items():
        if len(p["raw"]) < min_games:
            continue
        out[pid] = {"games": len(p["raw"]), "raw": mean_t(p["raw"]), "adjusted": mean_t(p["adj"]),
                    "unadjusted_games": p["unadjusted_games"]}
    return out


def mean_t(xs, level=statlib.LEVEL):
    n = len(xs)
    m = sum(xs) / n
    if n < 2:
        return {"mean": r3(m), "lo": None, "hi": None}
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    h = statlib.t_ppf(0.5 + level / 2, n - 1) * sd / math.sqrt(n)
    return {"mean": r3(m), "lo": r3(m - h), "hi": r3(m + h)}


def seat_effect(games, draws=10000, seed=2):
    """Wins by seat in 3 and 4 seat games against sum 1/n, with a 2.5 to 97.5% band from moving the
    win to a uniformly random seat within each game."""
    out = {}
    rng = random.Random(seed)
    for n in (3, 4):
        gs = [g for g in games if len(g["players"]) == n
              and sorted(r.get("seat") or 0 for r in g["players"]) == list(range(1, n + 1))]
        if not gs:
            continue
        obs = [0] * n
        for g in gs:
            obs[next(r["seat"] for r in g["players"] if r["player"] == g["winner"]) - 1] += 1
        sims = []
        for _ in range(draws):
            c = [0] * n
            for _g in gs:
                c[rng.randrange(n)] += 1
            sims.append(c)
        bars = []
        for s in range(n):
            col = sorted(x[s] for x in sims)
            bars.append({"seat": s + 1, "wins": obs[s], "expected": r3(len(gs) / n),
                         "lo": col[int(0.025 * draws)], "hi": col[int(0.975 * draws) - 1]})
        out[str(n)] = {"games": len(gs), "seats": bars}
    return out


# ---------------------------------------------------------------------------
# 1.4 Trade and bank profile (no badges yet), 1.5 steal share
# ---------------------------------------------------------------------------

def received_total(st):
    """Cards a seat received from any source the replay records: dice (gold picks included), player
    trades, bank and port trades, steals and monopoly. Year of Plenty and fog picks are not in the
    current replay fields, so they are left out until decoder v2 adds them."""
    return (st["resources_from_dice"] + st["trade_cards_received"] + st["bank_cards_received"]
            + st["steals"] + st["monopoly_cards"])


def profile_units(games, replays):
    """Per game: {pid: replay stats} for every seat, for games with a replay of every seat."""
    units = []
    for g in games:
        rep = replays.get(g["id"])
        if not rep or set(rep["players"]) != {r["player"] for r in g["players"]}:
            continue
        units.append({"game": g["id"], "n": len(g["players"]), "st": rep["players"]})
    return units


def mh_trade_rr(units, pid):
    """Mantel-Haenszel rate ratio of player-trade cards (given plus received) against the rest of the table,
    each seat counting one unit of exposure: RR = sum x_ig (n-1)/n / sum X_-ig / n."""
    num = den = 0.0
    for u in units:
        if pid not in u["st"]:
            continue
        x = {q: s["trade_cards_given"] + s["trade_cards_received"] for q, s in u["st"].items()}
        rest = sum(v for q, v in x.items() if q != pid)
        num += x[pid] * (u["n"] - 1) / u["n"]
        den += rest / u["n"]
    return num / den if den else None


def mh_bank_rd(units, pid):
    """Mantel-Haenszel risk difference in the share of received cards that came from the bank, player
    against the rest of the table: sum w (y_i/N_i - y_-/N_-) / sum w, with w = N_i N_- / (N_i + N_-)."""
    num = den = 0.0
    for u in units:
        if pid not in u["st"]:
            continue
        Ni = received_total(u["st"][pid])
        yi = u["st"][pid]["bank_cards_received"]
        Nr = sum(received_total(s) for q, s in u["st"].items() if q != pid)
        yr = sum(s["bank_cards_received"] for q, s in u["st"].items() if q != pid)
        if Ni and Nr:
            w = Ni * Nr / (Ni + Nr)
            num += w * (yi / Ni - yr / Nr)
            den += w
    return num / den if den else None


def boot_ci(units, fn, B, seed, level=statlib.LEVEL):
    sims = [v for v in statlib.cluster_bootstrap(units, fn, B=B, seed=seed) if v is not None]
    if len(sims) < B / 2:
        return None
    lo, hi = statlib.percentile_ci(sims, level)
    return [r3(lo), r3(hi)]


def trade_bank_profile(units, pids, min_games, B=2000):
    out = {}
    for k, pid in enumerate(pids):
        mine = [u for u in units if pid in u["st"]]
        if len(mine) < min_games:
            continue
        given = sum(u["st"][pid]["bank_cards_given"] for u in mine)
        got = sum(u["st"][pid]["bank_cards_received"] for u in mine)
        out[pid] = {
            "games": len(mine),
            "trade_rr": r3(mh_trade_rr(mine, pid)), "trade_rr_ci": boot_ci(mine, lambda s: mh_trade_rr(s, pid), B, 100 + k),
            "bank_rd": r3(mh_bank_rd(mine, pid)), "bank_rd_ci": boot_ci(mine, lambda s: mh_bank_rd(s, pid), B, 200 + k),
            "port_rate": r3(given / got) if got else None,
        }
    return out


def steal_share(units, pids, min_games, B=2000):
    """O_i = cards stolen from i. E_i = sum over games and other seats p of steals_p / (n - 1), an even split
    of everyone else's steals over their n - 1 possible victims (n counts every seat). Leader-robbing
    counts as excess here. Ratio O/E with a game-cluster bootstrap interval."""
    def ratio(sub, pid):
        o = e = 0.0
        for u in sub:
            o += u["st"][pid]["stolen_from"]
            e += sum(s["steals"] for q, s in u["st"].items() if q != pid) / (u["n"] - 1)
        return o / e if e else None
    out = {}
    for k, pid in enumerate(pids):
        mine = [u for u in units if pid in u["st"]]
        if len(mine) < min_games:
            continue
        o = sum(u["st"][pid]["stolen_from"] for u in mine)
        e = sum(sum(s["steals"] for q, s in u["st"].items() if q != pid) / (u["n"] - 1) for u in mine)
        out[pid] = {"games": len(mine), "observed": o, "expected": r3(e), "ratio": r3(o / e) if e else None,
                    "ci": boot_ci(mine, lambda s: ratio(s, pid), B, 300 + k)}
    return out


# ---------------------------------------------------------------------------
# 1.4 Win recipe
# ---------------------------------------------------------------------------

RECIPE = {"buildings": ("settlements", "cities", "other"), "development": ("vp_cards", "largest_army"),
          "bonuses": ("longest_road", "islands")}


def recipe_shares(vb):
    tot = sum(vb.values())
    return {c: sum(vb.get(k, 0) for k in keys) / tot for c, keys in RECIPE.items()} if tot else None


def win_recipe(games, pids, min_wins, B=2000, level=statlib.LEVEL):
    """VP shares of each win across Buildings, Development (VP cards and Largest Army) and Bonuses (Longest
    Road and islands). Tilt = mean over a player's wins of (q - b), where b is the mean share over the other
    winners' wins with the same scenario and VP target, falling back to the same scenario, then the same
    expansion. The tilts sum to 0. BCa bootstrap interval over the player's wins."""
    wins = []
    for g in games:
        w = next(r for r in g["players"] if r["player"] == g["winner"])
        q = recipe_shares(w.get("vp_breakdown") or {})
        if q is None:
            continue
        s = g.get("settings") or {}
        wins.append({"game": g["id"], "winner": g["winner"], "q": q,
                     "keys": [(s.get("expansion"), s.get("scenario"), s.get("vp_to_win")),
                              (s.get("expansion"), s.get("scenario")), (s.get("expansion"),)]})

    def baseline(w):
        for level_i in range(3):
            pool = [o for o in wins if o["winner"] != w["winner"] and o["keys"][level_i] == w["keys"][level_i]]
            if pool:
                return {c: sum(o["q"][c] for o in pool) / len(pool) for c in RECIPE}, level_i
        return None, None

    out = {}
    for pid in pids:
        mine = [w for w in wins if w["winner"] == pid]
        if len(mine) < min_wins:
            continue
        diffs, fallback = [], 0
        for w in mine:
            b, lv = baseline(w)
            if b is None:
                continue
            fallback += lv > 0
            diffs.append({c: w["q"][c] - b[c] for c in RECIPE})
        res = {"wins": len(diffs), "fallback_wins": fallback}
        for k, c in enumerate(RECIPE):
            xs = [d[c] for d in diffs]
            lo, hi = statlib.bca_ci(xs, lambda v: sum(v) / len(v), B=B, seed=400 + k, level=level)
            res[c] = {"tilt": r3(sum(xs) / len(xs)), "ci": [r3(lo), r3(hi)],
                      "share": r3(sum(w["q"][c] for w in mine) / len(mine))}
        out[pid] = res
    return out


# ---------------------------------------------------------------------------
# 1.7 "vs the table" markers
# ---------------------------------------------------------------------------

# Per-game stats that get a marker, with the direction that is good for the player: 1 good up,
# -1 good down, 0 neutral. Fixed in advance (stats proposal 1.7 and answer Q15: steals count as good).
MARKER_STATS = {
    "opening_dots": 1, "luck": 1, "production_index": 1, "steals": 1, "built_city": 1, "monopoly_cards": 1,
    "stolen_from": -1, "cards_discarded": -1, "blocked_by_robber": -1,
    "trades": 0, "bank_trades": 0, "built_road": 0, "built_ship": 0, "built_settlement": 0, "max_hand": 0,
    "knights": 0, "robber_moves": 0, "longest_road_length": 0, "dev_cards_bought": 0,
    "vp": 1, "vp_settlements": 1, "vp_cities": 1, "vp_vp_cards": 1, "vp_largest_army": 1, "vp_longest_road": 1,
    "vp_islands": 1,
}


def per_game_values(game, replay):
    """{stat: {pid: value}} for every seat of one game, for the stats each source supports."""
    out = defaultdict(dict)
    rows = game["players"]
    for r in rows:
        pid = r["player"]
        if r.get("vp") is not None:
            out["vp"][pid] = r["vp"]
        vb = r.get("vp_breakdown")
        if vb and all(x.get("vp_breakdown") for x in rows):
            for k in ("settlements", "cities", "vp_cards", "largest_army", "longest_road", "islands"):
                out["vp_" + k][pid] = vb.get(k, 0)
        dc = r.get("dev_cards_bought")
        if dc and all(x.get("dev_cards_bought") for x in rows):
            out["dev_cards_bought"][pid] = sum(dc.values())
    if replay and set(replay["players"]) == {r["player"] for r in rows}:
        prod_mean = sum(s["resources_from_dice"] for s in replay["players"].values()) / len(rows)
        for pid, st in replay["players"].items():
            for k in ("opening_dots", "steals", "monopoly_cards", "stolen_from", "cards_discarded", "blocked_by_robber",
                      "trades", "bank_trades", "max_hand", "robber_moves", "longest_road_length"):
                out[k][pid] = st[k]
            out["luck"][pid] = st["resources_from_dice"] - st["expected_from_dice"]
            if prod_mean:
                out["production_index"][pid] = st["resources_from_dice"] / prod_mean
            for k in ("city", "road", "ship", "settlement"):
                out["built_" + k][pid] = st["built"][k]
            out["knights"][pid] = st["dev_cards_played"]["knight"]
    for k in list(out):
        if len(out[k]) != len(rows):  # a marker needs every seat of the game
            del out[k]
    return out


def table_markers(games, replays, pids, min_games, ranks_of):
    """Within-game deviation in SDs for each player and stat (statlib.within_game_sd_marker), plus the two stats with a
    natural baseline: wins against sum 1/n (z), and beat rate against 0.5 (t interval of the per-game rate)."""
    by_stat = defaultdict(list)
    for g in games:
        for k, v in per_game_values(g, replays.get(g["id"])).items():
            by_stat[k].append(v)
    out = {pid: {} for pid in pids}
    for k, per_game in by_stat.items():
        res = statlib.within_game_sd_marker(per_game, level=statlib.LEVEL, min_games=1)
        for pid in pids:
            m = res.get(pid)
            if m is None or m["games"] < min_games or m["delta"] is None:
                continue
            out[pid][k] = {"delta": r3(m["delta"]), "lo": r3(m["lo"]), "hi": r3(m["hi"]),
                           "clear": m["clear"], "games": m["games"], "good": MARKER_STATS.get(k, 0)}
    z = statlib.norm_ppf(0.5 + statlib.LEVEL / 2)
    for pid in pids:
        won, ev, var, beat = 0, 0.0, 0.0, []
        for g in games:
            if pid not in {r["player"] for r in g["players"]}:
                continue
            n = len(g["players"])
            won += g["winner"] == pid
            ev += 1 / n
            var += (1 / n) * (1 - 1 / n)
            rk = ranks_of(g)
            opp = [o for o in rk if o != pid]
            beat.append(sum(1 if rk[pid] < rk[o] else 0.5 if rk[pid] == rk[o] else 0 for o in opp) / len(opp))
        if len(beat) < min_games:
            continue
        zw = (won - ev) / math.sqrt(var)
        out[pid]["wins"] = {"z": r3(zw), "clear": abs(zw) > z, "good": 1, "games": len(beat)}
        bt = mean_t([b - 0.5 for b in beat])
        out[pid]["beat_rate"] = {"diff": bt["mean"], "lo": bt["lo"], "hi": bt["hi"], "good": 1, "games": len(beat),
                                 "clear": bt["lo"] is not None and (bt["lo"] > 0 or bt["hi"] < 0)}
    return out


# ---------------------------------------------------------------------------
# One view
# ---------------------------------------------------------------------------

def view_insights(games, replays, pids, is_anon, ranks_of, all_view=None, fast=False):
    """Everything above for one slice of games. all_view is the all-games result: a view below the model
    guard (statlib.GUARDS) reuses its opening coefficients and says so. fast lowers resample counts (tests)."""
    G = statlib.GUARDS
    B, draws = (200, 1000) if fast else (2000, 10000)
    out = {"guards": G, "level": statlib.LEVEL}
    data = opening_data(games, replays)
    if len(data) >= G["model_games"]:
        out["opening"] = opening_effect(data)
        out["opening"]["source"] = "this view"
    elif all_view and all_view.get("opening"):
        out["opening"] = {**all_view["opening"], "source": "all games", "view_games": len(data)}
    if all_view is None and len(data) >= G["model_games"]:
        out["opening_robustness"] = opening_robustness(data, is_anon)
    if len(data) >= G["model_games"]:
        out["best_opener"] = best_opener(data, draws=draws)
    out["opening_by_player"] = opening_by_player(data, is_anon, G["player_rows"])
    out["seat_effect"] = seat_effect(games, draws=draws)
    units = profile_units(games, replays)
    out["trade_bank"] = trade_bank_profile(units, pids, G["player_rows"], B=B)
    out["steal_share"] = steal_share(units, pids, G["player_rows"], B=B)
    out["win_recipe"] = win_recipe(games, pids, 10, B=B)
    out["dice_calibration"] = dice_calibration(games)
    out["markers"] = table_markers(games, replays, pids, G["player_rows"], ranks_of)
    return out
