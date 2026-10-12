"""Threat index: who looks most dangerous from what the table can see, and three badges built on it.

Reads data/replay_events.json (decoder v3: per-seat reach in the state rows). Seats in the logs are 1-based;
ev["seats"][s - 1] is the player id in seat s. Guests and bots are seats like anyone else (they can be the
threat, and they count as alternatives), but never get a row.

Public features per seat, at every state row (after each roll and at each turn end):
    board_vp     VP minus VP cards still held
    income       expected cards per roll from the dice, robber hex excluded (sum_k dots(k) (gross - blocked)_k / 36)
    reach        pips over the legal settlement corners within 2 new roads or ships (decoder field)
    dev_held     dev cards in hand (bought minus played; VP cards stay in hand), a public count
    hand         resource cards in hand
    road_close   4 - min(4, segments short of Longest Road): need 5, or one more than the holder; holder 4
    army_close   3 - min(3, knights short of Largest Army): need 3, or one more than the holder; holder 3

Fitted index (compute_all, all games once). One stratum per turn end (end_turn rows; the winning turn has
none), the alternatives are the seats and the chosen one is the eventual winner: a conditional logit,
P(i wins | state) = exp(x_i b) / sum_j exp(x_j b). Features are divided by their pooled within-state SD,
so b is per SD. Strata from one game are dependent, so intervals use the game-cluster sandwich
V = I^-1 (sum_g U_g U_g') I^-1 (U_g = the game's summed scores at the estimate). Equal-weights check: the
sum of within-state z-scores, x one fitted scale. Both are cross-fitted over 5 folds of games, and every
probability used below is the out-of-fold one, so no game is scored by a model that saw its own winner.
The check compares out-of-fold log loss and accuracy (top threat = eventual winner) of the two versions
and of chance (1/n), overall and by thirds of the game.

The top threat in a state is the seat with the highest fitted probability. For an event (trade, robber
move) the state is the latest row at or before the event: the roll row of that turn.

Per view, per regular with enough games:
    top          turn ends as the top threat, against chance (sum of 1/n), O/E with a game bootstrap interval
    rank         average threat rank (1 = top) against chance ((n + 1) / 2)
    hidden       wins where someone else was the top threat at the last turn end before the win
    tyrant       trading with the tyrant, O/E. Ex ante: the tyrant is the top threat after that turn's roll.
                 Hindsight: the tyrant is the eventual winner, each trade weighted by (roll index + 1) / rolls.
                 Conditioned on the roller: on the player's own turn the partner could be any of n - 1
                 opponents (E += w / (n - 1)); on someone else's turn the partner is the roller, so E spreads
                 the player's off-turn trades over the other players' turns (weighted the same way) and
                 counts the share that were the tyrant's. Turns where the player is the tyrant (ex ante) and
                 games the player won (hindsight) are left out.
    coward       robber moves that spare the top threat among the mover's opponents, O/E (1 = as often as a
                 player who ignores who is winning), and that O/E divided by everyone else's at the same tables
                 (the badge: above 1 means sparing the threat more than the table does). Two decisions per
                 land move: the hex (when some legal hex touches the threat, dodging = the chosen hex does
                 not; E = the probability of a hex that does not, under a hex-choice model that ignores who
                 is winning: opponents' pips on the hex, own pips, opponents to steal from; fit leaving the
                 mover's own moves out) and the victim (when the threat and someone else were both eligible,
                 dodging = robbing someone else; E = 1 - 1 / eligible).
    groveler     cards given minus cards received in player trades with the current top threat, minus the
                 rest of the table's average in the same role (roller or partner), per trade.
"""

from __future__ import annotations

import math
from collections import defaultdict

import series
import statlib

