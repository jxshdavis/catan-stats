"""Resources: what the opening settlements sit on, whether that predicts the winner, and each player's mix.

Reads opening_picks[].res from data/replay_events.json (decoder v2: dots per resource under each setup
settlement at the moment it was placed, [wood, brick, sheep, wheat, ore, gold]) and production (cards from
dice per resource) from data/replays.json. Gold is left out of every share: no opening has touched gold so
far, and gold from dice is a free pick, not a resource.

views[v]["resources"]:
    model       conditional logit of the winner on opening dots per resource, each centered on the table
                (Firth, profile intervals), the total-dots model, and a likelihood ratio test of whether the
                mix matters beyond total dots. Views under 30 games reuse the all-games fit.
    missing     per resource: seats whose opening touched none of it, wins against chance (sum k/n) and
                against their total opening dots, with exact Poisson-binomial bands and p values.
    distinct    the same for the number of different resources the opening touched.
    players     per regular with 10+ games: opening dots share and dice cards share per resource against the
                rest of the same tables, 95% game-cluster bootstrap intervals, and the favorite resource.
    table       the pooled share of each resource over every seat in the view (board composition).
"""

from __future__ import annotations

import math
import random

import statlib

KEY = "resources"
RESOURCES = ["wood", "brick", "sheep", "wheat", "ore"]
G = statlib.GUARDS
LEVEL = statlib.LEVEL


def r3(x):
    return None if x is None else round(x, 3)


def r4(x):
    return None if x is None else round(x, 4)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def opening_rows(games, events):
    """Per game with an event log: seats (player ids in seat order), opening dots per resource per seat,
    and the winner's seat index."""
    out = []
    for g in games:
        ev = events.get(g["id"])
        if not ev or not ev.get("opening_picks") or "res" not in ev["opening_picks"][0]:
            continue
        seats = ev["seats"]
        if g["winner"] not in seats:
            continue
        res = [[0] * 5 for _ in seats]
        for op in ev["opening_picks"]:
            if op["pick"] <= 2:
                for k in range(5):
                    res[op["seat"] - 1][k] += op["res"][k]
        out.append({"game": g["id"], "seats": seats, "n": len(seats), "res": res, "win": seats.index(g["winner"])})
    return out


def dice_rows(games, replays):
    """Per game with a replay: {player: cards from dice per resource}."""
    out = []
    for g in games:
        rp = replays.get(g["id"])
        if not rp:
            continue
        rows = {p: [st["production"][r] for r in RESOURCES] for p, st in rp["players"].items()
                if st.get("production")}
        if len(rows) == len(g["players"]):
            out.append({"game": g["id"], "rows": rows})
    return out


# ---------------------------------------------------------------------------
# Opening resources and winning
# ---------------------------------------------------------------------------

def centered_strata(data, feats):
    strata = []
    for d in data:
        X = [feats(d, i) for i in range(d["n"])]
        m = [sum(x[k] for x in X) / d["n"] for k in range(len(X[0]))]
        strata.append({"X": [[x[k] - m[k] for k in range(len(m))] for x in X],
                       "y": [1 if i == d["win"] else 0 for i in range(d["n"])]})
    return strata


def win_model(data, level=LEVEL):
    """P(i wins g) proportional to exp(sum_r b_r x_igr), x = opening dots on resource r minus the table mean,
    Firth-penalized, profile intervals. The LR test compares it with one shared b on total dots (4 df),
    both fit by maximum likelihood."""
    s5 = centered_strata(data, lambda d, i: d["res"][i])
    s1 = centered_strata(data, lambda d, i: [sum(d["res"][i])])
    fit = statlib.cond_logit(s5, firth=True)
    per = {}
    for k, r in enumerate(RESOURCES):
        lo, hi = statlib.profile_ci(s5, k, level=level, firth=True, fit=fit)
        b = fit["beta"][k]
        per[r] = {"b": r4(b), "se": r4(fit["se"][k]), "or": r3(math.exp(b)),
                  "or_ci": [r3(math.exp(lo)), r3(math.exp(hi))]}
    f1 = statlib.cond_logit(s1, firth=True)
    lo, hi = statlib.profile_ci(s1, 0, level=level, firth=True, fit=f1)
    ml5, ml1 = statlib.cond_logit(s5, firth=False), statlib.cond_logit(s1, firth=False)
    lr = max(0.0, 2 * (ml5["loglik"] - ml1["loglik"]))
    return {"games": len(data), "per": per,
            "total": {"b": r4(f1["beta"][0]), "or": r3(math.exp(f1["beta"][0])),
                      "or_ci": [r3(math.exp(lo)), r3(math.exp(hi))]},
            "lr": {"chi2": r3(lr), "df": 4, "p": r3(statlib.chi2_sf(lr, 4))}}


