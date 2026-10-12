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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import insights  # noqa: E402  (model-based and group stats)

# Analysis modules that read the per-action logs. Each has KEY, and compute_all(games, replays, events, ctx)
# for a result stored once at stats.json[KEY] (all games), and may have compute_view(games, replays,
# events, ctx, all_result) for a per-view result at views[view][KEY]. ctx is built in compute_views.
MODULES = []
for _name in ("momentum", "robber", "classes", "resources"):
    try:
        MODULES.append(__import__(_name))
    except ModuleNotFoundError as _e:
        if _e.name != _name:
            raise

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
        "fog_islands": "Fog Islands",
        "six_islands": "Six Islands",
        "new_world": "New World",
    },
}
DEV_CARDS = ["knight", "victory_point", "road_building", "year_of_plenty", "monopoly"]
DICE_FACES = list(range(2, 13))
DICE_P = {s: (6 - abs(s - 7)) / 36 for s in DICE_FACES}
# Per-game numbers from decoded replays that the site averages for each player.
REPLAY_AVERAGES = ["resources_from_dice", "expected_from_dice", "blocked_by_robber", "opening_dots", "robber_moves",
                   "steals", "stolen_from", "cards_discarded", "monopoly_cards", "trades", "trade_cards_given",
                   "bank_trades", "bank_cards_given", "longest_road_length", "max_hand"]
BUILT = ["settlement", "city", "road", "ship"]
# TwoSheep piece colors. Each player is drawn in the site's version of the color they use most (site/styles.css --tc-*).
RECENT_GAMES = 4  # "Last 4 games" on the leaderboard: each player's own most recent games
FIRE_ABOVE = 1.0  # on fire: at least a full win above expected over those games...
ACTIVE_WINDOW = 10  # ...with their latest game among the view's last 10
GAME_COLORS = ["black", "white", "green", "blue", "teal", "orange", "yellow", "red", "pink", "purple"]
GUEST_PREFIX = "guest-"  # players outside players.json: count as seats and opponents, never listed
BOT_PREFIX = "bot-"  # TwoSheep bot seats: count in n and as opponents, never listed


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


def is_bot(pid):
    return isinstance(pid, str) and pid.startswith(BOT_PREFIX)


def is_anon(pid):
    """A seat that is never listed: a guest or a bot."""
    return is_guest(pid) or is_bot(pid)


NAME_MODES = ("initials", "usernames")  # site.json "player_names"


def display_name(p, mode="usernames"):
    """How a player is shown. "usernames": 'name' if set, else the most used TwoSheep name
    (aliases[0]), then initials, as in 'brickpump (JD)'. "initials": just the initials when the
    player has them, falling back to the username form."""
    if mode == "initials" and p.get("initials"):
        return p["initials"]
    base = p.get("name") or (p.get("aliases") or [p["id"]])[0]
    return f"{base} ({p['initials']})" if p.get("initials") else base


def validate(players_doc, games_doc, replays_doc=None):
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
    if any(is_anon(i) for i in ids):
        errors.append(f"players.json: ids starting with '{GUEST_PREFIX}' or '{BOT_PREFIX}' are reserved")
    unknown = sorted({r["game_color"] for g in games_doc.get("games", []) for r in g.get("players", [])
                      if r.get("game_color") and r["game_color"] not in GAME_COLORS})
    if unknown:
        warnings.append(f"games.json: unknown game_color {', '.join(unknown)}; add it to GAME_COLORS and styles.css")
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
            if pid not in known and not is_anon(pid):
                errors.append(f"{where}: unknown player '{pid}' (add them to players.json)")
        if all(is_anon(pid) for pid in pids):
            errors.append(f"{where}: every player is a guest or bot")
        elif sum(1 for pid in pids if not is_anon(pid)) < 2:
            errors.append(f"{where}: only one group member played (the rest are guests or bots), so leave it out")
        if g.get("winner") not in pids or is_bot(g.get("winner")):
            errors.append(f"{where}: winner '{g.get('winner')}' is not one of the players")
        for r in rows:
            # A bot's VP is only known from a decoded replay, so it may be missing
            if not isinstance(r.get("vp"), int) and not (is_bot(r.get("player")) and r.get("vp") is None):
                errors.append(f"{where}: {r.get('player')}: vp must be an integer")
        if g.get("n_seats") is not None and g["n_seats"] != len(rows):
            errors.append(f"{where}: n_seats is {g['n_seats']} but {len(rows)} seats are listed")
        if len(errors) > start:
            continue
        top = max(r["vp"] for r in rows if r.get("vp") is not None)
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
                elif r["vp"] is not None and sum(vb.values()) != r["vp"]:
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

    by_id = {g.get("id"): g for g in games_doc.get("games", [])}
    for gid, rep in ((replays_doc or {}).get("games") or {}).items():
        where = f"replays.json: game {gid}"
        g = by_id.get(gid)
        if g is None:
            errors.append(f"{where}: no such game in games.json")
            continue
        if rep.get("twosheep_id") != g.get("twosheep_id"):
            errors.append(f"{where}: twosheep_id doesn't match games.json")
        pids = {r.get("player") for r in g.get("players", [])}
        if set(rep.get("players", {})) != pids:
            errors.append(f"{where}: players don't match games.json")
        for key in ("vp", "cards_from_dice"):
            series = (rep.get("timeline") or {}).get(key) or {}
            if set(series) != pids or any(len(v) != len(rep["timeline"]["turn"]) for v in series.values()):
                errors.append(f"{where}: timeline.{key} needs one value per turn for each player")
    return errors, warnings


