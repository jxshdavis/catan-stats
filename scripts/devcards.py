"""Dev cards: what comes out of the deck, who buys and plays what, and whether any of it changes who wins.

Reads dev_events, vp_events, monopoly_events, robber_events, dev_deck and the per-roll states from
data/replay_events.json, plus resources_from_dice from data/replays.json. All games only (no per-view
result): the card-draw comparisons need every purchase to say anything.

stats.json["devcards"]:
    draw            per card: win rate after drawing it minus after drawing any other card bought in the same
                    third of the game (wins above 1/n), overall and by third, with 95% game-cluster bootstrap
                    intervals. Which card comes out is luck, so this is the one causal comparison here.
    vp_by_buys, winner_hidden_vp, final_turn_buys, vp_luck
                    what victory point cards are worth, described.
    by_buys, spend_grid, heavy_minus_light, first_buy
                    win rate by dev spending, with dice income held roughly fixed (descriptive).
    buy_hist, buy_timing, deck
                    when cards are bought.
    largest_army, knights_played, la_first_hist
                    Largest Army.
    robber_threat   how often knights and 7s rob the threat index's top threat, against a random pick among
                    the eligible victims (out-of-fold scores from scripts/threat.py).
    monopoly, hold, hold_hist, unplayed, knight_pre_roll
                    playing habits.
    players, markers
                    per group member with 5+ games, and site-style "vs the table" markers (10+ games).
"""

from __future__ import annotations

import math
import random
import statistics as stt
from collections import Counter, defaultdict

import statlib

KEY = "devcards"
CARDS = ["knight", "victory_point", "road_building", "monopoly", "year_of_plenty"]
ACTION = [c for c in CARDS if c != "victory_point"]
PHASES = [(0, 1 / 3, "early"), (1 / 3, 2 / 3, "middle"), (2 / 3, 1.01, "late")]
LEVEL = statlib.LEVEL
G = statlib.GUARDS
MIN_PLAYER_GAMES = 5
TENTHS = 10
# Which way is good for each habit marker: 1 up, -1 down, 0 neither (a style, not a skill).
MARKER_GOOD = {"buys": 0, "share": 0, "first": 0, "knights": 0, "la": 1, "pre": 0, "hold": 0, "unplayed": -1, "mono": 1}


def rnd(x, d=4):
    if isinstance(x, float):
        return round(x, d) if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: rnd(v, d) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [rnd(v, d) for v in x]
    return x


def wae(rows):
    """Wins above expected per row: win minus 1/n."""
    return sum(r["win"] - 1 / r["n"] for r in rows) / len(rows) if rows else None


def winr(rows):
    return sum(r["win"] for r in rows) / len(rows) if rows else None


def boot(fn, rows, rng, B):
    """Percentile interval for fn over game-cluster bootstrap resamples of rows (each row has "g")."""
    by = defaultdict(list)
    for r in rows:
        by[r["g"]].append(r)
    ids = list(by)
    if not ids:
        return None
    vals = []
    for _ in range(B):
        v = fn([r for gid in rng.choices(ids, k=len(ids)) for r in by[gid]])
        if v is not None:
            vals.append(v)
    if len(vals) < B // 2:
        return None
    vals.sort()
    a = (1 - LEVEL) / 2
    return [vals[int(a * len(vals))], vals[min(len(vals) - 1, int((1 - a) * len(vals)))]]


def phase_of(frac):
    return next(name for lo, hi, name in PHASES if lo <= frac < hi)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

