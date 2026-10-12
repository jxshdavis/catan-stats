"""Readers for data/replay_events.json (decoder v2 per-action logs).

The decoder writes "states" change-point encoded: the first row has every field and later rows only
the fields that changed. These helpers carry fields forward and index the result by roll, so the
analysis modules never deal with the encoding. Seats in the logs are 1-based; ev["seats"][s - 1] is
the player id (or guest or bot id) in seat s.
"""

from __future__ import annotations

DOTS = {s: 6 - abs(s - 7) for s in range(2, 13)}
DOTS[7] = 0


def full_rows(ev):
    """Every state row with all fields filled in (carried forward from earlier rows)."""
    out, cur = [], {}
    for row in ev["states"]:
        cur = {**cur, **row}
        out.append(cur)
    return out


def n_rolls(ev):
    return len(ev["roll_log"])


def at_rolls(ev):
    """State at each roll (index = roll_index): the "roll" row, whose pips are the ones that roll paid on."""
    out = [None] * n_rolls(ev)
    for row in full_rows(ev):
        if row["kind"] == "roll" and 0 <= row["roll_index"] < len(out):
            out[row["roll_index"]] = row
    return out


def at_turn_ends(ev):
    """State at the end of each turn (index = roll_index of that turn): the last row carrying that
    roll index, which is the end_turn row (or a paired build phase after it, or the final row)."""
    out = [None] * n_rolls(ev)
    for row in full_rows(ev):
        t = row["roll_index"]
        if 0 <= t < len(out):
            out[t] = row
    for t in range(1, len(out)):  # a turn with no row of its own keeps the previous state
        if out[t] is None:
            out[t] = out[t - 1]
    return out


def board_vp(row):
    """Public VP: VP minus VP cards still held, per seat."""
    return [v - h for v, h in zip(row["vp"], row["vp_cards_held"])]


def expected_cards(row, seat_i):
    """Expected cards for seat index seat_i (0-based) on one roll: sum over totals of dots/36 x (gross - blocked)."""
    g, b = row["pips_gross"][seat_i], row["pips_blocked"][seat_i]
    return sum(DOTS[s] * (g[k] - b[k]) for k, s in enumerate(range(2, 13))) / 36


def gross_expected(row, seat_i):
    """The same with the robber ignored."""
    g = row["pips_gross"][seat_i]
    return sum(DOTS[s] * g[k] for k, s in enumerate(range(2, 13))) / 36


def roll_variance(row, seat_i):
    """Variance of cards owed on one roll: sum_s P(s) f(s)^2 - E^2, where f(s) = (gross - blocked) at total s."""
    g, b = row["pips_gross"][seat_i], row["pips_blocked"][seat_i]
    f = [g[k] - b[k] for k in range(11)]
    e = sum(DOTS[s] * f[k] for k, s in enumerate(range(2, 13))) / 36
    return sum(DOTS[s] * f[k] ** 2 for k, s in enumerate(range(2, 13))) / 36 - e * e