KEY = "threat"
FEATS = ["board_vp", "income", "reach", "dev_held", "hand", "road_close", "army_close"]
LABELS = {
    "board_vp": "Board VP (per SD)",
    "income": "Dice income (per SD)",
    "reach": "Reach: open spots within 2 roads (per SD)",
    "dev_held": "Dev cards in hand (per SD)",
    "hand": "Resource cards in hand (per SD)",
    "road_close": "Closeness to Longest Road (per SD)",
    "army_close": "Closeness to Largest Army (per SD)",
}
ROAD_CAP, ARMY_CAP = 4, 3
FOLDS = 5
LEVEL = statlib.LEVEL
G = statlib.GUARDS
MIN_TRADES = 10  # trades with the top threat before a player gets a Groveler row
MIN_DECISIONS = 10  # robber decisions involving the top threat before a Coward row

_STATE = {}  # per-game rows from compute_all, reused by compute_view (never written to stats.json)


def r3(x):
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(x, 3)


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------

def dev_counts(ev):
    """Sorted (action_index, seat, held delta, knight delta) from dev_events."""
    out = []
    for d in ev.get("dev_events") or []:
        if d["action"] == "buy":
            out.append((d["action_index"], d["seat"], 1, 0))
        elif d["action"] == "play":
            out.append((d["action_index"], d["seat"], -1, 1 if d["card"] == "knight" else 0))
    return sorted(out)


def closeness(values, holder, minimum, cap):
    """cap - min(cap, short of the title): need `minimum`, or one more than the holder; the holder gets cap."""
    need = minimum if holder is None else values[holder - 1] + 1
    return [cap if holder == i + 1 else cap - min(cap, max(0, need - v)) for i, v in enumerate(values)]


def state_rows(ev):
    """Every state row as {action_index, roll_index, kind, actor, X (per seat feature list)}."""
    n = len(ev["seats"])
    devs, k = dev_counts(ev), 0
    held, knights = [0] * n, [0] * n
    out = []
    for row in series.full_rows(ev):
        while k < len(devs) and devs[k][0] <= row["action_index"]:
            _, s, dh, dk = devs[k]
            held[s - 1] += dh
            knights[s - 1] += dk
            k += 1
        vp = series.board_vp(row)
        road = closeness(row["road_length"], row["longest_road"], 5, ROAD_CAP)
        army = closeness(knights, row["largest_army"], 3, ARMY_CAP)
        X = [[vp[i], series.expected_cards(row, i), row.get("reach", [0] * n)[i], held[i],
              row["hand"][i], road[i], army[i]] for i in range(n)]
        out.append({"action_index": row["action_index"], "roll_index": row["roll_index"], "kind": row["kind"],
                    "actor": row["actor"], "X": X})
    return out


def game_data(games, events):
    """Per game with v3 state rows: seats, winner seat index, rows, and the turn-end rows the model uses."""
    out = []
    for g in games:
        ev = events.get(g["id"])
        if not ev or not ev.get("states") or "reach" not in ev["states"][0] or g["winner"] not in ev["seats"]:
            continue
        rows = state_rows(ev)
        out.append({"game": g["id"], "seats": ev["seats"], "n": len(ev["seats"]), "win": ev["seats"].index(g["winner"]),
                    "rows": rows, "ends": [r for r in rows if r["kind"] == "end_turn"], "ev": ev,
                    "rolls": len(ev["roll_log"])})
    return out


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def feature_scale(data):
    """Pooled within-state SD of each feature over the turn ends (1 when a feature never varies)."""
    k = len(FEATS)
    ss, df = [0.0] * k, 0
    for d in data:
        for r in d["ends"]:
            for f in range(k):
                col = [x[f] for x in r["X"]]
                m = sum(col) / len(col)
                ss[f] += sum((v - m) ** 2 for v in col)
            df += d["n"] - 1
    return [math.sqrt(s / df) if df and s > 0 else 1.0 for s in ss]


def z_sum(X):
    """Equal weights: sum over features of the within-state z-score (population SD; 0 when constant)."""
    n, k = len(X), len(X[0])
    out = [0.0] * n
    for f in range(k):
        col = [x[f] for x in X]
        m = sum(col) / n
        sd = math.sqrt(sum((v - m) ** 2 for v in col) / n)
        if sd > 0:
            for i in range(n):
                out[i] += (col[i] - m) / sd
    return out


