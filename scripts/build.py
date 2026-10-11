#!/usr/bin/env python3
"""Build the Catan stats site.

Reads data/players.json and data/games.json, validates them, computes every
statistic the front end shows, and writes a ready-to-deploy site into dist/.

    python scripts/build.py            # validate + build into dist/
    python scripts/build.py --check    # validate only, build nothing

The front end never computes stats itself; it only renders dist/data/stats.json.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

from openskill.models import PlackettLuce

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SITE = ROOT / "site"
DIST = ROOT / "dist"

VP_SOURCES = ["settlements", "cities", "vp_cards", "largest_army", "longest_road", "islands", "other"]
EXPANSIONS = {"base": "Base", "seafarers": "Seafarers"}  # add more here as you play them
SCENARIOS = {  # per expansion; each one gets its own leaderboard filter
    "seafarers": {
        "new_shores": "New Shores",
        "four_islands": "Four Islands",
        "through_the_desert": "Through the Desert",
    },
}
DEV_CARDS = ["knight", "victory_point", "road_building", "year_of_plenty", "monopoly"]
DICE_FACES = list(range(2, 13))
DICE_P = {s: (6 - abs(s - 7)) / 36 for s in DICE_FACES}
PROVISIONAL_GAMES = 5  # ratings with fewer games than this are flagged
GUEST_PREFIX = "guest-"  # players outside players.json: rated fresh each game, never listed


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------

class DataError(Exception):
    pass


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise DataError(f"{path.name}: invalid JSON at line {e.lineno}, column {e.colno}: {e.msg}")


def is_guest(pid):
    return isinstance(pid, str) and pid.startswith(GUEST_PREFIX)


NAME_MODES = ("initials", "usernames")  # site.json "player_names"


def display_name(p, mode="usernames"):
    """How a player is shown. "usernames": 'name' if set, else the most used TwoSheep name
    (aliases[0]), then initials, as in 'brickpump (JD)'. "initials": just the initials when the
    player has them, falling back to the username form."""
    if mode == "initials" and p.get("initials"):
        return p["initials"]
    base = p.get("name") or (p.get("aliases") or [p["id"]])[0]
    return f"{base} ({p['initials']})" if p.get("initials") else base


def validate(players_doc, games_doc):
    """Return (errors, warnings). Errors stop the build; warnings are printed."""
    errors, warnings = [], []
    players = players_doc.get("players", [])
    ids = [p.get("id") for p in players]
    if len(ids) != len(set(ids)):
        errors.append("players.json: duplicate player id")
    known = set(ids)
    slots = [p.get("color_slot") for p in players]
    for p in players:
        if not isinstance(p.get("color_slot"), int) or not 1 <= p["color_slot"] <= 8:
            errors.append(f"players.json: {p.get('id')}: color_slot must be an integer 1 to 8")
        aliases = p.get("aliases", [])
        if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
            errors.append(f"players.json: {p.get('id')}: aliases must be a list of names")
        elif not p.get("name") and not aliases:
            errors.append(f"players.json: {p.get('id')}: needs a name or at least one alias to show")
        initials = p.get("initials")
        if initials is not None and (not isinstance(initials, str) or not 1 <= len(initials) <= 4):
            errors.append(f"players.json: {p.get('id')}: initials must be 1 to 4 characters")
    if len([s for s in slots if s is not None]) != len(set(s for s in slots if s is not None)):
        warnings.append("players.json: two players share a color_slot, so charts will be hard to read")
    if any(is_guest(i) for i in ids):
        errors.append(f"players.json: ids starting with '{GUEST_PREFIX}' are reserved for guests")
    owner = {}
    for p in players:
        for acct in p.get("twosheep_accounts", []):
            if acct in owner:
                errors.append(f"players.json: account {acct} is listed under both {owner[acct]} and {p.get('id')}")
            owner[acct] = p.get("id")

    seen_games, seen_twosheep = set(), set()
    for g in games_doc.get("games", []):
        gid = g.get("id", "<missing id>")
        where = f"games.json: game {gid}"
        start = len(errors)
        if gid in seen_games:
            errors.append(f"{where}: duplicate game id")
        seen_games.add(gid)
        tsid = g.get("twosheep_id")
        if tsid is not None:
            if tsid in seen_twosheep:
                errors.append(f"{where}: twosheep_id {tsid} is already used by another game")
            seen_twosheep.add(tsid)
        try:
            date.fromisoformat(g.get("date", ""))
        except ValueError:
            errors.append(f"{where}: date must be YYYY-MM-DD")
        rows = g.get("players", [])
        if len(rows) < 2:
            errors.append(f"{where}: needs at least 2 players")
            continue
        pids = [r.get("player") for r in rows]
        if len(pids) != len(set(pids)):
            errors.append(f"{where}: a player appears twice")
        for pid in pids:
            if pid not in known and not is_guest(pid):
                errors.append(f"{where}: unknown player '{pid}' (add them to players.json)")
        if all(is_guest(pid) for pid in pids):
            errors.append(f"{where}: every player is a guest")
        if g.get("winner") not in pids:
            errors.append(f"{where}: winner '{g.get('winner')}' is not one of the players")
        for r in rows:
            if not isinstance(r.get("vp"), int):
                errors.append(f"{where}: {r.get('player')}: vp must be an integer")
        if len(errors) > start:
            continue
        top = max(r["vp"] for r in rows)
        win_vp = next(r["vp"] for r in rows if r["player"] == g["winner"])
        if win_vp < top:
            errors.append(f"{where}: winner has {win_vp} VP but someone else has {top}")
        settings = g.get("settings") or {}
        target = settings.get("vp_to_win")
        exp = settings.get("expansion")
        if exp is None:
            warnings.append(f"{where}: settings.expansion is not set, so it counts as 'unknown'")
        elif exp not in EXPANSIONS:
            warnings.append(f"{where}: expansion '{exp}' isn't in EXPANSIONS in build.py, so it shows as typed")
        scen = settings.get("scenario")
        if scen is not None and scen not in SCENARIOS.get(exp, {}):
            errors.append(f"{where}: scenario '{scen}' isn't listed under '{exp}' in SCENARIOS in build.py")
        if target is None:
            warnings.append(f"{where}: settings.vp_to_win is not set")
        if exp == "base" and any((r.get("vp_breakdown") or {}).get("islands") for r in rows):
            warnings.append(f"{where}: island VP recorded in a base game")
        if target is not None and win_vp < target:
            warnings.append(f"{where}: winner has fewer VP than vp_to_win (game ended early?)")

        seats = [r.get("seat") for r in rows]
        if any(s is not None for s in seats):
            if any(s is None for s in seats):
                errors.append(f"{where}: record a seat for every player or for none")
            elif sorted(seats) != list(range(1, len(rows) + 1)):
                errors.append(f"{where}: seats must be 1 to {len(rows)}, each used once")

        for r in rows:
            vb = r.get("vp_breakdown")
            if vb:
                bad = set(vb) - set(VP_SOURCES)
                if bad:
                    errors.append(f"{where}: {r['player']}: unknown vp_breakdown keys {sorted(bad)}")
                elif sum(vb.values()) != r["vp"]:
                    errors.append(
                        f"{where}: {r['player']}: vp_breakdown adds to {sum(vb.values())}, vp is {r['vp']}")
            dc = r.get("dev_cards_bought")
            if dc and set(dc) - set(DEV_CARDS):
                errors.append(f"{where}: {r['player']}: unknown dev card keys {sorted(set(dc) - set(DEV_CARDS))}")

        dice = (g.get("dice") or {}).get("counts")
        if dice:
            if set(dice) != {str(s) for s in DICE_FACES}:
                errors.append(f"{where}: dice.counts needs exactly the keys 2 to 12")
            elif g.get("turns") is not None and sum(dice.values()) != g["turns"]:
                warnings.append(
                    f"{where}: dice rolls total {sum(dice.values())} but turns is {g['turns']}")
    return errors, warnings


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def finishing_ranks(game):
    """Winner is rank 1. Others by VP, ties share a rank (1, 2, 3, 3, 5)."""
    others = sorted((r for r in game["players"] if r["player"] != game["winner"]),
                    key=lambda r: -r["vp"])
    ranks = {game["winner"]: 1}
    prev_vp, prev_rank = None, None
    for i, r in enumerate(others, start=2):
        if r["vp"] == prev_vp:
            ranks[r["player"]] = prev_rank
        else:
            ranks[r["player"]] = i
            prev_vp, prev_rank = r["vp"], i
    return ranks


def wilson(k, n, z=1.96):
    """95% Wilson score interval for a proportion."""
    if n == 0:
        return None
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [max(0.0, centre - half), min(1.0, centre + half)]


def chi2_sf_even_df(x, df):
    """Upper-tail p-value of a chi-square statistic; exact closed form for even df."""
    assert df % 2 == 0
    m = x / 2
    term, total = 1.0, 1.0
    for k in range(1, df // 2):
        term *= m / k
        total += term
    return math.exp(-m) * total


def dice_summary(counts):
    n = sum(counts.values())
    if n == 0:
        return None
    expected = {s: n * DICE_P[s] for s in DICE_FACES}
    chi2 = sum((counts[s] - expected[s]) ** 2 / expected[s] for s in DICE_FACES)
    return {
        "rolls": n,
        "counts": {str(s): counts[s] for s in DICE_FACES},
        "expected": {str(s): round(expected[s], 3) for s in DICE_FACES},
        "sevens": counts[7],
        "sevens_expected": round(expected[7], 2),
        "chi2": round(chi2, 3),
        "p_value": round(chi2_sf_even_df(chi2, 10), 4),
    }


def expansion_of(game):
    return (game.get("settings") or {}).get("expansion") or "unknown"


def type_key(game):
    """Finest game type: 'seafarers/four_islands' when the scenario is known, else 'seafarers'."""
    scen = (game.get("settings") or {}).get("scenario")
    return f"{expansion_of(game)}/{scen}" if scen else expansion_of(game)


def type_label(key):
    exp, _, scen = key.partition("/")
    name = EXPANSIONS.get(exp, "Unknown type" if exp == "unknown" else exp)
    return f"{name}: {SCENARIOS.get(exp, {}).get(scen, scen)}" if scen else name


def r3(x):
    return None if x is None else round(x, 3)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def compute(players_doc, games, number_of, name_mode="usernames"):
    """Every stat for one slice of games. number_of maps game id to its number among all games."""
    players = {p["id"]: p for p in players_doc["players"]}

    model = PlackettLuce()
    ratings = {pid: model.rating(name=pid) for pid in players}
    history = {pid: [] for pid in players}

    acc = {pid: defaultdict(list) for pid in players}
    by_count = {pid: defaultdict(lambda: {"games": 0, "wins": 0, "vp": []}) for pid in players}
    by_exp = {pid: defaultdict(lambda: {"games": 0, "wins": 0, "vp": [], "beat": []}) for pid in players}
    by_seat = {pid: defaultdict(lambda: {"games": 0, "wins": 0, "finish": []}) for pid in players}
    h2h = defaultdict(lambda: {"games": 0, "ahead": 0, "behind": 0, "tied": 0, "wins": 0, "losses_to": 0})
    vp_src = {pid: defaultdict(int) for pid in players}
    dev = {pid: defaultdict(int) for pid in players}
    all_dice = {s: 0 for s in DICE_FACES}
    out_games = []

    for idx, g in enumerate(games, start=1):
        rows = g["players"]
        n = len(rows)
        ranks = finishing_ranks(g)
        win_vp = max(r["vp"] for r in rows)
        target = (g.get("settings") or {}).get("vp_to_win") or win_vp
        prod_vals = [r.get("resources_from_dice") for r in rows if r.get("resources_from_dice") is not None]
        prod_mean = mean(prod_vals) if len(prod_vals) == n else None

        # Rating update: Plackett-Luce over the full finishing order. Guests enter at
        # the prior every game, so they inform everyone else's update but carry nothing over.
        order = [r["player"] for r in rows]
        current = {pid: model.rating(name=pid) if is_guest(pid) else ratings[pid] for pid in order}
        before = {pid: (current[pid].mu, current[pid].sigma) for pid in order}
        new = model.rate([[current[pid]] for pid in order], ranks=[ranks[pid] for pid in order])
        for pid, team in zip(order, new):
            if not is_guest(pid):
                ratings[pid] = team[0]

        game_rows = []
        for r in rows:
            pid = r["player"]
            rank = ranks[pid]
            if is_guest(pid):
                game_rows.append({"player": pid, "guest": True, "rank": rank, "vp": r["vp"], "seat": r.get("seat"),
                                  "game_color": r.get("game_color"), "vp_breakdown": r.get("vp_breakdown"),
                                  "dev_cards_bought": r.get("dev_cards_bought"),
                                  "resources_from_dice": r.get("resources_from_dice"), "rating_change": None})
                continue
            won = pid == g["winner"]
            opp = [o for o in rows if o["player"] != pid]
            beaten = sum(1 if ranks[pid] < ranks[o["player"]] else 0.5 if ranks[pid] == ranks[o["player"]] else 0
                         for o in opp)
            a = acc[pid]
            a["won"].append(1 if won else 0)
            a["expected_win"].append(1 / n)
            a["vp"].append(r["vp"])
            a["vp_share"].append(r["vp"] / target)
            a["rank"].append(rank)
            a["beat_rate"].append(beaten / len(opp))
            if prod_mean:
                a["production"].append(r["resources_from_dice"])
                a["production_index"].append(r["resources_from_dice"] / prod_mean)
            e = by_exp[pid][type_key(g)]
            e["games"] += 1
            e["wins"] += won
            e["vp"].append(r["vp"])
            e["beat"].append(beaten / len(opp))
            c = by_count[pid][n]
            c["games"] += 1
            c["wins"] += won
            c["vp"].append(r["vp"])
            if r.get("seat") is not None:
                s = by_seat[pid][r["seat"]]
                s["games"] += 1
                s["wins"] += won
                s["finish"].append(rank)
            for k, v in (r.get("vp_breakdown") or {}).items():
                vp_src[pid][k] += v
            if r.get("vp_breakdown"):
                vp_src[pid]["_games"] += 1
            for k, v in (r.get("dev_cards_bought") or {}).items():
                dev[pid][k] += v
            if r.get("dev_cards_bought"):
                dev[pid]["_games"] += 1
            for o in opp:
                if is_guest(o["player"]):
                    continue
                key = (pid, o["player"])
                h = h2h[key]
                h["games"] += 1
                if ranks[pid] < ranks[o["player"]]:
                    h["ahead"] += 1
                elif ranks[pid] > ranks[o["player"]]:
                    h["behind"] += 1
                else:
                    h["tied"] += 1
                h["wins"] += won
                h["losses_to"] += o["player"] == g["winner"]

            rt = ratings[pid]
            history[pid].append({
                "game": g["id"], "index": idx, "number": number_of[g["id"]], "date": g["date"],
                "mu": r3(rt.mu), "sigma": r3(rt.sigma), "ordinal": r3(rt.ordinal()),
            })
            game_rows.append({
                "player": pid,
                "rank": rank,
                "vp": r["vp"],
                "seat": r.get("seat"),
                "game_color": r.get("game_color"),
                "vp_breakdown": r.get("vp_breakdown"),
                "dev_cards_bought": r.get("dev_cards_bought"),
                "resources_from_dice": r.get("resources_from_dice"),
                "rating_change": r3(ratings[pid].mu - before[pid][0]),
            })

        game_rows.sort(key=lambda x: (x["rank"], x["player"]))
        dice = (g.get("dice") or {}).get("counts")
        dsum = None
        if dice:
            counts = {s: int(dice[str(s)]) for s in DICE_FACES}
            for s in DICE_FACES:
                all_dice[s] += counts[s]
            dsum = dice_summary(counts)
        out_games.append({
            "id": g["id"],
            "index": idx,
            "number": number_of[g["id"]],
            "date": g["date"],
            "platform": g.get("platform"),
            "twosheep_id": g.get("twosheep_id"),
            "turns": g.get("turns"),
            "vp_to_win": (g.get("settings") or {}).get("vp_to_win"),
            "expansion": expansion_of(g),
            "scenario": (g.get("settings") or {}).get("scenario"),
            "type": type_key(g),
            "type_label": type_label(type_key(g)),
            "settings": g.get("settings") or {},
            "winner": g["winner"],
            "n_players": n,
            "n_guests": sum(1 for r in rows if is_guest(r["player"])),
            "players": game_rows,
            "dice": dsum,
            "has_events": bool(g.get("events")),
        })

    # Per-player summary
    out_players = []
    for pid, p in players.items():
        a = acc[pid]
        gp = len(a["won"])
        wins = sum(a["won"])
        rt = ratings[pid]
        vs = vp_src[pid]
        dv = dev[pid]
        out_players.append({
            "id": pid,
            "name": display_name(p, name_mode),
            "initials": p.get("initials"),
            "aliases": p.get("aliases", []),
            "color_slot": p["color_slot"],
            "games": gp,
            "wins": wins,
            "win_rate": r3(wins / gp) if gp else None,
            "win_rate_ci": [r3(x) for x in wilson(wins, gp)] if gp else None,
            "expected_wins": r3(sum(a["expected_win"])),
            "avg_vp": r3(mean(a["vp"])),
            "avg_vp_share": r3(mean(a["vp_share"])),
            "avg_rank": r3(mean(a["rank"])),
            "beat_rate": r3(mean(a["beat_rate"])),
            "finish_counts": {str(k): a["rank"].count(k) for k in range(1, 9) if a["rank"].count(k)},
            "rating": {
                "mu": r3(rt.mu), "sigma": r3(rt.sigma), "ordinal": r3(rt.ordinal()),
                "provisional": gp < PROVISIONAL_GAMES,
            },
            "rating_history": history[pid],
            "by_player_count": {
                str(k): {"games": v["games"], "wins": v["wins"],
                         "win_rate": r3(v["wins"] / v["games"]), "avg_vp": r3(mean(v["vp"]))}
                for k, v in sorted(by_count[pid].items())
            },
            "by_type": {
                k: {"label": type_label(k) + (" (scenario not recorded)" if k in SCENARIOS else ""), "games": v["games"], "wins": v["wins"], "win_rate": r3(v["wins"] / v["games"]),
                    "avg_vp": r3(mean(v["vp"])), "beat_rate": r3(mean(v["beat"]))}
                for k, v in sorted(by_exp[pid].items(), key=lambda kv: -kv[1]["games"])
            },
            "by_seat": {
                str(k): {"games": v["games"], "wins": v["wins"],
                         "win_rate": r3(v["wins"] / v["games"]), "avg_rank": r3(mean(v["finish"]))}
                for k, v in sorted(by_seat[pid].items())
            },
            "production": {
                "games": len(a["production"]),
                "avg_from_dice": r3(mean(a["production"])),
                "avg_index": r3(mean(a["production_index"])),
            },
            "vp_sources_avg": (
                {k: r3(vs[k] / vs["_games"]) for k in VP_SOURCES} if vs["_games"] else None),
            "vp_sources_games": vs["_games"],
            "dev_cards_bought": (
                {**{k: dv[k] for k in DEV_CARDS}, "games": dv["_games"]} if dv["_games"] else None),
        })

    out_players.sort(key=lambda x: (x["games"] == 0, -(x["rating"]["ordinal"]), -x["wins"], x["name"].lower()))
    for i, p in enumerate(out_players, start=1):
        p["leaderboard_rank"] = i if p["games"] else None

    out_h2h = [
        {"player": a, "opponent": b, **v,
         "ahead_rate": r3((v["ahead"] + 0.5 * v["tied"]) / v["games"])}
        for (a, b), v in sorted(h2h.items())
    ]

    seat_known = sum(1 for g in games if all(r.get("seat") is not None for r in g["players"]))
    return {
        "summary": {
            "games": len(games),
            "first_date": games[0]["date"] if games else None,
            "last_date": games[-1]["date"] if games else None,
            "players_active": sum(1 for p in out_players if p["games"]),
            "games_with_seats": seat_known,
            "games_by_type": {type_label(k): sum(1 for g in out_games if g["type"] == k)
                              for k in sorted({g["type"] for g in out_games})},
            "games_with_dice": sum(1 for g in out_games if g["dice"]),
            "games_with_events": sum(1 for g in out_games if g["has_events"]),
            "games_with_guests": sum(1 for g in out_games if g["n_guests"]),
        },
        "dice_overall": dice_summary(all_dice),
        "players": out_players,
        "head_to_head": out_h2h,
        "games": list(reversed(out_games)),  # newest first
    }


def compute_views(players_doc, games_doc, name_mode="usernames"):
    """One full stats view per filter: all games, each expansion, each scenario.

    Each view is computed from scratch on its own slice, so a Seafarers rating
    only learns from Seafarers games.
    """
    games = sorted(games_doc["games"], key=lambda g: (g["date"], g["id"]))
    number_of = {g["id"]: i for i, g in enumerate(games, start=1)}
    slices = {"all": games}
    for exp in sorted({expansion_of(g) for g in games}, key=lambda e: (e not in EXPANSIONS, e)):
        slices[exp] = [g for g in games if expansion_of(g) == exp]
        for scen in SCENARIOS.get(exp, {}):
            sub = [g for g in slices[exp] if (g.get("settings") or {}).get("scenario") == scen]
            if sub:
                slices[f"{exp}/{scen}"] = sub
    view_list = []
    for key, sub in slices.items():
        exp, _, scen = key.partition("/")
        view_list.append({
            "key": key,
            "label": "All games" if key == "all" else (SCENARIOS[exp][scen] if scen else type_label(key)),
            "parent": exp if scen else ("all" if key != "all" else None),
            "games": len(sub),
            "unlabeled_scenarios": (sum(1 for g in sub if not (g.get("settings") or {}).get("scenario"))
                                    if key in SCENARIOS else None),
        })
    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rating_model": {
            "name": "Plackett-Luce (Weng-Lin Bayesian approximation, openskill)",
            "mu0": 25.0, "sigma0": round(25 / 3, 3),
            "ordinal": "mu - 3 sigma",
            "provisional_below_games": PROVISIONAL_GAMES,
        },
        "view_list": view_list,
        "player_names": name_mode,
        "views": {key: compute(players_doc, sub, number_of, name_mode) for key, sub in slices.items()},
    }


def build(check_only=False, data_dir=DATA, out_dir=DIST):
    try:
        players_doc = load_json(data_dir / "players.json")
        games_doc = load_json(data_dir / "games.json")
    except DataError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    errors, warnings = validate(players_doc, games_doc)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if errors:
        for e in errors:
            print(f"error: {e}", file=sys.stderr)
        print(f"\n{len(errors)} error(s). Nothing was built.", file=sys.stderr)
        return 1
    n = len(games_doc.get("games", []))
    if check_only:
        print(f"ok: {n} games, {len(players_doc['players'])} players")
        return 0

    site_cfg = data_dir / "site.json"
    site = load_json(site_cfg) if site_cfg.exists() else {"title": "Catan Stats"}
    name_mode = site.get("player_names", "usernames")
    if name_mode not in NAME_MODES:
        print(f"error: site.json: player_names must be one of {', '.join(NAME_MODES)}", file=sys.stderr)
        return 1
    stats = compute_views(players_doc, games_doc, name_mode)
    stats["site"] = site
    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(SITE, out_dir)
    (out_dir / "data").mkdir(exist_ok=True)
    (out_dir / "data" / "stats.json").write_text(json.dumps(stats, indent=1), encoding="utf-8")
    # The same data as a script, so dist/index.html also works when opened straight
    # from disk (browsers block fetch() on file:// pages but allow <script src>).
    (out_dir / "data" / "stats.js").write_text(
        "window.CATAN_STATS = " + json.dumps(stats, separators=(",", ":")) + ";\n", encoding="utf-8")
    (out_dir / ".nojekyll").write_text("")
    print(f"built {out_dir.name}/ from {n} games")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="validate the data files without building")
    ap.add_argument("--data", type=Path, default=DATA, help="folder holding players.json and games.json")
    ap.add_argument("--out", type=Path, default=DIST, help="output folder (default dist/)")
    args = ap.parse_args()
    sys.exit(build(args.check, args.data.resolve(), args.out.resolve()))
