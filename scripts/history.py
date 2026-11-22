"""Build data/history.js (window.HISTORY, v 2) for the History tab, site/history.html.

scripts/build.py runs this on every build, after it writes dist/data/stats.json, and serves the result as
dist/data/history.js. If it fails, the build keeps the last good copy (data/history.js) and says why.
It reads data/*.json, the stats just built, and data/history_eras.json (era names, by first game id).

By hand: python scripts/history.py [-v]   (after python scripts/build.py; -v prints every beat's text)

What the output holds
- The backbone: each game's place on the folded time axis (u), its winner and score, the cumulative wins race,
  both crowns (most wins; leaderboard #1 with a 10-game minimum), each player's wins above expected with its
  95% luck band, eras, breaks and month ticks, plus the pacing constants the page scrolls by.
- The beats. Each beat's copy is composed here from values computed on the data: as of its anchor game for
  claims about then, and as of the latest game (meta.as_of) for sentences that open "As of game N" or
  "Looking back from game N". Every number in a headline or body is recorded in the beat's vals and src.
  A composer asserts the premises its copy rests on and stops the build with a message if one fails. A
  looking-back clause that stops being true when games are added is reworded or dropped with a warning.

Rules the output keeps
- Players are pids. Text uses {pid} tokens, which the page renders as initials. A guest is "guest".
  No usernames or aliases are written.
- Computer seats never appear and are never counted as players. They count as seats only where the site's
  own definitions say so: expected wins (1 / seats) and "three-seat" games (n_seats == 3).
- No stored recap is written.
- No em or en dashes anywhere, in the output or in this file.
"""
import bisect
import datetime
import json
import math
import pathlib
import re
import sys
from collections import Counter, defaultdict
from decimal import Decimal, ROUND_HALF_UP

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
import argparse  # noqa: E402

import build  # noqa: E402
import classes  # noqa: E402
import insights  # noqa: E402

BREAK_DAYS = 7          # a gap between nights longer than this folds
NIGHT_GAP_U = 0.35      # axis units added between nights at most BREAK_DAYS apart
CROWN_MIN = 10          # games a player needs before they can hold the leaderboard crown
# Pacing. Every beat holds for the stage height plus a fade at each end, so the card is fully legible (and its
# chart fully drawn) for a whole stage height, at least one page step: Space or Page Down can never jump over a
# beat. The chart draws over draw_px of the hold, finishing as the card's fade-in does. Quiet games and the eases
# are kept short so the whole track stays under 50 stage heights.
PACE = {"px_game": 36, "px_night": 20, "px_break": "100 + 36 * log2(days / 7)", "ease_px": 80,
        "fade_px": 56, "draw_px": [14, 56], "hold": "stage height + 2 * fade_px", "window_u": 40,
        "cursor_at": 0.64, "outro_vh": 0.3, "merge_u": 2}
MINUS = "−"        # the minus sign used in chart labels (not a dash)


def fold_u(days):
    return 1 + 0.5 * math.log2(days / BREAK_DAYS)


def fold_px(days):
    return 100 + 36 * math.log2(days / BREAK_DAYS)


_ap = argparse.ArgumentParser(description="Build the History tab's data (see the docstring).")
_ap.add_argument("--data", type=pathlib.Path, default=REPO / "data", help="the data folder (default data/)")
_ap.add_argument("--stats", type=pathlib.Path, default=REPO / "dist/data/stats.json", help="the stats the build wrote")
_ap.add_argument("--out", type=pathlib.Path, default=REPO / "dist/data/history.js", help="where to write")
_ap.add_argument("-v", action="store_true", help="print every beat's kicker, headline and body")
ARGS = _ap.parse_args()
DATA = ARGS.data


class Premise(Exception):
    """A fact a beat's words rest on is no longer true."""


def _plain_failure(kind, e, tb):
    if kind is Premise:
        print(f"history: {e}", file=sys.stderr)
        sys.exit(1)
    sys.__excepthook__(kind, e, tb)


sys.excepthook = _plain_failure


def load(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------------------------------------
games = sorted(load(DATA / "games.json")["games"], key=lambda g: (g["date"], g["id"]))
players_doc = load(DATA / "players.json")
site = load(DATA / "site.json")
recaps = load(DATA / "recaps.json")["games"]
RP = load(DATA / "replays.json")["games"]
EV = load(DATA / "replay_events.json")["games"]
S = load(ARGS.stats)
eras_doc = load(DATA / "history_eras.json")

N = len(games)
num = {g["id"]: i for i, g in enumerate(games, 1)}
vg = {g["id"]: g for g in S["views"]["all"]["games"]}
if set(vg) != set(num):
    sys.exit("stats.json does not match data/games.json: rebuild the site first (python scripts/build.py)")
ST, MOM, TH = S["stories"], S["momentum"]["games"], S["threat"]["timelines"]
name_mode = site.get("player_names", "usernames")
registered = {p["id"]: p for p in players_doc["players"]}
is_bot, is_guest = build.is_bot, build.is_guest
WARN = []


def G(n):
    return games[n - 1]


def gid_of(n):
    return games[n - 1]["id"]


def need(cond, who, msg):
    if not cond:
        raise Premise(f"{who}: premise failed: {msg}")


def warn(who, msg):
    WARN.append(f"{who}: {msg}")


# ---------------------------------------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------------------------------------
def T(pid):
    return "{%s}" % pid


def Ts(pid):
    return T(pid) + "'s"


def ordinal(n):
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def fmt_dec(x, d):
    """Round half up to d decimals (3.45 -> 3.5), on the value rounded to 9 places first to undo float noise."""
    q = Decimal(1).scaleb(-d) if d else Decimal(1)
    return str(Decimal(repr(round(x, 9))).quantize(q, rounding=ROUND_HALF_UP))


def signed(x):
    s = fmt_dec(abs(x), 2)
    return f"plus {s}" if x >= 0 or s == "0.00" else f"minus {s}"


def chart_signed(x, d=2):
    s = fmt_dec(abs(x), d)
    return ("+" if x >= 0 or float(s) == 0 else MINUS) + s


def and_list(xs):
    xs = list(xs)
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def cap(s):
    return s[:1].upper() + s[1:]


def a_n(x):
    """'a' or 'an' before a number written in digits (an 8th, an 11th, an 18th, an 80th)."""
    s = str(x)
    return "an" if s.startswith("8") or s in ("11", "18") or (len(s) in (5, 6) and s[:2] in ("11", "18")) else "a"


WORDS = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine",
         10: "ten", 11: "eleven", 12: "twelve"}
ORD_WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
MON = [m[:3] for m in MONTHS]
WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def day(s):
    return datetime.date.fromisoformat(s)


def d_short(s):
    d = day(s)
    return f"{d.day} {MON[d.month - 1]} {d.year}"


def d_long(s):
    d = day(s)
    return f"{WD[d.weekday()]} {d.day} {MON[d.month - 1]} {d.year}"


def d_range(a, b):
    """'7 to 13 Jan 2026', '13 Oct to 6 Nov 2026' or '15 Nov 2025 to 7 Jan 2026'."""
    x, y = day(a), day(b)
    if x == y:
        return d_short(a)
    if (x.year, x.month) == (y.year, y.month):
        return f"{x.day} to {y.day} {MON[y.month - 1]} {y.year}"
    if x.year == y.year:
        return f"{x.day} {MON[x.month - 1]} to {y.day} {MON[y.month - 1]} {y.year}"
    return f"{d_short(a)} to {d_short(b)}"


def about_one_in(p):
    """1 / p, rounded for prose: to the unit below 20, to 5 below 100, to 10 above."""
    k = 1 / p
    return round(k) if k < 20 else 5 * round(k / 5) if k < 100 else 10 * round(k / 10)


# ---------------------------------------------------------------------------------------------------------
# Games, people, maps
# ---------------------------------------------------------------------------------------------------------
def ppl(n):
    """People at game n in seat order (guests included, computer seats left out)."""
    return [r["player"] for r in G(n)["players"] if not is_bot(r["player"])]


def seats_n(n):
    """Seats at game n, computer seats included: the site's denominator for expected wins."""
    return len(G(n)["players"])


def W(n):
    return G(n)["winner"]


def ident(pid):
    return "guest" if is_guest(pid) else pid


def vp_of(n, pid):
    return next(r["vp"] for r in G(n)["players"] if r["player"] == pid)


def score_of(n):
    w = W(n)
    return vp_of(n, w), max(r["vp"] for r in G(n)["players"] if r["player"] != w and not is_bot(r["player"]))


def runner_up(n):
    """The people on the best losing VP in game n."""
    o = score_of(n)[1]
    return [r["player"] for r in G(n)["players"] if r["player"] != W(n) and not is_bot(r["player"]) and r["vp"] == o]


def map_key(g):
    s = g.get("settings") or {}
    return s.get("scenario") or build.expansion_of(g)


def map_label(g):
    s = g.get("settings") or {}
    exp, scen = build.expansion_of(g), s.get("scenario")
    return build.SCENARIOS.get(exp, {}).get(scen, scen) if scen else build.EXPANSIONS.get(exp, exp)


def story(n):
    return ST[gid_of(n)]


def ending(n):
    return story(n)["ending"]


def endings(lo, hi):
    return Counter(ending(k) for k in range(lo, hi + 1))


def rank_of(n, pid):
    """Finishing place in game n as the site shows it (ties share the place)."""
    return next(r["rank"] for r in vg[gid_of(n)]["players"] if r["player"] == pid)


def own(p, lo=1, hi=None):
    hi = N if hi is None else hi
    return [k for k in range(lo, hi + 1) if p in ppl(k)]


def exp_wins(p, lo=1, hi=None):
    return sum(1 / seats_n(k) for k in own(p, lo, hi))


def wins_in(p, lo=1, hi=None):
    hi = N if hi is None else hi
    return sum(1 for k in range(lo, hi + 1) if W(k) == p)


def luck(n, p):
    r = RP[gid_of(n)]["players"][p]
    return r["resources_from_dice"] - r["expected_from_dice"]


def luck_rel(n, p):
    r = RP[gid_of(n)]["players"][p]
    return (r["resources_from_dice"] - r["expected_from_dice"]) / r["expected_from_dice"]


def luck_rank(n, p):
    """1 = the luckiest person at the table (dice paid most above expectation)."""
    me = luck(n, p)
    return 1 + sum(1 for q in ppl(n) if q != p and luck(n, q) > me + 1e-9)


def three_seat(lo, hi):
    return [k for k in range(lo, hi + 1) if seats_n(k) == 3]


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs)


def years_of():
    return sorted({g["date"][:4] for g in games})


def year_games(y):
    return [k for k in range(1, N + 1) if G(k)["date"].startswith(y)]


# ---------------------------------------------------------------------------------------------------------
# Players and colours (the site's own rule)
# ---------------------------------------------------------------------------------------------------------
colors = build.player_colors(players_doc, games)
site_colors = {p["id"]: p["color"] for p in S["views"]["all"]["players"]}
assert all(colors.get(k) == v for k, v in site_colors.items()), "player colours differ from stats.json"

# ---------------------------------------------------------------------------------------------------------
# Nights, breaks and the folded axis. Each game is 1 u wide; u is its centre.
# ---------------------------------------------------------------------------------------------------------
nights, night_of, gap_before = [], {}, {1: None}
for i, g in enumerate(games):
    if not nights or nights[-1]["d"] != g["date"]:
        gap = (day(g["date"]) - day(nights[-1]["d"])).days if nights else None
        nights.append({"d": g["date"], "g0": i + 1, "k": 0, "gap": gap})
    nights[-1]["k"] += 1
    night_of[g["id"]] = len(nights) - 1
left = [0.0]
for n in range(2, N + 1):
    gap = (day(G(n)["date"]) - day(G(n - 1)["date"])).days
    gap_before[n] = gap
    left.append(left[-1] + 1 + (0 if gap == 0 else NIGHT_GAP_U if gap <= BREAK_DAYS else fold_u(gap)))
U = {n: left[n - 1] + 0.5 for n in range(1, N + 1)}
TOTAL_U = left[-1] + 1
breaks = []
for n in range(2, N + 1):
    if gap_before[n] > BREAK_DAYS:
        breaks.append({"after": n - 1, "before": n, "days": gap_before[n], "from": G(n - 1)["date"],
                       "to": G(n)["date"], "u0": round(U[n - 1] + 0.5, 3), "u1": round(U[n] - 0.5, 3)})
short_gaps = sum(1 for n in range(2, N + 1) if 0 < gap_before[n] <= BREAK_DAYS)

# ---------------------------------------------------------------------------------------------------------
# Wins, crowns, the leaderboard as of every game
# ---------------------------------------------------------------------------------------------------------
wins, played = Counter(), Counter()
wins_after, played_after, mw = {}, {}, {}
for n, g in enumerate(games, 1):
    if g["winner"] in registered:
        wins[g["winner"]] += 1
    for r in g["players"]:
        if r["player"] in registered:
            played[r["player"]] += 1
    wins_after[n], played_after[n] = dict(wins), dict(played)
    top = max(wins.values())
    mw[n] = sorted(p for p, v in wins.items() if v == top)
wins_after[0], played_after[0] = {}, {}


def wa(k, p):
    return wins_after[k].get(p, 0)


# The site's own ranking (build.compute) on the first k games: wins above expected, then average share of the
# table's VP, then wins, then name. lb: #1 among players with CROWN_MIN or more games.
lb, elig_at = {}, {}
comp_last = None
for k in range(1, N + 1):
    out = build.compute(players_doc, games[:k], num, name_mode)
    ps = sorted((p for p in out["players"] if p["games"]), key=lambda p: p["leaderboard_rank"])
    elig_at[k] = [(p["id"], p["above_expected"], p["games"]) for p in ps if p["games"] >= CROWN_MIN]
    seated = {r["player"] for r in G(k)["players"]}
    e0 = elig_at[k][0] if elig_at[k] else None
    lb[k] = (e0[0], e0[0] in seated, e0[1]) if e0 else (None, None, None)
    comp_last = out
final = {p["id"]: p["leaderboard_rank"] for p in S["views"]["all"]["players"] if p["games"]}
assert {p["id"]: p["leaderboard_rank"] for p in comp_last["players"] if p["games"]} == final, \
    "leaderboard replica differs from stats.json"
PFINAL = {p["id"]: p for p in S["views"]["all"]["players"]}


def lb_spells():
    out = []
    for k in range(1, N + 1):
        p = lb[k][0]
        if out and out[-1][0] == p:
            out[-1][2] = k
        else:
            out.append([p, k, k])
    return out


# Standing history (wins above expected and the 95% luck band after each of the player's own games)
band = defaultdict(dict)
for p in S["views"]["all"]["players"]:
    for h in p["standing_history"]:
        band[p["id"]][h["number"]] = (h["above_expected"], tuple(h["luck_band"]))


def sh(p, n):
    """(WAE, band lo, band hi) after game n: the player's last own game at or before n, or None."""
    ks = [k for k in band[p] if k <= n]
    if not ks:
        return None
    ae, (lo, hi) = band[p][max(ks)]
    return ae, lo, hi


def rise_through(p, hi):
    """Largest rise in WAE over the player's own games through hi: (rise, low game, high game)."""
    pts = sorted((k, v[0]) for k, v in band[p].items() if k <= hi)
    best = (0.0, None, None)
    lo_v, lo_n = None, None
    for k, v in pts:
        if lo_v is None or v < lo_v:
            lo_v, lo_n = v, k
        if v - lo_v > best[0] + 1e-9:
            best = (v - lo_v, lo_n, k)
    return best


# ---------------------------------------------------------------------------------------------------------
# Streaks, droughts, attendance, distinct winners
# ---------------------------------------------------------------------------------------------------------
def streak_at(n, p):
    v = 0
    for k in reversed(own(p, 1, n)):
        if W(k) != p:
            break
        v += 1
    return v


def drought_at(n, p):
    v = 0
    for k in reversed(own(p, 1, n)):
        if W(k) == p:
            break
        v += 1
    return v


def longest_streak(p, hi):
    best = cur = 0
    for k in own(p, 1, hi):
        cur = cur + 1 if W(k) == p else 0
        best = max(best, cur)
    return best