def fitted_strata(data, scale):
    return [{"X": [[x[f] / scale[f] for f in range(len(FEATS))] for x in r["X"]],
             "y": [1 if i == d["win"] else 0 for i in range(d["n"])], "game": d["game"]}
            for d in data for r in d["ends"]]


def equal_strata(data):
    return [{"X": [[z] for z in z_sum(r["X"])], "y": [1 if i == d["win"] else 0 for i in range(d["n"])],
             "game": d["game"]} for d in data for r in d["ends"]]


def softmax(eta):
    m = max(eta)
    e = [math.exp(v - m) for v in eta]
    s = sum(e)
    return [v / s for v in e]


def probs(X, beta):
    return softmax([sum(b * v for b, v in zip(beta, x)) for x in X])


def cluster_cov(strata, fit):
    """Game-cluster sandwich covariance for a conditional logit with one chosen alternative per stratum."""
    k = len(fit["beta"])
    U = defaultdict(lambda: [0.0] * k)
    for s in strata:
        p = probs(s["X"], fit["beta"])
        y = s["y"].index(1)
        u = U[s["game"]]
        for f in range(k):
            u[f] += s["X"][y][f] - sum(p[i] * s["X"][i][f] for i in range(len(p)))
    M = [[sum(u[a] * u[b] for u in U.values()) for b in range(k)] for a in range(k)]
    C = fit["cov"]
    CM = [[sum(C[a][c] * M[c][b] for c in range(k)) for b in range(k)] for a in range(k)]
    return [[sum(CM[a][c] * C[c][b] for c in range(k)) for b in range(k)] for a in range(k)]


def fit_model(data):
    scale = feature_scale(data)
    st = fitted_strata(data, scale)
    fit = statlib.cond_logit([{"X": s["X"], "y": s["y"]} for s in st], firth=False)
    V = cluster_cov(st, fit)
    z = statlib.z_for(LEVEL)
    se = [math.sqrt(V[f][f]) if V[f][f] > 0 else None for f in range(len(FEATS))]
    eq = statlib.cond_logit([{"X": s["X"], "y": s["y"]} for s in equal_strata(data)], firth=False)
    return {"scale": scale, "beta": fit["beta"], "se": se,
            "ci": [[b - z * e, b + z * e] if e else None for b, e in zip(fit["beta"], se)],
            "gamma": eq["beta"][0], "games": len(data), "states": len(st)}


def fold_of(i):
    return i % FOLDS


def cross_fit(data):
    """Out-of-fold models: fold f is scored by the model fit on the other folds (games in id order)."""
    order = sorted(range(len(data)), key=lambda i: data[i]["game"])
    fold = {data[i]["game"]: fold_of(j) for j, i in enumerate(order)}
    models = {}
    for f in range(FOLDS):
        train = [d for d in data if fold[d["game"]] != f]
        if len(train) < 2:
            continue
        models[f] = fit_model(train)
    return fold, models


def score_rows(d, model):
    """Attach out-of-fold fitted and equal-weights probabilities, the top threat and ranks to every row."""
    beta, scale, gamma = model["beta"], model["scale"], model["gamma"]
    for r in d["rows"]:
        X = [[x[f] / scale[f] for f in range(len(FEATS))] for x in r["X"]]
        p = probs(X, beta)
        q = softmax([gamma * z for z in z_sum(r["X"])])
        order = sorted(range(d["n"]), key=lambda i: -p[i])
        r["p"], r["p_equal"] = p, q
        r["top"] = order[0]
        r["top_equal"] = max(range(d["n"]), key=lambda i: q[i])
        r["rank"] = [0] * d["n"]
        for k, i in enumerate(order):
            r["rank"][i] = k + 1


