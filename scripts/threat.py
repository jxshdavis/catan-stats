"""Threat index: who looks most dangerous from what the table can see, and three badges built on it.

Reads data/replay_events.json (decoder v4: per-seat reach, ports and income by resource in the state rows). Seats in the logs are 1-based;
ev["seats"][s - 1] is the player id in seat s. Guests and bots are seats like anyone else (they can be the
threat, and they count as alternatives), but never get a row.

Public features per seat, at every state row (after each roll and at each turn end):
    board_vp      VP minus VP cards still held
    income        expected cards per roll from the dice on the five resources, robber hex excluded
                  (dots under the seat's buildings / 36; a city counts twice)
    income_gold   the same, from gold hexes only (each card is a free pick, so it is its own sign)
    reach         pips over the legal settlement corners within 2 new roads or ships, gold hexes left out
    reach_gold    the gold pips on those corners
    reach_island  the island bonus (VP) the seat would get for its next new island, when one of those
                  corners is on an island that would earn it; else 0
    reach_port    port types the seat does not have yet with a port corner among those corners
    port_31       1 with a building on a 3:1 port
    port_21       income per roll in the resources the seat holds a 2:1 port for (a 2:1 port is worth
                  as much as the seat produces of that resource)
    dev_held      dev cards in hand (bought minus played; VP cards stay in hand), a public count
    hand          resource cards in hand
    road_close    4 - min(4, segments short of Longest Road): need 5, or one more than the holder; holder 4
    army_close    3 - min(3, knights short of Largest Army): need 3, or one more than the holder; holder 3

Stage: how far the game has gone, from what the table can see: the leader's board VP over the game's VP
target, capped at 1 (stage_of). Each feature's weight moves in a straight line with it:
    weight_f(stage) = main_f + shift_f (stage - 0.5)
so main_f is the weight at half the target, and the site reports the weights at stages 0.2, 0.5 and 0.8.

Fitted index (compute_all, all games once). One stratum per turn end (end_turn rows; the winning turn has
none), the alternatives are the seats and the chosen one is the eventual winner: a conditional logit,
P(i wins | state) = exp(x_i b) / sum_j exp(x_j b), with x_i = [z_i, z_i (stage - 0.5)] and z the features
divided by their pooled within-state SD (so weights are per SD). The fit is ridge-penalized: it maximizes
l(b) - 0.5 RIDGE_MAIN sum main_f^2 - 0.5 RIDGE_STAGE sum shift_f^2, so a weight, or a change in a weight,
only moves away from 0 when the games clearly back it up. Strata from one game are dependent, so intervals
use the game-cluster sandwich V = H^-1 (sum_g u_g u_g') H^-1, with H = I + diag(ridge) and u_g the game's
summed scores at the estimate, centred over games (the penalty's gradient spread evenly over the games;
without a penalty the scores already sum to 0). They describe the sampling spread of the penalized weights,
which are pulled toward 0 on purpose. Equal-weights check: the sum of within-state z-scores, x one fitted
scale. Both are cross-fitted over 5 folds of games, and every probability used below is the out-of-fold one,
so no game is scored by a model that saw its own winner. The check compares out-of-fold log loss and accuracy
(top threat = eventual winner) of the two versions and of chance (1/n), overall and by thirds of the game.

How the stage model was chosen (2026-11-26, 107 games). The earlier test (2026-11-15, 101 games) let every
weight move linearly with stage, or fit early and late halves separately, without a penalty, and both lost
to constant weights out of fold (1.047 and 1.048 against 1.038). With 26 weights and about 107 winners the
unpenalized shifts are mostly noise. With the ridge penalty, chosen by inner 5-fold CV inside each outer
training set (nested, so the outer folds never touched the choice), the stage model scored 1.031 against
1.044 for constant unpenalized weights: a gain of 0.014, game-bootstrap 95% -0.007 to 0.036, better in 52
of 107 games, the gain mostly in the first third of games and in 4+ player Seafarers games. It fixes the
constant model's overconfidence early on (calibration slope by thirds 0.72 / 0.82 / 0.98 for constant
weights, 0.97 / 0.97 / 1.18 for the stage model, 1 = calibrated) but is too cautious late. The penalties are
fixed at the centre of the flat region of a plain 5-fold CV over all 107 games (main 300 to 700 and stage
70 to 200 were all within 0.001 of the best log loss) rather than retuned on every build. The same day:
ridge alone with constant weights gained 0.003 (interval across 0); separate models for 3 player and 4+
player games did worse (-0.047, interval -0.084 to -0.010), and partial pooling between them chose no
difference in 4 of 5 folds; board VP as a share of the target, or -log(VP still needed), made no difference.
Because the stage model was picked from several tried on these 107 games, the constant model is still fit
and scored on every build, and check()["forward"] compares the two on games after FORWARD_AFTER only.

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
FEATS = ["board_vp", "income", "income_gold", "reach", "reach_gold", "reach_island", "reach_port", "port_31", "port_21",
         "dev_held", "hand", "road_close", "army_close"]
LABELS = {
    "board_vp": "Board VP (per SD)",
    "income": "Dice income, five resources (per SD)",
    "income_gold": "Dice income from gold hexes (per SD)",
    "reach": "Reach: open spots within 2 roads or ships (per SD)",
    "reach_gold": "Gold in reach (per SD)",
    "reach_island": "New island bonus in reach (per SD)",
    "reach_port": "New ports in reach (per SD)",
    "port_31": "Holds a 3:1 port (per SD)",
    "port_21": "2:1 ports, weighted by matching income (per SD)",
    "dev_held": "Dev cards in hand (per SD)",
    "hand": "Resource cards in hand (per SD)",
    "road_close": "Closeness to Longest Road (per SD)",
    "army_close": "Closeness to Largest Army (per SD)",
}
ROAD_CAP, ARMY_CAP = 4, 3
VP_COL = FEATS.index("board_vp")
STAGE_CENTER = 0.5  # a feature's main weight is its weight at this stage
STAGE_POINTS = [0.2, 0.5, 0.8]  # where the site reports the weights: early, middle, late
RIDGE_MAIN, RIDGE_STAGE = 450.0, 150.0  # fixed 2026-11-26 by CV over 107 games (see the docstring)
FORWARD_AFTER = "2026-11-26-b"  # the last game id seen when the stage model was chosen
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
        X = []
        for i in range(n):
            rp, ports = row["res_pips"][i], row["ports"][i]
            X.append([vp[i], sum(rp[:5]) / 36, rp[5] / 36, row["reach"][i] - row["reach_gold"][i], row["reach_gold"][i],
                      row["reach_island"][i], row["reach_port"][i], 1 if 0 in ports else 0,
                      sum(rp[t - 1] for t in ports if t) / 36, held[i], row["hand"][i], road[i], army[i]])
        out.append({"action_index": row["action_index"], "roll_index": row["roll_index"], "kind": row["kind"],
                    "actor": row["actor"], "X": X})
    return out


def stage_of(X, target):
    """How far the game has gone, from what the table can see: the leader's board VP over the VP target, capped at 1."""
    return min(1.0, max(x[VP_COL] for x in X) / target)


