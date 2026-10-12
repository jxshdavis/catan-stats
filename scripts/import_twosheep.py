#!/usr/bin/env python3
"""Turn fetched TwoSheep game summaries (raw/twosheep/) into data/games.json entries.

    python scripts/import_twosheep.py              # dry run: report what would change
    python scripts/import_twosheep.py --write      # apply the changes to data/games.json
    python scripts/import_twosheep.py --accounts   # list every account seen, and whose it is

Rules:
- Only finished games with at least 3 players are imported.
- Players are matched by TwoSheep account, not by username, because names
  change all the time. players.json lists each person's accounts under
  "twosheep_accounts" as a short SHA-256 hash, so raw account ids never land
  in the repo. Anyone else becomes a guest ("guest-1", "guest-2", ...).
- A TwoSheep bot keeps its seat as "bot-1", "bot-2", ... It counts in the
  number of seats ("n_seats") and as an opponent, but is never rated or listed.
  Its VP comes from the decoded replay, since summaries only score humans.
- A game with two accounts of the same person is left out (and removed if it
  was imported before the accounts were grouped).
- Each game is imported once, keyed on its TwoSheep replay id ("twosheep_id").
- Each player's "aliases" in players.json are kept as every TwoSheep name
  their accounts have used, most used on the site first; the site lists them on
  the player's page and, in "usernames" mode, uses the first as their name.
- A hand-entered game with the same players and VP within a day is linked to
  its replay instead of being added twice. Linking and re-running only fill
  fields that are empty; a field that disagrees is reported, never overwritten.
- When a decoded replay is in raw/twosheep/replay_stats/ (made by the local
  scripts/twosheep_replay.py), it sets turns, dice, resources from dice, dev
  cards bought and the VP breakdown. Unlike the summary fields, these replace
  hand-entered values: the replay is checked move by move against TwoSheep's
  result, while end-screen numbers were typed from screenshots. Each replaced
  value is reported. Its detailed stats and turn-by-turn timeline go to
  data/replays.json, which is rebuilt every run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from string import ascii_lowercase

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build  # noqa: E402  (validation and shared constants)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "raw" / "twosheep" / "replays"
REPLAY_STATS = ROOT / "raw" / "twosheep" / "replay_stats"
SOURCE = "twosheep import: game summary"
MIN_PLAYERS = 3
# TwoSheep map numbers (the options field "gM") that we've identified, as (expansion, scenario).
# Add one here once it's confirmed, then re-run the import to fill in older games.
# Names from TwoSheep's GameMode list, sent by the developer on 2026-10-11. A summary
# without "gM" is mode 0: TwoSheep leaves out options that have their default value.
TWOSHEEP_MAPS = {
    None: ("base", None),                  # BASE_4P
    0: ("base", None),                     # BASE_4P
    1: ("base", None),                     # BASE_6P
    8: ("base", None),                     # BASE_RANDOM_4P
    33: ("base", None),                    # BASE_4P_LEGACY
    4: ("seafarers", "new_shores"),        # SF_NEW_SHORES
    5: ("seafarers", "fog_islands"),       # SF_FOG_ISLAND
    6: ("seafarers", "four_islands"),      # SF_FOUR_ISLANDS
    7: ("seafarers", "through_the_desert"),  # SF_DESERT
    10: ("seafarers", "new_shores"),       # N_SF_3P_NEW_SHORES
    11: ("seafarers", "new_shores"),       # N_SF_4P_NEW_SHORES
    12: ("seafarers", "four_islands"),     # N_SF_3P_FOUR_ISLANDS
    13: ("seafarers", "four_islands"),     # N_SF_4P_FOUR_ISLANDS
    14: ("seafarers", "fog_islands"),      # N_SF_3P_FOG_ISLANDS
    15: ("seafarers", "fog_islands"),      # N_SF_4P_FOG_ISLANDS
    16: ("seafarers", "through_the_desert"),  # N_SF_3P_DESERT
    17: ("seafarers", "through_the_desert"),  # N_SF_4P_DESERT
    18: ("seafarers", "new_world"),        # N_SF_NEW_WORLD
    19: ("seafarers", "new_shores"),       # N_SF_6P_NEW_SHORES
    20: ("seafarers", "six_islands"),      # N_SF_6P_SIX_ISLANDS
    21: ("seafarers", "fog_islands"),      # N_SF_6P_FOG_ISLANDS
    22: ("seafarers", "through_the_desert"),  # N_SF_6P_DESERT
    23: ("seafarers", "new_world"),        # N_SF_6P_NEW_WORLD
}


def account_key(uid: str) -> str:
    """Public stand-in for a TwoSheep account id: first 16 hex digits of its SHA-256."""
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()[:16]


def load_summaries(raw_dir: Path):
    out = []
    for path in sorted(raw_dir.glob("*.json")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        rec.setdefault("replay_id", path.stem)
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# One summary to one game
# ---------------------------------------------------------------------------

def to_game(rec, owner, tz):
    """Map a summary to a games.json entry without an id. Returns (game, None) or (None, skip reason)."""
    f = rec["fields"]
    pdata = f.get("p") or {}
    opts = f.get("o") or {}
    if not f.get("d"):
        return None, "unfinished"
    if len(pdata) < MIN_PLAYERS:
        return None, f"{len(pdata)} players"
    if any(not isinstance(p.get("v"), int) for p in pdata.values()):
        return None, "missing VP"
    winners = [uid for uid, p in pdata.items() if p.get("w")]
    if len(winners) != 1:
        return None, f"{len(winners)} winners marked"

    seat_opts = [s for s in (opts.get("ps") or {}).values() if isinstance(s, dict)]
    color_of = {s.get("id"): s.get("c") for s in seat_opts}
    # Bot seats are in the options but not in the scored players: their "p" is not "ui".
    bots = sorted((s for s in seat_opts if s.get("id") not in pdata and s.get("p") not in (None, "ui")
                   and isinstance(s.get("i"), int)), key=lambda s: s["i"])
    seat_of = {uid: p.get("o") for uid, p in pdata.items()}
    seat_of.update({("bot", b["i"]): b["i"] for b in bots})
    n_seats = len(pdata) + len(bots)
    seats_known = sorted(o for o in seat_of.values() if isinstance(o, int)) == list(range(n_seats))
    uids = sorted(seat_of, key=lambda u: (seat_of[u] if seats_known else 0,
                                          isinstance(u, tuple), (pdata.get(u) or {}).get("n") or ""))

    rows, ids, guests, nbots = [], {}, 0, 0
    for uid in uids:
        if isinstance(uid, tuple):
            nbots += 1
            b = next(b for b in bots if b["i"] == uid[1])
            rows.append({"player": f"{build.BOT_PREFIX}{nbots}", "seat": b["i"] + 1 if seats_known else None,
                         "game_color": b.get("c"), "vp": None})
            continue
        pid = owner.get(account_key(uid))
        if pid is None:
            guests += 1
            pid = f"{build.GUEST_PREFIX}{guests}"
        elif pid in ids.values():
            return None, f"two accounts of {pid} in one game"
        ids[uid] = pid
        rows.append({
            "player": pid,
            "seat": pdata[uid]["o"] + 1 if seats_known else None,
            "game_color": color_of.get(uid),
            "vp": pdata[uid]["v"],
        })

    code = opts.get("gM")
    expansion, scenario = TWOSHEEP_MAPS.get(code, ("seafarers" if opts.get("sf") else None, None))
    if expansion == "base" and opts.get("sf"):
        expansion, scenario = "seafarers", None
    started = datetime.fromtimestamp(f["c"], tz=timezone.utc).astimezone(tz)
    return {
        "date": started.date().isoformat(),
        "platform": "twosheep",
        "source": SOURCE,
        "twosheep_id": rec["replay_id"],
        # TwoSheep leaves out options at their default, and the default target is 10 VP
        "settings": {"vp_to_win": opts.get("wVPA") or 10, "expansion": expansion, "scenario": scenario, "notes": ""},
        "n_seats": n_seats,
        "turns": None,
        "duration_seconds": None,
        "winner": ids[winners[0]],
        "players": rows,
        "dice": None,
        "events": None,
        "_started": started,
        "_map": code,
    }, None


# ---------------------------------------------------------------------------
# Merging into games.json
# ---------------------------------------------------------------------------

def same_result(a, b):
    key = lambda g: sorted((r["player"], r["vp"]) for r in g["players"] if not build.is_bot(r["player"]))
    return key(a) == key(b)


def fill(existing, new):
    """Fill empty fields of existing from new. Returns (changes, conflicts) as strings."""
    changes, conflicts = [], []
    if existing.get("winner") != new["winner"]:
        conflicts.append(f"winner is {existing.get('winner')}, TwoSheep says {new['winner']}")
    if existing.get("date") != new["date"]:
        conflicts.append(f"date is {existing.get('date')}, TwoSheep says {new['date']}")
    es = existing.setdefault("settings", {})
    for k in ("vp_to_win", "expansion", "scenario"):
        v = new["settings"][k]
        if v is None:
            continue
        if es.get(k) is None:
            es[k] = v
            changes.append(f"settings.{k} = {v}")
        elif es[k] != v:
            conflicts.append(f"settings.{k} is {es[k]}, TwoSheep says {v}")
    rows = {r["player"]: r for r in existing["players"]}
    if new.get("n_seats") is not None and existing.get("n_seats") is None and len(existing["players"]) == new["n_seats"]:
        put_after(existing, "n_seats", new["n_seats"], "settings")
        changes.append(f"n_seats = {new['n_seats']}")
    if any(build.is_bot(nr["player"]) for nr in new["players"]):
        conflicts.append("TwoSheep has a bot seat this hand-entered game doesn't list")
    for nr in new["players"]:
        if build.is_bot(nr["player"]):
            continue
        r = rows.get(nr["player"])
        if r is None:
            conflicts.append(f"{nr['player']} is not in this game")
            continue
        if r.get("vp") != nr["vp"]:
            conflicts.append(f"{nr['player']} has {r.get('vp')} VP, TwoSheep says {nr['vp']}")
        if nr["game_color"] is not None:
            if r.get("game_color") is None:
                r["game_color"] = nr["game_color"]
                changes.append(f"{nr['player']} game_color = {nr['game_color']}")
            elif r["game_color"] != nr["game_color"]:
                conflicts.append(f"{nr['player']} game_color is {r['game_color']}, TwoSheep says {nr['game_color']}")
    if new["players"] and all(nr["seat"] is not None for nr in new["players"]) \
            and len(new["players"]) == len(existing["players"]):
        if all(r.get("seat") is None for r in existing["players"]):
            for nr in new["players"]:
                if nr["player"] in rows:
                    rows[nr["player"]]["seat"] = nr["seat"]
            changes.append("seats")
        elif any(rows.get(nr["player"], {}).get("seat") != nr["seat"] for nr in new["players"]):
            conflicts.append("seat order differs from TwoSheep")
    return changes, conflicts


def refresh_imported(existing, new):
    """For a game this importer created: players come from TwoSheep, so rebuild them
    (an account added to players.json since turns a guest into that player). Extra
    hand-added fields on a row are kept by seat, or by player when seats are unknown (say a
    TwoSheep bot took a seat). Settings are only filled, never replaced."""
    changes = []
    old_by_seat = {r.get("seat"): r for r in existing["players"]}
    old_by_player = {r.get("player"): r for r in existing["players"]}
    rows = []
    for nr in new["players"]:
        old = old_by_seat.get(nr["seat"], {}) if nr["seat"] is not None and nr["seat"] in old_by_seat \
            else old_by_player.get(nr["player"], {})
        row = {**old, **nr}
        if nr["vp"] is None and old.get("player") == nr["player"]:
            row["vp"] = old.get("vp")  # a bot's VP, set from the decoded replay
        rows.append(row)
    if [(r["player"], r["vp"], r["seat"], r["game_color"]) for r in rows] != \
            [(r.get("player"), r.get("vp"), r.get("seat"), r.get("game_color")) for r in existing["players"]]:
        changes.append("players")
    existing["players"] = rows
    if new.get("n_seats") is not None and existing.get("n_seats") != new["n_seats"]:
        put_after(existing, "n_seats", new["n_seats"], "settings")
        changes.append(f"n_seats = {new['n_seats']}")
    if existing.get("winner") != new["winner"]:
        existing["winner"] = new["winner"]
        changes.append(f"winner = {new['winner']}")
    sub_changes, conflicts = fill(existing, {**new, "players": [], "winner": existing["winner"]})
    return changes + sub_changes, conflicts


def put_after(game, key, value, after):
    """Set game[key], placing a new key right after `after` so games.json keeps its field order."""
    if key in game:
        game[key] = value
        return
    items = list(game.items())
    at = next((i + 1 for i, (k, _) in enumerate(items) if k == after), len(items))
    items.insert(at, (key, value))
    game.clear()
    game.update(items)


def link(game, twosheep_id):
    """Add twosheep_id right after source, so it sits with the other provenance fields."""
    put_after(game, "twosheep_id", twosheep_id, "source")


def next_ids(games, new_games):
    """Give new games ids like 2026-10-07-a, lettered in start order after the date's existing ids."""
    taken = {g["id"] for g in games}
    for g in sorted(new_games, key=lambda g: g["_started"]):
        for letter in ascii_lowercase:
            gid = f"{g['date']}-{letter}"
            if gid not in taken:
                g["id"] = gid
                taken.add(gid)
                break
        else:
            raise SystemExit(f"error: more than 26 games on {g['date']}")