def collect(games, replays, events):
    """Purchases, plays, per-seat rows, per-game rows and Monopolies from every game with an event log."""
    buys, plays, pgs, gms, monos = [], [], [], [], []
    for g in games:
        e = events.get(g["id"])
        if not e or not e.get("dev_events") or not e.get("states"):
            continue
        gid, seats, win = g["id"], e["seats"], g["winner"]
        n = len(seats)
        if win not in seats:
            continue
        L = max(max(s.get("roll_index", 0) for s in e["states"]), 1)
        fin = {}
        for s in e["states"]:  # change-point encoded: carry every field forward
            fin.update(s)
        deck = dict(e.get("dev_deck") or {})
        deck_size = sum(deck.values())
        bought = defaultdict(list)
        held = defaultdict(lambda: defaultdict(list))
        exp_vp = Counter()
        var_vp = Counter()
        gplays = []
        for d in e["dev_events"]:
            p = seats[d["seat"] - 1]
            frac = max(d["roll_index"], 0) / L
            if d["action"] == "buy":
                left = sum(deck.values())
                if left > 0:
                    pv = deck.get("victory_point", 0) / left
                    exp_vp[p] += pv
                    var_vp[p] += pv * (1 - pv)
                if d["card"] in deck:
                    deck[d["card"]] -= 1
                buys.append({"g": gid, "p": p, "n": n, "win": p == win, "card": d["card"], "frac": frac,
                             "turn": d["own_turn"], "wt": p == win and d["roll_index"] == L})
                bought[p].append(d["card"])
                held[p][d["card"]].append(d["own_turn"])
            else:
                q = held[p][d["card"]]
                ht = d["own_turn"] - q.pop(0) if q else None  # first in, first out per card type
                gplays.append({"g": gid, "p": p, "n": n, "win": p == win, "card": d["card"], "frac": frac,
                               "pre": bool(d.get("pre_roll")), "hold": ht})
        plays.extend(gplays)
        la_events = [(x["roll_index"], c["seat"]) for x in e.get("vp_events") or []
                     for c in x["changes"] if c["type"] == "largest_army_taken"]
        la_final = seats[la_events[-1][1] - 1] if la_events else None
        held_vp = fin.get("vp_cards_held")
        gms.append({"g": gid, "n": n, "win": win, "date": g["date"], "buys": sum(len(v) for v in bought.values()),
                    "deck": deck_size, "la_final": la_final, "la_changes": len(la_events),
                    "la_first_frac": la_events[0][0] / L if la_events else None,
                    "winner_vp_cards": held_vp[seats.index(win)] if held_vp else None})
        gmonos = []
        for m in e.get("monopoly_events") or []:
            gmonos.append({"g": gid, "p": seats[m["seat"] - 1], "n": n, "res": m["resource"], "take": sum(m["taken"]),
                           "frac": max(m["roll_index"], 0) / L, "win": seats[m["seat"] - 1] == win})
        monos.extend(gmonos)
        rp = (replays.get(gid) or {}).get("players") or {}
        tot_res = sum(rp[p].get("resources_from_dice") or 0 for p in seats if p in rp)
        spent = fin.get("spent") or {}
        for i, p in enumerate(seats):
            tot = sum(spent[k][i] for k in spent)
            played = Counter(x["card"] for x in gplays if x["p"] == p)
            b = Counter(bought[p])
            mine = [x for x in buys if x["g"] == gid and x["p"] == p]
            prod = rp[p].get("resources_from_dice") if p in rp else None
            pgs.append({"g": gid, "p": p, "n": n, "win": p == win, "buys": len(bought[p]), "vp": b["victory_point"],
                        "exp_vp": exp_vp[p], "var_vp": var_vp[p], "kn_played": played["knight"], "la": la_final == p,
                        "unplayed": sum(max(b[c] - played[c], 0) for c in ACTION),
                        "dev_share": (spent["dev"][i] / tot) if tot and "dev" in spent else 0.0,
                        "prod": (prod * n / tot_res) if prod is not None and tot_res else None,
                        "first": min((x["turn"] for x in mine), default=None),
                        "mono_take": sum(m["take"] for m in gmonos if m["p"] == p)})
    return buys, plays, pgs, gms, monos


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