def replays_text(doc) -> str:
    """replays.json with one line per player and per timeline series, so diffs stay readable."""
    line = lambda v: json.dumps(v, ensure_ascii=False, separators=(", ", ": "))
    out = ["{", f'  "schema_version": {line(doc["schema_version"])},', f'  "source": {line(doc["source"])},', '  "games": {']
    games = list(doc["games"].items())
    for i, (gid, g) in enumerate(games):
        tl = g["timeline"]
        players = ",\n".join(f"        {line(pid)}: {line(st)}" for pid, st in g["players"].items())
        series = ",\n".join(
            f"        {line(key)}: {{\n" + ",\n".join(f"          {line(pid)}: {line(v)}" for pid, v in tl[key].items())
            + "\n        }" for key in ("vp", "cards_from_dice"))
        out.append(f"    {line(gid)}: {{\n      \"twosheep_id\": {line(g['twosheep_id'])},\n"
                   f"      \"players\": {{\n{players}\n      }},\n"
                   f"      \"timeline\": {{\n        \"turn\": {line(tl['turn'])},\n{series}\n      }}\n"
                   f"    }}" + ("," if i < len(games) - 1 else ""))
    return "\n".join(out + ["  }", "}"]) + "\n"


def events_text(doc) -> str:
    """replay_events.json with one line per event row, so diffs stay readable."""
    line = lambda v: json.dumps(v, ensure_ascii=False, separators=(",", ":"))
    out = ["{", f'  "schema_version": {line(doc["schema_version"])},', f'  "source": {line(doc["source"])},', '  "games": {']
    games = list(doc["games"].items())
    for i, (gid, g) in enumerate(games):
        parts = []
        for k, v in g.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                parts.append(f"      {line(k)}: [\n" + ",\n".join(f"        {line(x)}" for x in v) + "\n      ]")
            else:
                parts.append(f"      {line(k)}: {line(v)}")
        out.append(f"    {line(gid)}: {{\n" + ",\n".join(parts) + "\n    }" + ("," if i < len(games) - 1 else ""))
    return "\n".join(out + ["  }", "}"]) + "\n"


# ---------------------------------------------------------------------------
# Statistics helpers
# ---------------------------------------------------------------------------

