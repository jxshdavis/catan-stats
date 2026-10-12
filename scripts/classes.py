"""Player classes (stats proposal 1.4) and the Phase 7 extras that share its inputs.

Everything here reads data/replay_events.json (decoder v2) through scripts/series.py, plus the
per-player replay totals for the trade and bank axes (computed by the functions in insights.py).

stats.json["classes"] (all games, from compute_all):
    badges        per-player badge decision (all-games view only, spec 1.4 badge rule)
    axes          REML tau^2, Cochran's Q and the gate for each badge axis
    games         per game: t* (roll index) and the winner's board-VP gap there (comebacks)
views[v]["classes"] (every view, from compute_view):
    profile       spending mix, trade and bank axes: raw MH estimate, shrunk estimate, intervals,
                  losses-only estimate (and Navigator in Seafarers views)
    comebacks     gallery ids and counts at d >= 0.2 and gaps of 2, 3 and 4 VP, and the record
    first_to      first-to-c conversion for c = 0.5 and 0.75
    draft         draft-order grid, pick percentile histogram, per-player pick percentile
    km            Kaplan-Meier: first dev buy, knight hold time, first city
    hoarder       per-player share of 7-discards that were avoidable (Hoarder column)
    dev_luck      dev draw luck O - E per player
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path

import insights
import series
import statlib

KEY = "classes"
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"
CACHE_VERSION = 1  # bump when profile() changes

G = statlib.GUARDS
LEVEL = statlib.LEVEL
GATE_P = 0.10  # Cochran's Q gate for a badge axis
MAX_BADGES = 2
KM_MIN_RISK = 5
KNIGHT_MIN = 20
# Badge axes, fixed in advance (spec 1.4 table). scale "rd": risk difference, table value 0;
# "log_rr": log rate ratio, table value 0 (ratio 1).
AXES = [
    {"key": "dev", "badge": "Scientist", "label": "Dev card share of spending", "scale": "rd"},
    {"key": "city", "badge": "Empire Builder", "label": "City share of spending", "scale": "rd"},
    {"key": "expansion", "badge": "Expander", "label": "Settlement, road and ship share of spending", "scale": "rd"},
    {"key": "trade", "badge": "Ambassador", "label": "Player-trade rate vs the table", "scale": "log_rr"},
    {"key": "bank", "badge": "Merchant", "label": "Bank share of cards received", "scale": "rd"},
]
AXIS_KEYS = [a["key"] for a in AXES]
SPEND_PARTS = {"dev": ("dev",), "city": ("city",), "expansion": ("settlement", "road", "ship")}
CITY_COST = (0, 0, 0, 2, 3)  # [wood, brick, sheep, wheat, ore]
DEV_COST = (0, 0, 1, 1, 1)
CITY_LIMIT = 4
HEX_NEIGHBORS = [(1, -1), (1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1)]
UNIT = [(1, 0, 0), (0, 1, 0), (0, 0, 1)]
PAIR = [(1, 1, 0), (1, 0, 1), (0, 1, 1)]


def r3(x):
    return None if x is None else round(x, 3)


def r4(x):
    return None if x is None else round(x, 4)


def _sd(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def _is_regular(pid, ctx):
    return not ctx["is_anon"](pid)


def _target(game):
    return (game.get("settings") or {}).get("vp_to_win") or 10


# ---------------------------------------------------------------------------
# Per-game facts, computed once per build
# ---------------------------------------------------------------------------

_FACTS = {}


def facts(game, ev, replay=None):
    """Everything the module needs from one game's event log, memoized by game id and log identity."""
    key = (game["id"], id(ev), id(replay))
    if key in _FACTS:
        return _FACTS[key]
    rows = series.full_rows(ev)
    seats = ev["seats"]
    n = len(seats)
    last = rows[-1]
    spent = last["spent"]
    f = {
        "id": game["id"], "seats": seats, "n": n, "G": _target(game), "winner": game["winner"],
        "scenario": (game.get("settings") or {}).get("scenario"),
        "expansion": (game.get("settings") or {}).get("expansion"),
        "N": [sum(spent[k][j] for k in ("dev", "city", "settlement", "road", "ship")) for j in range(n)],
        "spend": {ax: [sum(spent[k][j] for k in parts) for j in range(n)] for ax, parts in SPEND_PARTS.items()},
        "ship": list(spent["ship"]),
        "picked": list(last.get("picked") or [0] * n),
        "own_turns": [sum(1 for r in ev["roll_log"] if r["roller"] == s + 1) for s in range(n)],
    }
    f["comeback"] = _comeback(f, rows)
    f["first_to"] = {c: _first_to(f, rows, c) for c in (0.5, 0.75)}
    f["unit"] = _profile_unit(game, replay, ev, f) if replay else None
    _FACTS[key] = f
    return f