def draw_effects(buys, rng, B):
    """Each card against every other card bought in the same third of the game."""
    out = {}
    for c in CARDS:
        def eff(rows, c=c):
            tot = wsum = 0
            for lo, hi, _ in PHASES:
                aa = [r for r in rows if r["card"] == c and lo <= r["frac"] < hi]
                bb = [r for r in rows if r["card"] != c and lo <= r["frac"] < hi]
                if aa and bb:
                    tot += len(aa) * (wae(aa) - wae(bb))
                    wsum += len(aa)
            return tot / wsum if wsum else None

        def diff(rows, c=c):
            a = [r for r in rows if r["card"] == c]
            b = [r for r in rows if r["card"] != c]
            return wae(a) - wae(b) if a and b else None

        nwt = [r for r in buys if not r["wt"]]
        mine = [r for r in buys if r["card"] == c]
        row = {"n": len(mine), "win": winr(mine), "effect": eff(buys), "ci": boot(eff, buys, rng, B),
               "effect_nwt": eff(nwt), "ci_nwt": boot(eff, nwt, rng, B), "phases": {}}
        for lo, hi, name in PHASES:
            ph = [r for r in buys if lo <= r["frac"] < hi]
            a = [r for r in ph if r["card"] == c]
            b = [r for r in ph if r["card"] != c]
            row["phases"][name] = {"n": len(a), "win": winr(a), "other_win": winr(b), "diff": diff(ph),
                                   "ci": boot(diff, ph, rng, B)}
        out[c] = row
    return out


def tercile(v, cuts):
    return 0 if v < cuts[0] else (1 if v < cuts[1] else 2)


def spending(pgs, rng, B):
    pp = [r for r in pgs if r["prod"] is not None]
    pc = stt.quantiles([r["prod"] for r in pp], n=3)
    sh = stt.quantiles([r["dev_share"] for r in pp], n=3)
    grid = []
    for i in range(3):
        rows = [r for r in pp if tercile(r["prod"], pc) == i]
        cells = []
        for j in range(3):
            cc = [r for r in rows if tercile(r["dev_share"], sh) == j]
            cells.append({"n": len(cc), "win": winr(cc), "wae": wae(cc)})
        grid.append({"cells": cells})

    def slope(rows):  # heavy minus light dev spenders, averaged over income thirds
        d = []
        for i in range(3):
            rr = [r for r in rows if tercile(r["prod"], pc) == i]
            hi_ = [r for r in rr if tercile(r["dev_share"], sh) == 2]
            lo_ = [r for r in rr if tercile(r["dev_share"], sh) == 0]
            if hi_ and lo_:
                d.append(wae(hi_) - wae(lo_))
        return sum(d) / len(d) if d else None

    fb = [r for r in pp if r["first"] is not None]
    bins = [(0, 6, "1–5"), (6, 11, "6–10"), (11, 16, "11–15"), (16, 10 ** 6, "16+")]
    first = [{"label": lab, "n": len(rr), "win": winr(rr), "wae": wae(rr),
              "prod": stt.mean(r["prod"] for r in rr) if rr else None}
             for lo, hi, lab in bins for rr in [[r for r in fb if lo <= r["first"] < hi]]]
    nb = [r for r in pp if r["first"] is None]
    first.append({"label": "never", "n": len(nb), "win": winr(nb), "wae": wae(nb),
                  "prod": stt.mean(r["prod"] for r in nb) if nb else None})
    bb = defaultdict(list)
    for r in pgs:
        bb[min(r["buys"], 7)].append(r)
    by_buys = [{"k": k, "n": len(v), "win": winr(v), "exp": stt.mean(1 / r["n"] for r in v),
                "prod": stt.mean([r["prod"] for r in v if r["prod"] is not None] or [0])} for k, v in sorted(bb.items())]
    return {
        "spend_grid": {"prod_cuts": pc, "share_cuts": sh, "rows": grid},
        "heavy_minus_light": {"v": slope(pp), "ci": boot(slope, pp, rng, B)},
        "avg_dev_share": stt.mean(r["dev_share"] for r in pp),
        "first_buy": first,
        "by_buys": by_buys,
    }