def check(data):
    """Out-of-fold log loss and accuracy at turn ends, fitted vs equal weights vs chance, overall and by
    thirds of the game (turn end's roll index over the game's rolls), with game-bootstrap intervals for the
    log loss differences."""
    def summary(rows):
        n = len(rows)
        if not n:
            return None
        return {"states": n,
                "logloss": r3(sum(-math.log(max(r[0], 1e-12)) for r in rows) / n),
                "logloss_equal": r3(sum(-math.log(max(r[1], 1e-12)) for r in rows) / n),
                "logloss_chance": r3(sum(math.log(r[2]) for r in rows) / n),
                "acc": r3(sum(r[3] for r in rows) / n), "acc_equal": r3(sum(r[4] for r in rows) / n),
                "acc_chance": r3(sum(1 / r[2] for r in rows) / n), "agree": r3(sum(r[5] for r in rows) / n)}
    per_game, thirds = [], [[], [], []]
    for d in data:
        rows = []
        for r in d["ends"]:
            t = min(2, int(3 * (r["roll_index"] + 1) / (d["rolls"] + 1)))
            row = (r["p"][d["win"]], r["p_equal"][d["win"]], d["n"], r["top"] == d["win"],
                   r["top_equal"] == d["win"], r["top"] == r["top_equal"])
            rows.append(row)
            thirds[t].append(row)
        per_game.append(rows)
    flat = [r for g in per_game for r in g]

    def diff(sample):
        rows = [r for g in sample for r in g]
        # log loss of equal weights minus log loss of the fitted model (above 0: fitted calls the winner better)
        return sum(math.log(max(r[0], 1e-12)) - math.log(max(r[1], 1e-12)) for r in rows) / len(rows) if rows else None
    boots = [b for b in statlib.cluster_bootstrap(per_game, diff, B=statlib.B_DESCRIPTIVE, seed=11) if b is not None]
    a = (1 - LEVEL) / 2
    out = summary(flat)
    out["equal_minus_fitted"] = {"est": r3(diff(per_game)), "lo": r3(statlib.quantile(boots, a)),
                                 "hi": r3(statlib.quantile(boots, 1 - a))}
    out["thirds"] = [summary(t) for t in thirds]
    return out


# ---------------------------------------------------------------------------
# Per-game derived events
# ---------------------------------------------------------------------------

def row_at(d, action_index):
    """The latest state row at or before an action (None before the first roll)."""
    best = None
    for r in d["rows"]:
        if r["action_index"] <= action_index:
            best = r
        else:
            break
    return best


def top_among(r, exclude):
    """Seat index with the highest fitted probability among everyone but `exclude`."""
    return max((i for i in range(len(r["p"])) if i != exclude), key=lambda i: r["p"][i])


def turn_rows(d):
    """Per roll index, the roll row (start of that turn's trading)."""
    out = {}
    for r in d["rows"]:
        if r["kind"] == "roll":
            out[r["roll_index"]] = r
    return out


def trades(d):
    """Player trades as {roll, seat, partner (0-based), given, received (seat's side), top}."""
    out = []
    turns = turn_rows(d)
    for t in d["ev"].get("trade_events") or []:
        if t["partner"] is None:
            continue
        r = turns.get(t["roll_index"]) or row_at(d, t["action_index"])
        if r is None:
            continue
        out.append({"roll": t["roll_index"], "seat": t["seat"] - 1, "partner": t["partner"] - 1,
                    "given": sum(t["give"]), "received": sum(t["get"]), "top": r["top"]})
    return out


ROB_FEATS = ["opp_pips", "own_pips", "n_steal"]


def robber_moves(d):
    """Land robber moves with a known pre-move state: candidate features for the baseline model, which
    candidates touch the top threat, the chosen candidate, and the victim decision."""
    out = []
    for e in d["ev"].get("robber_events") or []:
        if e["pirate"] or not e.get("candidates"):
            continue
        r = row_at(d, e["action_index"] - 1)
        if r is None:
            continue
        mover = e["mover"] - 1
        tau = top_among(r, mover)
        X, touch, chosen = [], [], None
        for c in e["candidates"]:
            m = c["m"]
            opp = sum(m[j] for j in range(len(m)) if j != mover)
            n_steal = sum(1 for j in range(len(m)) if j != mover and m[j] > 0 and e["hand"][j] > 0)
            X.append([c["dots"] * opp, c["dots"] * m[mover], n_steal])
            touch.append(m[tau] > 0)
            if c["hex"] == e["hex"]:
                chosen = len(X) - 1
        if chosen is None:
            continue
        elig = [s - 1 for s in e.get("eligible") or []]
        out.append({"mover": mover, "tau": tau, "X": X, "touch": touch, "chosen": chosen,
                    "eligible": elig, "victim": e["victim"] - 1 if e.get("victim") else None})
    return out