def _profile_unit(game, replay, ev, f):
    """insights.profile_units entry for this game, with free picks added to the received-cards denominator.

    The decoder's picked counts every free card taken: gold from dice (already in resources_from_dice),
    gold at setup, Year of Plenty and fog. Picks beyond gold_from_dice are added (folded into the
    monopoly_cards field, which insights.received_total sums; only the denominator changes)."""
    units = insights.profile_units([game], {game["id"]: replay})
    if not units:
        return None
    u = units[0]
    st = {}
    for pid, s in u["st"].items():
        j = f["seats"].index(pid) if pid in f["seats"] else None
        extra = max(0, f["picked"][j] - (s.get("gold_from_dice") or 0)) if j is not None else 0
        st[pid] = {**s, "monopoly_cards": s["monopoly_cards"] + extra}
    return {**u, "st": st}


def _comeback(f, rows):
    """t* = first state row where the max board VP (VP minus VP cards held) reaches G - 3. The winner's gap
    there is max - winner's board VP; d = gap / G. Also the VP cards the winner held at the finish."""
    w = f["seats"].index(f["winner"]) if f["winner"] in f["seats"] else None
    if w is None:
        return None
    G_ = f["G"]
    vp_cards = rows[-1]["vp_cards_held"][w]
    for row in rows:
        b = series.board_vp(row)
        top = max(b)
        if top >= G_ - 3:
            gap = top - b[w]
            return {"t_roll": row["roll_index"], "kind": row["kind"], "gap": gap, "d": gap / G_,
                    "leaders": [f["seats"][j] for j, v in enumerate(b) if v == top],
                    "winner_bvp": b[w], "max_bvp": top, "vp_cards": vp_cards}
    return {"t_roll": None, "gap": None, "d": None, "vp_cards": vp_cards}


def _first_to(f, rows, c):
    """tau_c = first state row with max board VP >= 2 + c (G - 2). F = seats at or above that line then.
    Returns {seat index: 1/|F|} or None when nobody reached it on board VP before the end."""
    line = 2 + c * (f["G"] - 2)
    for row in rows:
        b = series.board_vp(row)
        F = [j for j, v in enumerate(b) if v >= line - 1e-9]
        if F:
            return {j: 1 / len(F) for j in F}
    return None


# ---------------------------------------------------------------------------
# Spending mix, trade and bank axes (MH contrasts against the rest of the table)
# ---------------------------------------------------------------------------

def _mh_spend(recs, pid, axis):
    strata = []
    for f in recs:
        j = f["seats"].index(pid)
        if axis == "navigator":
            y, N = f["ship"], f["spend"]["expansion"]
        else:
            y, N = f["spend"][axis], f["N"]
        strata.append((y[j], N[j], sum(y) - y[j], sum(N) - N[j]))
    res = statlib.mh_risk_difference(strata)
    return res["rd"] if res else None


def axis_value(recs, pid, axis):
    """MH estimate of one axis for one player over the given game records (repeats allowed)."""
    mine = [f for f in recs if pid in f["seats"]]
    if not mine:
        return None
    if axis in SPEND_PARTS or axis == "navigator":
        return _mh_spend(mine, pid, axis)
    units = [f["unit"] for f in mine if f["unit"]]
    if not units:
        return None
    if axis == "trade":
        rr = insights.mh_trade_rr(units, pid)
        return math.log(rr) if rr and rr > 0 else None
    return insights.mh_bank_rd(units, pid)


def estimates(recs, pids, axes):
    """{axis: {pid: (all-games estimate, losses-only estimate)}}."""
    out = {a: {} for a in axes}
    for pid in pids:
        mine = [f for f in recs if pid in f["seats"]]
        lost = [f for f in mine if f["winner"] != pid]
        for a in axes:
            out[a][pid] = (axis_value(mine, pid, a), axis_value(lost, pid, a) if lost else None)
    return out


def _reml_fixed(y, se, tau2):
    """Random-effects mean with tau^2 held fixed (views that reuse the all-games tau^2)."""
    w = [1 / (s * s + tau2) for s in se]
    return sum(wi * yi for wi, yi in zip(w, y)) / sum(w)


def _shrink_set(y, se, tau2_fixed=None):
    """REML (or fixed tau^2) then normal-normal shrinkage. Returns (fit dict, [(theta, post_sd)])."""
    if tau2_fixed is None:
        fit = statlib.reml_tau2(y, se)
    else:
        fit = {"tau2": tau2_fixed, "mu": _reml_fixed(y, se, tau2_fixed), "p": None, "Q": None, "df": len(y) - 1}
    return fit, statlib.shrink(y, se, fit["tau2"], fit["mu"])