def longest_drought(p, hi):
    best = cur = 0
    for k in own(p, 1, hi):
        cur = 0 if W(k) == p else cur + 1
        best = max(best, cur)
    return best


def attendance_runs(p, hi):
    """[(length, first game, last game)] of runs of consecutive group games played, through hi."""
    runs, cur = [], None
    for k in range(1, hi + 1):
        if p in ppl(k):
            cur = [cur[0] + 1, cur[1], k] if cur else [1, k, k]
        elif cur:
            runs.append(tuple(cur)); cur = None
    if cur:
        runs.append(tuple(cur))
    return runs


def distinct_run(end):
    """Length of the longest run of games ending at `end` with no repeat winner (guests count as one)."""
    seen, L = set(), 0
    for j in range(end, 0, -1):
        w = ident(W(j))
        if w in seen:
            break
        seen.add(w); L += 1
    return L


# ---------------------------------------------------------------------------------------------------------
# Closeness as of then: the site's index recomputed over the first k games only
# ---------------------------------------------------------------------------------------------------------
TLS = {g["id"]: insights.board_timeline(EV[g["id"]]) for g in games if g["id"] in EV}
_close = {}
full = insights.closeness_on(games, TLS, lambda g: len(g["players"]), TH)
assert all(full["games"][k]["index"] == S["closeness"]["games"][k]["index"] for k in full["games"]), \
    "closeness replica differs"


def close_on(k):
    """[(index, game number)] over the first k games, closest first."""
    if k not in _close:
        out = insights.closeness_on(games[:k], TLS, lambda g: len(g["players"]), TH)
        _close[k] = sorted(((v["index"], num[i]) for i, v in out["games"].items()), key=lambda t: (-t[0], t[1]))
    return _close[k]


# ---------------------------------------------------------------------------------------------------------
# The robber, trades and the board at the moment of an action (people only)
# ---------------------------------------------------------------------------------------------------------
_vpidx = {}


def board_at(gid, ai):
    """Board VP per seat just after the last VP event at or before action ai."""
    if gid not in _vpidx:
        vs = EV[gid]["vp_events"]
        _vpidx[gid] = ([v["action_index"] for v in vs], [v["board_vp"] for v in vs])
    a, b = _vpidx[gid]
    i = bisect.bisect_right(a, ai) - 1
    return b[i] if i >= 0 else [0] * len(EV[gid]["seats"])


def robber_rate(lo, hi):
    """Robber moves onto land by people. Leader = the mover's opponents (people) with the most board VP at the
    moment of the move; when several are level each counts. A move touches a leader if the chosen hex borders a
    building of any of them. rnd = mean share of the candidate hexes that would have."""
    hit = tot = tied = 0
    rnd = 0.0
    for k in range(lo, hi + 1):
        gid = gid_of(k)
        seats = EV[gid]["seats"]
        for e in EV[gid]["robber_events"]:
            if e.get("pirate"):
                continue
            mv = e["mover"] - 1
            if is_bot(seats[mv]):
                continue
            bv = board_at(gid, e["action_index"])
            opp = [j for j in range(len(seats)) if j != mv and not is_bot(seats[j])]
            topv = max(bv[j] for j in opp)
            L = [j for j in opp if bv[j] == topv]
            ch = next((c for c in e["candidates"] if c["hex"] == e["hex"]), None)
            if ch is None:
                continue
            tot += 1
            tied += len(L) > 1
            hit += any(ch["m"][j] > 0 for j in L)
            rnd += sum(1 for c in e["candidates"] if any(c["m"][j] > 0 for j in L)) / len(e["candidates"])
    return {"hit": hit, "tot": tot, "rate": 100 * hit / tot, "rnd": 100 * rnd / tot, "tied": tied}


def trade_parts(k):
    """Per game: (trades involving the sole leader, trades while one person led alone, expected involving)."""
    gid = gid_of(k)
    seats = EV[gid]["seats"]
    hum = [i for i, s in enumerate(seats) if not is_bot(s)]
    inv = tot = 0
    ex = 0.0
    for e in EV[gid]["trade_events"]:
        if e["partner"] is None:
            continue
        a, b = e["seat"] - 1, e["partner"] - 1
        if is_bot(seats[a]) or is_bot(seats[b]):
            continue
        bv = board_at(gid, e["action_index"])
        vals = [bv[i] for i in hum]
        topv = max(vals)
        if vals.count(topv) > 1:
            continue
        L = hum[vals.index(topv)]
        tot += 1
        inv += a == L or b == L
        ex += 2 / len(hum)
    return inv, tot, ex


def trade_rate(lo, hi):
    inv = tot = 0
    ex = 0.0
    for k in range(lo, hi + 1):
        a, b, c = trade_parts(k)
        inv += a; tot += b; ex += c
    return {"inv": inv, "tot": tot, "rate": 100 * inv / tot, "exp": 100 * ex / tot}


def luckiest_won(lo, hi):
    """Games the luckiest person at the table won (ties: any of them), and the chance sum(tied / seats)."""
    w = 0
    ch = 0.0
    for k in range(lo, hi + 1):
        L = {p: luck(k, p) for p in ppl(k)}
        topv = max(L.values())
        tied = [p for p, v in L.items() if abs(v - topv) < 1e-9]
        w += W(k) in tied
        ch += len(tied) / seats_n(k)
    return w, hi - lo + 1, ch


def best_opening_won(lo, hi):
    """Among games where one person alone had the most opening pips: (won, games, chance sum(1 / seats))."""
    w = c = 0
    ch = 0.0
    for k in range(lo, hi + 1):
        D = {p: RP[gid_of(k)]["players"][p]["opening_dots"] for p in ppl(k)}
        topv = max(D.values())
        best = [p for p, v in D.items() if v == topv]
        if len(best) == 1:
            c += 1
            w += W(k) == best[0]
            ch += 1 / seats_n(k)
    return w, c, ch


def title_steals(lo, hi):
    """Longest Road and Largest Army taken from a holder (people only), and per-game road steals."""
    road = army = 0
    per = Counter()
    for k in range(lo, hi + 1):
        gid = gid_of(k)
        seats = EV[gid]["seats"]
        for v in EV[gid]["vp_events"]:
            for c in v["changes"]:
                if c["type"] in ("longest_road_taken", "largest_army_taken") and c.get("from") is not None:
                    if is_bot(seats[c["seat"] - 1]) or is_bot(seats[c["from"] - 1]):
                        continue
                    if c["type"] == "longest_road_taken":
                        road += 1; per[k] += 1
                    else:
                        army += 1
    return road, army, per


def winner_titles(lo, hi):
    road = army = 0
    for k in range(lo, hi + 1):
        r = next(x for x in G(k)["players"] if x["player"] == W(k))
        road += r["vp_breakdown"]["longest_road"] > 0
        army += r["vp_breakdown"]["largest_army"] > 0
    return road, army


def p_drought(qs, L):
    """Exact chance of a run of L or more losses somewhere in a sequence of games won with chance q each."""
    s = [0.0] * L
    s[0] = 1.0
    hit = 0.0
    for q in qs:
        t = [0.0] * L
        t[0] = sum(s) * q
        for j in range(L):
            if j + 1 < L:
                t[j + 1] += s[j] * (1 - q)
            else:
                hit += s[j] * (1 - q)
        s = t
    return hit


# ---------------------------------------------------------------------------------------------------------
# Eras: hand-named in history-eras.json, snapped to nights, everything else computed
# ---------------------------------------------------------------------------------------------------------
starts = []
for e in eras_doc["eras"]:
    if e["first"] not in num:
        sys.exit(f"history_eras.json: no game with id {e['first']}")
    nt = nights[night_of[e["first"]]]
    starts.append((nt["g0"], e["name"]))
starts.sort()
if starts[0][0] != 1:
    starts.insert(0, (1, "The beginning"))
eras = []
for i, (a, name) in enumerate(starts):
    b = (starts[i + 1][0] - 1) if i + 1 < len(starts) else N
    if b < a:
        sys.exit(f"history_eras.json: era '{name}' has no games after snapping to nights")
    d0, d1 = G(a)["date"], G(b)["date"]
    eras.append({"name": name, "first": gid_of(a), "last": gid_of(b), "from": a, "to": b, "start": d0, "end": d1,
                 "games": b - a + 1, "nights": len({G(k)["date"] for k in range(a, b + 1)}),
                 "days": (day(d1) - day(d0)).days + 1, "u0": round(U[a] - 0.5, 3), "u1": round(U[b] + 0.5, 3),
                 "open": b == N})
era_of = {k: i for i, e in enumerate(eras) for k in range(e["from"], e["to"] + 1)}


# ---------------------------------------------------------------------------------------------------------
# Beats
# ---------------------------------------------------------------------------------------------------------
class Beat:
    def __init__(self, bid, n, kind, size, span=None, closing=False):
        self.id, self.n, self.kind, self.size, self.span, self.closing = bid, n, kind, size, span, closing
        self.focus, self.headline, self.body, self.chart, self.emphasis = [], "", "", None, None
        self.vals, self.src, self.ok = [], [], []

    # every number that reaches a headline or body goes through one of these
    def v(self, s, how):
        s = str(s)
        self.vals.append(s)
        self.src.append({"says": s, "how": how})
        return s

    def i(self, x, how):
        return self.v(f"{x:,}", how)

    def f(self, x, d, how):
        return self.v(fmt_dec(x, d), how)

    def pct(self, a, b, how, d=1):
        return self.v(fmt_dec(100 * a / b, d) + "%", how)

    def pc(self, x, how, d=1):
        return self.v(fmt_dec(x, d) + "%", how)

    def p100(self, x, how, d=1):
        return self.v(fmt_dec(100 * x, d) + "%", how)

    def sg(self, x, how):
        return self.v(signed(x), how)

    def o(self, k, how):
        return self.v(ordinal(k), how)

    def date(self, s, how="date"):
        return self.v(d_short(s), how)

    def drange(self, a, b, how="dates"):
        return self.v(d_range(a, b), how)

    def score(self, n):
        w, o = score_of(n)
        return f"{self.i(w, f'winner VP, game {n}')} to {self.i(o, f'best other VP, game {n}')}"

    def need(self, cond, msg):
        need(cond, f"beat {self.id}", msg)

    def asof_ok(self, phrase, why):
        self.ok.append({"text": phrase, "why": why})

    def set_chart(self, typ, w, h, data, through, label=None):
        self.chart = {"type": typ, "w": w, "h": h, "label": label, "through": through, "data": data}


def asof_lead(b, asof, look=False):
    """'As of game N' or 'Looking back from game N', with N registered."""
    return ("Looking back from game " if look else "As of game ") + b.i(asof, "the latest game (meta.as_of)")


def anchor(gid, who):
    need(gid in num, who, f"anchor game {gid} is not in the data")
    return num[gid]


# --- 1 -----------------------------------------------------------------------------------------------------
def beat_game_1(asof):
    n = 1
    b = Beat("game-1", n, "milestone", "short")
    s, w = story(n), W(n)
    table = ppl(n)
    b.need(all(p in registered for p in table), "game 1's people are all registered players")
    leads = [p for p in s["points"] if p["kind"] == "lead"]
    b.need(s["lead"]["changes"] == 1 and len(leads) == 2, "game 1 has exactly one lead change")
    first, last = leads
    b.need(last["who"] == w and first["who"] != w, "the first leader is passed by the winner")
    b.focus = table
    b.headline = f"Game {b.i(n, 'game number')}"
    b.body = (f"{and_list([T(p) for p in table])} play the first recorded game. "
              f"{T(first['who'])} takes the first lead on turn {b.i(first['t'], 'stories.points, first lead')}. "
              f"{T(w)} passes {T(first['who'])} on turn {b.i(last['t'], 'stories.points, the lead change')}, "
              f"in the game's only lead change, and wins {b.score(n)}.")
    return b


# --- 2 -----------------------------------------------------------------------------------------------------
def beat_new_shores(asof):
    n = next((k for k in range(1, N + 1) if build.expansion_of(G(k)) == "seafarers"), None)
    need(n is not None, "beat new-shores", "a Seafarers game exists")
    b = Beat("new-shores", n, "milestone", "short")
    g, s, w = G(n), story(n), W(n)
    key, lab = map_key(g), map_label(g)
    b.need(s["deficit"] > 0 and s["lead"]["changes"] > 1, "the winner trailed and the lead changed hands")
    b.focus = [w]
    b.headline = f"{lab} arrives"
    hosted = sum(1 for k in range(1, asof + 1) if map_key(G(k)) == key)
    runs = []
    for k in range(1, asof + 1):
        mk = map_key(G(k))
        if runs and runs[-1][0] == mk:
            runs[-1][2] = k
        else:
            runs.append([mk, k, k])
    opening = next(r for r in runs if r[1] == n)
    olen = opening[2] - opening[1] + 1
    longest = max(r[2] - r[1] + 1 for r in runs)
    same = [r for r in runs if r[2] - r[1] + 1 == olen and r is not opening]
    last = (f"{asof_lead(b, asof)}, {lab} has hosted {b.i(hosted, 'games on this map')} of the "
            f"{b.i(asof, 'games played')} games")
    if olen == longest:
        last += (f", and its opening run, games {b.i(opening[1], 'first game of the run')} to "
                 f"{b.i(opening[2], 'last game of the run')}, is still the "
                 f"{'joint ' if same else ''}longest on one map at {b.i(olen, 'run length')}.")
    else:
        last += "."
        warn(b.id, "the opening run is no longer the longest on one map; clause dropped")
    b.body = (f"Game {b.i(n, 'first game with expansion seafarers')} is the first Seafarers game, on {lab}. "
              f"{T(w)} wins it {b.score(n)} after trailing by {b.i(s['deficit'], 'stories.deficit')}, through "
              f"{b.i(s['lead']['changes'], 'stories.lead.changes')} lead changes. " + last)
    return b


# --- 3 -----------------------------------------------------------------------------------------------------
def beat_robber_on_the_leader(asof):
    n = anchor("2025-02-13-a", "beat robber-on-the-leader")
    b = Beat("robber-on-the-leader", n, "analysis", "full")
    a, z = robber_rate(1, n), robber_rate(1, asof)
    b.need(n in WORDS, "the anchor game has a word")
    b.need(a["rate"] > 2 * a["rnd"], "the robber picks the leader far more often than chance")
    b.headline = "The robber goes where the points are"
    drift = z["rate"] - a["rate"]
    held = ("the habit has held" if abs(drift) <= 5 else "the habit has softened" if drift < 0 else
            "the habit has grown")
    if abs(drift) > 5:
        warn(b.id, f"robber rate moved {drift:.1f} points since game {n}")
    b.body = (f"{cap(WORDS[n])} games in, a habit is already plain. Of {b.i(a['tot'], 'robber moves onto land by people, games 1 to anchor')} "
              f"robber moves onto land made by people at the table, {b.i(a['hit'], 'moves touching a leader')} "
              f"({b.pc(a['rate'], 'share touching a leader')}) put the robber on a hex touching a building of "
              f"the leader, where a hex picked at random would have done so {b.pc(a['rnd'], 'random hex rate')} "
              f"of the time. {asof_lead(b, asof)}, {held}: {b.i(z['hit'], 'moves touching a leader, all games')} "
              f"of {b.i(z['tot'], 'robber moves onto land by people, all games')} such moves ({b.pc(z['rate'], 'share, all games')}), "
              f"against {b.pc(z['rnd'], 'random hex rate, all games')}.")
    rows = [{"label": f"Games 1 to {n}", "v": round(a["rate"], 1), "ref": round(a["rnd"], 1),
             "text": fmt_dec(a["rate"], 1) + "%", "ref_text": "random " + fmt_dec(a["rnd"], 1) + "%"},
            {"label": f"As of game {asof}", "v": round(z["rate"], 1), "ref": round(z["rnd"], 1),
             "text": fmt_dec(z["rate"], 1) + "%", "ref_text": "random " + fmt_dec(z["rnd"], 1) + "%"}]
    b.set_chart("paired_bars", 320, 64, {"domain": [0, 100], "unit": "%", "rows": rows}, asof,
                "Robber moves onto land made by people at the table. Leader = the mover's opponent with the most "
                "board VP at that moment; when several are level, each counts.")
    return b