def victory_points(pgs, gms, buys, rng, B):
    bb = [r for r in pgs if r["buys"] > 0]
    up = lambda r: r["vp"] - r["exp_vp"] >= 0.5
    down = lambda r: r["vp"] - r["exp_vp"] <= -0.5

    def f(rows):
        a = [r for r in rows if up(r)]
        b = [r for r in rows if down(r)]
        return wae(a) - wae(b) if a and b else None

    groups = [(1, 2, "1–2"), (3, 4, "3–4"), (5, 99, "5+")]
    kinds = [("0", lambda r: r["vp"] == 0), ("1", lambda r: r["vp"] == 1), ("2+", lambda r: r["vp"] >= 2)]
    return {
        "vp_by_buys": [{"label": lab, "cells": [{"k": k, "n": len(rr), "win": winr(rr)} for k, fk in kinds
                                                 for rr in [[r for r in pgs if lo <= r["buys"] <= hi and fk(r)]]]}
                       for lo, hi, lab in groups],
        "vp_luck": {"diff": f(bb), "ci": boot(f, bb, rng, B)},
        "winner_hidden_vp": dict(Counter(str(min(g["winner_vp_cards"], 3)) for g in gms if g["winner_vp_cards"] is not None)),
        "final_turn_buys": dict(Counter(r["card"] for r in buys if r["wt"])),
        "games_won_on_final_turn_vp": len({r["g"] for r in buys if r["wt"] and r["card"] == "victory_point"}),
    }


def army(pgs, gms):
    la = [g for g in gms if g["la_final"]]
    if not la:
        return {"largest_army": None, "knights_played": [], "la_first_hist": []}
    kp = defaultdict(list)
    for r in pgs:
        kp[min(r["kn_played"], 5)].append(r)
    return {
        "largest_army": {"games": len(gms), "awarded": len(la), "holder_won": sum(g["la_final"] == g["win"] for g in la),
                         "holder_win_rate": sum(g["la_final"] == g["win"] for g in la) / len(la),
                         "expected": stt.mean(1 / g["n"] for g in la),
                         "changed": sum(1 for g in la if g["la_changes"] > 1),
                         "first_frac": stt.median(g["la_first_frac"] for g in la)},
        "knights_played": [{"k": k, "n": len(v), "win": winr(v), "wae": wae(v), "la": sum(r["la"] for r in v) / len(v)}
                           for k, v in sorted(kp.items())],
        "la_first_hist": [sum(1 for g in la if min(int(g["la_first_frac"] * TENTHS), TENTHS - 1) == t) for t in range(TENTHS)],
    }


def monopoly(monos):
    if not monos:
        return None
    by_res = defaultdict(list)
    for m in monos:
        by_res[m["res"]].append(m["take"])
    best = max(monos, key=lambda m: m["take"])
    return {"n": len(monos), "mean": stt.mean(m["take"] for m in monos), "zero": sum(m["take"] == 0 for m in monos),
            "big": sum(m["take"] >= 6 for m in monos),
            "best": {k: best[k] for k in ("g", "p", "res", "take", "win")},
            "by_res": {k: {"n": len(v), "mean": stt.mean(v)} for k, v in by_res.items()},
            "by_n": {str(k): {"n": sum(m["n"] == k for m in monos), "mean": stt.mean(m["take"] for m in monos if m["n"] == k)}
                     for k in sorted({m["n"] for m in monos})},
            "dist": dict(Counter(str(min(m["take"], 10)) for m in monos))}


def holding(plays, pgs, buys):
    kn = [x for x in plays if x["card"] == "knight"]
    hold = {}
    hist = {}
    for c in ACTION:
        h = [x["hold"] for x in plays if x["card"] == c and x["hold"] is not None]
        if h:
            hold[c] = {"n": len(h), "median": stt.median(h), "mean": stt.mean(h), "next": sum(v <= 1 for v in h) / len(h)}
            hist[c] = [sum(1 for v in h if min(max(v, 1), 5) == k) for k in range(1, 6)]
    nonvp = sum(1 for r in buys if r["card"] != "victory_point")
    up = sum(r["unplayed"] for r in pgs)
    return {"hold": hold, "hold_hist": hist, "knight_pre_roll": sum(x["pre"] for x in kn) / len(kn) if kn else None,
            "unplayed": {"cards": up, "of": nonvp, "share": up / nonvp if nonvp else None,
                         "winners": sum(r["unplayed"] for r in pgs if r["win"])}}