def robber_baseline(data, ctx):
    """P(each candidate hex) from a hex-choice logit on ROB_FEATS, fit leaving the mover out: one refit per
    regular, and one for all guest and bot moves together. Stored on each move as "p_hex"."""
    groups = defaultdict(list)
    for d in data:
        for mv in d["moves"]:
            pid = d["seats"][mv["mover"]]
            groups["anon" if ctx["is_anon"](pid) else pid].append(mv)
    for key, mine in groups.items():
        train = [{"X": mv["X"], "y": [1 if i == mv["chosen"] else 0 for i in range(len(mv["X"]))]}
                 for k2, moves in groups.items() if k2 != key for mv in moves if len(mv["X"]) > 1]
        beta = statlib.cond_logit(train, firth=True)["beta"] if len(train) >= 30 else [0.0] * len(ROB_FEATS)
        for mv in mine:
            mv["p_hex"] = probs(mv["X"], beta)


# ---------------------------------------------------------------------------
# Per-player statistics for a set of games
# ---------------------------------------------------------------------------

def ratio_interval(units, B, seed):
    """O/E over units [(O, E)] and a game-bootstrap percentile interval."""
    O = sum(u[0] for u in units)
    E = sum(u[1] for u in units)
    if E <= 0:
        return None
    boots = []
    for s in statlib.cluster_bootstrap(units, lambda xs: (sum(x[0] for x in xs), sum(x[1] for x in xs)), B=B, seed=seed):
        if s[1] > 0:
            boots.append(s[0] / s[1])
    a = (1 - LEVEL) / 2
    lo, hi = statlib.quantile(boots, a), statlib.quantile(boots, 1 - a)
    return {"O": r3(O), "E": r3(E), "ratio": r3(O / E), "lo": r3(lo), "hi": r3(hi), "games": len(units),
            "clear": lo > 1 or hi < 1}


def mean_interval(units, B, seed):
    """Mean per item over units [list of values per game] and a game-bootstrap interval."""
    flat = [v for u in units for v in u]
    if not flat:
        return None
    boots = []
    for s in statlib.cluster_bootstrap(units, lambda xs: [v for u in xs for v in u], B=B, seed=seed):
        if s:
            boots.append(sum(s) / len(s))
    a = (1 - LEVEL) / 2
    lo, hi = statlib.quantile(boots, a), statlib.quantile(boots, 1 - a)
    return {"est": r3(sum(flat) / len(flat)), "lo": r3(lo), "hi": r3(hi), "n": len(flat),
            "games": sum(1 for u in units if u), "clear": lo > 0 or hi < 0}


def relative_interval(units, B, seed):
    """(O/E for the player) / (O/E for everyone else at the same tables), over units [(O, E, O_rest, E_rest)]
    per game, with a game-bootstrap percentile interval. clear: the interval excludes 1."""
    def rel(xs):
        O, E, Or, Er = (sum(x[k] for x in xs) for k in range(4))
        return (O / E) / (Or / Er) if E > 0 and Er > 0 and Or > 0 else None
    est = rel(units)
    if est is None:
        return None
    boots = [b for b in statlib.cluster_bootstrap(units, rel, B=B, seed=seed) if b is not None]
    a = (1 - LEVEL) / 2
    lo, hi = statlib.quantile(boots, a), statlib.quantile(boots, 1 - a)
    Or, Er = sum(u[2] for u in units), sum(u[3] for u in units)
    return {"ratio": r3(est), "lo": r3(lo), "hi": r3(hi), "rest": r3(Or / Er), "clear": lo > 1 or hi < 1}