# --- 4 -----------------------------------------------------------------------------------------------------
def beat_at_debut(asof):
    p = "a"
    n = own(p)[0] if own(p) else None
    need(n is not None, "beat at-debut", "AT has played")
    b = Beat("at-debut", n, "player", "short")
    s = story(n)
    b.need(W(n) == p, "AT won a first game")
    od = {q: RP[gid_of(n)]["players"][q]["opening_dots"] for q in ppl(n)}
    others = sorted(v for q, v in od.items() if q != p)
    b.need(od[p] < min(others), "AT had the weakest opening at the table")
    b.need(s["lead"]["changes"] == 0, "the lead never changed hands")
    prior = max(story(k)["margin"] for k in range(1, n))
    b.need(s["margin"] > prior, "the margin is the biggest yet")
    b.focus = [p]
    b.headline = f"{T(p)} wins on debut"
    vs = (f"{b.i(others[0], 'opening pips of the others')} for each of the others" if len(set(others)) == 1 else
          and_list([b.i(x, "opening pips of another") for x in others]))
    b.body = (f"{T(p)} plays a first game and wins it {b.score(n)} in {map_label(G(n))}, from the weakest opening at "
              f"the table, {b.i(od[p], 'opening pips (opening_dots)')} dots against {vs}, and without the lead "
              f"ever changing hands. The {b.i(s['margin'], 'stories.margin')}-point margin is the biggest yet.")
    return b


# --- 5 -----------------------------------------------------------------------------------------------------
def beat_no_trades_with_the_leader(asof):
    n = anchor("2025-03-13-b", "beat no-trades-with-the-leader")
    b = Beat("no-trades-with-the-leader", n, "analysis", "full")
    a, z = trade_rate(1, n), trade_rate(1, asof)
    b.need(a["rate"] < a["exp"] - 10, "the leader trades well below chance through the anchor")
    ys = years_of()
    yr = []
    for y in ys:
        ks = year_games(y)
        r = trade_rate(ks[0], ks[-1])
        yr.append(f"{b.pc(r['rate'], f'trades with the sole leader, {y}')} in {b.v(y, 'year')}")
    b.headline = "The leader gets fewer trades"
    held = "the gap has not closed" if z["rate"] < z["exp"] - 10 else "the gap has narrowed"
    if z["rate"] >= z["exp"] - 10:
        warn(b.id, "the leader's trade share is now within 10 points of chance")
    b.body = (f"Through game {b.i(n, 'anchor game')}, whenever one player led alone on the board, that player took "
              f"part in only {b.i(a['inv'], 'trades involving the sole leader')} of "
              f"{b.i(a['tot'], 'player-to-player trades during a sole lead')} player-to-player trades "
              f"({b.pc(a['rate'], 'share')}). If trading partners were random, the leader would have been in "
              f"{b.pc(a['exp'], 'mean of 2 / people')} of them. {asof_lead(b, asof)}, {held}: "
              f"{b.i(z['inv'], 'trades involving the sole leader, all games')} of "
              f"{b.i(z['tot'], 'trades during a sole lead, all games')} ({b.pc(z['rate'], 'share, all games')}) against "
              f"{b.pc(z['exp'], 'chance, all games')}, with {and_list(yr)}.")
    k0 = next(k for k in range(1, n + 1) if trade_rate(1, k)["tot"] > 0)
    k0 = max(5, k0)
    series, ref = [], []
    for k in range(k0, n + 1):
        r = trade_rate(1, k)
        series.append({"n": k, "v": round(r["rate"], 1)})
        ref.append({"n": k, "v": round(r["exp"], 1)})
    b.set_chart("rate_line", 320, 120, {"x": [k0, n], "y": [0, 100], "series": series, "ref": ref,
                                        "end_text": fmt_dec(a["rate"], 1) + "%",
                                        "ref_text": "random " + fmt_dec(a["exp"], 1) + "%"}, n,
                "Player-to-player trades while one player led alone on the board, counted from game 1.")
    return b


# --- 6 -----------------------------------------------------------------------------------------------------
def first_win_game(p, hi):
    for i, k in enumerate(own(p, 1, hi), 1):
        if W(k) == p:
            return k, i
    return None


def beat_ms_first_win(asof):
    p = "ms"
    fw = first_win_game(p, N)
    need(fw is not None, "beat ms-first-win", "MS has won")
    n, k = fw
    b = Beat("ms-first-win", n, "player", "full")
    od = {q: RP[gid_of(n)]["players"][q]["opening_dots"] for q in ppl(n)}
    others = sorted(v for q, v in od.items() if q != p)
    b.need(od[p] < min(others), "MS had the weakest opening")
    firsts = {q: first_win_game(q, n) for q in registered if q != p and own(q, 1, n)}
    winners = {q: v for q, v in firsts.items() if v}
    most = max(v[1] for v in winners.values())
    b.need(all(len(own(q, 1, n)) <= most for q, v in firsts.items() if not v),
           "nobody without a win has played more games than the slowest first win")
    cl = close_on(n)
    b.need(cl[0][1] == n, "the game is the closest yet, recomputed over the games so far")
    b.focus = [p]
    b.headline = f"{Ts(p)} first win, at the {b.o(k, 'games played at first win')} attempt"
    b.body = (f"{T(p)} wins for the first time, {b.score(n)}, in {Ts(p)} {b.o(k, 'games played at first win')} game, "
              f"and from the weakest opening at the table: {b.i(od[p], 'opening pips')} dots against "
              f"{and_list([b.i(x, 'opening pips of another') for x in others])}. Nobody else has needed more than "
              f"{b.i(most, 'most games anyone else needed for a first win')} games to win one. On the site's "
              f"closeness index, recomputed over the first {b.i(n, 'games so far')} games, it is the closest game yet.")
    rows = sorted(([q, v[1], v[0]] for q, v in winners.items()), key=lambda r: (r[1], r[2])) + [[p, k, n]]
    b.set_chart("dot_plot", 320, 110, {"rows": [{"pid": q, "v": v, "text": str(v)} for q, v, _ in rows],
                                       "domain": [1, max(10, k + 1)], "highlight": p,
                                       "axis": "games played at first win"}, n)
    return b


# --- 7 -----------------------------------------------------------------------------------------------------
def beat_four_in_a_row(asof):
    n = anchor("2025-04-15-a", "beat four-in-a-row")
    p = W(n)
    v = streak_at(n, p)
    run = own(p, 1, n)[-v:]
    b = Beat("four-in-a-row", n, "streak", "full", span=[run[0], run[-1]])
    b.need(v >= 3 and v in WORDS, "a streak of three or more")
    b.need(all(longest_streak(q, n - 1) < v for q in registered), "the longest streak yet")
    b.need(wa(n, p) >= 10 > max(wins_after[n - 1].values()), "the first player to 10 wins")
    w2 = sorted(wins_after[n].values(), reverse=True)[1]
    second = sorted(q for q, x in wins_after[n].items() if x == w2)
    worst = [k for k in run if luck_rank(k, p) == len(ppl(k))]
    tot = sum(luck(k, p) for k in run)
    b.need(tot < 0 and len(worst) * 2 > len(run), "the run came on bad dice")
    b.focus = [p]
    # "Worst at the table" is ranked in cards (the page's measure for one table); say so in the copy.
    b.headline = f"{cap(WORDS[v])} in a row, against the dice"
    gap_all = max(sorted(wins_after[k].values(), reverse=True)[0] -
                  (sorted(wins_after[k].values(), reverse=True)[1:2] or [0])[0] for k in range(1, asof + 1))
    gap_now = wa(n, p) - w2
    others_best = max(longest_streak(q, asof) for q in registered if q != p)
    tail = ""
    if others_best < v and longest_streak(p, asof) == v and gap_all == gap_now:
        tail = (f" {asof_lead(b, asof)}, both marks still stand: no one else has won "
                f"{b.i(v, 'streak length')} in a row, and no lead in the wins count has been bigger than "
                f"{b.i(gap_now, 'biggest lead in the wins count, all games')}.")
    else:
        warn(b.id, "a mark from the streak has been matched or beaten; hindsight sentence dropped")
    b.body = (f"{T(p)} wins {a_n(v)} {b.o(v, 'win streak')} straight game and becomes the first player to "
              f"{b.i(wa(n, p), 'wins after the anchor')} wins, {b.i(gap_now, 'lead over the next player')} clear of "
              f"{and_list([T(q) for q in second])}. In {b.i(len(worst), 'games of the run with the worst dice, in cards')} of "
              f"the {b.i(v, 'games in the run')} games {T(p)} was the most cards short on the dice of anyone at the "
              f"table, and over the run "
              f"{Ts(p)} dice paid {b.f(-tot, 1, 'sum of dice luck over the run, negated')} fewer cards than "
              f"{Ts(p)} buildings should have earned." + tail)
    bars = [{"n": k, "v": round(luck(k, p), 1), "rank": luck_rank(k, p), "of": len(ppl(k)),
             "label": f"game {k}", "sub": f"{luck_rank(k, p)} of {len(ppl(k))}"} for k in run]
    b.set_chart("hanging_bars", 320, 110, {"pid": p, "unit": "cards", "bars": bars,
                                           "note": "rank at the table by cards above or below expectation; 1 = the luckiest"}, n)
    return b


# --- 8 -----------------------------------------------------------------------------------------------------
KEY = {"led": "ahead before the last turn", "walk_off": "won on the last turn", "reveal": "won by a reveal"}


def beat_the_139_turn_game(asof):
    n = anchor("2025-07-04-a", "beat the-139-turn-game")
    g, s, w = G(n), story(n), W(n)
    b = Beat(f"the-{g['turns']}-turn-game", n, "special", "full")
    b.need(g["turns"] > max(G(k)["turns"] for k in range(1, n)), "the longest game yet")
    b.need(s["ending"] == "reveal", "the game was won by a reveal")
    lead_by = max((q for q in s["lead"]["share"] if q != w and not is_bot(q)), key=lambda q: s["lead"]["share"][q])
    e = endings(1, n)
    b.focus = [w, lead_by]
    b.headline = f"The {b.i(g['turns'], 'turns')}-turn game"
    b.body = (f"{T(w)} wins the longest game yet, {b.score(n)}, from {b.i(s['deficit'], 'stories.deficit')} down, by "
              f"revealing {b.i(s['revealed'], 'stories.revealed')} VP cards on the final turn. {T(lead_by)} had led "
              f"alone for {b.p100(s['lead']['share'][lead_by], 'stories.lead.share')} of it. It is a familiar kind of "
              f"finish: of the first {b.i(n, 'games so far')} winners, only {b.i(e['led'], 'ending led')} were already "
              f"ahead on the board before their final turn, {b.i(e['walk_off'], 'ending walk_off')} were level or "
              f"behind and won on that turn, and {b.i(e['reveal'], 'ending reveal')} won by revealing hidden VP cards.")
    b.set_chart("ending_strip", 320, 40, {"games": [{"n": k, "e": ending(k)} for k in range(1, n + 1)],
                                          "rows": [[1, n]], "mark": n, "bracket": None, "key": KEY}, n)
    return b


# --- 9 and 23: the mirror pair --------------------------------------------------------------------------------
MIRROR = ("2025-09-01-a", "2026-09-14-a")


def wae_series(p, lo, hi):
    """WAE after every group game from the player's debut (flat while absent), as [[n, v]]."""
    out = []
    for k in range(max(lo, own(p)[0]), hi + 1):
        x = sh(p, k)
        if x:
            out.append([k, round(x[0], 3)])
    return out


def mirror_scale(pids):
    hi = num[MIRROR[1]]
    m = max(abs(v) for p in pids for _, v in wae_series(p, 1, hi))
    return [-math.ceil(m), math.ceil(m)], [1, hi]


def beat_ld_top_ms_bottom(asof):
    n = anchor(MIRROR[0], "beat ld-top-ms-bottom")
    b = Beat("ld-top-ms-bottom", n, "standings", "full")
    top, bot = "ld", "ms"
    el = elig_at[n]
    b.need(W(n) == top and lb[n][0] == top, "LD wins and is leaderboard #1")
    b.need(el[-1][0] == bot, "MS is last among eligible players")
    b.focus = [top, bot]
    b.headline = f"{T(top)} on top, {T(bot)} at the bottom"
    t_own = len(own(top, 1, n))
    m_own = len(own(bot, 1, n))
    b.body = (f"{T(top)} wins {b.score(n)} for {a_n(wa(n, top))} {b.o(wa(n, top), 'wins so far')} win in "
              f"{b.i(t_own, 'games played')} games and stands at {b.sg(sh(top, n)[0], 'standing_history WAE')} wins "
              f"above expected, #{b.i(1, 'leaderboard rank')} on the leaderboard. {T(bot)}, with "
              f"{b.i(wa(n, bot), 'wins so far')} wins from {b.i(m_own, 'games played')} games, is last of the "
              f"{b.i(len(el), 'players with 10 or more games')} players with {b.i(CROWN_MIN, 'crown minimum')} or more "
              f"games, at {b.sg(sh(bot, n)[0], 'standing_history WAE')}.")
    y, x = mirror_scale([top, bot])
    b.set_chart("wae_lines", 320, 130, {
        "pids": [bot, top], "x": x, "drawn_to": n, "y": y,
        "series": {p: wae_series(p, 1, n) for p in (bot, top)},
        "marks": [{"pid": p, "n": n, "v": round(sh(p, n)[0], 3), "text": f"{T(p)} {chart_signed(sh(p, n)[0])}"}
                  for p in (top, bot)], "cross": None}, n)
    return b


# --- 10 ----------------------------------------------------------------------------------------------------
def near(obs, exp):
    r = obs / exp
    return "close to" if 0.85 <= r <= 1.15 else "above" if r > 1.15 else "below"


def beat_dice_over_openings(asof):
    n = anchor("2025-09-06-a", "beat dice-over-openings")
    b = Beat("dice-over-openings", n, "analysis", "full")
    lw, lg, lch = luckiest_won(1, n)
    ow, og, och = best_opening_won(1, n)
    LW, LG, LCH = luckiest_won(1, asof)
    OW, OG, OCH = best_opening_won(1, asof)
    b.need(lw / lch > ow / och, "dice beat openings as of then")
    b.headline = "Dice decide more than openings"
    tail = "so dice still count for more" if LW / LCH > OW / OCH else "and openings have caught up"
    if LW / LCH <= OW / OCH:
        warn(b.id, "openings now convert as well as dice")
    b.body = (f"Through game {b.i(n, 'anchor game')}, the player whose dice paid the most above expectation won "
              f"{b.i(lw, 'games won by the luckiest person')} of {b.i(lg, 'games')} games, where chance gives about "
              f"{b.f(lch, 1, 'sum of tied / seats')}. The player with the strongest opening, the most pips on the two "
              f"starting settlements, won {b.i(ow, 'games won by the sole best opening')} of the "
              f"{b.i(og, 'games with a sole best opening')} games where one player had it alone, {near(ow, och)} the "
              f"{b.f(och, 1, 'sum of 1 / seats')} chance gives. {asof_lead(b, asof)}, the luckiest dice have won "
              f"{b.i(LW, 'luckiest won, all games')} of {b.i(LG, 'games')} ({b.f(LCH, 1, 'chance, all games')} by "
              f"chance) and the best opening {b.i(OW, 'best opening won, all games')} of "
              f"{b.i(OG, 'games with a sole best opening, all')} ({b.f(OCH, 1, 'chance, all games')} by chance), {tail}.")
    rows = [{"label": "Luckiest dice", "v": round(100 * lw / lg, 1), "ref": round(100 * lch / lg, 1),
             "text": f"{lw} of {lg}", "ref_text": "chance " + fmt_dec(lch, 1)},
            {"label": "Best opening", "v": round(100 * ow / og, 1), "ref": round(100 * och / og, 1),
             "text": f"{ow} of {og}", "ref_text": "chance " + fmt_dec(och, 1)}]
    b.set_chart("paired_bars", 320, 72, {"domain": [0, 100], "unit": "%", "rows": rows}, n,
                f"Games 1 to {n}. Bars are win rates; ticks are what chance gives.")
    return b