def finishing_ranks(game):
    """Winner is rank 1. Others by VP, ties share a rank (1, 2, 3, 3, 5). A bot with unknown VP gets no rank."""
    others = sorted((r for r in game["players"] if r["player"] != game["winner"] and r.get("vp") is not None),
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


def poisson_binomial_step(pmf, p):
    """Add one Bernoulli(p) trial to the pmf of a sum of independent trials."""
    out = [0.0] * (len(pmf) + 1)
    for k, q in enumerate(pmf):
        out[k] += q * (1 - p)
        out[k + 1] += q * p
    return out


def luck_band(st, level=0.95):
    """Central range of wins above expected under chance alone: the exact (level) quantiles of the
    Poisson binomial number of wins, minus expected wins. Discrete, so each tail holds at most (1 - level) / 2."""
    a, cdf, lo, hi = (1 - level) / 2, 0.0, None, None
    for k, q in enumerate(st["dist"]):
        cdf += q
        if lo is None and cdf > a:
            lo = k
        if hi is None and cdf >= 1 - a - 1e-12:
            hi = k
            break
    return [r3(lo - st["expected"]), r3(hi - st["expected"])]


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


# ---------------------------------------------------------------------------
# Main computation
# ---------------------------------------------------------------------------

def replay_row(st):
    """The replay numbers the game page shows for one player."""
    keys = ["resources_from_dice", "production", "gold_from_dice", "expected_from_dice", "blocked_by_robber",
            "opening_dots", "rolls", "sevens_rolled", "robber_moves", "steals", "stolen_from", "cards_discarded",
            "monopoly_cards", "trades", "bank_trades", "built", "dev_cards_played", "longest_road_length", "max_hand"]
    return {k: st[k] for k in keys}


def player_colors(players_doc, games):
    """Each player's site color: the TwoSheep color they used most over all games, ties going to the one used
    most recently. Players with more games choose first; anyone whose favorite is taken gets their next most
    used color, then the first free one in GAME_COLORS. The same in every filter, so a player never changes color."""
    uses = {p["id"]: {} for p in players_doc["players"]}
    for i, g in enumerate(games):  # games are in date order, so i is recency
        for r in g["players"]:
            c = r.get("game_color")
            if r["player"] in uses and c in GAME_COLORS:
                n, _ = uses[r["player"]].get(c, (0, 0))
                uses[r["player"]][c] = (n + 1, i)
    out, taken = {}, set()
    for pid in sorted(uses, key=lambda k: (-sum(n for n, _ in uses[k].values()), k)):
        ranked = sorted(uses[pid], key=lambda c: uses[pid][c], reverse=True)
        out[pid] = next((c for c in ranked + GAME_COLORS if c not in taken), None)
        taken.add(out[pid])
    return out


def compute(players_doc, games, number_of, name_mode="usernames", replays=None, colors=None):
    """Every stat for one slice of games. number_of maps game id to its number among all games.
    replays maps game id to its data/replays.json entry, for the games that have one.
    colors maps player id to their site color (player_colors over all games)."""
    replays = replays or {}
    colors = colors or {}
    players = {p["id"]: p for p in players_doc["players"]}

    history = {pid: [] for pid in players}
    standing = {pid: {"wins": 0, "expected": 0.0, "dist": [1.0]} for pid in players}  # running totals for the ranking

    acc = {pid: defaultdict(list) for pid in players}
    by_count = {pid: defaultdict(lambda: {"games": 0, "wins": 0, "vp": []}) for pid in players}
    by_exp = {pid: defaultdict(lambda: {"games": 0, "wins": 0, "vp": [], "beat": []}) for pid in players}
    by_seat = {pid: defaultdict(lambda: {"games": 0, "wins": 0, "finish": []}) for pid in players}
    by_color = {pid: defaultdict(int) for pid in players}
    h2h = defaultdict(lambda: {"games": 0, "ahead": 0, "behind": 0, "tied": 0, "wins": 0, "losses_to": 0,
                               "replay_games": 0, "steals": 0, "trades": 0})
    rp = {pid: defaultdict(list) for pid in players}  # per-game replay numbers
    rp_tot = {pid: defaultdict(int) for pid in players}
    vp_src = {pid: defaultdict(int) for pid in players}
    dev = {pid: defaultdict(int) for pid in players}
    all_dice = {s: 0 for s in DICE_FACES}
    out_games = []
    ranks_after = []  # leaderboard rank of every player with a game, after each game of the slice

    def rank_key(pid):
        st = standing[pid]
        return (-r3(st["wins"] - st["expected"]), -(r3(mean(acc[pid]["table_share"])) or 0), -st["wins"],
                display_name(players[pid], name_mode).lower())

    for idx, g in enumerate(games, start=1):
        rows = g["players"]
        n = len(rows)  # every seat, bots included: expected wins and beat rate use it
        replay = replays.get(g["id"])
        ranks = finishing_ranks(g)
        win_vp = max(r["vp"] for r in rows if r.get("vp") is not None)
        target = (g.get("settings") or {}).get("vp_to_win") or win_vp
        prod_vals = [r.get("resources_from_dice") for r in rows if r.get("resources_from_dice") is not None]
        prod_mean = mean(prod_vals) if len(prod_vals) == n else None
        known_vp = [r["vp"] for r in rows if r.get("vp") is not None]
        table_vp = sum(known_vp) if len(known_vp) == n else None

        game_rows = []
        for r in rows:
            pid = r["player"]
            if is_bot(pid):
                continue
            rank = ranks[pid]
            if is_guest(pid):
                game_rows.append({"player": pid, "guest": True, "rank": rank, "vp": r["vp"], "seat": r.get("seat"),
                                  "game_color": r.get("game_color"), "vp_breakdown": r.get("vp_breakdown"),
                                  "dev_cards_bought": r.get("dev_cards_bought"),
                                  "resources_from_dice": r.get("resources_from_dice"), "above_expected": None})
                continue
            won = pid == g["winner"]
            opp = [o for o in rows if o["player"] != pid and o["player"] in ranks]
            beaten = sum(1 if ranks[pid] < ranks[o["player"]] else 0.5 if ranks[pid] == ranks[o["player"]] else 0
                         for o in opp)
            a = acc[pid]
            a["won"].append(1 if won else 0)
            a["expected_win"].append(1 / n)
            a["vp"].append(r["vp"])
            a["vp_share"].append(r["vp"] / target)
            if table_vp:
                a["table_share"].append(r["vp"] / table_vp)
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
            if r.get("game_color"):
                by_color[pid][r["game_color"]] += 1
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
            if replay:
                st = replay["players"][pid]
                for k in REPLAY_AVERAGES:
                    rp[pid][k].append(st[k])
                rp[pid]["luck"].append(st["resources_from_dice"] - st["expected_from_dice"])
                rp[pid]["knights"].append(st["dev_cards_played"]["knight"])
                for k in BUILT:
                    rp[pid]["built_" + k].append(st["built"][k])
                for k in ("resources_from_dice", "expected_from_dice", "rolls", "sevens_rolled"):
                    rp_tot[pid][k] += st[k]
                rp_tot[pid]["games"] += 1
                rp_tot[pid]["max_hand"] = max(rp_tot[pid]["max_hand"], st["max_hand"])
            for o in opp:
                if is_anon(o["player"]):
                    continue
                key = (pid, o["player"])
                h = h2h[key]
                h["games"] += 1
                if replay:
                    h["replay_games"] += 1
                    h["steals"] += replay["players"][pid]["steals_by_victim"].get(o["player"], 0)
                    h["trades"] += replay["players"][pid]["trade_partners"].get(o["player"], 0)
                if ranks[pid] < ranks[o["player"]]:
                    h["ahead"] += 1
                elif ranks[pid] > ranks[o["player"]]:
                    h["behind"] += 1
                else:
                    h["tied"] += 1
                h["wins"] += won
                h["losses_to"] += o["player"] == g["winner"]

            # Ranking: a win is worth 1, and every game costs 1/n, the share of wins chance alone would give.
            # Under chance each game is a 1-in-n draw, so wins follow a Poisson binomial; dist is its pmf.
            st = standing[pid]
            st["wins"] += won
            st["expected"] += 1 / n
            st["dist"] = poisson_binomial_step(st["dist"], 1 / n)
            history[pid].append({
                "game": g["id"], "index": idx, "number": number_of[g["id"]], "date": g["date"], "won": won,
                "delta": r3((1 if won else 0) - 1 / n),
                "above_expected": r3(st["wins"] - st["expected"]), "luck_band": luck_band(st),
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
                "above_expected": r3((1 if won else 0) - 1 / n),
            })

        game_rows.sort(key=lambda x: (x["rank"], x["player"]))
        active = sorted((pid for pid in players if acc[pid]["won"]), key=rank_key)
        ranks_after.append({pid: i for i, pid in enumerate(active, start=1)})
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
            "n_bots": sum(1 for r in rows if is_bot(r["player"])),
            "players": game_rows,
            "dice": dsum,
            "has_events": bool(g.get("events")),
            "has_replay": bool(replay),
        })

    # Per-player summary
    out_players = []
    for pid, p in players.items():
        a = acc[pid]
        gp = len(a["won"])
        wins = sum(a["won"])
        st = standing[pid]
        vs = vp_src[pid]
        last = history[pid][-RECENT_GAMES:]
        streak = 0
        for h in reversed(history[pid]):
            if not h["won"]:
                break
            streak += 1
        recent_above = r3(sum(h["delta"] for h in last))
        is_active = bool(last) and last[-1]["index"] > len(games) - ACTIVE_WINDOW
        dv = dev[pid]
        out_players.append({
            "id": pid,
            "name": display_name(p, name_mode),
            "initials": p.get("initials"),
            "aliases": p.get("aliases", []),
            "color_slot": p["color_slot"],
            "color": colors.get(pid),
            "by_color": dict(sorted(by_color[pid].items(), key=lambda kv: (-kv[1], kv[0]))),
            "games": gp,
            "wins": wins,
            "win_rate": r3(wins / gp) if gp else None,
            "win_rate_ci": [r3(x) for x in wilson(wins, gp)] if gp else None,
            "expected_wins": r3(sum(a["expected_win"])),
            "above_expected": r3(wins - sum(a["expected_win"])) if gp else None,
            "luck_band": luck_band(st) if gp else None,
            "avg_table_share": r3(mean(a["table_share"])),
            "avg_vp": r3(mean(a["vp"])),
            "avg_vp_share": r3(mean(a["vp_share"])),
            "avg_rank": r3(mean(a["rank"])),
            "beat_rate": r3(mean(a["beat_rate"])),
            "finish_counts": {str(k): a["rank"].count(k) for k in range(1, 9) if a["rank"].count(k)},
            "standing_history": history[pid],
            # Movement: rank before the slice's latest game, and before its last RECENT_GAMES games (None: no games yet).
            "rank_prev": ranks_after[-2].get(pid) if len(ranks_after) > 1 else None,
            "rank_recent_ago": ranks_after[-RECENT_GAMES - 1].get(pid) if len(ranks_after) > RECENT_GAMES else None,
            "recent": {
                "games": [{"game": h["game"], "date": h["date"], "won": h["won"], "delta": h["delta"]} for h in last],
                "above": recent_above, "wins": sum(1 for h in last if h["won"]), "streak": streak,
                "active": is_active, "on_fire": is_active and len(last) == RECENT_GAMES and recent_above >= FIRE_ABOVE,
            } if last else None,
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
            "replay": replay_summary(rp[pid], rp_tot[pid]),
        })

    # Wins above expected, then share of the table's VP (the World Championship tiebreaker), then wins.
    out_players.sort(key=lambda x: (x["games"] == 0, -(x["above_expected"] or 0), -(x["avg_table_share"] or 0),
                                    -x["wins"], x["name"].lower()))
    for i, p in enumerate(out_players, start=1):
        p["leaderboard_rank"] = i if p["games"] else None

    out_h2h = [
        {"player": a, "opponent": b, **v,
         "ahead_rate": r3((v["ahead"] + 0.5 * v["tied"]) / v["games"]),
         "stolen_by": h2h[(b, a)]["steals"] if (b, a) in h2h else 0}
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
            "games_with_replays": sum(1 for g in out_games if g["has_replay"]),
            "games_with_guests": sum(1 for g in out_games if g["n_guests"]),
        },
        "dice_overall": dice_summary(all_dice),
        "players": out_players,
        "head_to_head": out_h2h,
        "games": list(reversed(out_games)),  # newest first
    }