def profile(recs, pids, axes, B, seed, tau2_fixed=None, want_stability=False):
    """Raw MH estimates, bootstrap SEs, REML tau^2 with Cochran's Q, shrunk estimates and their game-cluster
    bootstrap intervals (each draw re-estimates every player and re-fits tau^2), losses-only estimates.

    tau2_fixed: {axis: tau^2} to hold tau^2 at the all-games value (small views)."""
    est = estimates(recs, pids, axes)
    draws = statlib.cluster_bootstrap(recs, lambda s: estimates(s, pids, axes), B=B, seed=seed)
    z = statlib.z_for(LEVEL)
    out = {}
    for a in axes:
        ok = [p for p in pids if est[a][p][0] is not None]
        se = {p: _sd([d[a][p][0] for d in draws]) for p in ok}
        ok = [p for p in ok if se[p] and se[p] > 0]
        res = {"players": {}, "k": len(ok)}
        if len(ok) >= 2:
            y = [est[a][p][0] for p in ok]
            s = [se[p] for p in ok]
            t2 = None if tau2_fixed is None else tau2_fixed.get(a)
            fit, th = _shrink_set(y, s, t2)
            res.update({"tau2": r4(fit["tau2"]), "mu": r4(fit["mu"]), "Q": r3(fit.get("Q")), "df": fit.get("df"),
                        "p": r4(fit.get("p")), "tau2_source": "this view" if t2 is None else "all games"})
            res["gate"] = bool(fit["tau2"] > 0 and fit.get("p") is not None and fit["p"] < GATE_P)
            # Bootstrap the whole shrinkage step: per draw, estimates for every player, tau^2 re-fitted.
            th_b = {p: [] for p in ok}
            stab = {p: 0 for p in ok}
            for d in draws:
                yb = [(p, d[a][p][0]) for p in ok if d[a][p][0] is not None]
                if len(yb) < 2:
                    continue
                fb, tb = _shrink_set([v for _, v in yb], [se[p] for p, _ in yb], t2)
                gate_b = fb["tau2"] > 0 and fb.get("p") is not None and fb["p"] < GATE_P
                for (p, _), (tv, sdv) in zip(yb, tb):
                    th_b[p].append(tv)
                    lb = d[a][p][1]
                    if want_stability and gate_b and tv - z * sdv > 0 and lb is not None and lb > 0:
                        stab[p] += 1
            for p, (tv, sdv) in zip(ok, th):
                lo, hi = statlib.percentile_ci(th_b[p], LEVEL)
                rlo, rhi = statlib.percentile_ci([d[a][p][0] for d in draws], LEVEL)
                row = {"raw": r4(est[a][p][0]), "raw_ci": [r4(rlo), r4(rhi)], "se": r4(se[p]),
                       "theta": r4(tv), "theta_ci": [r4(lo), r4(hi)], "theta_sd": r4(_sd(th_b[p])),
                       "loss": r4(est[a][p][1])}
                if want_stability:
                    row["stability"] = r3(stab[p] / len(draws))
                res["players"][p] = row
        else:
            for p in ok:
                rlo, rhi = statlib.percentile_ci([d[a][p][0] for d in draws], LEVEL)
                res["players"][p] = {"raw": r4(est[a][p][0]), "raw_ci": [r4(rlo), r4(rhi)], "se": r4(se[p]),
                                     "loss": r4(est[a][p][1])}
        out[a] = res
    return out


def badges(prof, games_of, min_games=G["badges"]):
    """Badge rule (spec 1.4): the axis passes the gate (tau^2 > 0 and Q p < 0.10), the bootstrap interval of the
    shrunk estimate lies above the table value, the losses-only estimate has the same sign, and the player has
    at least min_games games. At most MAX_BADGES, keeping the largest theta / bootstrap SD of theta."""
    out = {}
    for pid, n in games_of.items():
        if n < min_games:
            out[pid] = {"games": n, "eligible": False, "badges": []}
            continue
        cands = []
        for ax in AXES:
            a = prof.get(ax["key"]) or {}
            r = a.get("players", {}).get(pid)
            if not a.get("gate") or not r or r.get("theta_ci") is None or r["theta_ci"][0] is None:
                continue
            if r["theta_ci"][0] > 0 and r["loss"] is not None and r["loss"] > 0:
                score = r["theta"] / r["theta_sd"] if r.get("theta_sd") else 0
                cands.append({"axis": ax["key"], "name": ax["badge"], "theta": r["theta"], "ci": r["theta_ci"],
                              "loss": r["loss"], "stability": r.get("stability"), "score": r3(score)})
        cands.sort(key=lambda c: -c["score"])
        out[pid] = {"games": n, "eligible": True, "badges": cands[:MAX_BADGES], "dropped": [c["axis"] for c in cands[MAX_BADGES:]]}
    return out


# ---------------------------------------------------------------------------
# Comebacks and first-to-c
# ---------------------------------------------------------------------------

THRESHOLDS = [("d20", "d >= 0.2", lambda c: c["d"] >= 0.2 - 1e-9), ("gap2", "2 VP", lambda c: c["gap"] >= 2),
              ("gap3", "3 VP", lambda c: c["gap"] >= 3), ("gap4", "4 VP", lambda c: c["gap"] >= 4)]