# --- 11 ----------------------------------------------------------------------------------------------------
def vp_cards(lo, hi, who=None):
    v = t = 0
    for k in range(lo, hi + 1):
        for r in G(k)["players"]:
            if is_bot(r["player"]) or (who and r["player"] != who):
                continue
            d = r.get("dev_cards_bought") or {}
            v += d.get("victory_point", 0)
            t += sum(d.values())
    return v, t


def beat_nd_wins_in_the_dark(asof):
    n = anchor("2025-10-25-a", "beat nd-wins-in-the-dark")
    p = "nd"
    b = Beat("nd-wins-in-the-dark", n, "player", "full")
    s = story(n)
    b.need(W(n) == p and s["ending"] == "reveal", "ND wins by a reveal")
    b.need(s["lead"]["changes"] > max(story(k)["lead"]["changes"] for k in range(1, n)), "a record for lead changes")
    rev = [k for k in range(1, n + 1) if ending(k) == "reveal"]
    mine = [k for k in rev if W(k) == p]
    v1, t1 = vp_cards(1, n, p)
    v2, t2 = vp_cards(1, n)
    b.need(v1 / t1 <= v2 / t2, "ND does not draw VP cards more often than the table")
    REV = [k for k in range(1, asof + 1) if ending(k) == "reveal"]
    MINE = [k for k in REV if W(k) == p]
    expect = len(REV) * wa(asof, p) / asof
    b.focus = [p]
    b.headline = f"{T(p)} wins in the dark"
    tail = ""
    if len(MINE) > expect:
        tail = (f" {asof_lead(b, asof)}, {T(p)} holds {b.i(len(MINE), 'reveal wins by ND, all games')} of the group's "
                f"{b.i(len(REV), 'reveal wins, all games')} reveal wins, where {Ts(p)} share of all wins would predict "
                f"about {b.f(expect, 1, 'reveals x ND wins / games')}.")
    else:
        warn(b.id, "ND no longer holds more reveal wins than ND's share of wins predicts")
    b.body = (f"{T(p)} wins a game of {b.i(s['lead']['changes'], 'stories.lead.changes')} lead changes, a record, by "
              f"revealing {b.i(s['revealed'], 'stories.revealed')} hidden VP cards to finish {b.score(n)}. It is "
              f"{Ts(p)} {b.o(len(mine), 'reveal wins by ND so far')} win by reveal, of "
              f"{b.i(len(rev), 'reveal wins so far')} in the group so far. It is not luck of the draw: {T(p)} has drawn "
              f"a VP card in {b.pct(v1, t1, 'ND VP cards / dev cards bought')} of dev card buys, against "
              f"{b.pct(v2, t2, 'all people, VP cards / dev cards bought')} for the table as a whole." + tail)
    b.set_chart("game_strip", 320, 36, {"range": [1, n], "dots": [{"n": k, "pid": ident(W(k))} for k in rev],
                                        "highlight": p}, n,
                f"Wins decided by revealing VP cards, games 1 to {n}.")
    return b


# --- 12 ----------------------------------------------------------------------------------------------------
def beat_year_one(asof):
    y = years_of()[0]
    ks = year_games(y)
    n = ks[-1]
    b = Beat("year-one", n, "milestone", "full")
    b.need(n < N and G(n + 1)["date"][:4] > y, "the first year is over in the data")
    reg = [p for p in registered if own(p, ks[0], n)]
    full_ = [p for p in reg if len(own(p, ks[0], n)) == len(ks)]
    b.need(len(full_) == 1, "exactly one player played every game of the year")
    p = full_[0]
    wc = Counter(W(k) for k in ks if W(k) in registered).most_common()
    b.need(wc[0][0] == p and wc[0][1] > wc[1][1] and wc[1][1] > wc[2][1] and wc[2][1] > wc[3][1],
           "the player who never missed won the most, and the next two are clear")
    runs = {q: max((r for r in attendance_runs(q, asof)), key=lambda r: r[0]) for q in registered if own(q, 1, asof)}
    mine = runs[p]
    nxt = max(v[0] for q, v in runs.items() if q != p)
    nxt_who = sorted(q for q, v in runs.items() if q != p and v[0] == nxt)
    b.focus = [p]
    b.headline = f"The year {T(p)} never missed"
    tail = ""
    if mine[0] == len(ks) and mine[1] == 1 and mine[0] > nxt:
        who = (f"{Ts(nxt_who[0])} {b.i(nxt, 'next longest run')}" if len(nxt_who) == 1 else
               f"{b.i(nxt, 'next longest run')}, by {and_list([T(q) for q in nxt_who])}")
        tail = (f" {asof_lead(b, asof)}, {Ts(p)} run of {b.i(mine[0], 'consecutive games played')} straight games from "
                f"game {b.i(1, 'first game')} is still the longest anyone has played; the next best is {who}.")
    else:
        warn(b.id, "the attendance run is no longer the longest; hindsight sentence dropped")
    # Nobody knew on the night that this was the year's last game: the sentence is framed as hindsight.
    b.body = (f"{asof_lead(b, asof, look=True)}, this was the last game of {b.v(y, 'year')}, which closed at "
              f"{b.i(len(ks), 'games in the year')} games over "
              f"{b.i(len({G(k)['date'] for k in ks}), 'distinct dates')} nights. {T(p)} played all "
              f"{b.i(len(ks), 'games in the year')}, the only player to, and won the most, {b.i(wc[0][1], 'wins')}, "
              f"ahead of {T(wc[1][0])} with {b.i(wc[1][1], 'wins')} and {T(wc[2][0])} with "
              f"{b.i(wc[2][1], 'wins')}." + tail)
    order = sorted(reg, key=lambda q: (-len(own(q, ks[0], n)), registered[q]["initials"]))
    rows = [{"pid": q, "cells": [(2 if W(k) == q else 1) if q in ppl(k) else 0 for k in ks]} for q in order]
    b.set_chart("attendance", 282, 46, {"cols": ks, "rows": rows}, n)
    return b


# --- 13 ----------------------------------------------------------------------------------------------------
def beat_a_new_face(asof):
    y2 = years_of()[1]
    n = year_games(y2)[0]
    b = Beat("a-new-face", n, "milestone", "short")
    gap = gap_before[n]
    b.need(gap > max(v for k, v in gap_before.items() if v is not None and k < n), "the longest break yet")
    new = [p for p in ppl(n) if p in registered and own(p)[0] == n]
    b.need(len(new) == 1, "one new player")
    p, w = new[0], W(n)
    b.need(w != p, "the new player did not win")
    b.need(G(n)["turns"] < min(G(k)["turns"] for k in range(1, n)), "the shortest game yet")
    others = sorted((q for q in ppl(n) if q != p), key=lambda q: registered.get(q, {"initials": "~"})["initials"])
    b.need(all(q in registered for q in others), "no guest at the table")
    rk = rank_of(n, p)
    tied = sum(1 for r in vg[gid_of(n)]["players"] if r["rank"] == rk) > 1
    prev = year_games(years_of()[0])
    missing = [q for q in registered if len(own(q, prev[0], prev[-1])) == len(prev) and q not in ppl(n)]
    b.focus = [p]
    b.headline = f"After {b.i(gap, 'days since the previous game')} days, a new face"
    tail = ""
    if missing:
        q = missing[0]
        tail = f" {T(q)}, who played every game of {b.v(years_of()[0], 'year')}, is not at the table."
    b.body = (f"The group returns from its longest break yet, {b.i(gap, 'days since the previous game')} days, with a "
              f"new player. {T(p)} sits down with {and_list([T(q) for q in others])} and finishes "
              f"{'tied ' if tied else ''}{b.o(rk, 'finishing place')} as {T(w)} wins {b.score(n)} in "
              f"{b.i(G(n)['turns'], 'turns')} turns, the shortest game yet." + tail)
    return b


# --- 14 ----------------------------------------------------------------------------------------------------
def beat_nd_passes_jd(asof):
    n = anchor("2026-01-10-b", "beat nd-passes-jd")
    a, q = "nd", "jd"
    y = G(n)["date"][:4]
    k0 = year_games(y)[0]
    b = Beat("nd-passes-jd", n, "standings", "full", span=[k0, n])
    b.need(len(own(a, k0, n)) == n - k0 + 1 and not own(q, k0, n), "ND played every game of the year, JD none")
    b.need(wa(n, a) > wa(n, q) and wa(n - 1, a) <= wa(n - 1, q) and mw[n] == [a], "ND passes JD here, alone on top")
    caught = next(k for k in range(k0, n + 1) if wa(k, a) >= wa(k, q))
    b.need(wa(caught, a) == wa(caught, q), "ND first draws level")
    on_top = [k for k in range(1, n) if q in mw[k]]
    b.focus = [a, q]
    b.headline = f"{T(a)} passes {T(q)} without {T(q)} losing a game"
    back = [k for k in range(n, asof + 1) if q in mw[k]]
    tail = ""
    if not back:
        tail = f" {asof_lead(b, asof)}, {T(q)} has not been back on top."
    else:
        warn(b.id, f"JD has been back on top (game {back[0]}); hindsight sentence dropped")
    b.body = (f"{T(a)} has played all {b.i(n - k0 + 1, 'games of the new year so far')} games of the new year and "
              f"{T(q)} none of them. {T(a)} caught {T(q)} at {b.i(wa(caught, a), 'wins when level')} wins in game "
              f"{b.i(caught, 'game where ND drew level')} and passes, {b.i(wa(n, a), 'ND wins')} to "
              f"{b.i(wa(n, q), 'JD wins')}, here. {T(q)} had been on top of the wins count, alone or tied, after "
              f"{b.i(len(on_top), 'games with JD at the top, sole or tied')} of the first "
              f"{b.i(n - 1, 'games before this one')} games." + tail)
    return b


# --- 15 ----------------------------------------------------------------------------------------------------
def beat_dh_straight_to_number_one(asof):
    p = "dh"
    mine = own(p)
    need(len(mine) >= CROWN_MIN, "beat dh-straight-to-number-one", "DH has 10 games")
    n = mine[CROWN_MIN - 1]
    b = Beat("dh-straight-to-number-one", n, "standings", "full")
    b.need(lb[n][0] == p and lb[n - 1][0] == "ld", "DH takes #1 from LD in DH's 10th game")
    b.need(W(n) == p, "DH wins the game")
    sp = [s for s in lb_spells() if s[2] == n - 1 and s[0] == "ld"]
    b.need(sp, "LD's spell ends at the game before")
    _, s0, s1 = sp[0]
    b.need(all(t[2] - t[1] < s1 - s0 + 1 for t in lb_spells() if t[2] < s0), "LD's reign is the longest yet")
    b.focus = [p, "ld"]
    b.emphasis = "lb"
    b.headline = f"{T(p)} goes straight to #{b.i(1, 'leaderboard rank')}"
    ranks = [[e[0] for e in elig_at[k]].index(p) + 1 for k in range(n, asof + 1)]
    tail = ""
    if max(ranks) <= 2:
        tail = (f" {asof_lead(b, asof)}, {T(p)} has been #{b.i(1, 'rank')} or #{b.i(2, 'rank')} after every game "
                f"since.")
    else:
        warn(b.id, "DH has fallen below #2 since; hindsight sentence dropped")
    b.body = (f"Game {b.i(n, 'DH 10th game')} is {Ts(p)} {b.o(CROWN_MIN, 'games played')}, the first in which {T(p)} "
              f"counts for the leaderboard's {b.i(CROWN_MIN, 'crown minimum')}-game minimum, and with {a_n(wa(n, p))} "
              f"{b.o(wa(n, p), 'DH wins')} win {T(p)} is #{b.i(1, 'rank')} at once, at "
              f"{b.sg(sh(p, n)[0], 'standing_history WAE')} wins above expected. It ends {Ts('ld')} "
              f"{b.i(s1 - s0 + 1, 'length of the spell at #1')} straight games at #{b.i(1, 'rank')} (games "
              f"{b.i(s0, 'spell start')} to {b.i(s1, 'spell end')}), the longest reign yet." + tail)
    return b


# --- 16 ----------------------------------------------------------------------------------------------------
def beat_nd_the_constant(asof):
    p = "nd"
    mine = own(p)
    need(len(mine) >= 50, "beat nd-the-constant", "ND has 50 games")
    n = mine[49]
    b = Beat("nd-the-constant", n, "player", "full")
    b.need(all(len(own(q, 1, n - 1)) < 50 for q in registered), "ND is the first to 50 games")
    b.need(W(n) == p, "ND wins the 50th game")
    fin = {}
    for q in registered:
        ks = own(q, 1, asof)
        if len(ks) >= CROWN_MIN:
            c = Counter(rank_of(k, q) for k in ks)
            fin[q] = (c[1], c[2], len(ks) - c[1] - c[2], len(ks))
    for q, (a1, a2, _, gp) in fin.items():
        fc = PFINAL[q]["finish_counts"] if asof == N else None
        if fc is not None:
            need(fc.get("1", 0) == a1 and fc.get("2", 0) == a2, b.id, f"finish counts for {q} match stats.json")
    share = {q: (v[0] + v[1]) / v[3] for q, v in fin.items()}
    best = max(share.values())
    w_now = wa(asof, p)
    tops = mw[asof]
    most = ("has the most wins, " + b.i(w_now, "ND wins") if tops == [p] else
            "shares the most wins, " + b.i(w_now, "ND wins") if p in tops else "has " + b.i(w_now, "ND wins") + " wins")
    a1, a2, _, gp = fin[p]
    s2 = (f"{asof_lead(b, asof)}, {T(p)} has played {b.i(gp, 'ND games')} of the {b.i(asof, 'games')} games, {most}, "
          f"and has finished first or second in {b.i(a1 + a2, 'first or second finishes')} of them "
          f"({b.pct(a1 + a2, gp, 'share')})" + (", the best rate of any regular." if share[p] == best else "."))
    ex = exp_wins(p, 1, asof)
    dev = w_now - ex
    how_close = "almost exactly" if abs(dev) < 1 else "close to" if abs(dev) < 2 else None
    after = [sh(p, k)[0] for k in range(n + 1, asof + 1)]
    clauses = []
    if after and max(after) <= 0:
        clauses.append("has not been above zero since this game")
    if p not in {lb[k][0] for k in range(1, asof + 1)}:
        clauses.append(f"has never been leaderboard #{b.i(1, 'rank')} under the {b.i(CROWN_MIN, 'crown minimum')}-game "
                       f"minimum")
    s3 = ""
    if how_close and clauses:
        s3 = (f" {asof_lead(b, asof, look=True)}, those {b.i(w_now, 'ND wins')} wins are {how_close} the "
              f"{b.f(ex, 2, 'expected wins, sum of 1 / seats')} that chance predicts at {Ts(p)} tables: {T(p)} "
              f"{' and '.join(clauses)}.")
    else:
        warn(b.id, "the chance comparison no longer holds; hindsight sentence dropped")
    b.focus = [p]
    b.headline = f"{T(p)}, the constant"
    b.body = (f"In {Ts(p)} {b.o(50, 'games played')} game, which makes {T(p)} the first player to reach "
              f"{b.i(50, 'games played')}, {T(p)} wins {b.score(n)} and stands at {b.sg(sh(p, n)[0], 'standing_history WAE')} "
              f"wins above expected. " + s2 + s3)
    rows = sorted(({"pid": q, "games": v[3], "first": v[0], "second": v[1], "rest": v[2],
                    "pct": fmt_dec(100 * (v[0] + v[1]) / v[3], 1) + "%"} for q, v in fin.items()),
                  key=lambda r: (-(r["first"] + r["second"]) / r["games"], r["pid"]))
    b.set_chart("stacked_finish", 320, 130, {"rows": rows}, asof,
                f"As of game {asof}. Finishing places, ties counted at the shared place.")
    return b