def poisson_binomial(ps):
    """Exact distribution of a sum of independent Bernoullis with probabilities ps."""
    dist = [1.0]
    for p in ps:
        nxt = [0.0] * (len(dist) + 1)
        for k, v in enumerate(dist):
            nxt[k] += v * (1 - p)
            nxt[k + 1] += v * p
        dist = nxt
    return dist


def pb_summary(ps, observed, level=LEVEL):
    """Band (central `level`) and two-sided exact p for an observed count under Poisson-binomial(ps)."""
    dist = poisson_binomial(ps)
    cdf, acc = [], 0.0
    for v in dist:
        acc += v
        cdf.append(acc)
    a = (1 - level) / 2
    lo = next(k for k, c in enumerate(cdf) if c >= a)
    hi = next(k for k, c in enumerate(cdf) if c >= 1 - a)
    o = int(round(observed))
    below = cdf[o]
    above = 1 - (cdf[o - 1] if o > 0 else 0.0)
    return lo, hi, min(1.0, 2 * min(below, above))


def group_test(data, b_total, member):
    """Seats where member(d, i) holds: wins, chance expectation (each seat 1/n) and expectation given every
    seat's total opening dots (the total-dots model), with exact bands and two-sided p values for both."""
    seats = wins = 0
    p_chance, p_dots = [], []
    for d in data:
        tot = [sum(r) for r in d["res"]]
        m = sum(tot) / d["n"]
        w = [math.exp(b_total * (t - m)) for t in tot]
        W = sum(w)
        idx = [i for i in range(d["n"]) if member(d, i)]
        if not idx:
            continue
        seats += len(idx)
        wins += sum(1 for i in idx if i == d["win"])
        p_chance.append(len(idx) / d["n"])
        p_dots.append(sum(w[i] for i in idx) / W)
    if not seats:
        return None
    lo, hi, p = pb_summary(p_chance, wins)
    dlo, dhi, dp = pb_summary(p_dots, wins)
    return {"seats": seats, "games": len(p_chance), "wins": wins,
            "expected": r3(sum(p_chance)), "lo": lo, "hi": hi, "p": r3(p),
            "expected_dots": r3(sum(p_dots)), "lo_dots": dlo, "hi_dots": dhi, "p_dots": r3(dp)}


def winning(data):
    if len(data) < G["model_games"]:
        return None
    model = win_model(data)
    b = model["total"]["b"]
    missing = {r: group_test(data, b, lambda d, i, k=k: d["res"][i][k] == 0) for k, r in enumerate(RESOURCES)}
    distinct = {}
    for c in range(1, 6):
        t = group_test(data, b, lambda d, i, c=c: sum(1 for v in d["res"][i] if v > 0) == c)
        if t:
            distinct[str(c)] = t
    return {"model": model, "missing": missing, "distinct": distinct}


# ---------------------------------------------------------------------------
# Each player's resource mix against the table
# ---------------------------------------------------------------------------

def mix_units(per_game):
    """per_game: list of {player: [5 counts]}. Returns per game {player: (own counts, rest-of-table counts)}."""
    units = []
    for rows in per_game:
        tot = [sum(v[k] for v in rows.values()) for k in range(5)]
        units.append({p: (v, [tot[k] - v[k] for k in range(5)]) for p, v in rows.items()})
    return units