def per_player(pids, pgs, plays, buys, monos):
    out = []
    for p in pids:
        R = [r for r in pgs if r["p"] == p]
        if len(R) < MIN_PLAYER_GAMES:
            continue
        P = [x for x in plays if x["p"] == p]
        K = [x for x in P if x["card"] == "knight"]
        M = [m for m in monos if m["p"] == p]
        H = [x["hold"] for x in P if x["hold"] is not None]
        F = [r["first"] for r in R if r["first"] is not None]
        out.append({"p": p, "games": len(R), "win": winr(R), "wae": wae(R),
                    "buys": stt.mean(r["buys"] for r in R), "share": stt.mean(r["dev_share"] for r in R),
                    "first": stt.median(F) if F else None, "knights": stt.mean(r["kn_played"] for r in R),
                    "la": sum(r["la"] for r in R) / len(R), "pre": sum(x["pre"] for x in K) / len(K) if K else None,
                    "hold": stt.mean(H) if H else None, "unplayed": stt.mean(r["unplayed"] for r in R),
                    "cards": dict(Counter(x["card"] for x in buys if x["p"] == p)),
                    "mono_n": len(M), "mono_avg": stt.mean(m["take"] for m in M) if M else None,
                    "mono_pg": sum(r["mono_take"] for r in R) / len(R)})
    return out


def markers(players, pgs, plays):
    """The site's "vs the table" markers (statlib.within_game_sd_marker), plus a z for wins against sum 1/n."""
    by_seat = defaultdict(list)
    for x in plays:
        by_seat[(x["g"], x["p"])].append(x)

    def val(r, key):
        xs = by_seat[(r["g"], r["p"])]
        kn = [x for x in xs if x["card"] == "knight"]
        hs = [x["hold"] for x in xs if x["hold"] is not None]
        return {"buys": lambda: r["buys"], "share": lambda: r["dev_share"], "first": lambda: r["first"],
                "knights": lambda: r["kn_played"], "la": lambda: int(r["la"]),
                "pre": lambda: sum(x["pre"] for x in kn) / len(kn) if kn else None,
                "hold": lambda: sum(hs) / len(hs) if hs else None, "unplayed": lambda: r["unplayed"],
                "mono": lambda: r["mono_take"]}[key]()

    by_game = defaultdict(list)
    for r in pgs:
        by_game[r["g"]].append(r)
    out = {p["p"]: {} for p in players}
    for key, good in MARKER_GOOD.items():
        per_game = [{r["p"]: val(r, key) for r in rows} for rows in by_game.values()]
        res = statlib.within_game_sd_marker(per_game, level=LEVEL, min_games=G["player_rows"])
        for pid in out:
            m = res.get(pid)
            if m and m.get("delta") is not None and m["games"] >= G["player_rows"]:
                out[pid][key] = {"delta": m["delta"], "lo": m["lo"], "hi": m["hi"], "clear": m["clear"],
                                 "games": m["games"], "good": good}
    zc = statlib.z_for(LEVEL)
    for p in players:
        R = [r for r in pgs if r["p"] == p["p"]]
        if len(R) < G["player_rows"]:
            continue
        won = sum(r["win"] for r in R)
        ev = sum(1 / r["n"] for r in R)
        var = sum((1 / r["n"]) * (1 - 1 / r["n"]) for r in R)
        z = (won - ev) / math.sqrt(var)
        out[p["p"]]["wins"] = {"z": z, "clear": abs(z) > zc, "good": 1, "games": len(R)}
    return out