# --- 17 ----------------------------------------------------------------------------------------------------
def beat_dh_january(asof):
    p = "dh"
    n0 = own(p)[0]
    table = {r["player"] for r in G(n0)["players"]}
    n = n0
    while n + 1 <= N and {r["player"] for r in G(n + 1)["players"]} == table:
        n += 1
    b = Beat("dh-january", n, "era", "full", span=[n0, n])
    ks = list(range(n0, n + 1))
    b.need(len(table) == 3 and all(q in registered for q in table), "a table of three registered players")
    dates = sorted({G(k)["date"] for k in ks})
    dw = sum(1 for k in ks if W(k) == p)
    ex = exp_wins(p, n0, n)
    led = sum(1 for k in ks if W(k) == p and ending(k) == "led")
    ae, lo, hi = sh(p, n)
    b.need(ae > hi, "DH is above the luck band at the end of the run")
    outs = sorted((k, q) for q in band for k, (v, (l_, h_)) in band[q].items() if (v > h_ or v < l_) and k <= n)
    b.need(outs and outs[0] == (n, p), "the first time any player has been outside the band")
    el = elig_at[n]
    b.need(el[-1][0] == "ld", "LD is last of the eligible players")
    last_from = n
    while last_from - 1 >= 1 and elig_at[last_from - 1] and elig_at[last_from - 1][-1][0] == "ld":
        last_from -= 1
    sp = [s for s in lb_spells() if s[0] == "ld" and s[1] <= n]
    b.need(sp, "LD held #1 before")
    ld_until = sp[-1][2]
    b.need(ld_until < last_from, "LD was #1 before being last")
    others = sorted(table, key=lambda q: registered[q]["initials"])
    same_later = [k for k in range(1, asof + 1) if k not in ks and {r["player"] for r in G(k)["players"]} == table]
    b.focus = [p]
    b.headline = (f"{Ts(p)} {MONTHS[day(dates[0]).month - 1]}: {b.i(len(ks), 'games in the run')} games in "
                  f"{b.i((day(dates[-1]) - day(dates[0])).days + 1, 'days spanned')} days")
    b.need(day(dates[0]).month == day(dates[-1]).month, "the run sits in one month")
    s2 = ""
    if not same_later:
        s2 = f" {asof_lead(b, asof)}, no other game has had exactly that table."
    else:
        warn(b.id, "that table has met again; hindsight sentence dropped")
    b.body = (f"From {b.drange(dates[0], dates[-1])} the group plays {b.i(len(ks), 'games in the run')} games over "
              f"{b.i(len(dates), 'nights')} nights, every one with the same three people, "
              f"{and_list([T(q) for q in others])}." + s2 +
              f" {T(p)} wins {b.i(dw, 'DH wins in the run')}, against {b.f(ex, 2, 'DH expected wins in the run')} "
              f"expected, and {b.i(led, 'DH wins with ending led')} of the {b.i(dw, 'DH wins in the run')} from in front. "
              f"That leaves {T(p)} at {b.sg(ae, 'standing_history WAE')} wins above expected, past the top of the "
              f"{b.v('95%', 'the luck band is the 95% band')} luck band at {b.sg(hi, 'luck_band top')}, the first time "
              f"any player has been outside it. {T('ld')}, #{b.i(1, 'rank')} on the leaderboard until game "
              f"{b.i(ld_until, 'end of LD spell at #1')}, has been last of the {b.i(len(el), 'eligible players')} since "
              f"game {b.i(last_from, 'first game LD is last, in the current run')}.")
    pts = [{"n": k, "v": round(band[p][k][0], 3), "lo": round(band[p][k][1][0], 3), "hi": round(band[p][k][1][1], 3)}
           for k in ks if k in band[p]]
    lo_d = math.floor(min(min(x["v"], x["lo"]) for x in pts))
    hi_d = math.ceil(max(max(x["v"], x["hi"]) for x in pts))
    b.set_chart("band_line", 320, 130, {"pid": p, "points": pts, "domain": [min(lo_d, -4), max(hi_d, 4)],
                                        "mark": {"n": n, "v": round(ae, 3),
                                                 "text": f"{chart_signed(ae)}, outside the band"}}, n)
    return b


# --- 18 ----------------------------------------------------------------------------------------------------
def beat_the_road_changes_hands(asof):
    n = anchor("2026-02-10-b", "beat the-road-changes-hands")
    b = Beat("the-road-changes-hands", n, "analysis", "full")
    gid = gid_of(n)
    seats = EV[gid]["seats"]
    st_ = [(seats[c["seat"] - 1], seats[c["from"] - 1]) for v in EV[gid]["vp_events"] for c in v["changes"]
           if c["type"] == "longest_road_taken" and c.get("from") is not None]
    pair = sorted({x for s in st_ for x in s})
    b.need(len(pair) == 2 and all(q in registered for q in pair), "the steals are between two players")
    by = Counter(t for t, _ in st_)
    w = W(n)
    b.need(w in pair and st_[-1][0] == w, "the winner made the last steal")
    b.need(next(r for r in G(n)["players"] if r["player"] == w)["vp_breakdown"]["longest_road"] > 0,
           "the winner ends holding the road")
    road, army, per = title_steals(1, n)
    b.need(per[n] > max(v for k, v in per.items() if k < n), "the most road steals in a game so far")
    hr, ha = winner_titles(1, n)
    R2, A2, _ = title_steals(1, asof)
    HR, HA = winner_titles(1, asof)
    other = next(q for q in pair if q != w)
    b.focus = [w, other]
    b.headline = "The road changes hands, the army stays put"
    each = (f", {b.i(by[w], 'steals each')} each" if by[w] == by[other] else
            f", {b.i(by[w], 'steals by the winner')} to {b.i(by[other], 'steals by the other')}")
    b.body = (f"{T(w)} and {T(other)} take Longest Road from each other {b.i(len(st_), 'road steals in the game')} times"
              f"{each}, the most in any game so far, and {T(w)} ends up holding it and wins {b.score(n)}. Through game "
              f"{b.i(n, 'anchor game')}, Longest Road has been taken from its holder {b.i(road, 'road steals so far')} "
              f"times and Largest Army only {b.i(army, 'army steals so far')}. Of the {b.i(n, 'winners so far')} "
              f"winners, {b.i(hr, 'winners holding the road')} finished holding the road, and "
              f"{b.i(ha, 'winners holding the army')} the army. {asof_lead(b, asof)}, it is "
              f"{b.i(R2, 'road steals, all games')} steals to {b.i(A2, 'army steals, all games')}, and "
              f"{b.i(HR, 'winners holding the road, all games')} winners to {b.i(HA, 'winners holding the army, all games')}.")
    b.set_chart("bar_pairs", 320, 90, {
        "series": [{"key": "road", "label": "Longest Road"}, {"key": "army", "label": "Largest Army"}],
        "groups": [{"label": "Taken from the holder", "road": road, "army": army},
                   {"label": "Held by the winner at the end", "road": hr, "army": ha}]}, n,
        f"Games 1 to {n}.")
    return b


# --- 19 ----------------------------------------------------------------------------------------------------
def winner_min_chance(k):
    t = TH.get(gid_of(k))
    if not t or W(k) not in t["seats"]:
        return None
    p = t["p"][t["seats"].index(W(k))]
    m = min(p)
    return m, t["turn"][p.index(m)]


def beat_back_from_one_percent(asof):
    n = anchor("2026-02-12-a", "beat back-from-one-percent")
    b = Beat("back-from-one-percent", n, "special", "full")
    s, w = story(n), W(n)
    ru = runner_up(n)
    b.need(len(ru) == 1 and ru[0] in registered, "one runner-up")
    prev = [k for k in range(1, n) if story(k)["deficit"] == s["deficit"]]
    b.need(prev and s["deficit"] >= max(story(k)["deficit"] for k in range(1, n)), "ties the comeback record")
    b.need(s["ending"] == "reveal", "won by a reveal")
    m, turn = winner_min_chance(n)
    t = TH[gid_of(n)]
    pw = t["p"][t["seats"].index(w)]
    mins = [(winner_min_chance(k) or (2, 0))[0] for k in range(1, asof + 1)]
    lower = [k for k in range(1, asof + 1) if mins[k - 1] < m]
    below10 = sum(1 for x in mins if x < 0.10)
    b.focus = [w, ru[0]]
    b.headline = f"Back from {b.pc(100 * m, 'threat timeline minimum for the winner')}"
    if not lower:
        s4 = (f" {asof_lead(b, asof)}, no winner has come back from lower, and {b.i(below10, 'winners below 10%')} of "
              f"the {b.i(asof, 'winners')} winners were below {b.v('10%', 'threshold')} at some point.")
    else:
        s4 = (f" {asof_lead(b, asof)}, {b.i(len(lower), 'winners lower')} "
              f"{'winner has' if len(lower) == 1 else 'winners have'} come back from lower, and "
              f"{b.i(below10, 'winners below 10%')} of the {b.i(asof, 'winners')} winners were below "
              f"{b.v('10%', 'threshold')} at some point.")
        warn(b.id, "a winner has come back from lower; sentence reworded")
    b.body = (f"{T(w)} comes back from {b.i(s['deficit'], 'stories.deficit')} down to beat {T(ru[0])} {b.score(n)}, "
              f"tying the comeback record from {'game' if len(prev) == 1 else 'games'} "
              f"{and_list([b.i(k, 'earlier game with the same deficit') for k in prev])}, and finishes by revealing "
              f"{b.i(s['revealed'], 'stories.revealed')} hidden VP cards. {asof_lead(b, asof, look=True)}, the site's "
              f"win-chance model, fitted on all {b.i(asof, 'games')} games, puts {T(w)} at "
              f"{b.pc(100 * m, 'threat timeline minimum')} on turn {b.i(turn, 'turn of the minimum')} of "
              f"{b.i(G(n)['turns'], 'turns')}." + s4)
    pts = [[tt, round(100 * x, 1)] for tt, x in zip(t["turn"], pw)]
    b.set_chart("chance_line", 320, 110, {
        "pid": w, "points": pts, "x": [1, t["turn"][-1]], "y": [0, 100], "grid": [50],
        "min": {"turn": turn, "v": round(100 * m, 1), "text": f"{fmt_dec(100 * m, 1)}%, turn {turn}"},
        "end": {"turn": t["turn"][-1], "v": round(100 * pw[-1], 1),
                "text": f"{fmt_dec(100 * pw[-1], 0)}% before the reveal"}}, asof, LABEL_MODEL)
    return b


# --- 20 ----------------------------------------------------------------------------------------------------
def beat_leads_that_hold(asof):
    n = anchor("2026-03-24-a", "beat leads-that-hold")
    y1, y2 = years_of()[0], G(n)["date"][:4]
    a = year_games(y1)
    k0 = year_games(y2)[0]
    b = Beat("leads-that-hold", n, "analysis", "full", span=[k0, n])
    e1, e2 = endings(a[0], a[-1]), endings(k0, n)
    t1, t2 = three_seat(a[0], a[-1]), three_seat(k0, n)
    m1, m2 = mean(G(k)["turns"] for k in t1), mean(G(k)["turns"] for k in t2)
    led3 = sum(1 for k in t1 if ending(k) == "led")
    span_n = n - k0 + 1
    b.need(e2["led"] / span_n > e1["led"] / len(a) + 0.2, "leads held clearly more often")
    b.need(m2 < m1 - 5, "three-seat games got quicker")
    b.need(led3 / len(t1) < e2["led"] / span_n, "three-seat games of the first year were not won from in front as often")
    b.headline = "Shorter games, and leads that hold"
    b.body = (f"Of the {b.i(span_n, 'games since the new year began')} winners since the new year began, "
              f"{b.i(e2['led'], 'ending led, since the new year')} were already ahead on the board before their final "
              f"turn; in the {b.i(len(a), 'games in the first year')} games of {b.v(y1, 'year')} it was "
              f"{b.i(e1['led'], 'ending led, first year')}. The three-seat game has got quicker too: "
              f"{b.f(m2, 1, 'mean turns, n_seats 3, since the new year')} turns on average in the "
              f"{b.i(len(t2), 'three-seat games since the new year')} played since game {b.i(k0, 'first game of the year')}, "
              f"against {b.f(m1, 1, 'mean turns, n_seats 3, first year')} in the {b.i(len(t1), 'three-seat games, first year')} "
              f"of {b.v(y1, 'year')}. Table size alone does not explain the first change, since {b.v(y1, 'year')}'s "
              f"three-seat games had been won from in front only {b.i(led3, 'three-seat games won led, first year')} "
              f"times in {b.i(len(t1), 'three-seat games, first year')}.")
    half = math.ceil(n / 2)
    b.set_chart("ending_strip", 320, 56, {
        "games": [{"n": k, "e": ending(k)} for k in range(1, n + 1)], "rows": [[1, half], [half + 1, n]],
        "mark": None, "key": KEY,
        "bracket": {"from": k0, "to": n,
                    "text": f"since the new year: {e2['led']} of {span_n} ahead before the last turn"}}, n)
    return b


# --- 21 ----------------------------------------------------------------------------------------------------
def beat_the_long_pause(asof):
    k0 = anchor("2026-06-05-a", "beat the-long-pause")
    n = anchor("2026-08-30-a", "beat the-long-pause")
    ks = list(range(k0, n + 1))
    b = Beat("the-long-pause", n, "era", "short", span=[k0, n])
    gap = gap_before[k0]
    b.need(gap > max(v for k, v in gap_before.items() if v is not None and k < k0), "the longest break yet")
    months = [day(G(k)["date"]).month for k in ks]
    b.need(len(set(months)) == len(ks) and all(gap_before[k] > BREAK_DAYS for k in ks[1:]),
           "one game a month, each after a break")
    ws = [W(k) for k in ks]
    b.need(len(set(ws)) == len(ws) and all(w in registered for w in ws) and len(ks) in WORDS,
           "a different winner each time")
    b.headline = "The long pause"
    b.body = (f"After {a_n(gap)} {b.i(gap, 'days between the dates of the two games')}-day break, the longest yet, the group "
              f"meets {and_list([f'once in {MONTHS[m - 1]}' for m in months])}. {cap(WORDS[len(ks)])} games, "
              f"{WORDS[len(ks)]} different winners: {and_list([T(w) for w in ws])}.")
    return b


# --- 22 ----------------------------------------------------------------------------------------------------
def firsts_through(hi):
    maps, sizes = {}, {}
    for k in range(1, hi + 1):
        g = G(k)
        maps.setdefault(map_key(g), (k, W(k), map_label(g)))
        sizes.setdefault(len(ppl(k)), (k, W(k)))
    return maps, sizes


def beat_six_at_the_table(asof):
    n = anchor("2026-09-01-a", "beat six-at-the-table")
    big = len(ppl(n))
    b = Beat("six-at-the-table", n, "milestone", "full")
    w = W(n)
    b.need(big > max(len(ppl(k)) for k in range(1, n)), "the first game with this many people")
    b.need(big in WORDS and w in registered, "a first game at the biggest table, won by a player")
    tps = G(n)["turns"] / seats_n(n)
    b.need(tps < min(G(k)["turns"] / seats_n(k) for k in range(1, n)), "the fewest turns per seat yet")
    maps, sizes = firsts_through(n)
    mine_m = [v[2] for k, v in sorted(maps.items(), key=lambda kv: kv[1][0]) if v[1] == w]
    mine_s = [k for k, v in sorted(sizes.items()) if v[1] == w]
    parts = [f"on {lab}" for lab in mine_m] + [f"with {b.i(s, 'table size')}" + (" people" if i == 0 else "")
                                               for i, s in enumerate(mine_s)]
    b.need(len(parts) >= 3, "several firsts for the winner")
    q = "dh"
    prevq = own(q, 1, n - 1)
    b.need(q in ppl(n) and prevq, "DH returns here")
    away = (day(G(n)["date"]) - day(G(prevq[-1])["date"])).days
    ae, lo, hi = sh(q, n)
    pae, plo, phi = sh(q, prevq[-1])
    b.need(ae > hi and pae > phi, "DH was above the band before and still is")
    b.focus = [w, q]
    b.headline = f"{cap(WORDS[big])} at the table"
    b.asof_ok("is back after", "DH was above the band after DH's previous game and has played no game in between")
    b.body = (f"{T(w)} wins the first game with {b.i(big, 'people at the table')} people, {b.score(n)}. At "
              f"{b.i(G(n)['turns'], 'turns')} turns over {b.i(seats_n(n), 'seats')} seats, each player gets "
              f"{b.f(tps, 1, 'turns / seats')} turns, the fewest yet. {T(w)} has now won the first game "
              f"{and_list(parts)}. {T(q)} is back after {b.i(away, 'days since DH last played')} days away and is still "
              f"above the luck band, at {b.sg(ae, 'standing_history WAE')} against a top of "
              f"{b.f(hi, 2, 'luck_band top')}.")
    b.set_chart("firsts", 320, 120, {"highlight": w, "columns": [
        {"title": "First on each map",
         "rows": [{"label": v[2], "pid": ident(v[1]), "n": v[0]} for _, v in sorted(maps.items(), key=lambda kv: kv[1][0])]},
        {"title": "First at each table size",
         "rows": [{"label": f"{k} people", "pid": ident(v[1]), "n": v[0]} for k, v in sorted(sizes.items())]}]}, n)
    return b