def tyrant_units(d, i, hindsight):
    """(O, E) for seat i in one game (see the module docstring), or None if nothing counts."""
    turns = turn_rows(d)
    T = max(1, d["rolls"])
    if hindsight and i == d["win"]:
        return None

    def tyrant(roll):
        if hindsight:
            return d["win"]
        r = turns.get(roll)
        return None if r is None else r["top"]

    def weight(roll):
        return (roll + 1) / T if hindsight else 1.0
    num = den = 0.0  # exposure on other players' turns
    for roll, r in turns.items():
        roller, tau = r["actor"] - 1, tyrant(roll)
        if roller == i or tau is None or tau == i:
            continue
        den += weight(roll)
        num += weight(roll) * (roller == tau)
    O = E = 0.0
    for t in d["trades"]:
        if i not in (t["seat"], t["partner"]):
            continue
        tau = tyrant(t["roll"])
        if tau is None or tau == i:
            continue
        w = weight(t["roll"])
        other = t["partner"] if t["seat"] == i else t["seat"]
        O += w * (other == tau)
        if t["seat"] == i:
            E += w / (d["n"] - 1)
        elif den > 0:
            E += w * num / den
    return (O, E) if E > 0 or O > 0 else None


def grovel_items(d, i, base):
    """Per trade of seat i with the current top threat: given minus received, minus the table's role mean."""
    out = []
    for t in d["trades"]:
        tau = t["top"]
        if tau == i or i not in (t["seat"], t["partner"]) or tau not in (t["seat"], t["partner"]):
            continue
        roller = t["seat"] == i
        net = (t["given"] - t["received"]) if roller else (t["received"] - t["given"])
        out.append(net - base[roller])
    return out


def grovel_base(data, pid):
    """The rest of the table's mean net cards given in trades with the top threat, by role (roller True)."""
    acc = {True: [0.0, 0], False: [0.0, 0]}
    for d in data:
        for t in d["trades"]:
            tau = t["top"]
            for j, roller in ((t["seat"], True), (t["partner"], False)):
                other = t["partner"] if roller else t["seat"]
                if other != tau or d["seats"][j] == pid:
                    continue
                net = (t["given"] - t["received"]) if roller else (t["received"] - t["given"])
                acc[roller][0] += net
                acc[roller][1] += 1
    return {k: (s / n if n else 0.0) for k, (s, n) in acc.items()}


def coward_units(d, i):
    """(O, E, hex decisions, victim decisions) for seat i's robber moves in one game."""
    O = E = 0.0
    nh = nv = 0
    for mv in d["moves"]:
        if mv["mover"] != i:
            continue
        if any(mv["touch"]) and not all(mv["touch"]):
            nh += 1
            O += 0 if mv["touch"][mv["chosen"]] else 1
            E += sum(p for p, t in zip(mv["p_hex"], mv["touch"]) if not t)
        if mv["victim"] is not None and mv["tau"] in mv["eligible"] and len(mv["eligible"]) >= 2:
            nv += 1
            O += 1 if mv["victim"] != mv["tau"] else 0
            E += 1 - 1 / len(mv["eligible"])
    return O, E, nh, nv