def comebacks(fs):
    rows = [f for f in fs if f["comeback"] and f["comeback"]["gap"] is not None]
    gallery = sorted((f for f in rows if f["comeback"]["gap"] >= 2), key=lambda f: (-f["comeback"]["d"], f["id"]))
    counts = {k: sum(1 for f in rows if test(f["comeback"])) for k, _, test in THRESHOLDS}
    rec = None
    if rows:
        best = max(f["comeback"]["d"] for f in rows)
        if best > 0:
            rec = [f["id"] for f in rows if abs(f["comeback"]["d"] - best) < 1e-12]
    return {"games": len(fs), "with_t_star": len(rows), "counts": counts, "gallery": [f["id"] for f in gallery],
            "record": rec}


def first_to(fs, ctx, c):
    """Group: P(first to c wins) with ties split 1/|F|, Wilson interval, baseline mean(1/n).
    Per player (10+ games): conversion P(win | first) and comeback P(win | not first) with fractional counts."""
    used = [f for f in fs if f["first_to"][c] is not None]
    k = sum(w for f in used for j, w in f["first_to"][c].items() if f["seats"][j] == f["winner"])
    grp = None
    if used:
        lo, hi = statlib.wilson(k, len(used))
        grp = {"p": r3(k / len(used)), "ci": [r3(lo), r3(hi)], "wins": r3(k), "games": len(used),
               "base": r3(sum(1 / f["n"] for f in used) / len(used))}
    players = {}
    for pid in ctx["pids"]:
        mine = [f for f in used if pid in f["seats"]]
        if len(mine) < G["player_rows"]:
            continue
        nf = kf = nn = kn = 0.0
        for f in mine:
            j = f["seats"].index(pid)
            w = f["first_to"][c].get(j, 0.0)
            won = 1.0 if f["winner"] == pid else 0.0
            nf += w
            kf += w * won
            nn += 1 - w
            kn += (1 - w) * won
        row = {"games": len(mine), "base": r3(sum(1 / f["n"] for f in mine) / len(mine)),
               "first": r3(nf), "first_wins": r3(kf), "not_first": r3(nn), "not_first_wins": r3(kn)}
        if nf > 0:
            lo, hi = statlib.wilson(kf, nf)
            row.update({"conv": r3(kf / nf), "conv_ci": [r3(lo), r3(hi)]})
        if nn > 0:
            lo, hi = statlib.wilson(kn, nn)
            row.update({"comeback": r3(kn / nn), "comeback_ci": [r3(lo), r3(hi)]})
        players[pid] = row
    return {"c": c, "group": grp, "skipped": len(fs) - len(used), "players": players}


# ---------------------------------------------------------------------------
# Draft-order grid and pick percentile
# ---------------------------------------------------------------------------

def corner_hexes(v):
    offs = UNIT if sum(v) == 1 else PAIR
    return [(v[0] - o[0], v[1] - o[1]) for o in offs]


def start_region(ev, desert_is_water):
    """Land hexes from the robber logs (every non-pirate robber event lists every legal land hex except the
    robber's current one, which is its prior_hex), split into islands by hex adjacency; in Through the Desert
    zero-dot land (the desert) separates islands. Returns the largest island as a set of hexes, or None."""
    dots = {}
    for r in ev.get("robber_events") or []:
        if r.get("pirate") or not r.get("candidates"):
            continue
        for c in r["candidates"]:
            dots[tuple(c["hex"])] = c["dots"]
        if r.get("prior_hex") is not None:
            dots.setdefault(tuple(r["prior_hex"]), None)
    if not dots:
        return None
    land = {h for h, d in dots.items() if not (desert_is_water and d == 0)}
    seen, best = set(), set()
    for h in sorted(land):
        if h in seen:
            continue
        comp, stack = {h}, [h]
        seen.add(h)
        while stack:
            a = stack.pop()
            for dx, dy in HEX_NEIGHBORS:
                b = (a[0] + dx, a[1] + dy)
                if b in land and b not in seen:
                    seen.add(b)
                    comp.add(b)
                    stack.append(b)
        if len(comp) > len(best):
            best = comp
    return best


def midrank(chosen, values):
    below = sum(1 for v in values if v < chosen)
    tie = sum(1 for v in values if v == chosen)
    return (below + 0.5 * tie) / len(values)