# --- 23 ----------------------------------------------------------------------------------------------------
def beat_the_mirror(asof):
    n = anchor(MIRROR[1], "beat the-mirror")
    m38 = num[MIRROR[0]]
    up, down = "ms", "ld"
    b = Beat("the-mirror", n, "standings", "full")
    k = streak_at(n, up)
    b.need(W(n) == up and k >= 2, "MS wins again")
    b.need(len(mw[n]) == 2 and up in mw[n], "MS ties for most wins")
    tied_with = next(q for q in mw[n] if q != up)
    b.need(lb[n][0] == up and all(lb[j][0] != up for j in range(1, n)), "MS is leaderboard #1 for the first time")
    el = elig_at[n]
    b.need(el[-1][0] == down, "LD is last")
    b.need(lb[m38][0] == down and elig_at[m38][-1][0] == up, "the other way round at the earlier beat")
    dr = drought_at(n, down)
    b.need(dr > 0 and W(n) != down, "LD has not won for a while")
    sign = []
    prev = None
    for j in range(m38, n + 1):
        d = sh(up, j)[0] - sh(down, j)[0]
        if prev is not None and (d > 0) != (prev > 0):
            sign.append(j)
        prev = d
    b.need(sign, "the lines crossed")
    gu, wu, eu = len(own(up, m38 + 1, n)), wins_in(up, m38 + 1, n), exp_wins(up, m38 + 1, n)
    gd, wd, ed = len(own(down, m38 + 1, n)), wins_in(down, m38 + 1, n), exp_wins(down, m38 + 1, n)
    b.focus = [up, down]
    b.headline = "The mirror"
    b.asof_ok("Since then", "counts games after the earlier beat up to this game, true as of then")
    b.body = (f"{T(up)} wins {a_n(k)} {b.o(k, 'win streak')} straight game to tie {T(tied_with)} at {b.i(wa(n, up), 'wins')} "
              f"wins and becomes leaderboard #{b.i(1, 'rank')} for the first time, at "
              f"{b.sg(sh(up, n)[0], 'standing_history WAE')} wins above expected. {T(down)}, "
              f"{b.i(dr, 'games without a win')} games without a win, is last at {b.sg(sh(down, n)[0], 'standing_history WAE')}. "
              f"At game {b.i(m38, 'the earlier beat')} it was the other way round. Since then {T(up)} has won "
              f"{b.i(wu, 'MS wins since')} of {b.i(gu, 'MS games since')} games ({b.f(eu, 1, 'MS expected wins since')} "
              f"expected) and {T(down)} {b.i(wd, 'LD wins since')} of {b.i(gd, 'LD games since')} "
              f"({b.f(ed, 1, 'LD expected wins since')} expected), and their lines "
              f"{'crossed' if len(sign) == 1 else 'first crossed'} in game {b.i(sign[0], 'game where MS passes LD')}.")
    y, x = mirror_scale([up, down])
    marks = ([{"pid": p, "n": m38, "v": round(sh(p, m38)[0], 3), "text": str(m38)} for p in (down, up)] +
             [{"pid": p, "n": n, "v": round(sh(p, n)[0], 3), "text": f"{T(p)} {chart_signed(sh(p, n)[0])}"}
              for p in (up, down)])
    c = sign[0]
    b.set_chart("wae_lines", 320, 130, {
        "pids": [up, down], "x": x, "drawn_to": n, "y": y,
        "series": {p: wae_series(p, 1, n) for p in (up, down)}, "marks": marks,
        "cross": {"n": c, "v": round((sh(up, c)[0] + sh(down, c)[0]) / 2, 3)}}, n)
    return b


# --- 24 ----------------------------------------------------------------------------------------------------
def beat_ms_needed_good_dice(asof):
    n = anchor(MIRROR[1], "beat ms-needed-good-dice")
    p = "ms"
    b = Beat("ms-needed-good-dice", n, "analysis", "full")
    before = own(p, 1, n - 1)
    below = [k for k in before if luck(k, p) < 0]
    above = [k for k in before if luck(k, p) >= 0]
    wb, wab = sum(W(k) == p for k in below), sum(W(k) == p for k in above)
    b.need(wb == 0 and wab > 0, "MS had never won on below-par dice before")
    b.need(W(n) == p and luck(n, p) < 0 and luck_rank(n, p) == len(ppl(n)), "MS wins on the worst dice at the table")
    rel = luck_rel(n, p)
    b.need(all(luck_rel(k, W(k)) > rel for k in range(1, n) if W(k) in RP[gid_of(k)]["players"]),
           "the worst relative dice of any winner yet")
    allb = [k for k in own(p, 1, asof) if luck(k, p) < 0]
    won = [k for k in allb if W(k) == p]
    b.focus = [p]
    b.headline = f"{T(p)} needed good dice, until now"
    b.body = (f"Before this game, {T(p)} had won {b.i(wab, 'MS wins at or above par')} of the "
              f"{b.i(len(above), 'MS games at or above par')} games in which {Ts(p)} dice paid at or above expectation, "
              f"and none of the {b.i(len(below), 'MS games below par')} in which they paid below it. Here {T(p)} wins with "
              f"dice {b.pc(-100 * rel, 'dice luck / expected, negated')} short of expectation, the worst at the table and "
              f"the worst, relative to expectation, of any winner yet. {asof_lead(b, asof)}, {T(p)} has won "
              f"{b.i(len(won), 'MS below-par wins, all games')} below-par games in {b.i(len(allb), 'MS below-par games, all')}: "
              f"{and_list([b.i(k, 'game') for k in won])}.")
    # One dot per game MS had played before this one, in order, split by whether the dice paid at least what was
    # expected; filled = won. Game n is added at the end of the below-par row and ringed.
    b.set_chart("par_strip", 320, 84, {
        "pid": p,
        "rows": [{"label": "Dice at or above par", "games": [{"n": k, "won": W(k) == p} for k in above],
                  "text": f"won {wab} of {len(above)}"},
                 {"label": "Dice below par", "games": [{"n": k, "won": W(k) == p} for k in below],
                  "text": f"won {wb} of {len(below)}"}],
        "mark": {"row": 1, "n": n, "won": True, "text": f"game {n}, {chart_signed(100 * rel, 1)}%"}},
        n, f"{Ts(p)} {len(before)} games through game {n - 1}, in order; filled dots are wins. "
           f"Ringed: game {n}, won with the dice {fmt_dec(-100 * rel, 1)}% short.")
    return b


# --- 25 ----------------------------------------------------------------------------------------------------
def beat_ld_drought_ends(asof):
    n = anchor("2026-10-03-a", "beat ld-drought-ends")
    p = "ld"
    b = Beat("ld-drought-ends", n, "player", "full")
    b.need(W(n) == p, "LD wins")
    dr = own(p, 1, n - 1)
    last_win = max(k for k in dr if W(k) == p)
    games_ = [k for k in dr if k > last_win]
    b.span = [games_[0], n]
    L = len(games_)
    longest_others = max(longest_drought(q, n - 1) for q in registered if q != p)
    own_before = longest_drought(p, last_win)
    b.need(L > longest_others and L > own_before, "the longest drought anyone has had")
    days = (day(G(n)["date"]) - day(G(last_win)["date"])).days
    mine = own(p, 1, n)
    pr = p_drought([1 / seats_n(k) for k in mine], L)
    one_in = about_one_in(pr)
    lk = sum(luck(k, p) for k in games_)
    b.need(lk > 0, "LD's dice paid above expectation over the drought")
    fin = Counter(rank_of(k, p) for k in games_)
    place, times = max(fin.items(), key=lambda kv: (kv[1], -kv[0]))
    s = story(n)
    b.need(s["deficit"] >= max(story(k)["deficit"] for k in range(1, n)), "ties the comeback record")
    gid = gid_of(n)
    seats = EV[gid]["seats"]
    steals = [(v["roll_index"] + 1, seats[c["seat"] - 1], seats[c["from"] - 1]) for v in EV[gid]["vp_events"]
              for c in v["changes"] if c["type"] == "longest_road_taken" and c.get("from") is not None]
    b.need(steals and steals[-1][1] == p and steals[-1][0] == G(n)["turns"], "LD takes the road on the final turn")
    victim = steals[-1][2]
    b.need(victim in registered, "from a player")
    b.focus = [p]
    b.headline = f"{Ts(p)} drought ends"
    b.body = (f"{T(p)} had gone {b.i(L, 'LD games without a win')} games and {b.i(days, 'days since the last win')} days "
              f"without a win, since game {b.i(last_win, 'LD last win')}, the longest drought anyone has had. With an "
              f"equal chance for every seat, a drought this long would turn up somewhere in {Ts(p)} first "
              f"{b.i(len(mine), 'LD games through this one')} games about once in "
              f"{b.i(one_in, 'exact chance of a run this long, 1 / p, rounded')}. It was not the dice: over the "
              f"{b.i(L, 'drought games')} games {Ts(p)} rolls paid {b.f(lk, 1, 'sum of dice luck over the drought')} cards "
              f"more than expected, and {T(p)} finished {b.o(place, 'most common place')} {b.i(times, 'times in that place')} "
              f"times. {T(p)} ends it from {b.i(s['deficit'], 'stories.deficit')} down, tying the comeback record, by "
              f"taking Longest Road from {T(victim)} on the final turn to win {b.score(n)}.")
    b.v(fmt_dec(pr, 4), "exact chance (not shown)")
    cols, folds = [], []
    for i, k in enumerate(games_):
        cols.append({"n": k, "v": round(luck(k, p), 1), "place": rank_of(k, p)})
        if i:
            sat = sum(1 for j in range(games_[i - 1] + 1, k))
            if sat >= 3:
                folds.append({"after": games_[i - 1], "before": k, "sat_out": sat})
    b.set_chart("drought_bars", 320, 100, {"pid": p, "cols": cols, "folds": folds,
                                           "note": "bars: dice luck in cards; digits: finishing place"}, n)
    return b


# --- 26 ----------------------------------------------------------------------------------------------------
def beat_six_winners(asof):
    n = anchor("2026-11-06-a", "beat six-winners")
    L = distinct_run(n)
    k0 = n - L + 1
    b = Beat("six-winners", n, "streak", "short", span=[k0, n])
    b.need(L in WORDS and L >= 5, "a long run of different winners")
    prior = [distinct_run(e) for e in range(1, k0)]
    rec = max(prior)
    rec_at = prior.index(rec) + 1
    b.need(L > rec, "a record")
    ws = [W(k) for k in range(k0, n + 1)]
    b.need(all(w in registered for w in ws), "every winner is a player")
    again = [e for e in range(1, asof + 1) if distinct_run(e) >= L and e != n]
    b.focus = ws
    b.headline = f"{cap(WORDS[L])} games, {WORDS[L]} winners"
    tail = ""
    if not again:
        tail = f" {asof_lead(b, asof)}, it has happened only this once."
    else:
        warn(b.id, "another run this long has happened; hindsight sentence dropped")
    b.body = (f"{and_list([T(w) for w in ws])} win games {b.i(k0, 'first game of the run')} to "
              f"{b.i(n, 'last game of the run')}, in that order, between "
              f"{b.v(d_range(G(k0)['date'], G(n)['date']).replace(' to ', ' and ', 1), 'dates')}. The longest run "
              f"without a repeat winner had been {b.i(rec, 'previous record run')}, set at game "
              f"{b.i(rec_at, 'end of the previous record run')}." + tail)
    b.set_chart("chips", 320, 28, {"items": [{"pid": w, "n": k} for k, w in zip(range(k0, n + 1), ws)]}, n)
    return b


# --- 27 ----------------------------------------------------------------------------------------------------
def beat_ms_leads_alone(asof):
    p = "ms"
    n = next((k for k in range(1, N + 1) if mw[k] == [p]), None)
    need(n is not None, "beat ms-leads-alone", "MS leads the wins count alone at some point")
    b = Beat("ms-leads-alone", n, "standings", "full")
    s = story(n)
    b.need(W(n) == p and s["deficit"] > 0, "MS wins it from behind")
    w2 = sorted(wins_after[n].values(), reverse=True)[1]
    second = [q for q, v in wins_after[n].items() if v == w2]
    b.need(len(second) == 1, "one player second")
    b.need(lb[n][0] == p, "MS is leaderboard #1 too")
    both = [k for k in range(1, n) if len(mw[k]) == 1 and mw[k][0] == lb[k][0]]
    b.need(both and mw[both[-1]][0] != p, "someone else held both crowns before")
    last_both, holder = both[-1], mw[both[-1]][0]
    rises = {q: rise_through(q, n) for q in registered if band[q] and min(band[q]) <= n}
    r, lo_n, hi_n = rises[p]
    b.need(hi_n == n and all(v[0] < r for q, v in rises.items() if q != p), "MS's rise is the biggest and ends here")
    b.focus = [p]
    b.headline = f"{T(p)} leads alone, and holds both crowns"
    b.body = (f"{T(p)} comes back from {b.i(s['deficit'], 'stories.deficit')} down through "
              f"{b.i(s['lead']['changes'], 'stories.lead.changes')} lead changes to win {b.score(n)} and, in {Ts(p)} "
              f"{b.o(len(own(p, 1, n)), 'MS games played')} game, leads the wins count alone for the first time, "
              f"{b.i(wa(n, p), 'MS wins')} to {Ts(second[0])} {b.i(w2, 'second most wins')}. As leaderboard "
              f"#{b.i(1, 'rank')} too, {T(p)} is the first player to hold both crowns since {T(holder)} in game "
              f"{b.i(last_both, 'last game with both crowns on one player')}. From a low of "
              f"{b.sg(band[p][lo_n][0], 'standing_history WAE at the low')} after game {b.i(lo_n, 'game of the low')}, "
              f"{T(p)} has climbed to {b.sg(band[p][hi_n][0], 'standing_history WAE now')}, a rise of "
              f"{b.f(r, 2, 'rise')}, the biggest anyone has made.")
    rows = sorted(({"pid": q, "v": round(v[0], 2), "text": fmt_dec(v[0], 2)} for q, v in rises.items()),
                  key=lambda x: (-x["v"], x["pid"]))
    b.set_chart("dot_plot", 320, 130, {"rows": rows, "domain": [0, math.ceil(max(x["v"] for x in rows))],
                                       "highlight": p,
                                       "axis": "biggest rise in wins above expected, from any low to a later high"}, n,
                f"Games 1 to {n}.")
    return b