def robber_threat(games, events, rng, B):
    """Share of knight and 7 robberies that took from the top threat, when the threat and someone else could
    both be robbed. Uses the threat module's out-of-fold scores when it has run; otherwise fits its own."""
    import threat
    data = list(threat._STATE.values())
    if not data:
        data = threat.game_data(games, events)
        if len(data) < G["model_games"]:
            return None
        full = threat.fit_model(data)
        fold, models = threat.cross_fit(data)
        for d in data:
            threat.score_rows(d, models.get(fold[d["game"]], full))
    units = {}
    for d in data:
        u = []
        for e in d["ev"].get("robber_events") or []:
            if not e.get("victim"):
                continue
            r = threat.row_at(d, e["action_index"] - 1)
            if r is None:
                continue
            tau = threat.top_among(r, e["mover"] - 1)
            elig = [s - 1 for s in e.get("eligible") or []]
            if tau not in elig or len(elig) < 2:
                continue
            u.append((e["cause"], e["victim"] - 1 == tau, 1 / len(elig)))
        units[d["game"]] = u
    ids = list(units)

    def summ(sample, cause):
        rows = [x for g in sample for x in units[g] if x[0] == cause]
        return sum(x[1] for x in rows), sum(x[2] for x in rows), len(rows)

    def pct_ci(vals):
        vals = sorted(v for v in vals if v is not None)
        a = (1 - LEVEL) / 2
        return [vals[int(a * len(vals))], vals[min(len(vals) - 1, int((1 - a) * len(vals)))]] if vals else None

    out = {}
    for cause in ("knight", "seven"):
        O, E, n = summ(ids, cause)
        if not n:
            return None
        bs = []
        for _ in range(B):
            o, e_, _n = summ(rng.choices(ids, k=len(ids)), cause)
            bs.append(o / e_ if e_ else None)
        out[cause] = {"n": n, "rate": O / n, "chance": E / n, "ratio": O / E, "ci": pct_ci(bs)}

    def dif(sample):
        a, ea, _ = summ(sample, "knight")
        b, eb, _ = summ(sample, "seven")
        return a / ea - b / eb if ea and eb else None

    out["diff"] = {"v": dif(ids), "ci": pct_ci([dif(rng.choices(ids, k=len(ids))) for _ in range(B)])}
    out["games"] = len(ids)
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def compute_all(games, replays, events, ctx):
    buys, plays, pgs, gms, monos = collect(games, replays, events or {})
    if len(gms) < G["model_games"] or not buys:
        return {"games": len(gms)}
    rng = random.Random(7)
    B = 200 if ctx.get("fast") else statlib.B_DESCRIPTIVE
    deck_sizes = Counter(g["deck"] for g in gms)
    players = per_player(ctx["pids"], pgs, plays, buys, monos)
    out = {
        "games": len(gms), "level": LEVEL, "n_buys": len(buys), "n_plays": len(plays),
        "first_date": min(g["date"] for g in gms), "last_date": max(g["date"] for g in gms),
        "expected_all": stt.mean(1 / r["n"] for r in pgs),
        "draw": draw_effects(buys, rng, B),
        **victory_points(pgs, gms, buys, rng, B),
        **spending(pgs, rng, B),
        **army(pgs, gms),
        **holding(plays, pgs, buys),
        "robber_threat": robber_threat(games, events or {}, rng, B),
        "monopoly": monopoly(monos),
        "deck": {"size": deck_sizes.most_common(1)[0][0], "avg_buys": stt.mean(g["buys"] for g in gms),
                 "max_buys": max(g["buys"] for g in gms), "emptied": sum(g["buys"] >= g["deck"] for g in gms)},
        "buy_timing": {name: sum(1 for r in buys if phase_of(r["frac"]) == name) / len(buys) for _, _, name in PHASES},
        "buy_hist": [{c: sum(1 for r in buys if r["card"] == c and min(int(r["frac"] * TENTHS), TENTHS - 1) == t)
                      for c in CARDS} for t in range(TENTHS)],
        "players": players,
        "markers": markers(players, pgs, plays),
    }
    return rnd(out)