def share_diff(units, pid):
    """Pooled share of each resource in the player's counts, the rest of the same tables' pooled share, and
    the difference (None if either side is empty)."""
    own, rest = [0.0] * 5, [0.0] * 5
    for u in units:
        if pid in u:
            a, b = u[pid]
            for k in range(5):
                own[k] += a[k]
                rest[k] += b[k]
    so, sr = sum(own), sum(rest)
    if so <= 0 or sr <= 0:
        return None
    s = [own[k] / so for k in range(5)]
    t = [rest[k] / sr for k in range(5)]
    return s, t, [s[k] - t[k] for k in range(5)]


def player_mix(units, pid, B, seed, level=LEVEL):
    mine = [u for u in units if pid in u]
    est = share_diff(mine, pid)
    if est is None:
        return None
    s, t, d = est
    rng = random.Random(seed)
    draws = [[] for _ in range(5)]
    n = len(mine)
    for _ in range(B):
        e = share_diff([mine[rng.randrange(n)] for _ in range(n)], pid)
        if e is None:
            continue
        for k in range(5):
            draws[k].append(e[2][k])
    a = (1 - level) / 2
    lo = [statlib.quantile(x, a) for x in draws]
    hi = [statlib.quantile(x, 1 - a) for x in draws]
    return {"share": [r4(x) for x in s], "table": [r4(x) for x in t], "diff": [r4(x) for x in d],
            "lo": [r4(x) for x in lo], "hi": [r4(x) for x in hi], "games": n}


def favorite(mix):
    """The resource whose share is furthest above the table's. clear: its interval excludes 0."""
    k = max(range(5), key=lambda j: mix["diff"][j])
    return {"resource": RESOURCES[k], "diff": mix["diff"][k], "lo": mix["lo"][k], "hi": mix["hi"][k],
            "share": mix["share"][k], "table": mix["table"][k], "clear": mix["lo"][k] > 0}


def pooled_table(per_game):
    tot = [sum(v[k] for rows in per_game for v in rows.values()) for k in range(5)]
    s = sum(tot)
    return [r4(x / s) for x in tot] if s else None


def mixes(games, replays, events, ctx):
    B = 200 if ctx.get("fast") else statlib.B_DESCRIPTIVE
    op = opening_rows(games, events)
    open_games = [{d["seats"][i]: d["res"][i] for i in range(d["n"])} for d in op]
    dice_games = [d["rows"] for d in dice_rows(games, replays)]
    ou, du = mix_units(open_games), mix_units(dice_games)
    players = {}
    for j, pid in enumerate(ctx["pids"]):
        if ctx["is_anon"](pid):
            continue
        n = sum(1 for u in ou if pid in u)
        if n < G["player_rows"]:
            continue
        o = player_mix(ou, pid, B, seed=100 + j)
        dm = player_mix(du, pid, B, seed=200 + j)
        if o is None:
            continue
        players[pid] = {"opening": o, "dice": dm, "favorite": favorite(o),
                        "dice_favorite": favorite(dm) if dm else None}
    return {"players": players, "B": B,
            "table": {"opening": pooled_table(open_games), "dice": pooled_table(dice_games)},
            "games": {"opening": len(open_games), "dice": len(dice_games)}}


# ---------------------------------------------------------------------------
# Module entry points (see build.MODULES)
# ---------------------------------------------------------------------------

_WIN_MEMO = {}  # game ids -> winning(), so the all-games view reuses compute_all's fit


def compute_all(games, replays, events, ctx):
    data = opening_rows(games, events)
    w = winning(data)
    _WIN_MEMO[tuple(d["game"] for d in data)] = w
    return {"resources": RESOURCES, "level": LEVEL, "winning": w}


def compute_view(games, replays, events, ctx, all_result):
    data = opening_rows(games, events)
    if len(data) >= G["model_games"]:
        key = tuple(d["game"] for d in data)
        if key not in _WIN_MEMO:
            _WIN_MEMO[key] = winning(data)
        w, source = _WIN_MEMO[key], "this view"
    else:
        w, source = all_result["winning"], "all games"
    return {"winning": w, "winning_source": source, "view_games": len(data), **mixes(games, replays, events, ctx)}