def draft_picks(game, ev):
    """Per opening pick: L_t = the decoder's legal corners restricted to the start region (base: the whole
    board; New Shores: the main island; Through the Desert: the mainland), b_t = max pips over L_t, and the
    chosen corner's mid-rank percentile in L_t. Returns (picks, dropped legal corners) or (None, reason)."""
    scen = (game.get("settings") or {}).get("scenario")
    region = None
    if scen is not None:
        region = start_region(ev, desert_is_water=scen == "through_the_desert")
        if not region:
            return None, "no robber move to read the land from"
    out, dropped = [], 0
    for p in ev["opening_picks"]:
        legal = [(tuple(c[:3]), c[3]) for c in p["legal"]]
        if region is not None:
            keep = [(v, s) for v, s in legal if any(h in region for h in corner_hexes(v))]
            dropped += len(legal) - len(keep)
            legal = keep
        corner = tuple(p["corner"])
        if not legal or corner not in {v for v, _ in legal}:
            return None, "an opening pick outside the start region"
        vals = [s for _, s in legal]
        b = max(vals)
        out.append({"seat": p["seat"], "pick": p["pick"], "order": p["order"], "pid": ev["seats"][p["seat"] - 1],
                    "pips": p["pips"], "b": b, "pct": midrank(p["pips"], vals), "top": p["pips"] == b, "L": len(vals)})
    return out, dropped


def in_draft_scope(game):
    """Base, New Shores and Through the Desert (players open on the mainland, answer Q14). Four Islands and
    Fog Islands stay out: their start region cannot be read from the board without circularity."""
    s = game.get("settings") or {}
    exp, scen = s.get("expansion"), s.get("scenario")
    return (exp == "base" and scen is None) or (exp == "seafarers" and scen in ("new_shores", "through_the_desert"))


def draft(games, events, ctx):
    scope = [g for g in games if g["id"] in events and in_draft_scope(g)]
    picks, excluded, dropped = [], [], 0
    for g in scope:
        ps, info = draft_picks(g, events[g["id"]])
        if ps is None:
            excluded.append({"id": g["id"], "why": info})
            continue
        dropped += info
        for p in ps:
            picks.append({**p, "game": g["id"], "n": len(events[g["id"]]["seats"])})
    if not picks:
        return {"games": 0, "excluded": excluded}
    grid = {}
    for n in (3, 4):
        cells = defaultdict(list)
        gs = {p["game"] for p in picks if p["n"] == n}
        for p in picks:
            if p["n"] == n:
                cells[(p["seat"], p["pick"])].append(p)
        if gs:
            grid[str(n)] = {"games": len(gs), "cells": [
                {"seat": s, "pick": k, "order": v[0]["order"], "b": r3(sum(x["b"] for x in v) / len(v)),
                 "chosen": r3(sum(x["pips"] for x in v) / len(v)), "top": r3(sum(x["top"] for x in v) / len(v)),
                 "L": r3(sum(x["L"] for x in v) / len(v)), "n": len(v)}
                for (s, k), v in sorted(cells.items())]}
    hist = [0] * 10
    for p in picks:
        hist[min(9, int(p["pct"] * 10))] += 1
    players = {}
    for pid in ctx["pids"]:
        mine = [p for p in picks if p["pid"] == pid]
        ng = len({p["game"] for p in mine})
        if ng < G["player_rows"]:
            continue
        m, lo, hi = statlib.t_interval([p["pct"] for p in mine])
        k = sum(p["top"] for p in mine)
        wl, wh = statlib.wilson(k, len(mine))
        players[pid] = {"games": ng, "picks": len(mine), "mean_pct": r3(m), "ci": [r3(lo), r3(hi)],
                        "top": r3(k / len(mine)), "top_ci": [r3(wl), r3(wh)]}
    top = sum(p["top"] for p in picks)
    return {"games": len({p["game"] for p in picks}), "picks": len(picks), "grid": grid, "hist": hist,
            "mean_pct": r3(sum(p["pct"] for p in picks) / len(picks)), "top": r3(top / len(picks)),
            "players": players, "excluded": excluded, "dropped_per_pick": r3(dropped / len(picks)),
            "scenarios": sorted({(g.get("settings") or {}).get("scenario") or "base" for g in scope})}


# ---------------------------------------------------------------------------
# Kaplan-Meier: first dev buy, knight hold time, first city
# ---------------------------------------------------------------------------

def km_samples(game, ev):
    """Per seat: (time, event) for first dev buy and first city, and a list for each knight bought.
    Times are in the seat's own turns. Knights are matched to plays first in, first out."""
    n = len(ev["seats"])
    T = [sum(1 for r in ev["roll_log"] if r["roller"] == s + 1) for s in range(n)]
    dev, city = [None] * n, [None] * n
    held = [[] for _ in range(n)]
    knights = [[] for _ in range(n)]
    for e in ev["dev_events"]:
        j = e["seat"] - 1
        if e["action"] == "buy":
            if dev[j] is None:
                dev[j] = e["own_turn"]
            if e["card"] == "knight":
                held[j].append(e["own_turn"])
        elif e["action"] == "play" and e["card"] == "knight" and held[j]:
            knights[j].append((e["own_turn"] - held[j].pop(0), 1))
    for j in range(n):
        knights[j] += [(max(0, T[j] - b), 0) for b in held[j]]
    for e in ev["vp_events"]:
        for c in e["changes"]:
            if c["type"] == "city" and city[c["seat"] - 1] is None:
                city[c["seat"] - 1] = e["own_turn"]
    out = []
    for j in range(n):
        out.append({"pid": ev["seats"][j],
                    "dev": (dev[j], 1) if dev[j] is not None else (T[j], 0),
                    "city": (city[j], 1) if city[j] is not None else (T[j], 0),
                    "knights": knights[j]})
    return out