def replay_summary(lists, totals):
    """A player's per-game averages over the games that have a decoded replay."""
    n = totals["games"]
    if not n:
        return None
    out = {"games": n}
    for k, v in lists.items():
        out["avg_" + k] = r3(mean(v))
    exp = totals["expected_from_dice"]
    out["dice_ratio"] = r3(totals["resources_from_dice"] / exp) if exp else None
    out["rolls"] = totals["rolls"]
    out["sevens_rolled"] = totals["sevens_rolled"]
    out["seven_rate"] = r3(totals["sevens_rolled"] / totals["rolls"]) if totals["rolls"] else None
    out["max_hand"] = totals["max_hand"]
    return out


def dense_timeline(tl, turns):
    """Fill a replay timeline forward so it has a value for every turn from 0 to the last."""
    out = {"vp": {}, "cards_from_dice": {}}
    for key in out:
        for pid, vals in tl[key].items():
            series, j, cur = [], 0, 0
            for t in range(turns + 1):
                while j < len(tl["turn"]) and tl["turn"][j] <= t:
                    cur = vals[j]
                    j += 1
                series.append(cur)
            out[key][pid] = series
    return out


SIZES = {"3p": lambda n: n == 3, "4p": lambda n: n >= 4}  # table-size filters, by seat count