def plan(players_doc, games_doc, summaries, tz):
    owner = {acct: p["id"] for p in players_doc["players"] for acct in p.get("twosheep_accounts", [])}
    games = games_doc["games"]
    by_tsid = {g["twosheep_id"]: g for g in games if g.get("twosheep_id")}
    report = {"new": [], "linked": [], "updated": [], "removed": [], "unchanged": 0, "skipped": {}, "conflicts": [],
              "unknown_maps": {}, "invalid": [], "replay_filled": [], "replay_corrected": []}
    new_games = []

    def drop(rid, why):
        """A game that no longer qualifies (say, two of one person's accounts in it) leaves games.json
        if this importer added it; a hand-entered game is only flagged."""
        old = by_tsid.get(rid)
        if old is None:
            return
        if old.get("source") == SOURCE:
            games.remove(old)
            report["removed"].append((old["id"], why))
        else:
            report["conflicts"].append((old["id"], f"its TwoSheep summary is now excluded ({why})"))

    for rec in sorted(summaries, key=lambda r: r["fields"].get("c") or 0):
        g, why = to_game(rec, owner, tz)
        if g is None:
            report["skipped"].setdefault(why, []).append(rec["replay_id"])
            drop(rec["replay_id"], why)
            continue
        errors, _ = build.validate(players_doc, {"games": [{**g, "id": "check"}]})
        if errors:
            report["invalid"].append((rec["replay_id"], [e.split(": ", 2)[-1] for e in errors]))
            drop(rec["replay_id"], "invalid")
            continue
        if g["settings"]["scenario"] is None and g["_map"] not in TWOSHEEP_MAPS:
            report["unknown_maps"].setdefault((g["_map"], g["settings"]["expansion"]), []).append(g)
        existing = by_tsid.get(g["twosheep_id"])
        if existing is None:
            day = datetime.fromisoformat(g["date"]).date()
            candidates = [e for e in games if not e.get("twosheep_id") and same_result(e, g)
                          and abs((datetime.fromisoformat(e["date"]).date() - day).days) <= 1]
            if len(candidates) == 1:
                existing = candidates[0]
                g["id"] = existing["id"]
                link(existing, g["twosheep_id"])
                changes, conflicts = fill(existing, g)
                report["linked"].append((existing["id"], g["twosheep_id"], changes))
                report["conflicts"] += [(existing["id"], c) for c in conflicts]
                continue
            if len(candidates) > 1:
                report["conflicts"].append((g["twosheep_id"], "matches more than one hand-entered game"))
                continue
            new_games.append(g)
            continue
        g["id"] = existing["id"]
        if existing.get("source") == SOURCE:
            changes, conflicts = refresh_imported(existing, g)
        else:
            changes, conflicts = fill(existing, g)
        if changes:
            report["updated"].append((existing["id"], changes))
        else:
            report["unchanged"] += 1
        report["conflicts"] += [(existing["id"], c) for c in conflicts]
    next_ids(games, new_games)
    for g in new_games:
        report["new"].append(g)
        games.append({"id": g["id"], **{k: v for k, v in g.items() if k != "id" and not k.startswith("_")}})
    games.sort(key=lambda g: (g["date"], g["id"]))
    return report