def km_curve(samples):
    rows = statlib.kaplan_meier([t for t, _ in samples], [e for _, e in samples])
    cut = [r for r in rows if r["n_risk"] >= KM_MIN_RISK]
    return cut


def km_median(rows):
    """Median and its interval from the pointwise log(-log) band (Brookmeyer-Crowley style): the first time S
    drops to 0.5 or below, and the first times the lower and the upper band do (None: not reached)."""
    def first(key):
        return next((r["time"] for r in rows if r[key] is not None and r[key] <= 0.5), None)
    return first("surv"), first("lo"), first("hi")


def km_pack(samples):
    rows = km_curve(samples)
    med, lo, hi = km_median(rows)
    return {"n": len(samples), "events": sum(e for _, e in samples),
            "t": [r["time"] for r in rows], "risk": [r["n_risk"] for r in rows], "s": [r4(r["surv"]) for r in rows],
            "lo": [r4(r["lo"]) for r in rows], "hi": [r4(r["hi"]) for r in rows],
            "median": med, "median_ci": [lo, hi]}


def km_view(games, events, ctx):
    per = []
    for g in games:
        if g["id"] in events:
            per += km_samples(g, events[g["id"]])
    knights = [k for s in per for k in s["knights"]]
    out = {"dev": km_pack([s["dev"] for s in per]), "city": km_pack([s["city"] for s in per]),
           "knight": {"bought": len(knights), "shown": len(knights) >= KNIGHT_MIN, "min": KNIGHT_MIN}}
    if len(knights) >= KNIGHT_MIN:
        out["knight"].update(km_pack(knights))
    cols = {}
    for pid in ctx["pids"]:
        mine = [s for s in per if s["pid"] == pid]
        if len(mine) < G["player_rows"]:
            continue
        row = {"games": len(mine)}
        for k in ("dev", "city"):
            p = km_pack([s[k] for s in mine])
            row[k] = {"median": p["median"], "ci": p["median_ci"], "events": p["events"]}
        kn = [k for s in mine for k in s["knights"]]
        row["knight"] = {"bought": len(kn)}
        if len(kn) >= KNIGHT_MIN:
            p = km_pack(kn)
            row["knight"].update({"median": p["median"], "ci": p["median_ci"], "events": p["events"]})
        cols[pid] = row
    out["players"] = cols
    return out


# ---------------------------------------------------------------------------
# Dev draw luck
# ---------------------------------------------------------------------------

def deck_of(ev):
    """Initial dev deck composition from the decoder's dev_deck field ({card type: count})."""
    d = ev.get("dev_deck")
    return (dict(d), "decoder") if d else (None, "no dev_deck in the replay log")


def dev_luck_game(ev):
    deck, how = deck_of(ev)
    if deck is None:
        return None, how
    buys = [e for e in ev["dev_events"] if e["action"] == "buy"]
    if len(buys) > sum(deck.values()) or any(sum(1 for e in buys if e["card"] == k) > deck[k] for k in deck):
        return None, "buys do not fit the assumed deck"
    rem = dict(deck)
    out = defaultdict(lambda: {"buys": 0, "vp": [0, 0.0, 0.0], "knight": [0, 0.0, 0.0]})
    for e in buys:
        pid = ev["seats"][e["seat"] - 1]
        tot = sum(rem.values())
        row = out[pid]
        row["buys"] += 1
        for key, card in (("vp", "victory_point"), ("knight", "knight")):
            p = rem[card] / tot
            row[key][0] += e["card"] == card
            row[key][1] += p
            row[key][2] += p * (1 - p)
        rem[e["card"]] -= 1
    return dict(out), how