def players_stats(data, ctx):
    B = 200 if ctx.get("fast") else statlib.B_DESCRIPTIVE
    out = {}
    for j, pid in enumerate(ctx["pids"]):
        if ctx["is_anon"](pid):
            continue
        mine = [(d, d["seats"].index(pid)) for d in data if pid in d["seats"]]
        if len(mine) < G["player_rows"]:
            continue
        top_units, ranks, exp_ranks = [], [], []
        wins = hidden = 0
        for d, i in mine:
            O = sum(1 for r in d["ends"] if r["top"] == i)
            E = len(d["ends"]) / d["n"]
            top_units.append((O, E))
            ranks += [r["rank"][i] for r in d["ends"]]
            exp_ranks += [(d["n"] + 1) / 2] * len(d["ends"])
            if d["win"] == i:
                wins += 1
                if d["ends"] and d["ends"][-1]["top"] != i:
                    hidden += 1
        row = {"games": len(mine), "top": ratio_interval(top_units, B, seed=300 + j),
               "rank": r3(sum(ranks) / len(ranks)) if ranks else None,
               "rank_chance": r3(sum(exp_ranks) / len(exp_ranks)) if exp_ranks else None,
               "wins": wins, "hidden_wins": hidden}
        for key, hind in (("tyrant_ante", False), ("tyrant_hind", True)):
            units = [u for d, i in mine for u in [tyrant_units(d, i, hind)] if u]
            row[key] = ratio_interval(units, B, seed=400 + j + (50 if hind else 0)) if units else None
        cw = [coward_units(d, i) for d, i in mine]
        dec = sum(c[2] + c[3] for c in cw)
        row["coward"] = ratio_interval([(c[0], c[1]) for c in cw if c[2] or c[3]], B, seed=500 + j) \
            if dec >= MIN_DECISIONS else None
        if row["coward"]:
            rest = [[coward_units(d, k) for k in range(d["n"]) if k != i] for d, i in mine]
            units = [(c[0], c[1], sum(x[0] for x in r), sum(x[1] for x in r)) for c, r in zip(cw, rest)]
            row["coward"].update({"hex_decisions": sum(c[2] for c in cw), "victim_decisions": sum(c[3] for c in cw),
                                  "vs_table": relative_interval(units, B, seed=550 + j)})
        base = grovel_base(data, pid)
        items = [grovel_items(d, i, base) for d, i in mine]
        n_items = sum(len(x) for x in items)
        row["groveler"] = mean_interval(items, B, seed=600 + j) if n_items >= MIN_TRADES else None
        if row["groveler"]:
            row["groveler"]["table_roller"], row["groveler"]["table_partner"] = r3(base[True]), r3(base[False])
        out[pid] = row
    return out


def hidden_summary(data):
    """How often the top threat at the last turn end before the win went on to win, against the model's own
    probability for them (calibration) and chance."""
    games = [d for d in data if d["ends"]]
    if not games:
        return None
    won = sum(1 for d in games if d["ends"][-1]["top"] == d["win"])
    return {"games": len(games), "top_won": won,
            "expected": r3(sum(d["ends"][-1]["p"][d["ends"][-1]["top"]] for d in games)),
            "chance": r3(sum(1 / d["n"] for d in games))}


def timelines(data):
    """Per game: roll index and each seat's out-of-fold win probability at every turn end (game page chart)."""
    return {d["game"]: {"seats": d["seats"], "turn": [r["roll_index"] + 1 for r in d["ends"]],
                        "p": [[round(r["p"][i], 3) for r in d["ends"]] for i in range(d["n"])],
                        "top": [r["top"] for r in d["ends"]]}
            for d in data}


# ---------------------------------------------------------------------------
# Module entry points (see build.MODULES)
# ---------------------------------------------------------------------------

def prepare(games, events, ctx):
    data = game_data(games, events)
    if len(data) < G["model_games"]:
        return data, None, None
    full = fit_model(data)
    fold, models = cross_fit(data)
    for d in data:
        score_rows(d, models.get(fold[d["game"]], full))
        d["trades"] = trades(d)
        d["moves"] = robber_moves(d)
    robber_baseline(data, ctx)
    return data, full, check(data)


def compute_all(games, replays, events, ctx):
    data, full, chk = prepare(games, events, ctx)
    _STATE.clear()
    _STATE.update({d["game"]: d for d in data})
    if full is None:
        return {"model": None, "games": len(data)}
    model = {"feats": FEATS, "labels": LABELS, "games": full["games"], "states": full["states"], "level": LEVEL,
             "beta": [r3(b) for b in full["beta"]], "se": [r3(s) for s in full["se"]],
             "ci": [[r3(c[0]), r3(c[1])] if c else None for c in full["ci"]],
             "scale": [r3(s) for s in full["scale"]], "gamma": r3(full["gamma"]), "check": chk}
    return {"model": model, "games": len(data), "timelines": timelines(data)}


def compute_view(games, replays, events, ctx, all_result):
    data = [_STATE[g["id"]] for g in games if g["id"] in _STATE]
    if all_result.get("model") is None:
        return {"games": len(data), "players": {}}
    return {"games": len(data), "players": players_stats(data, ctx), "hidden": hidden_summary(data)}