# --- 28 ----------------------------------------------------------------------------------------------------
def beat_the_duel(asof):
    n = anchor("2026-11-14-c", "beat the-duel")
    a, q = "nd", "ms"

    def ok(k):
        v = sorted(wins_after[k].values(), reverse=True)
        return (abs(wa(k, a) - wa(k, q)) <= 1 and min(wa(k, a), wa(k, q)) >= v[1]
                and (len(v) < 3 or v[2] < min(wa(k, a), wa(k, q))))
    need(ok(n), "beat the-duel", "ND and MS are the top two, at most 1 apart")
    k0 = n
    while k0 - 1 >= 1 and ok(k0 - 1):
        k0 -= 1
    b = Beat("the-duel", n, "standings", "full", span=[k0, n])
    p_in = W(k0)
    b.need(p_in in (a, q), "one of the two pulled within 1")
    other = a if p_in == q else q
    ga, wa_, ea = len(own(a, k0 + 1, n)), wins_in(a, k0 + 1, n), exp_wins(a, k0 + 1, n)
    gq, wq, eq = len(own(q, k0 + 1, n)), wins_in(q, k0 + 1, n), exp_wins(q, k0 + 1, n)
    rest = Counter(ident(W(k)) for k in range(k0 + 1, n + 1) if W(k) not in (a, q))
    first_win = {}
    for k in range(k0 + 1, n + 1):
        first_win.setdefault(ident(W(k)), k)
    names = [T(x) for x, _ in sorted(rest.items(), key=lambda kv: (-kv[1], first_win[kv[0]])) if x != "guest"]
    if "guest" in rest:
        names.append("a guest" if rest["guest"] == 1 else "guests")
    b.need(abs(wa_ - ea) <= 1.5 and abs(wq - eq) <= 1.5, "both close to chance")
    b.need(W(n) in (a, q), "one of the two wins the 100th game")
    b.focus = [a, q]
    b.headline = "A duel neither could break"
    b.asof_ok("pulled within", "the run is counted from its first game up to this game, so it is true as of then")
    b.body = (f"Since {T(p_in)} pulled within {b.i(1, 'gap')} of {T(other)} in game {b.i(k0, 'start of the run')}, the two "
              f"have been the top two in the wins count and never more than {b.i(1, 'gap')} apart, "
              f"{b.i(n - k0 + 1, 'games in the run')} games in a row. Neither has broken away. From game "
              f"{b.i(k0 + 1, 'game after the start')} to here {T(a)} has won {b.i(wa_, 'ND wins')} of "
              f"{b.i(ga, 'ND games')} and {T(q)} {b.i(wq, 'MS wins')} of {b.i(gq, 'MS games')}, close to the "
              f"{b.f(ea, 1, 'ND expected wins')} and {b.f(eq, 1, 'MS expected wins')} that chance predicts, while "
              f"{and_list(names)} took the other {b.i(sum(rest.values()), 'wins by others')}. {Ts(W(n))} win in the "
              f"{b.o(n, 'game number')} game makes it {b.i(wa(n, W(n)), 'wins')} to "
              f"{b.i(wa(n, q if W(n) == a else a), 'wins')}.")
    x0 = max(1, k0 - 7)
    ser = {p: [[k, wa(k, p)] for k in range(x0, n + 1)] for p in (a, q)}
    vals = [v for p in ser for _, v in ser[p]]
    b.set_chart("mini_race", 320, 120, {"x": [x0, n], "y": [min(vals) - 1, max(vals) + 1], "series": ser,
                                        "band": [k0, n],
                                        "others": [k for k in range(k0, n + 1) if W(k) not in (a, q)]}, n)
    return b


# --- 29 ----------------------------------------------------------------------------------------------------
def beat_closest_game(asof):
    n = anchor("2026-11-14-d", "beat closest-game")
    p, q = "nd", "ms"
    b = Beat("closest-game", n, "special", "full")
    nt = nights[night_of[gid_of(n)]]
    ks = list(range(nt["g0"], nt["g0"] + nt["k"]))
    b.need(ks[-1] == n and nt["k"] in WORDS, "the last game of the night")
    big = [x for x in nights[:night_of[gid_of(n)] + 1] if x["k"] >= nt["k"]]
    b.need(len(big) in ORD_WORDS, "an ordinal word for the night")
    mine = [k for k in ks if W(k) == p]
    b.need(len(mine) >= 2 and mine[-1] == n, "ND wins several, including this one")
    before = (wa(ks[0] - 1, p), wa(ks[0] - 1, q))
    after = (wa(n, p), wa(n, q))
    b.need(before[1] > before[0] and after[0] > after[1], "ND turns a deficit into a lead")
    s = story(n)
    b.need(s["ending"] == "reveal", "won by a reveal")
    rv = sum(1 for k in range(1, n + 1) if ending(k) == "reveal" and W(k) == p)
    cl = close_on(n)
    b.need(cl[0][1] == n, "the closest game yet, recomputed over the games so far")
    b.focus = [p]
    b.headline = f"{cap(WORDS[nt['k']])} games in a night, and the closest yet"
    k_rev = s["revealed"]
    rtxt = "a single VP card" if k_rev == 1 else f"{b.i(k_rev, 'stories.revealed')} VP cards"
    b.body = (f"On the group's {ORD_WORDS[len(big)]} {b.i(nt['k'], 'games in the night')}-game night, {T(p)} wins "
              f"{b.i(len(mine), 'ND wins on the night')} of them, games "
              f"{and_list([b.i(k, 'game') for k in mine[:-1]] + ['this one'])}, turning a "
              f"{b.i(before[1] - before[0], 'wins behind before the night')}-win deficit to {T(q)} into a "
              f"{b.i(after[0], 'ND wins')} to {b.i(after[1], 'MS wins')} lead. {T(p)} takes game {b.i(n, 'game')} "
              f"{b.score(n)} by revealing {rtxt}, {Ts(p)} {b.o(rv, 'ND reveal wins so far')} win by reveal. Recomputed "
              f"over the first {b.i(n, 'games so far')} games, it is the closest game the group has played on the site's "
              f"closeness index: {b.f(cl[0][0], 1, 'closeness index, recomputed over games 1 to n')}, against game "
              f"{b.i(cl[1][1], 'the next closest')}'s {b.f(cl[1][0], 1, 'its index on the same scale')}.")
    return b


# --- 30 ----------------------------------------------------------------------------------------------------
def first_to_75(lo, hi, p):
    """First on the board to 2 + 0.75 (target - 2) VP (the site's first_to), with ties split: (first, first_wins)."""
    f = fw = 0.0
    for k in own(p, lo, hi):
        fa = classes.facts(G(k), EV[gid_of(k)])
        ft = fa["first_to"][0.75]
        if not ft:
            continue
        j = fa["seats"].index(p)
        w = ft.get(j, 0.0)
        f += w
        fw += w * (W(k) == p)
    return f, fw


def beat_dh_retakes_the_top(asof):
    n = anchor("2026-11-15-a", "beat dh-retakes-the-top")
    p = "dh"
    b = Beat("dh-retakes-the-top", n, "player", "full")
    s = story(n)
    b.need(W(n) == p and s["deficit"] > 0 and luck(n, p) < 0, "DH wins from behind on bad dice")
    b.need(lb[n][0] == p and lb[n - 1][0] != p, "DH takes back #1")
    rival = elig_at[n][1][0]
    mine = own(p, 1, n)
    split = next(i for i in range(1, len(mine)) if (day(G(mine[i])["date"]) - day(G(mine[i - 1])["date"])).days > 60)
    g1, g2 = mine[:split], mine[split:]
    w1, e1 = sum(W(k) == p for k in g1), exp_wins(p, g1[0], g1[-1])
    w2, e2 = sum(W(k) == p for k in g2), sum(1 / seats_n(k) for k in g2)
    total = sh(p, n)[0]
    jan = w1 - e1
    b.need(len(g1) == len(own(p, g1[0], g1[-1])), "the first block is one stretch")
    months = {day(G(k)["date"]).month for k in g1}
    when = f"in {MONTHS[months.pop() - 1]}" if len(months) == 1 else f"in {Ts(p)} first {b.i(len(g1), 'games')} games"
    lead = ("All of it, and more," if jan > total and w2 - e2 < 0 else "Most of it" if jan >= 0.75 * total else
            "Much of it")
    away = (day(G(g2[0])["date"]) - day(G(g1[-1])["date"])).days

    def city_share(q):
        c = Counter()
        for k in range(1, n + 1):
            if W(k) == q:
                c.update(next(r for r in G(k)["players"] if r["player"] == q)["vp_breakdown"])
        return c["cities"] / sum(c.values()), wa(n, q)
    cs, nw = city_share(p)
    cr, nr = city_share(rival)
    b.need(cs > cr, "DH takes more of the points from cities")
    f, fw = first_to_75(1, n, p)
    b.need(f > 0, "DH has been first to three quarters")
    b.focus = [p]
    b.headline = f"The week that made {Ts(p)} standing"
    b.need((day(G(g1[-1])["date"]) - day(G(g1[0])["date"])).days <= 7, "the first block fits in a week")
    if abs(f - round(f)) < 1e-9 and abs(fw - round(fw)) < 1e-9:
        ftxt = (f"all {b.i(round(f), 'games DH was first to three quarters')}" if round(fw) == round(f) else
                f"{b.i(round(fw), 'of them won')} of the {b.i(round(f), 'games DH was first to three quarters')}")
    else:
        ftxt = None
        warn(b.id, "DH's first-to count is fractional; clause dropped")
    tail = (f", and has won {ftxt} games in which {T(p)} was first on the board to three quarters of the way to the "
            f"target." if ftxt else ".")
    b.body = (f"{T(p)} comes back from {b.i(s['deficit'], 'stories.deficit')} down, on dice "
              f"{b.f(-luck(n, p), 1, 'dice luck, negated')} cards short of expectation, to win {b.score(n)} and take "
              f"back leaderboard #{b.i(1, 'rank')} at {b.sg(total, 'standing_history WAE')}, ahead of {T(rival)} at "
              f"{b.sg(sh(rival, n)[0], 'standing_history WAE')}. {lead} was built {when}: {b.i(w1, 'DH wins, first block')} "
              f"wins in {Ts(p)} first {b.i(len(g1), 'DH games, first block')} games "
              f"({b.f(e1, 2, 'DH expected wins, first block')} expected), against {b.i(w2, 'DH wins since the return')} in "
              f"the {b.i(len(g2), 'DH games since the return')} since {Ts(p)} return "
              f"({b.f(e2, 1, 'DH expected wins since the return')} expected). {T(p)} wins on cities, "
              f"{b.pc(100 * cs, 'cities / all VP in DH wins')} of the points in {Ts(p)} {b.i(nw, 'DH wins')} wins against "
              f"{b.pc(100 * cr, 'cities / all VP in the rival wins')} in {Ts(rival)} {b.i(nr, 'rival wins')}" + tail)
    b.set_chart("dot_row_gap", 320, 44, {
        "pid": p, "groups": [{"games": [{"n": k, "won": W(k) == p} for k in g1], "text": f"{w1} of {len(g1)}"},
                             {"games": [{"n": k, "won": W(k) == p} for k in g2], "text": f"{w2} of {len(g2)}"}],
        "gap": {"after": g1[-1], "before": g2[0], "text": f"{away} days"}}, n)
    return b


# --- 31 ----------------------------------------------------------------------------------------------------
def beat_what_changed(asof):
    n = asof
    b = Beat("what-changed", n, "analysis", "full", closing=True)
    y1 = years_of()[0]
    a = year_games(y1)
    k0 = a[-1] + 1
    later = sorted({G(k)["date"][:4] for k in range(k0, n + 1)})
    y2 = later[0] if len(later) == 1 else f"{later[0]} on"
    lg = n - k0 + 1
    t1, t2 = three_seat(a[0], a[-1]), three_seat(k0, n)
    m1, m2 = mean(G(k)["turns"] for k in t1), mean(G(k)["turns"] for k in t2)
    e1, e2 = endings(a[0], a[-1])["led"], endings(k0, n)["led"]
    lp = anchor("2026-06-05-a", "beat what-changed")   # the first game after the long pause (beat the-long-pause)
    e3 = endings(lp, n)["led"]
    r1, r2 = robber_rate(a[0], a[-1]), robber_rate(k0, n)
    q1, q2 = trade_rate(a[0], a[-1]), trade_rate(k0, n)
    l1, _, _ = luckiest_won(a[0], a[-1])
    l2, _, _ = luckiest_won(k0, n)
    moved = m2 < m1 - 5 and e2 / lg > e1 / len(a) + 0.1
    flat = (abs(r1["rate"] - r2["rate"]) <= 5 and abs(q1["rate"] - q2["rate"]) <= 5
            and abs(l1 / len(a) - l2 / lg) <= 0.1)
    b.need(moved, "turns and leads moved between the years")
    b.headline = "What changed, and what did not"
    habits = "The table's habits stayed put." if flat else "The table's habits moved less."
    if not flat:
        warn(b.id, "a habit moved more than the threshold")
    pause = (f", though since the long pause it is {b.i(e3, 'ending led since the long pause')} of "
             f"{b.i(n - lp + 1, 'games since the long pause')}")
    b.body = (f"Between the {b.i(len(a), 'games in the first year')} games of {b.v(y1, 'year')} and the "
              f"{b.i(lg, 'games since')} of {b.v(y2, 'year')}, two things moved. Three-seat games got shorter, from "
              f"{b.f(m1, 1, 'mean turns, n_seats 3, first year')} turns to {b.f(m2, 1, 'mean turns, n_seats 3, since')}, "
              f"and leads held more often: {b.i(e1, 'ending led, first year')} of {b.i(len(a), 'games')} winners were "
              f"ahead on the board before their final turn in {b.v(y1, 'year')}, and {b.i(e2, 'ending led, since')} of "
              f"{b.i(lg, 'games')} in {b.v(y2, 'year')}{pause}. {habits} The robber touched a leader "
              f"{b.pc(r1['rate'], 'robber on a leader, first year')} and {b.pc(r2['rate'], 'robber on a leader, since')} "
              f"of the time, the sole leader was in {b.pc(q1['rate'], 'trades with the sole leader, first year')} and "
              f"{b.pc(q2['rate'], 'trades with the sole leader, since')} of trades, and the luckiest dice won "
              f"{b.i(l1, 'luckiest won, first year')} of {b.i(len(a), 'games')} and {b.i(l2, 'luckiest won, since')} of "
              f"{b.i(lg, 'games')}.")
    lo_t, hi_t = 20 * math.floor(min(m1, m2) / 20), 20 * math.ceil(max(m1, m2) / 20)
    panels = [
        {"label": "Three-seat turns", "a": round(m1, 1), "b": round(m2, 1), "a_text": fmt_dec(m1, 1),
         "b_text": fmt_dec(m2, 1), "domain": [lo_t, hi_t], "moving": True},
        {"label": "Won from in front", "a": round(100 * e1 / len(a), 1), "b": round(100 * e2 / lg, 1),
         "a_text": fmt_dec(100 * e1 / len(a), 0) + "%", "b_text": fmt_dec(100 * e2 / lg, 0) + "%",
         "domain": [0, 100], "moving": True},
        {"label": "Robber on the leader", "a": round(r1["rate"], 1), "b": round(r2["rate"], 1),
         "a_text": fmt_dec(r1["rate"], 1) + "%", "b_text": fmt_dec(r2["rate"], 1) + "%", "domain": [0, 100],
         "moving": False},
        {"label": "Trades with the leader", "a": round(q1["rate"], 1), "b": round(q2["rate"], 1),
         "a_text": fmt_dec(q1["rate"], 1) + "%", "b_text": fmt_dec(q2["rate"], 1) + "%", "domain": [0, 100],
         "moving": False},
        {"label": "Luckiest dice won", "a": round(100 * l1 / len(a), 1), "b": round(100 * l2 / lg, 1),
         "a_text": fmt_dec(100 * l1 / len(a), 0) + "%", "b_text": fmt_dec(100 * l2 / lg, 0) + "%",
         "domain": [0, 100], "moving": False}]
    b.set_chart("slope_multiples", 320, 120, {"from": y1, "to": y2, "panels": panels}, n)
    return b