def compute_views(players_doc, games_doc, name_mode="usernames", replays_doc=None, fast=False, events_doc=None):
    """One full stats view per filter: all games, each expansion, each scenario, and each of those at 3 seats
    and at 4 or more.

    Each view is computed from scratch on its own slice, so the Seafarers ranking
    only counts Seafarers games.
    """
    games = sorted(games_doc["games"], key=lambda g: (g["date"], g["id"]))
    number_of = {g["id"]: i for i, g in enumerate(games, start=1)}
    replays = (replays_doc or {}).get("games") or {}
    slices = {"all": games}
    for exp in sorted({expansion_of(g) for g in games}, key=lambda e: (e not in EXPANSIONS, e)):
        slices[exp] = [g for g in games if expansion_of(g) == exp]
        for scen in SCENARIOS.get(exp, {}):
            sub = [g for g in slices[exp] if (g.get("settings") or {}).get("scenario") == scen]
            if sub:
                slices[f"{exp}/{scen}"] = sub
    # Every game-type view also splits by table size (seats, bots included): key "<type>+3p" or "<type>+4p".
    for key, sub in list(slices.items()):
        for size, keep in SIZES.items():
            part = [g for g in sub if keep(len(g["players"]))]
            if part:
                slices[f"{key}+{size}"] = part
    view_list = []
    for key, sub in slices.items():
        base, _, size = key.partition("+")
        exp, _, scen = base.partition("/")
        view_list.append({
            "key": key,
            "label": "All games" if base == "all" else (SCENARIOS[exp][scen] if scen else type_label(base)),
            "parent": exp if scen else ("all" if base != "all" else None),
            "type": base,
            "size": size or None,
            "games": len(sub),
            "unlabeled_scenarios": (sum(1 for g in sub if not (g.get("settings") or {}).get("scenario"))
                                    if base in SCENARIOS else None),
        })
    colors = player_colors(players_doc, games)
    views = {key: compute(players_doc, sub, number_of, name_mode, replays, colors) for key, sub in slices.items()}
    pids = [p["id"] for p in players_doc["players"]]
    all_ins = insights.view_insights(games, replays, pids, is_anon, finishing_ranks, fast=fast)
    for key, sub in slices.items():
        views[key]["insights"] = all_ins if key == "all" else insights.view_insights(
            sub, replays, pids, is_anon, finishing_ranks, all_view=all_ins, fast=fast)
    events = (events_doc or {}).get("games") or {}
    ctx = {"pids": pids, "is_anon": is_anon, "is_bot": is_bot, "is_guest": is_guest, "finishing_ranks": finishing_ranks,
           "fast": fast, "players": {p["id"]: p for p in players_doc["players"]}}
    module_out = {}
    for mod in MODULES:
        module_out[mod.KEY] = mod.compute_all(games, replays, events, ctx)
        if hasattr(mod, "compute_view"):
            for key, sub in slices.items():
                views[key][mod.KEY] = mod.compute_view(sub, replays, events, ctx, module_out[mod.KEY])
    return {
        "schema_version": 3,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ranking": {
            "name": "Wins above expected",
            "expected": "sum of 1/n over games played, n counting every seat",
            "luck_band": "central 95% of wins minus expected under chance (exact Poisson binomial, each game a 1-in-n draw)",
            "tiebreak": "average share of the table's VP",
            "recent_games": RECENT_GAMES, "fire_above": FIRE_ABOVE, "active_window": ACTIVE_WINDOW,
        },
        "view_list": view_list,
        "player_names": name_mode,
        "views": views,
        # Closeness percentiles always use every decoded game, so a game's tile never changes with the filter.
        "closeness": insights.closeness(games, replays, lambda g: len(g["players"]),
                                        (events_doc or {}).get("games")),
        **module_out,
        # Shared by every view, so stored once: per-game replay numbers and turn-by-turn timelines.
        "game_replays": {gid: {pid: replay_row(st) for pid, st in r["players"].items()} for gid, r in replays.items()},
        "timelines": {gid: dense_timeline(r["timeline"], max(r["timeline"]["turn"]))
                      for gid, r in replays.items()},
    }


def build(check_only=False, data_dir=DATA, out_dir=DIST):
    try:
        players_doc = load_json(data_dir / "players.json")
        games_doc = load_json(data_dir / "games.json")
        replays_path = data_dir / "replays.json"
        replays_doc = load_json(replays_path) if replays_path.exists() else None
        events_path = data_dir / "replay_events.json"
        events_doc = load_json(events_path) if events_path.exists() else None
    except DataError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    errors, warnings = validate(players_doc, games_doc, replays_doc)
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
    stats = compute_views(players_doc, games_doc, name_mode, replays_doc, events_doc=events_doc)
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