def dev_luck(games, events, ctx):
    z = statlib.z_for(LEVEL)
    acc = defaultdict(lambda: {"games": 0, "buys": 0, "vp": [0, 0.0, 0.0], "knight": [0, 0.0, 0.0]})
    excluded, used, group = [], 0, {"vp": [0, 0.0, 0.0], "knight": [0, 0.0, 0.0], "buys": 0}
    for g in games:
        if g["id"] not in events:
            continue
        res, how = dev_luck_game(events[g["id"]])
        if res is None:
            excluded.append({"id": g["id"], "why": how})
            continue
        used += 1
        for pid in events[g["id"]]["seats"]:
            acc[pid]["games"] += 1
        for pid, r in res.items():
            a = acc[pid]
            a["buys"] += r["buys"]
            group["buys"] += r["buys"]
            for k in ("vp", "knight"):
                for i in range(3):
                    a[k][i] += r[k][i]
                    group[k][i] += r[k][i]

    def pack(v):
        O, E, V = v
        sd = math.sqrt(V)
        return {"O": O, "E": r3(E), "diff": r3(O - E), "lo": r3(O - E - z * sd), "hi": r3(O - E + z * sd),
                "z": r3((O - E) / sd) if sd > 0 else None}
    players = {pid: {"games": a["games"], "buys": a["buys"], "vp": pack(a["vp"]), "knight": pack(a["knight"])}
               for pid, a in acc.items() if pid in ctx["pids"] and a["games"] >= G["player_rows"]}
    return {"games": used, "excluded": excluded, "buys": group["buys"],
            "group": {"vp": pack(group["vp"]), "knight": pack(group["knight"])}, "players": players}


# ---------------------------------------------------------------------------
# Hoarder: avoidable 7-discards
# ---------------------------------------------------------------------------

def _affords(hand, cost):
    return all(h >= c for h, c in zip(hand, cost))


def discard_checks(ev):
    """For every 7-discard: was it avoidable? At the discarding seat's previous end of turn (its last end_turn
    row, or paired_end row in a 5-6 player build phase, before the discard), with that row's hand_cards, the
    seat could afford a city (2 wheat, 3 ore) while owning a settlement and fewer than 4 cities, or a dev card
    (sheep, wheat, ore) while the deck still had cards. Settlements and cities owned come from vp_events
    (every settlement placed, setup included, minus cities); cards left in the deck = dev_deck size minus buys.
    Discards before the seat's first turn ended have no previous end of turn and are returned as None."""
    rows = [r for r in series.full_rows(ev) if r["kind"] in ("end_turn", "paired_end")]
    deck = sum((ev.get("dev_deck") or {}).values())
    buys = sorted(e["action_index"] for e in ev["dev_events"] if e["action"] == "buy")
    builds = [(v["action_index"], c["type"], c["seat"]) for v in ev["vp_events"] for c in v["changes"]
              if c["type"] in ("settlement", "city")]
    out = []
    for d in ev["discard_events"]:
        s = d["seat"]
        prev = None
        for r in rows:
            if r["action_index"] >= d["action_index"]:
                break
            if r["actor"] == s:
                prev = r
        if prev is None or prev.get("hand_cards") is None:
            out.append((s, None))
            continue
        t = prev["action_index"]
        hand = prev["hand_cards"][s - 1]
        setl = sum(1 for a, k, q in builds if a <= t and q == s and k == "settlement")
        city = sum(1 for a, k, q in builds if a <= t and q == s and k == "city")
        left = deck - sum(1 for a in buys if a <= t)
        can_city = setl - city > 0 and city < CITY_LIMIT and _affords(hand, CITY_COST)
        can_dev = left > 0 and _affords(hand, DEV_COST)
        out.append((s, {"city": can_city, "dev": can_dev, "avoidable": can_city or can_dev}))
    return out


def hoarder(games, events, ctx):
    rows = defaultdict(lambda: {"games": 0, "discards": 0, "checked": 0, "avoidable": 0, "city": 0, "dev": 0})
    grp = {"discards": 0, "checked": 0, "avoidable": 0}
    for g in games:
        ev = events.get(g["id"])
        if not ev:
            continue
        for pid in ev["seats"]:
            rows[pid]["games"] += 1
        for s, chk in discard_checks(ev):
            r = rows[ev["seats"][s - 1]]
            r["discards"] += 1
            grp["discards"] += 1
            if chk is None:
                continue
            r["checked"] += 1
            grp["checked"] += 1
            r["avoidable"] += chk["avoidable"]
            grp["avoidable"] += chk["avoidable"]
            r["city"] += chk["city"]
            r["dev"] += chk["dev"]
    players = {}
    for pid in ctx["pids"]:
        r = rows.get(pid)
        if not r or r["games"] < G["player_rows"]:
            continue
        row = dict(r)
        if r["checked"]:
            lo, hi = statlib.wilson(r["avoidable"], r["checked"])
            row.update({"share": r3(r["avoidable"] / r["checked"]), "ci": [r3(lo), r3(hi)]})
        players[pid] = row
    out = {**grp, "players": players}
    if grp["checked"]:
        lo, hi = statlib.wilson(grp["avoidable"], grp["checked"])
        out.update({"share": r3(grp["avoidable"] / grp["checked"]), "ci": [r3(lo), r3(hi)]})
    return out


# ---------------------------------------------------------------------------
# Module entry points
# ---------------------------------------------------------------------------

_VIEW_MEMO = {}


def _recs(games, replays, events):
    return [facts(g, events[g["id"]], replays.get(g["id"])) for g in games if g["id"] in events]