# ---------------------------------------------------------------------------
# Decoded replays
# ---------------------------------------------------------------------------

def load_replay_stats(folder: Path):
    if not folder.exists():
        return {}
    return {path.stem: json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.json"))}


def replay_seats(game, rec, owner):
    """Map each replay seat to a row of the game: by account, or by seat for guests. None if they don't line up."""
    rows = game["players"]
    by_pid = {r["player"]: r for r in rows}
    by_seat = {r.get("seat"): r for r in rows if r.get("seat") is not None}
    bots = [r for r in rows if build.is_bot(r["player"])]
    out = {}
    for rp in rec["players"]:
        if rp["account"] is None:  # a TwoSheep bot: its row by seat, or the only bot row when seats are unknown
            row = by_seat.get(rp["seat"]) if by_seat else (bots[0] if len(bots) == 1 else None)
            if row is None or not build.is_bot(row["player"]) or row["vp"] not in (None, rp["vp"]):
                return None
            out[rp["seat"]] = row
            continue
        pid = owner.get(account_key(rp["account"]))
        row = by_pid.get(pid) if pid else by_seat.get(rp["seat"])
        if row is None or row["vp"] != rp["vp"] or any(r is row for r in out.values()):
            return None
        out[rp["seat"]] = row
    return out if len(out) == len(rows) else None


def fill_from_replay(game, rec, seats):
    """Set fields from a decoded replay. The replay is checked against TwoSheep's own result, so it
    wins over anything typed in from the end screen. Returns (changes, corrections): corrections
    are hand-entered values the replay replaced, worded for the report."""
    changes, corrections = [], []

    def put(where, key, value, label):
        if where.get(key) is None:
            changes.append(label)
        elif where[key] != value:
            corrections.append(f"{label} was {where[key]}, now {value} from the replay")
        where[key] = value

    put(game, "turns", rec["turns"], "turns")
    for rp in rec["players"]:
        row = seats.get(rp["seat"])
        if row is not None and build.is_bot(row["player"]):
            put(row, "vp", rp["vp"], f"{row['player']} vp")
            if row.get("seat") is None:  # the replay's seat order fills seats TwoSheep's summary left out
                put(row, "seat", rp["seat"], f"{row['player']} seat")
    put(game, "dice", {"counts": rec["dice"]}, "dice")
    for rp in rec["players"]:
        row = seats.get(rp["seat"])
        if row is None:
            continue
        who = row["player"]
        put(row, "resources_from_dice", rp["resources_from_dice"], f"{who} resources_from_dice")
        put(row, "dev_cards_bought", {k: rp["dev_cards_bought"][k] for k in build.DEV_CARDS}, f"{who} dev_cards_bought")
        put(row, "vp_breakdown", rp["vp_breakdown"], f"{who} vp_breakdown")
    # One message per field kind, not per player, keeps the report short
    kinds = {}
    for c in changes:
        kinds.setdefault(c.split(" ")[-1], 0)
        kinds[c.split(" ")[-1]] += 1
    return [k if n == 1 else f"{k} ({n})" for k, n in kinds.items()], corrections


REPLAY_FIELDS = ["resources_from_dice", "production", "gold_from_dice", "expected_from_dice", "blocked_by_robber",
                 "opening_dots", "rolls", "sevens_rolled", "robber_moves", "steals", "stolen_from", "discards",
                 "cards_discarded", "monopoly_cards", "monopoly_lost", "trades", "trade_cards_given",
                 "trade_cards_received", "bank_trades", "bank_cards_given", "bank_cards_received", "built",
                 "dev_cards_played", "longest_road_length", "max_hand", "fog_discovered"]


def replay_entry(rec, seats):
    """data/replays.json entry for one game: stats by player id, timelines as one list per player."""
    pid = {seat: row["player"] for seat, row in seats.items()}
    players = {}
    for rp in rec["players"]:
        if rp["seat"] not in pid:
            continue
        d = {k: rp[k] for k in REPLAY_FIELDS}
        d["steals_by_victim"] = {pid[int(s)]: n for s, n in rp["steals_by_victim"].items() if int(s) in pid}
        d["trade_partners"] = {pid[int(s)]: n for s, n in rp["trade_partners"].items() if int(s) in pid}
        players[pid[rp["seat"]]] = d
    seat_order = [rp["seat"] for rp in rec["players"]]
    tl = rec["timeline"]
    timeline = {"turn": tl["turn"]}
    for key in ("vp", "cards_from_dice"):
        timeline[key] = {pid[s]: [snap[i] for snap in tl[key]] for i, s in enumerate(seat_order) if s in pid}
    return {"twosheep_id": rec["replay_id"], "players": players, "timeline": timeline}


# Per-action logs from decoder v2, copied as they are. Seats stay 1-based seat numbers; the entry's
# "seats" list maps each seat to its player id (or guest or bot id).
EVENT_KEYS = ["states", "roll_log", "robber_events", "trade_events", "dev_events", "discard_events",
              "monopoly_events", "opening_picks", "vp_events"]


def events_entry(rec, seats):
    return {"twosheep_id": rec["replay_id"], "decoder_version": rec["decoder_version"],
            "seats": [seats[s]["player"] for s in sorted(seats)],
            **({"dev_deck": rec["dev_deck"]} if "dev_deck" in rec else {}), **{k: rec[k] for k in EVENT_KEYS}}


def apply_replays(players_doc, games_doc, stats, report):
    """Fill games from decoded replays. Returns the data/replays.json document and the
    data/replay_events.json document (None when no replay has decoder v2 logs)."""
    owner = {acct: p["id"] for p in players_doc["players"] for acct in p.get("twosheep_accounts", [])}
    entries, events = {}, {}
    for game in games_doc["games"]:
        rec = stats.get(game.get("twosheep_id"))
        if rec is None:
            continue
        seats = replay_seats(game, rec, owner)
        if seats is None:
            report["conflicts"].append((game["id"], "the decoded replay's players or VP don't match this game"))
            continue
        changes, corrections = fill_from_replay(game, rec, seats)
        if changes:
            report["replay_filled"].append((game["id"], changes))
        report["replay_corrected"] += [(game["id"], c) for c in corrections]
        entries[game["id"]] = replay_entry(rec, seats)
        if all(k in rec for k in EVENT_KEYS) and sorted(seats) == list(range(1, len(rec["players"]) + 1)):
            events[game["id"]] = events_entry(rec, seats)
    report["replays"] = len(entries)
    report["replay_events"] = len(events)
    doc = {"schema_version": 1, "source": "decoded TwoSheep replay files", "games": entries}
    ev = {"schema_version": 1, "source": "decoded TwoSheep replay files, decoder v2 per-action logs",
          "games": events} if events else None
    return doc, ev


def print_report(report, names):
    new = report["new"]
    print(f"{len(new)} new, {len(report['linked'])} linked to hand-entered games, "
          f"{len(report['updated'])} updated, {len(report['removed'])} removed, {report['unchanged']} unchanged")
    for g in new:
        label = lambda pid: "Guest" if build.is_guest(pid) else "Bot" if build.is_bot(pid) else names.get(pid, pid)
        order = ", ".join(f"{label(r['player'])} {'?' if r['vp'] is None else r['vp']}"
                          for r in sorted(g["players"], key=lambda r: -(r["vp"] or 0)))
        print(f"  new     {g['id']}  {g['settings']['expansion'] or '?'}/{g['settings']['scenario'] or '?'}  {order}")
    for gid, tsid, changes in report["linked"]:
        print(f"  linked  {gid} to replay {tsid}: {', '.join(changes) or 'nothing to fill'}")
    for gid, changes in report["updated"]:
        print(f"  updated {gid}: {', '.join(changes)}")
    for gid, why in report["removed"]:
        print(f"  removed {gid}: {why}")
    if "replays" in report:
        print(f"\n{report['replays']} games have decoded replays, {report.get('replay_events', 0)} with per-action logs")
        for gid, changes in report["replay_filled"]:
            print(f"  filled  {gid}: {', '.join(changes)}")
        for gid, c in report["replay_corrected"]:
            print(f"  corrected {gid}: {c}")
    if report["skipped"]:
        print("\nskipped: " + ", ".join(f"{len(v)} {k}" for k, v in sorted(report["skipped"].items(), key=lambda kv: -len(kv[1]))))
    for tsid, errs in report["invalid"]:
        print(f"invalid {tsid}: {'; '.join(errs)}")
    if report["unknown_maps"]:
        print("\nunidentified TwoSheep maps (scenario left empty; tell Claude which these are):")
        for (code, exp), gs in sorted(report["unknown_maps"].items(), key=lambda kv: (kv[0][0] is None, kv[0][0] or 0)):
            counts = sorted({len(g["players"]) for g in gs})
            targets = sorted({g["settings"]["vp_to_win"] for g in gs}, key=lambda v: (v is None, v))
            print(f"  map {code}: {len(gs)} games, {exp or 'no Seafarers flag'}, {'/'.join(map(str, counts))} players, "
                  f"VP target {'/'.join(str(t) for t in targets)}, e.g. {', '.join(g['id'] for g in gs[:3])}")
    if report["conflicts"]:
        print("\nconflicts (left as they are in games.json):")
        for gid, c in report["conflicts"]:
            print(f"  {gid}: {c}")


def sync_aliases(players_doc, summaries, on_site=frozenset()):
    """Make each player's aliases every TwoSheep name their accounts have used in any fetched game.
    Order: most games on the site first (on_site is the set of replay ids in games.json), then most
    games overall, so aliases[0] is the name people saw most. Hand-added aliases that never show up
    in a summary stay at the end. Returns [(player id, names added)] for the players that changed."""
    seen = {}
    for rec in summaries:
        here = rec["replay_id"] in on_site
        for uid, p in ((rec["fields"].get("p") or {}).items()):
            if p.get("n"):
                counts = seen.setdefault(account_key(uid), {})
                site, total = counts.get(p["n"], (0, 0))
                counts[p["n"]] = (site + here, total + 1)
    changed = []
    for player in players_doc["players"]:
        counts = {}
        for acct in player.get("twosheep_accounts", []):
            for name, (site, total) in seen.get(acct, {}).items():
                s, t = counts.get(name, (0, 0))
                counts[name] = (s + site, t + total)
        if not counts:
            continue
        old = player.get("aliases", [])
        new = sorted(counts, key=lambda name: (-counts[name][0], -counts[name][1], name.lower())) \
            + [a for a in old if a not in counts]
        if new != old:
            player["aliases"] = new
            changed.append((player["id"], [a for a in new if a not in old]))
    return changed


def players_text(players_doc) -> str:
    """players.json in its hand-written style: one key per line, short lists inline."""
    out = ["{"] + [f"  {json.dumps(k)}: {json.dumps(v)}," for k, v in players_doc.items() if k != "players"]
    out.append('  "players": [')
    for i, p in enumerate(players_doc["players"]):
        body = ",\n".join(f"      {json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}" for k, v in p.items())
        out.append("    {\n" + body + "\n    }" + ("," if i < len(players_doc["players"]) - 1 else ""))
    return "\n".join(out + ["  ]", "}"]) + "\n"


def list_accounts(players_doc, summaries):
    owner = {acct: p["id"] for p in players_doc["players"] for acct in p.get("twosheep_accounts", [])}
    seen = {}
    for rec in summaries:
        f = rec["fields"]
        counted = bool(f.get("d")) and len(f.get("p") or {}) >= MIN_PLAYERS
        for uid, p in (f.get("p") or {}).items():
            a = seen.setdefault(account_key(uid), {"games": 0, "names": {}})
            a["games"] += counted
            a["names"][p.get("n")] = a["names"].get(p.get("n"), 0) + 1
    print("account           player             games  names used")
    for acct, a in sorted(seen.items(), key=lambda kv: (kv[0] not in owner, -kv[1]["games"])):
        names = ", ".join(n for n, _ in sorted(a["names"].items(), key=lambda kv: -kv[1]))
        print(f"{acct}  {owner.get(acct, 'guest'):17s}  {a['games']:5d}  {names}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help="write the result to games.json (default: dry run)")
    ap.add_argument("--accounts", action="store_true", help="list every account seen and whose it is")
    ap.add_argument("--data", type=Path, default=build.DATA, help="folder holding players.json and games.json")
    ap.add_argument("--raw", type=Path, default=RAW, help="folder of fetched summaries")
    ap.add_argument("--replay-stats", type=Path, default=REPLAY_STATS, help="folder of decoded replays")
    ap.add_argument("--tz", help="time zone for game dates, e.g. America/Los_Angeles (default: this computer's)")
    args = ap.parse_args(argv)

    tz = None
    if args.tz:
        from zoneinfo import ZoneInfo
        tz = ZoneInfo(args.tz)
    else:
        tz = datetime.now().astimezone().tzinfo
    players_doc = build.load_json(args.data / "players.json")
    games_path = args.data / "games.json"
    games_doc = build.load_json(games_path)
    summaries = load_summaries(args.raw)
    if not summaries:
        print(f"error: no summaries in {args.raw}. Run scripts/fetch_twosheep.py first.", file=sys.stderr)
        return 1
    if args.accounts:
        list_accounts(players_doc, summaries)
        return 0

    report = plan(players_doc, games_doc, summaries, tz)
    replay_stats = load_replay_stats(args.replay_stats)
    replays_doc, events_doc = apply_replays(players_doc, games_doc, replay_stats, report) if replay_stats else (None, None)
    print_report(report, {p["id"]: build.display_name(p) for p in players_doc["players"]})
    alias_changes = sync_aliases(players_doc, summaries, {g.get("twosheep_id") for g in games_doc["games"]})
    if alias_changes:
        print("\nnew TwoSheep names for players.json aliases:")
        for pid, added in alias_changes:
            print(f"  {pid}: {', '.join(added) if added else '(reordered by use)'}")
    errors, _ = build.validate(players_doc, games_doc, replays_doc)
    if errors:
        print("\nThe result would not pass validation, so nothing was written:", file=sys.stderr)
        for e in errors:
            print(f"  {e}", file=sys.stderr)
        return 1
    if not args.write:
        print("\nDry run. Run again with --write to save.")
        return 0
    games_path.write_text(json.dumps(games_doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    written = [games_path]
    if replays_doc is not None:
        replays_path = args.data / "replays.json"
        replays_path.write_text(build.replays_text(replays_doc), encoding="utf-8")
        written.append(replays_path)
    if events_doc is not None:
        events_path = args.data / "replay_events.json"
        events_path.write_text(build.events_text(events_doc), encoding="utf-8")
        written.append(events_path)
    if alias_changes:
        players_path = args.data / "players.json"
        players_path.write_text(players_text(players_doc), encoding="utf-8")
        written.append(players_path)
    print("\nwrote " + ", ".join(str(p.relative_to(ROOT) if p.is_relative_to(ROOT) else p) for p in written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