def game_data(games, events):
    """Per game with v4 state rows: seats, winner seat index, rows (each with its stage), and the turn-end rows
    the model uses."""
    out = []
    for g in games:
        ev = events.get(g["id"])
        if not ev or not ev.get("states") or "res_pips" not in ev["states"][0] or g["winner"] not in ev["seats"]:
            continue
        rows = state_rows(ev)
        target = g["settings"]["vp_to_win"]
        for r in rows:
            r["stage"] = stage_of(r["X"], target)
        out.append({"game": g["id"], "seats": ev["seats"], "n": len(ev["seats"]), "win": ev["seats"].index(g["winner"]),
                    "rows": rows, "ends": [r for r in rows if r["kind"] == "end_turn"], "ev": ev,
                    "rolls": len(ev["roll_log"]), "target": target})
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


def design(X, scale, stage, staged=True):
    """Model rows for one state: each feature over its scale, then (staged) the same times (stage - 0.5)."""
    c = stage - STAGE_CENTER
    out = []
    for x in X:
        z = [x[f] / scale[f] for f in range(len(FEATS))]
        out.append(z + [v * c for v in z] if staged else z)
    return out


def fitted_strata(data, scale, staged=True):
    return [{"X": design(r["X"], scale, r["stage"], staged),
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
    """Game-cluster sandwich covariance for a conditional logit with one chosen alternative per stratum:
    H^-1 (sum_g u_g u_g') H^-1, H the (penalized) information, u_g the game's summed scores centred over games.
    Unpenalized, the scores already sum to 0; with a ridge penalty they sum to its gradient, and centring
    spreads that evenly over the games (the sandwich of the penalized estimating equation)."""
    k = len(fit["beta"])
    U = defaultdict(lambda: [0.0] * k)
    for s in strata:
        p = probs(s["X"], fit["beta"])
        y = s["y"].index(1)
        u = U[s["game"]]
        for f in range(k):
            u[f] += s["X"][y][f] - sum(p[i] * s["X"][i][f] for i in range(len(p)))
    mean = [sum(u[f] for u in U.values()) / len(U) for f in range(k)]
    cen = [[u[f] - mean[f] for f in range(k)] for u in U.values()]
    M = [[sum(u[a] * u[b] for u in cen) for b in range(k)] for a in range(k)]
    C = fit["cov"]
    CM = [[sum(C[a][c] * M[c][b] for c in range(k)) for b in range(k)] for a in range(k)]
    return [[sum(CM[a][c] * C[c][b] for c in range(k)) for b in range(k)] for a in range(k)]


def fit_model(data, staged=True, ridge=None, start=None):
    """staged: the stage model, a main weight and a stage shift per feature, ridge-penalized (ridge defaults to
    (RIDGE_MAIN, RIDGE_STAGE)). staged=False: one constant weight per feature, unpenalized unless ridge says
    otherwise (the model used before 2026-11-26). beta is [main..., shift...] (just main when not staged)."""
    k = len(FEATS)
    if ridge is None:
        ridge = (RIDGE_MAIN, RIDGE_STAGE) if staged else (0.0, 0.0)
    pen = [ridge[0]] * k + ([ridge[1]] * k if staged else [])
    scale = feature_scale(data)
    st = fitted_strata(data, scale, staged)
    fit = statlib.cond_logit([{"X": s["X"], "y": s["y"]} for s in st], firth=False, ridge=pen, start=start)
    V = cluster_cov(st, fit)
    z = statlib.z_for(LEVEL)
    se = [math.sqrt(V[f][f]) if V[f][f] > 0 else None for f in range(len(pen))]
    eq = statlib.cond_logit([{"X": s["X"], "y": s["y"]} for s in equal_strata(data)], firth=False)
    return {"staged": staged, "ridge": list(ridge), "scale": scale, "beta": fit["beta"], "se": se, "cov": V,
            "ci": [[b - z * e, b + z * e] if e else None for b, e in zip(fit["beta"], se)],
            "gamma": eq["beta"][0], "games": len(data), "states": len(st)}


def stage_weights(model, points=STAGE_POINTS):
    """Each feature's weight at the given stages, main + shift (stage - 0.5), with sandwich intervals."""
    k, b, V = len(FEATS), model["beta"], model["cov"]
    z = statlib.z_for(LEVEL)
    out = []
    for f in range(k):
        est, lo, hi = [], [], []
        for t in points:
            c = t - STAGE_CENTER
            w = b[f] + c * b[k + f]
            var = V[f][f] + c * c * V[k + f][k + f] + 2 * c * V[f][k + f]
            se = math.sqrt(var) if var > 0 else None
            est.append(w)
            lo.append(w - z * se if se else None)
            hi.append(w + z * se if se else None)
        out.append({"est": est, "lo": lo, "hi": hi})
    return out


def fold_of(i):
    return i % FOLDS


def cross_fit(data, staged=True, start=None):
    """Out-of-fold models: fold f is scored by the model fit on the other folds (games in id order). start warm-
    starts every fold's fit (e.g. from the all-games estimate)."""
    order = sorted(range(len(data)), key=lambda i: data[i]["game"])
    fold = {data[i]["game"]: fold_of(j) for j, i in enumerate(order)}
    models = {}
    for f in range(FOLDS):
        train = [d for d in data if fold[d["game"]] != f]
        if len(train) < 2:
            continue
        models[f] = fit_model(train, staged=staged, start=start)
    return fold, models


def model_probs(r, model):
    """A model's win probabilities for the seats in state row r."""
    return probs(design(r["X"], model["scale"], r["stage"], model["staged"]), model["beta"])


def reason(r, model):
    """Why the top threat in state row r is ahead of the next most likely winner. Their log-odds gap,
    log(p_top / p_next) = eta_top - eta_next, splits exactly into one part per feature: (z_top - z_next) times the
    feature's weight at this stage (main + shift (stage - 0.5); the one weight for a constant model), z being the
    feature over its scale. Returns (feature index, top's raw value, next seat, next's raw value) for the largest
    part, or None when no part favours the top threat (a tie)."""
    n = len(r["p"])
    if n < 2:
        return None
    order = sorted(range(n), key=lambda i: -r["p"][i])
    t, s = order[0], order[1]
    k, beta, scale, c = len(FEATS), model["beta"], model["scale"], r["stage"] - STAGE_CENTER
    parts = [(r["X"][t][f] - r["X"][s][f]) / scale[f] * (beta[f] + (beta[k + f] * c if model["staged"] else 0.0))
             for f in range(k)]
    f = max(range(k), key=lambda j: parts[j])
    if parts[f] <= 1e-12:
        return None
    return f, r["X"][t][f], s, r["X"][s][f]


def score_rows(d, model):
    """Attach out-of-fold fitted and equal-weights probabilities, the top threat and ranks to every row, and at
    turn ends the biggest reason the top threat leads (reason)."""
    gamma = model["gamma"]
    for r in d["rows"]:
        p = model_probs(r, model)
        q = softmax([gamma * z for z in z_sum(r["X"])])
        order = sorted(range(d["n"]), key=lambda i: -p[i])
        r["p"], r["p_equal"] = p, q
        if r["kind"] == "end_turn":
            r["why"] = reason(r, model)
        r["top"] = order[0]
        r["top_equal"] = max(range(d["n"]), key=lambda i: q[i])
        r["rank"] = [0] * d["n"]
        for k, i in enumerate(order):
            r["rank"][i] = k + 1


def check(data):
    """Out-of-fold log loss and accuracy at turn ends: the fitted (stage) model against equal weights, the
    constant-weight model it replaced (rows' "p_constant") and chance, overall and by thirds of the game (turn
    end's roll index over the game's rolls), with game-bootstrap intervals for the log loss differences.
    "forward" repeats fitted vs constant on games after FORWARD_AFTER only, which played no part in choosing
    the stage model; the all-games comparison does not have that protection."""
    def ll(rows, key):
        return sum(-math.log(max(r[key], 1e-12)) for r in rows) / len(rows)

    def summary(rows):
        n = len(rows)
        if not n:
            return None
        out = {"states": n, "logloss": r3(ll(rows, "p")), "logloss_equal": r3(ll(rows, "pe")),
               "logloss_chance": r3(sum(math.log(r["n"]) for r in rows) / n),
               "acc": r3(sum(r["hit"] for r in rows) / n), "acc_equal": r3(sum(r["hit_e"] for r in rows) / n),
               "acc_chance": r3(sum(1 / r["n"] for r in rows) / n), "agree": r3(sum(r["agree"] for r in rows) / n)}
        if all(r["pc"] is not None for r in rows):
            out["logloss_constant"] = r3(ll(rows, "pc"))
            out["acc_constant"] = r3(sum(r["hit_c"] for r in rows) / n)
        return out

    def gap(per_game, key, seed):
        """Log loss of `key` minus the fitted model's, per turn end, with a game bootstrap (above 0: fitted is
        better)."""
        def diff(sample):
            rows = [r for g in sample for r in g]
            return sum(math.log(max(r["p"], 1e-12)) - math.log(max(r[key], 1e-12)) for r in rows) / len(rows) if rows else None
        est = diff(per_game)
        if est is None:
            return None
        if len(per_game) < 2:
            return {"est": r3(est), "lo": None, "hi": None}
        boots = [b for b in statlib.cluster_bootstrap(per_game, diff, B=statlib.B_DESCRIPTIVE, seed=seed) if b is not None]
        a = (1 - LEVEL) / 2
        return {"est": r3(est), "lo": r3(statlib.quantile(boots, a)), "hi": r3(statlib.quantile(boots, 1 - a))}

    per_game, thirds, ids = [], [[], [], []], []
    for d in data:
        rows = []
        for r in d["ends"]:
            t = min(2, int(3 * (r["roll_index"] + 1) / (d["rolls"] + 1)))
            pc = r.get("p_constant")
            row = {"p": r["p"][d["win"]], "pe": r["p_equal"][d["win"]], "pc": pc[d["win"]] if pc else None,
                   "n": d["n"], "hit": r["top"] == d["win"], "hit_e": r["top_equal"] == d["win"],
                   "hit_c": bool(pc) and max(range(d["n"]), key=lambda i: pc[i]) == d["win"],
                   "agree": r["top"] == r["top_equal"]}
            rows.append(row)
            thirds[t].append(row)
        per_game.append(rows)
        ids.append(d["game"])
    out = summary([r for g in per_game for r in g])
    out["equal_minus_fitted"] = gap(per_game, "pe", 11)
    out["thirds"] = [summary(t) for t in thirds]
    if "logloss_constant" in out:
        out["constant_minus_fitted"] = gap(per_game, "pc", 12)
        fwd = [g for g, i in zip(per_game, ids) if i > FORWARD_AFTER and g]
        out["forward"] = {"after": FORWARD_AFTER, "games": len(fwd), **(summary([r for g in fwd for r in g]) or {}),
                          "constant_minus_fitted": gap(fwd, "pc", 13)}
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
    """Per game: roll index and each seat's out-of-fold win probability at every turn end (game page chart), and
    why: per turn end [feature index into FEATS, top threat's raw value, next seat, next seat's raw value], or None
    (see reason)."""
    return {d["game"]: {"seats": d["seats"], "turn": [r["roll_index"] + 1 for r in d["ends"]],
                        "p": [[round(r["p"][i], 3) for r in d["ends"]] for i in range(d["n"])],
                        "top": [r["top"] for r in d["ends"]],
                        "why": [[w[0], r3(w[1]), w[2], r3(w[3])] if (w := r.get("why")) else None for r in d["ends"]]}
            for d in data}


# ---------------------------------------------------------------------------
# Module entry points (see build.MODULES)
# ---------------------------------------------------------------------------

def prepare(games, events, ctx):
    data = game_data(games, events)
    if len(data) < G["model_games"]:
        return data, None, None
    full = fit_model(data)
    fold, models = cross_fit(data, start=full["beta"])
    _, constant = cross_fit(data, staged=False)  # the model before 2026-11-26, kept for check()'s comparison
    for d in data:
        score_rows(d, models.get(fold[d["game"]], full))
        cm = constant.get(fold[d["game"]])
        if cm:
            for r in d["ends"]:
                r["p_constant"] = model_probs(r, cm)
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
    # beta, se and ci run over terms: each feature's main weight (at stage 0.5), then its stage shift.
    # weights[f] is feature f's weight at each of stage.points, with its interval.
    model = {"feats": FEATS, "labels": LABELS, "games": full["games"], "states": full["states"], "level": LEVEL,
             "terms": FEATS + [f + ":stage" for f in FEATS],
             "beta": [r3(b) for b in full["beta"]], "se": [r3(s) for s in full["se"]],
             "ci": [[r3(c[0]), r3(c[1])] if c else None for c in full["ci"]],
             "stage": {"center": STAGE_CENTER, "points": STAGE_POINTS, "ridge_main": RIDGE_MAIN,
                       "ridge_stage": RIDGE_STAGE},
             "weights": [{k: [r3(v) for v in w[k]] for k in ("est", "lo", "hi")} for w in stage_weights(full)],
             "scale": [r3(s) for s in full["scale"]], "gamma": r3(full["gamma"]), "check": chk}
    return {"model": model, "games": len(data), "timelines": timelines(data)}


def compute_view(games, replays, events, ctx, all_result):
    data = [_STATE[g["id"]] for g in games if g["id"] in _STATE]
    if all_result.get("model") is None:
        return {"games": len(data), "players": {}}
    return {"games": len(data), "players": players_stats(data, ctx), "hidden": hidden_summary(data)}
