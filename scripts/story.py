"""The story of one game, as plain facts: how the lead moved, the turning points, and a few notes per player.

Everything here is deterministic and comes from numbers the other modules already produce (board VP after
every action, the play of the game, closeness, the threat index, per-player replay counts). The game page
draws its summary from it, and scripts/recaps.py hands the same facts to a language model to write the
short recap, so the model never sees anything the page does not also show.

    stories = story.compute(games, events, stats)      # {game id: story}
    facts = story.facts(story_of_game, name_of)        # what the recap is written from

Turns are numbered the way the race chart numbers them: turn 1 is the first roll, so turn = roll_index + 1.
Player text uses {pid} tokens ("takes Longest Road from {jd}"); the page swaps in the player chip and
facts() swaps in the display name. Bots are never named.
"""

from __future__ import annotations

KEY = "stories"

MAX_NOTES = 3
# Thresholds for the game label, as shares of the VP target so 10 and 14 point games read the same.
COMEBACK_SHARE, BLOWOUT_SHARE = 0.35, 0.40

def is_bot(pid):
    return str(pid).startswith("bot-")


def tok(pid):
    """A player token for text, or a plain word for a seat that is never named."""
    return "the bot" if is_bot(pid) else "{%s}" % pid


def label(game, timeline_vp):
    """comeback / close / blowout / solid, from the final score and the true VP timeline.

    comeback: the winner trailed the best opponent by at least 35% of the target (3 VP or more) at some
    point after the first quarter of the game; close: won by 1 VP or less; blowout: won by 40% of the target."""
    target = game.get("vp_to_win") or 10
    ps = sorted(game["players"], key=lambda r: r["rank"])
    margin = ps[0]["vp"] - ps[1]["vp"]
    deficit = 0
    mine = (timeline_vp or {}).get(game["winner"])
    if mine:
        others = [v for k, v in timeline_vp.items() if k != game["winner"]]
        for i in range(len(mine) // 4, len(mine)):
            deficit = max(deficit, max(o[i] for o in others) - mine[i])
    if deficit >= max(3, round(COMEBACK_SHARE * target)):
        return "comeback", margin, deficit
    if margin <= 1:
        return "close", margin, deficit
    if margin >= BLOWOUT_SHARE * target:
        return "blowout", margin, deficit
    return "solid", margin, deficit


def lead_story(ev, seats):
    """Who held the sole lead on board VP, action by action, after setup and before the final reveal.

    Returns (events, share, last): events are the moments a new seat took the sole lead (the first one
    is "first lead", not a change); share is each seat's fraction of rolls spent as sole leader at the
    end of the roll; last is the seat leading alone before the reveal, or None for a tie."""
    events, leader = [], None
    by_roll = {}
    for e in ev["vp_events"]:
        if e.get("phase") == "setup" or e.get("action") == "reveal":
            continue
        vp = e["board_vp"]
        top = max(vp)
        sole = vp.index(top) if vp.count(top) == 1 else None
        by_roll[e["roll_index"]] = vp
        if sole is not None and sole != leader:
            rest = max(v for j, v in enumerate(vp) if j != sole)
            events.append({"t": e["roll_index"] + 1, "seat": sole, "vp": top, "next": rest, "first": leader is None})
            leader = sole
    n_rolls = len(ev.get("roll_log") or [])
    counts, vp, last = [0] * len(seats), None, None
    for r in range(n_rolls):
        vp = by_roll.get(r, vp)
        if vp is None:
            continue
        top = max(vp)
        last = vp.index(top) if vp.count(top) == 1 else None
        if last is not None:
            counts[last] += 1
    share = {seats[i]: round(c / n_rolls, 3) if n_rolls else 0.0 for i, c in enumerate(counts)}
    return events, share, (seats[last] if last is not None else None)


def title_events(ev, seats):
    out = []
    for e in ev["vp_events"]:
        for ch in e["changes"]:
            who = seats[ch["seat"] - 1]
            if ch["type"] in ("longest_road_taken", "largest_army_taken"):
                name = "Longest Road" if ch["type"].startswith("longest") else "Largest Army"
                prev = seats[ch["from"] - 1] if ch.get("from") else None
                out.append({"t": e["roll_index"] + 1, "kind": "title", "who": who,
                            "text": f"takes {name}" + (f" from {tok(prev)}" if prev else "")})
            elif ch["type"] == "longest_road_lost":
                out.append({"t": e["roll_index"] + 1, "kind": "title", "who": who, "text": "loses Longest Road after a ship move"})
    return out


def describe_changes(changes):
    """A short phrase for what one action or turn scored."""
    words = []
    for ch in changes:
        t = ch["type"] if isinstance(ch, dict) else ch
        w = {"settlement": "a settlement", "city": "a city", "island_bonus": "an island bonus",
             "longest_road_taken": "Longest Road", "largest_army_taken": "Largest Army"}.get(t)
        if w and w not in words:
            words.append(w)
    if not words:
        return ""
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def winning_move(ev, seats, winner, go):
    """How the game ended: the winner's last scoring action, or the reveal of VP cards."""
    w = seats.index(winner) + 1
    reveal = next((ch.get("vp_cards", 0) for e in ev["vp_events"] if e.get("action") == "reveal"
                   for ch in e["changes"] if ch["seat"] == w), 0)
    last = next((e for e in reversed(ev["vp_events"]) if e.get("action") != "reveal" and e.get("actor") == w
                 and e.get("phase") != "setup"), None)
    t = len(ev.get("roll_log") or [])
    what = describe_changes(last["changes"]) if last else ""
    kind = (go or {}).get("kind")
    if kind == "reveal" and reveal:
        text = f"reveals {reveal} VP {'card' if reveal == 1 else 'cards'} to win"
    elif kind == "walk_off":
        text = f"wins it on the final turn{' with ' + what if what else ''}"
    else:
        text = f"finishes it{' with ' + what if what else ''}" + (f", plus {reveal} hidden VP {'card' if reveal == 1 else 'cards'}" if reveal else "")
    return {"t": t, "kind": "win", "who": winner, "text": text}, reveal


def player_notes(game, rows, lead_share, margin):
    """Up to three short notes per named player: the things that stand out at this table."""
    named = [r for r in game["players"] if not is_bot(r["player"])]
    notes = {r["player"]: [] for r in named}
    have = {p: rows[p] for p in notes if p in rows}

    def extreme(key, f=lambda x: x):
        vals = {p: f(x) for p, x in have.items() if key(x) is not None}
        if len(vals) < 2:
            return None, None
        hi, lo = max(vals, key=vals.get), min(vals, key=vals.get)
        top = [p for p in vals if vals[p] == vals[hi]]
        bot = [p for p in vals if vals[p] == vals[lo]]
        return (hi if len(top) == 1 else None), (lo if len(bot) == 1 else None)

    win = game["winner"]
    if win in notes:
        s = lead_share.get(win, 0)
        notes[win].append("never led before the final turn" if s == 0 else f"led for {round(s * 100)}% of the game")
    for r in named:
        if r["player"] != win and r["rank"] == 2 and margin <= 1:
            notes[r["player"]].append(f"finished {margin} VP short" if margin else "tied on VP")
    hi, lo = extreme(lambda x: x.get("opening_dots"), lambda x: x["opening_dots"])
    if hi:
        notes[hi].append(f"best opening ({have[hi]['opening_dots']} dots)")
    if lo:
        notes[lo].append(f"weakest opening ({have[lo]['opening_dots']} dots)")
    luck = lambda x: x["resources_from_dice"] - x["expected_from_dice"]
    hi, lo = extreme(lambda x: x.get("expected_from_dice"), luck)
    if hi and luck(have[hi]) >= 5:
        notes[hi].append(f"hottest dice (+{round(luck(have[hi]))} cards)")
    if lo and luck(have[lo]) <= -5:
        notes[lo].append(f"coldest dice (−{round(-luck(have[lo]))} cards)")
    hi, _ = extreme(lambda x: x.get("stolen_from"), lambda x: x["stolen_from"])
    if hi and have[hi]["stolen_from"] >= 4:
        notes[hi].append(f"robbed the most ({have[hi]['stolen_from']} cards)")
    hi, _ = extreme(lambda x: x.get("blocked_by_robber"), lambda x: x["blocked_by_robber"])
    if hi and have[hi]["blocked_by_robber"] >= 8:
        notes[hi].append(f"{have[hi]['blocked_by_robber']} cards blocked by the robber")
    for p, x in have.items():
        if (x.get("cards_discarded") or 0) >= 8:
            notes[p].append(f"discarded {x['cards_discarded']} cards to 7s")
    for r in named:
        vb = r.get("vp_breakdown") or {}
        if vb.get("longest_road"):
            notes[r["player"]].append("held Longest Road")
        if vb.get("largest_army"):
            notes[r["player"]].append("held Largest Army")
        if vb.get("vp_cards"):
            n = vb["vp_cards"]
            notes[r["player"]].append(f"{n} VP {'card' if n == 1 else 'cards'}")
    return {p: v[:MAX_NOTES] for p, v in notes.items()}


def one(game, ev, stats):
    """The story of one decoded game."""
    gid, seats, win = game["id"], ev["seats"], game["winner"]
    mom = ((stats.get("momentum") or {}).get("games") or {}).get(gid) or {}
    close = ((stats.get("closeness") or {}).get("games") or {}).get(gid)
    comeback = ((stats.get("classes") or {}).get("games") or {}).get(gid)
    threat = ((stats.get("threat") or {}).get("timelines") or {}).get(gid)
    rows = (stats.get("game_replays") or {}).get(gid) or {}
    tl = ((stats.get("timelines") or {}).get(gid) or {}).get("vp")
    tag, margin, deficit = label(game, tl)
    leads, share, last = lead_story(ev, seats)
    go = mom.get("go_ahead")
    final, reveal = winning_move(ev, seats, win, go)

    points = []
    for e in leads:
        who = seats[e["seat"]]
        points.append({"t": e["t"], "kind": "lead", "who": who,
                       "text": f"takes the {'first ' if e['first'] else ''}lead, {e['vp']} to {e['next']}"})
    points += title_events(ev, seats)
    pick = (mom.get("play") or {}).get("pick")
    play = None
    if pick:
        what = describe_changes([w for a in pick["actions"] for w in a.get("what", [])])
        play = {"t": pick["roll_index"] + 1, "swing": pick["swing"], "from": pick["from"], "to": pick["to"], "what": what}
        points.append({"t": play["t"], "kind": "play", "who": win,
                       "text": f"makes the play of the game: {what or 'a scoring turn'}, a {pick['swing']} VP swing"})
    if comeback and comeback.get("t") is not None and comeback.get("gap", 0) >= 2:
        lead = [p for p in comeback.get("leaders", []) if p != win]
        if lead:
            points.append({"t": comeback["t"] + 1, "kind": "reach", "who": lead[0],
                           "text": f"gets within 3 of winning with {tok(win)} {comeback['gap']} VP behind"})
    points.append(final)
    order = {"lead": 1, "title": 0, "play": 2, "reach": 3, "win": 9}
    points = [p for p in points if not is_bot(p["who"])]
    points.sort(key=lambda p: (p["t"], order[p["kind"]]))
    # A title that also brought the lead on the same turn reads as one event.
    merged = []
    for p in points:
        prev = merged[-1] if merged else None
        if prev and p["kind"] == "lead" and prev["kind"] == "title" and prev["t"] == p["t"] and prev["who"] == p["who"]:
            prev["kind"] = "lead"
            prev["text"] += " and " + p["text"].replace("takes ", "", 1)
        else:
            merged.append(dict(p))
    points = merged

    top_before = None
    if threat and threat.get("top"):
        top_before = threat["seats"][threat["top"][-1]]
    named_leads = [e for e in leads if not e["first"]]
    longest = max(share, key=share.get) if share and max(share.values()) > 0 else None
    return {
        "tag": tag, "margin": margin, "deficit": deficit,
        "turns": len(ev.get("roll_log") or []), "seats": len(seats),
        "lead": {"changes": close["lead_changes"] if close else len(named_leads), "share": share,
                 "longest": longest, "before_end": last},
        "ending": (go or {}).get("kind"), "revealed": reveal,
        "play": play,
        "top_threat": top_before, "hidden_threat": bool(top_before and top_before != win),
        "closeness": {"index": close["index"], "rank": close["rank"], "of": stats["closeness"]["n"],
                      "closest_tier": close["closest_tier"], "one_sided_tier": close["one_sided_tier"]} if close else None,
        "points": points,
        "notes": player_notes(game, rows, share, margin),
    }


def compute(games, events, stats):
    out = {}
    for g in games:
        ev = (events or {}).get(g["id"])
        if not ev or not ev.get("vp_events") or g["winner"] not in ev["seats"]:
            continue
        out[g["id"]] = one(g, ev, stats)
    return out


def facts(game, story, stats, name_of):
    """What a recap is written from: the story with names filled in, plus each player's line of numbers.

    Kept compact and free of presentation, because scripts/recaps.py hashes it to decide whether a stored
    recap still matches the game."""
    rows = (stats.get("game_replays") or {}).get(game["id"]) or {}
    nm = lambda pid: name_of(pid)

    def fill(text):
        for pid in story["lead"]["share"]:
            text = text.replace("{%s}" % pid, nm(pid))
        return text

    players = []
    for r in sorted(game["players"], key=lambda r: r["rank"]):
        pid = r["player"]
        if is_bot(pid):
            continue
        x = rows.get(pid) or {}
        vb = r.get("vp_breakdown") or {}
        p = {"name": nm(pid), "place": r["rank"], "vp": r["vp"], "turn_order": r.get("seat"),
             "share_of_game_in_sole_lead_pct": round(story["lead"]["share"].get(pid, 0) * 100),
             "notes": story["notes"].get(pid, [])}
        if x:
            p.update({"opening_dots": x["opening_dots"], "cards_from_dice": x["resources_from_dice"],
                      "cards_expected_from_dice": round(x["expected_from_dice"]),
                      "cards_stolen_from_them": x["stolen_from"], "cards_they_stole": x["steals"],
                      "cards_discarded_to_sevens": x["cards_discarded"], "player_trades": x["trades"],
                      "cities_built": x["built"]["city"], "settlements_built": x["built"]["settlement"],
                      "knights_played": x["dev_cards_played"].get("knight", 0)})
        for k, lab in (("longest_road", "held_longest_road"), ("largest_army", "held_largest_army")):
            if vb.get(k):
                p[lab] = True
        if vb.get("vp_cards"):
            p["vp_cards"] = vb["vp_cards"]
        if vb.get("islands"):
            p["vp_from_islands"] = vb["islands"]
        players.append(p)
    c = story["closeness"]
    out = {
        "game_number": game["number"], "date": game["date"], "type": game["type_label"],
        "vp_target": game.get("vp_to_win") or 10, "seats": story["seats"], "turns": story["turns"],
        "has_bot_seat": any(is_bot(r["player"]) for r in game["players"]),
        "winner": nm(game["winner"]), "label": story["tag"], "winning_margin_vp": story["margin"],
        "winner_biggest_deficit_vp": story["deficit"],
        "lead_changes": story["lead"]["changes"],
        "longest_in_sole_lead": nm(story["lead"]["longest"]) if story["lead"]["longest"] else None,
        "sole_leader_before_the_last_move": nm(story["lead"]["before_end"]) if story["lead"]["before_end"] else None,
        "ending": {"walk_off": "the winner was level or behind and won it on their final turn",
                   "led": "the winner already led before their final turn",
                   "reveal": "hidden VP cards decided it"}.get(story["ending"]),
        "play_of_the_game": ({"turn": story["play"]["t"], "what": story["play"]["what"],
                              "vp_swing_against_best_opponent": story["play"]["swing"]} if story["play"] else None),
        "most_dangerous_looking_player_before_the_last_turn": nm(story["top_threat"]) if story["top_threat"] and not is_bot(story["top_threat"]) else None,
        "winner_was_a_hidden_threat": story["hidden_threat"],
        "closeness": ({"index_out_of_100": round(c["index"]), "rank": c["rank"], "of_games": c["of"],
                       "in_closest_tier": c["closest_tier"], "in_most_one_sided_tier": c["one_sided_tier"]} if c else None),
        "turning_points": [{"turn": p["t"], "event": f"{nm(p['who'])} {fill(p['text'])}"} for p in story["points"]],
        "players": players,
    }
    return out