# --- 32 ----------------------------------------------------------------------------------------------------
def beat_where_things_stand(asof):
    n = asof
    b = Beat("where-things-stand", n, "standings", "full", closing=True)
    ps = [q for q in registered if own(q, 1, n)]
    fin = sorted(ps, key=lambda q: -sh(q, n)[0])
    ph = [f"{T(q)} at {b.sg(sh(q, n)[0], 'standing_history WAE now')}" for q in fin]
    if len(ph) >= 6:
        txt = (f"from {and_list(ph[:2])}, through {and_list(ph[2:-3])}, to {and_list(ph[-3:])}")
    else:
        txt = f"from {ph[0]} to {and_list(ph[1:])}" if len(ph) > 1 else f"at {ph[0]}"
    outside = [q for q in ps if not (sh(q, n)[1] <= sh(q, n)[0] <= sh(q, n)[2])]
    band_txt = ("Nobody is outside the luck band." if not outside else
                f"{and_list([T(q) for q in outside])} {'is' if len(outside) == 1 else 'are'} outside the luck band.")
    wc = sorted(ps, key=lambda q: (-wa(n, q), registered[q]["initials"]))
    peaks = {}
    for q in ps:
        pts = sorted(band[q].items())
        mx = max(v[0] for _, v in pts)
        at = next(k for k, v in pts if v[0] == mx)
        peaks[q] = (mx, at, mx - sh(q, n)[0])
    fallen = sorted((q for q in ps if peaks[q][2] >= 3), key=lambda q: -peaks[q][2])[:2]
    b.focus = fin
    b.headline = f"Where things stand, as of game {b.i(n, 'the latest game')}"
    tail = ""
    if fallen:
        tail = (" Some lines have travelled a long way to get here: " +
                and_list([f"{T(q)}{' stood' if i == 0 else ''} at {b.sg(peaks[q][0], 'peak WAE')} after game "
                          f"{b.i(peaks[q][1], 'game of the peak')}" for i, q in enumerate(fallen)]) + ".")
    if wa(n, wc[0]) > wa(n, wc[1]):
        most = (f"{T(wc[0])} has the most wins, {b.i(wa(n, wc[0]), 'wins')}, ahead of {T(wc[1])} with "
                f"{b.i(wa(n, wc[1]), 'wins')} and {T(wc[2])} with {b.i(wa(n, wc[2]), 'wins')}.")
    else:
        top = [q for q in wc if wa(n, q) == wa(n, wc[0])]
        most = f"{and_list([T(q) for q in top])} share the most wins, {b.i(wa(n, wc[0]), 'wins')}."
        warn(b.id, "the most wins are shared")
    b.body = f"Wins above expected now runs {txt}. {band_txt} {most}" + tail
    rows = []
    for q in fin:
        pts = sorted(band[q].items())
        lo_v = min(v[0] for _, v in pts)
        rows.append({"pid": q, "points": [[k, round(v[0], 3)] for k, v in pts], "final": round(sh(q, n)[0], 3),
                     "final_text": chart_signed(sh(q, n)[0]),
                     "peak": {"n": peaks[q][1], "v": round(peaks[q][0], 3)},
                     "low": {"n": next(k for k, v in pts if v[0] == lo_v), "v": round(lo_v, 3)}})
    allv = [v for r in rows for _, v in r["points"]]
    b.set_chart("sparklines", 320, 170, {"rows": rows, "domain": [math.floor(min(allv)), math.ceil(max(allv))],
                                         "x_mode": "own_index", "x_max": max(len(r["points"]) for r in rows)}, n)
    return b


LABEL_MODEL = (f"Win chance from today's model, fitted on all {N} games. It counts dev cards in hand but cannot "
               f"see what they are.")

COMPOSERS = [beat_game_1, beat_new_shores, beat_robber_on_the_leader, beat_at_debut, beat_no_trades_with_the_leader,
             beat_ms_first_win, beat_four_in_a_row, beat_the_139_turn_game, beat_ld_top_ms_bottom,
             beat_dice_over_openings, beat_nd_wins_in_the_dark, beat_year_one, beat_a_new_face, beat_nd_passes_jd,
             beat_dh_straight_to_number_one, beat_nd_the_constant, beat_dh_january, beat_the_road_changes_hands,
             beat_back_from_one_percent, beat_leads_that_hold, beat_the_long_pause, beat_six_at_the_table,
             beat_the_mirror, beat_ms_needed_good_dice, beat_ld_drought_ends, beat_six_winners, beat_ms_leads_alone,
             beat_the_duel, beat_closest_game, beat_dh_retakes_the_top, beat_what_changed, beat_where_things_stand]

# A beat whose composer fails (a premise that stopped being true, or data it did not expect) is left out with a
# warning, so one beat never takes the whole History tab down.
built = []
for fn in COMPOSERS:
    try:
        built.append(fn(N))
    except Exception as e:  # noqa: BLE001
        warn(fn.__name__.replace("beat_", "").replace("_", "-"),
             f"left out: {e if isinstance(e, Premise) else type(e).__name__ + ': ' + str(e)}")


def kicker(b):
    if b.closing:
        return f"As of game {b.n} · {d_short(G(b.n)['date'])}"
    if b.span and b.span[0] != b.span[1]:
        return f"Games {b.span[0]} to {b.span[1]} · {d_range(G(b.span[0])['date'], G(b.span[1])['date'])}"
    return f"Game {b.n} · {d_long(G(b.n)['date'])}"


beats_out = []
for b in built:
    beats_out.append({
        "id": b.id, "n": b.n, "game": gid_of(b.n), "u": round(U[b.n], 3), "era": era_of[b.n],
        "span": b.span, "kind": b.kind, "size": b.size, "closing": b.closing,
        "focus": list(dict.fromkeys(b.focus)), "emphasis": b.emphasis,
        "kicker": kicker(b), "headline": b.headline, "body": b.body, "chart": b.chart,
        "vals": b.vals, "src": b.src, "asof_then_ok": b.ok})

# ---------------------------------------------------------------------------------------------------------
# Backbone series
# ---------------------------------------------------------------------------------------------------------
players_out = {}
for pid in registered:
    if played.get(pid):
        pf = PFINAL[pid]
        players_out[pid] = {"initials": registered[pid]["initials"], "color": colors.get(pid), "debut": own(pid)[0],
                            "games": played[pid], "wins": wins.get(pid, 0), "wae": pf["above_expected"],
                            "band": pf["luck_band"]}
race = {pid: [(wa(k, pid) if k >= own(pid)[0] else None) for k in range(1, N + 1)] for pid in players_out}
crowns = {"mw": [mw[k][0] if len(mw[k]) == 1 else mw[k] for k in range(1, N + 1)],
          "mwv": [wa(k, mw[k][0]) for k in range(1, N + 1)],
          "lb": [lb[k][0] for k in range(1, N + 1)], "lbp": [lb[k][1] for k in range(1, N + 1)],
          "lbv": [None if lb[k][2] is None else round(lb[k][2], 3) for k in range(1, N + 1)]}
standing = {pid: [[k, round(v[0], 3), round(v[1][0], 3), round(v[1][1], 3)] for k, v in sorted(band[pid].items())]
            for pid in players_out}
games_out = []
for n in range(1, N + 1):
    g = G(n)
    games_out.append({"id": g["id"], "n": n, "d": g["date"], "era": era_of[n], "u": round(U[n], 3),
                      "gap": gap_before[n], "seats": [ident(p) for p in ppl(n)], "people": len(ppl(n)),
                      "w": ident(W(n)), "score": list(score_of(n)), "map": map_key(g), "turns": g["turns"]})
maps_out = {}
for g in games:
    maps_out.setdefault(map_key(g), map_label(g))
months, seen_m = [], set()
for n in range(1, N + 1):
    ym = G(n)["date"][:7]
    if ym not in seen_m:
        seen_m.add(ym)
        mth = int(ym[5:7])
        months.append({"n": n, "u": round(U[n] - 0.5, 3), "m": MON[mth - 1],
                       "y": int(ym[:4]) if mth == 1 or not months else None})

meta = {
    "as_of": {"id": gid_of(N), "n": N, "d": G(N)["date"]},
    "span": [G(1)["date"], G(N)["date"]], "games": N, "nights": len(nights), "crown_min": CROWN_MIN,
    "axis": {"night_gap_u": NIGHT_GAP_U, "break_days": BREAK_DAYS, "break_u": "1 + 0.5 * log2(days / 7)",
             "total_u": round(TOTAL_U, 2), "short_gaps": short_gaps, "breaks": len(breaks),
             "game_u": "each game is 1 u wide and games[].u is its centre"},
    "pacing": PACE,
    "labels": {"asof": f"As of game {N}", "lb": f"Leaderboard #1 ({CROWN_MIN}-game minimum)", "mw": "Most wins",
               "lb_row": f"LEADERBOARD #1, {CROWN_MIN}-GAME MINIMUM", "mw_row": "MOST WINS",
               "lb_before": f"starts at game {CROWN_MIN}", "model": LABEL_MODEL,
               "kinds": {"milestone": "Milestone", "standings": "Standings", "analysis": "Analysis",
                         "player": "Player", "special": "Special game", "streak": "Streak", "era": "Era"}},
    "site_url": "./#/game/",
}
doc = {"v": 2, "meta": meta, "players": players_out, "maps": maps_out, "eras": eras, "breaks": breaks,
       "months": months, "games": games_out, "race": race, "crowns": crowns, "standing": standing,
       "beats": beats_out}
text = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)


# The scroll budget the page builds (history.html buildTable), estimated at a given stage height.
def pacing_estimate(vh=800):
    hold = {s: vh + 2 * PACE["fade_px"] for s in ("full", "short")}
    segs = []
    for n in range(1, N + 1):
        segs.append((U[n] - 0.5, U[n] + 0.5, PACE["px_game"]))
        if n < N:
            gp = gap_before[n + 1]
            if gp:
                segs.append((U[n] + 0.5, U[n + 1] - 0.5, PACE["px_night"] if gp <= BREAK_DAYS else fold_px(gp)))

    def quiet(u0, u1):
        t = 0.0
        for a, z, px in segs:
            lo, hi = max(a, u0), min(z, u1)
            if hi > lo:
                t += px * (hi - lo) / (z - a)
        return t
    anchors = sorted({b["u"] for b in beats_out})
    groups = [[anchors[0]]]
    for x in anchors[1:]:
        (groups[-1].append(x) if x - groups[-1][-1] < PACE["merge_u"] else groups.append([x]))
    total = quiet(0, TOTAL_U)
    eases, spans = 0, []
    for gr in groups:
        a0, a1 = max(0.0, gr[0] - 1), min(TOTAL_U, gr[-1] + 1)
        total += 2 * PACE["ease_px"] - quiet(a0, gr[0]) - quiet(gr[-1], a1)
        eases += 2
        spans.append((a0, a1))
    holds = sum(hold[b["size"]] for b in beats_out)
    total += holds + PACE["outro_vh"] * vh
    gaps = [quiet(0, spans[0][0])] + [quiet(spans[i][1], spans[i + 1][0]) for i in range(len(spans) - 1)] + \
           [quiet(spans[-1][1], TOTAL_U)]
    return total, holds, eases, max(gaps), (holds + eases * PACE["ease_px"]) / total


# ---------------------------------------------------------------------------------------------------------
# Checks that fail the build
# ---------------------------------------------------------------------------------------------------------
problems = []
DASHES = ((chr(0x2014), "em dash"), (chr(0x2013), "en dash"))
for ch, nm in DASHES:
    if ch in text:
        problems.append(f"{nm} in output")
src_text = pathlib.Path(__file__).read_text(encoding="utf-8")
if any(ch in src_text for ch, _ in DASHES):
    problems.append("dash in scripts/history.py")
names = set()
for p in players_doc["players"]:
    names.update(p.get("aliases") or [])
    if p.get("name"):
        names.add(p["name"])
    names.update(p.get("twosheep_accounts") or [])
low = text.lower()
for nm in sorted(names):
    if re.search(r"(?<![a-z0-9])" + re.escape(nm.lower()) + r"(?![a-z0-9])", low):
        problems.append(f"username or account in output: {nm[:2]}...")
if re.search(r'"bot-|\{bot', text):
    problems.append("computer seat in output")
NUMRE = re.compile(r"\d[\d,.]*%?")


def numbers(s):
    return [m.rstrip(".,") for m in NUMRE.findall(s)]


def strings(x):
    if isinstance(x, str):
        yield x
    elif isinstance(x, dict):
        for v in x.values():
            yield from strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from strings(v)


HIND = re.compile(r"\b(still|since then|has not been|never|only this once|lasted)\b", re.I)
SENT = re.compile(r"(?<=[.?])\s+(?=[A-Z{])")
for b in beats_out:
    for t in re.findall(r"\{([^}]*)\}", " ".join([b["headline"], b["body"], b["kicker"], *strings(b["chart"])])):
        if t not in registered:
            problems.append(f"{b['id']}: unknown token {{{t}}}")
    allowed = {x for v in b["vals"] for x in numbers(v)}
    for part in ("headline", "body"):
        for x in numbers(b[part]):
            if x not in allowed:
                problems.append(f"{b['id']}: number {x} in {part} is not in vals")
    for sent in SENT.split(b["body"]):
        if HIND.search(sent):
            if sent.startswith((f"As of game {N}", f"Looking back from game {N}")):
                continue
            if any(o["text"] in sent for o in b["asof_then_ok"]):
                continue
            problems.append(f"{b['id']}: hindsight word without a frame: {sent}")
    c = b["chart"]
    if c and c["through"] > b["n"] and not c["label"]:
        problems.append(f"{b['id']}: chart uses games past the anchor but has no label")
ns = [b["n"] for b in beats_out]
if ns != sorted(ns):
    problems.append("beats are not in anchor order")
if not 22 <= len(beats_out) <= 32:
    problems.append(f"{len(beats_out)} beats; expected 22 to 32")
if len({b["id"] for b in beats_out}) != len(beats_out):
    problems.append("duplicate beat ids")
for gid, rc in recaps.items():
    r = (rc or {}).get("recap") or ""
    if len(r) > 30 and r[:60] in text:
        problems.append(f"stored recap for {gid} in output")
for pid in players_out:
    if is_bot(pid) or is_guest(pid):
        problems.append(f"{pid} listed as a player")
# The pacing limits were set for the story at game 102. Every new game lengthens the track, and games after the
# last written beat make a quiet stretch at the end, so going over them is a warning (time to tune PACE or write
# a beat), never a reason to stop the History tab updating.
_t, _h, _e, _q, _s = pacing_estimate(800)
if (_t + 800) / 800 > 50:
    warn("pacing", f"track {(_t + 800) / 800:.1f} stage heights at an 800 px stage, over the 50 it was designed for")
if _q > 2 * 800:
    warn("pacing", f"a quiet stretch of {_q:.0f} px is longer than 2 stage heights; a new beat would break it up")
if problems:
    print("\n".join(problems))
    sys.exit(1)

ARGS.out.parent.mkdir(parents=True, exist_ok=True)
ARGS.out.write_text(
    "// Generated by scripts/history.py from the data. Do not edit by hand.\nwindow.HISTORY = " + text + ";\n",
    encoding="utf-8")


# ---------------------------------------------------------------------------------------------------------
# Summary, with the pacing estimate at an 800 px stage
# ---------------------------------------------------------------------------------------------------------
print(f"history: {len(beats_out)} beats through game {N} ({G(N)['date']})" +
      (f", {len(WARN)} warning(s)" if WARN else ""))
ini = lambda p: registered[p]["initials"] if p in registered else p  # noqa: E731
print(f"wrote {ARGS.out}: {ARGS.out.stat().st_size:,} bytes (v 2)")
print(f"games {N} ({G(1)['date']} to {G(N)['date']}), nights {len(nights)}, axis {TOTAL_U:.1f} u "
      f"({short_gaps} short night gaps, {len(breaks)} folded breaks)")
print("eras: " + "; ".join(f"{e['name']} {e['from']} to {e['to']}" for e in eras))
spells = lb_spells()
print("leaderboard spells: " + ", ".join(f"{ini(p) if p else '-'} {a} to {c}" for p, a, c in spells))
tot, holds, eases, worst_gap, share = pacing_estimate(800)
print(f"pacing at an 800 px stage: scroll budget about {tot:,.0f} px = {tot / 800:.1f} stage heights (the track "
      f"element adds one stage: {(tot + 800) / 800:.1f}); holds {holds:,.0f} px, {eases} eases; holds and eases "
      f"{100 * share:.0f}% of it; longest quiet stretch {worst_gap:,.0f} px ({worst_gap / 800:.2f} stage heights)")
kinds = Counter(b["kind"] for b in beats_out)
charts = [b["chart"]["type"] for b in beats_out if b["chart"]]
print(f"beats {len(beats_out)}: {dict(kinds)}; charts {len(charts)} of {len(beats_out)}, {len(set(charts))} types")
for b in beats_out:
    c = b["chart"]
    print(f"  {b['n']:>3} {b['id']:<28} {b['kind']:<9} {b['size']:<5} "
          f"{(c['type'] + (' (label)' if c['label'] else '')) if c else '-'}")
    if ARGS.v:
        print(f"      {b['kicker']} | {b['headline']}")
        print(f"      {b['body']}")
print("warnings: " + ("none" if not WARN else ""))
for w_ in WARN:
    print("history: warning: " + w_)
print("checks passed: no dashes, no usernames, no computer seats, tokens registered, every number in vals, "
      "hindsight framed, chart labels, beat order, no stored recap")