def _games_of(recs, pids):
    return {p: sum(1 for f in recs if p in f["seats"]) for p in pids}


def _cache_key(recs, B):
    h = hashlib.sha256()
    h.update(json.dumps({"B": B, "v": CACHE_VERSION, "axes": AXIS_KEYS, "level": LEVEL}).encode())
    for f in recs:
        h.update(json.dumps([f["id"], f["seats"], f["winner"], f["N"], f["spend"], f["ship"], f["picked"],
                             f["unit"]["st"] if f["unit"] else None], sort_keys=True).encode())
    return h.hexdigest()[:16]


def _profile_cached(recs, pids, axes, B, seed, want_stability, tau2_fixed=None, use_cache=True):
    if not use_cache:
        return profile(recs, pids, axes, B, seed, tau2_fixed=tau2_fixed, want_stability=want_stability)
    key = _cache_key(recs, B) + f"-{seed}-{int(want_stability)}-{','.join(axes)}-{','.join(pids)}-{json.dumps(tau2_fixed, sort_keys=True)}"
    path = CACHE / f"{KEY}-{hashlib.sha256(key.encode()).hexdigest()[:20]}.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            pass
    out = profile(recs, pids, axes, B, seed, tau2_fixed=tau2_fixed, want_stability=want_stability)
    try:
        CACHE.mkdir(exist_ok=True)
        path.write_text(json.dumps(out))
    except OSError:
        pass
    return out


def _view(games, replays, events, ctx, all_tau2=None, all_view=False):
    recs = _recs(games, replays, events)
    B = 200 if ctx.get("fast") else statlib.B_DESCRIPTIVE
    games_of = _games_of(recs, ctx["pids"])
    rows_pids = [p for p in ctx["pids"] if _is_regular(p, ctx) and games_of[p] >= G["player_rows"]]
    seafarers = bool(recs) and all(f["expansion"] == "seafarers" for f in recs)
    axes = AXIS_KEYS + (["navigator"] if seafarers else [])
    out = {"games": len(recs), "level": LEVEL}
    if rows_pids:
        small = len(recs) < G["model_games"]
        tau2_fixed = {a: all_tau2[a] for a in all_tau2 if all_tau2[a] is not None} if small and all_tau2 else None
        prof = _profile_cached(recs, rows_pids, axes, B, seed=11, want_stability=all_view, tau2_fixed=tau2_fixed,
                              use_cache=not ctx.get("fast"))
        out["profile"] = {"axes": prof, "players": {p: games_of[p] for p in rows_pids},
                          "losses": {p: sum(1 for f in recs if p in f["seats"] and f["winner"] != p) for p in rows_pids},
                          "tau2_source": "all games" if tau2_fixed else "this view", "B": B}
    out["comebacks"] = comebacks(recs)
    out["first_to"] = {str(c): first_to(recs, ctx, c) for c in (0.5, 0.75)}
    out["draft"] = draft(games, events, ctx)
    out["km"] = km_view(games, events, ctx)
    out["dev_luck"] = dev_luck(games, events, ctx)
    out["hoarder"] = hoarder(games, events, ctx)
    return out


def compute_all(games, replays, events, ctx):
    view = _view(games, replays, events, ctx, all_view=True)
    _VIEW_MEMO[tuple(g["id"] for g in games)] = view
    recs = _recs(games, replays, events)
    prof = (view.get("profile") or {}).get("axes") or {}
    games_of = _games_of(recs, [p for p in ctx["pids"] if _is_regular(p, ctx)])
    gal = {}
    for f in recs:
        cb = f["comeback"]
        if not cb:
            continue
        row = {"t": cb["t_roll"], "gap": cb["gap"], "d": r3(cb["d"]), "vp_cards": cb["vp_cards"], "G": f["G"],
               "winner": f["winner"]}
        if cb["gap"] is not None:
            row.update({"leaders": cb["leaders"], "winner_bvp": cb["winner_bvp"], "max_bvp": cb["max_bvp"]})
        gal[f["id"]] = row
    return {
        "level": LEVEL,
        "axes": [{**a, **{k: prof.get(a["key"], {}).get(k) for k in ("tau2", "mu", "Q", "df", "p", "gate", "k")}}
                 for a in AXES],
        "gate_p": GATE_P, "max_badges": MAX_BADGES, "min_games": G["badges"],
        "badges": badges(prof, {p: n for p, n in games_of.items() if n >= G["player_rows"]}),
        "games": gal,
    }


def compute_view(games, replays, events, ctx, all_result):
    key = tuple(g["id"] for g in games)
    if key in _VIEW_MEMO:
        return _VIEW_MEMO[key]
    all_tau2 = {a["key"]: a.get("tau2") for a in all_result.get("axes", [])}
    return _view(games, replays, events, ctx, all_tau2=all_tau2)
