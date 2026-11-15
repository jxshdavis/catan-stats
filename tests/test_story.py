"""Tests for scripts/story.py and scripts/recaps.py on a synthetic game (never data/, never the API).

    python -m unittest discover -s tests
"""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import recaps  # noqa: E402
import story  # noqa: E402


def vpe(roll, actor, vp, *changes, action="settlement", phase="turn"):
    return {"roll_index": roll, "actor": actor, "action": action, "phase": phase, "board_vp": list(vp),
            "changes": [dict(c) for c in changes]}


def synthetic():
    """Three seats to 6 VP. b leads first, a takes Longest Road and the lead on one turn, c gets close,
    a wins by revealing a VP card."""
    seats = ["a", "b", "c"]
    ev = {"seats": seats, "roll_log": [{"roll_index": i} for i in range(12)], "vp_events": [
        vpe(-1, 1, [2, 2, 2], {"type": "settlement", "seat": 1}, phase="setup"),
        vpe(1, 2, [2, 3, 2], {"type": "settlement", "seat": 2}),
        vpe(3, 1, [3, 3, 2], {"type": "city", "seat": 1}, action="city"),
        vpe(6, 1, [5, 3, 2], {"type": "longest_road_taken", "seat": 1, "from": None}, action="road"),
        vpe(8, 3, [5, 3, 4], {"type": "settlement", "seat": 3}, {"type": "island_bonus", "seat": 3, "vp": 1}),
        vpe(11, None, [6, 3, 4], {"type": "reveal", "seat": 1, "vp_cards": 1}, action="reveal", phase="end"),
    ]}
    game = {"id": "g1", "number": 1, "date": "2026-01-02", "type_label": "Base", "vp_to_win": 6, "winner": "a",
            "players": [{"player": "a", "rank": 1, "vp": 6, "seat": 1, "vp_breakdown": {"longest_road": 2, "vp_cards": 1}},
                        {"player": "c", "rank": 2, "vp": 4, "seat": 3, "vp_breakdown": {}},
                        {"player": "b", "rank": 3, "vp": 3, "seat": 2, "vp_breakdown": {}}]}
    row = lambda dots, got, exp, robbed: {"opening_dots": dots, "resources_from_dice": got, "expected_from_dice": exp,
                                          "stolen_from": robbed, "steals": 1, "blocked_by_robber": 2, "cards_discarded": 0,
                                          "trades": 3, "built": {"city": 1, "settlement": 1}, "dev_cards_played": {"knight": 0}}
    stats = {"momentum": {"games": {"g1": {"go_ahead": {"kind": "reveal"}, "play": {"pick": None}}}},
             "closeness": {"n": 1, "games": {"g1": {"lead_changes": 1, "index": 40.0, "rank": 1,
                                                    "closest_tier": False, "one_sided_tier": False}}},
             "game_replays": {"g1": {"a": row(20, 30, 22.0, 1), "b": row(18, 20, 21.0, 5), "c": row(15, 12, 20.0, 2)}}}
    return game, ev, stats


class StoryTest(unittest.TestCase):
    def setUp(self):
        self.game, self.ev, self.stats = synthetic()
        self.story = story.compute([self.game], {"g1": self.ev}, self.stats)["g1"]

    def test_lead_events_and_share(self):
        leads, share, last = story.lead_story(self.ev, self.ev["seats"])
        self.assertEqual([(e["t"], e["seat"], e["first"]) for e in leads], [(2, 1, True), (7, 0, False)])
        # b leads alone at the end of rolls 1 and 2 (tied from roll 3), a from roll 6 to 11.
        self.assertEqual(share, {"a": 0.5, "b": round(2 / 12, 3), "c": 0.0})
        self.assertEqual(last, "a")

    def test_points_are_ordered_and_merged(self):
        pts = self.story["points"]
        self.assertEqual([p["t"] for p in pts], sorted(p["t"] for p in pts))
        road = next(p for p in pts if "Longest Road" in p["text"])
        self.assertEqual((road["t"], road["who"], road["kind"]), (7, "a", "lead"))
        self.assertEqual(road["text"], "takes Longest Road and the lead, 5 to 3")
        self.assertEqual(pts[-1], {"t": 12, "kind": "win", "who": "a", "text": "reveals 1 VP card to win"})

    def test_notes(self):
        n = self.story["notes"]
        self.assertIn("led for 50% of the game", n["a"])
        self.assertIn("best opening (20 dots)", n["a"])
        self.assertIn("robbed the most (5 cards)", n["b"])
        self.assertIn("weakest opening (15 dots)", n["c"])
        self.assertIn("coldest dice (−8 cards)", n["c"])
        self.assertTrue(all(len(v) <= story.MAX_NOTES for v in n.values()))

    def test_label(self):
        # Won 6 to 4: a margin of 2 is more than "close" (1) and under the blowout line (40% of 6 = 2.4).
        self.assertEqual((self.story["tag"], self.story["margin"]), ("solid", 2))

    def test_bot_is_never_named(self):
        game, ev, stats = synthetic()
        ev["seats"] = ["a", "bot-1", "c"]
        game["players"][2]["player"] = "bot-1"
        stats["game_replays"]["g1"]["bot-1"] = stats["game_replays"]["g1"].pop("b")
        st = story.compute([game], {"g1": ev}, stats)["g1"]
        self.assertNotIn("bot-1", st["notes"])
        self.assertFalse(any(p["who"] == "bot-1" for p in st["points"]))
        f = story.facts(game, st, stats, lambda pid: pid.upper())
        self.assertTrue(f["has_bot_seat"])
        self.assertNotIn("BOT", json.dumps(f).upper().replace("HAS_BOT_SEAT", ""))

    def test_facts_use_names(self):
        f = story.facts(self.game, self.story, self.stats, lambda pid: pid.upper())
        self.assertEqual(f["winner"], "A")
        self.assertEqual([p["name"] for p in f["players"]], ["A", "C", "B"])
        self.assertFalse(any("{" in p["event"] for p in f["turning_points"]))


class FakeClient:
    """Stands in for anthropic.Anthropic(): returns the queued replies in order."""

    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.beta = self
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        text = json.dumps(self.replies.pop(0))
        block = type("B", (), {"type": "text", "text": text})()
        return type("R", (), {"stop_reason": "end_turn", "content": [block], "model": kw["model"]})()


class RecapsTest(unittest.TestCase):
    def setUp(self):
        game, ev, stats = synthetic()
        st = story.compute([game], {"g1": ev}, stats)["g1"]
        self.facts = {"g1": story.facts(game, st, stats, lambda pid: pid.upper())}

    def test_check_flags_unknown_numbers_and_dashes(self):
        ok = {"headline": "A wins game 1 on a hidden card", "recap": "A won 6 to 4 after taking the lead on turn 7."}
        self.assertEqual(recaps.check(ok, self.facts["g1"]), [])
        bad = {"headline": "A wins", "recap": "A won by 99 points — easily."}
        probs = " ".join(recaps.check(bad, self.facts["g1"]))
        self.assertIn("99", probs)
        self.assertIn("dash", probs)

    def test_retry_then_store_and_reuse(self):
        doc = {"schema_version": 1, "games": {}}
        bad = {"headline": "A wins", "recap": "A won by 99."}
        good = {"headline": "A wins it late.", "recap": "A won 6 to 4."}
        client = FakeClient([bad, good])
        written, skipped = recaps.ensure(doc, self.facts, client=client, log=lambda *_: None)
        self.assertEqual((written, skipped), (1, {}))
        self.assertEqual(len(client.calls), 2)
        self.assertIn("99", client.calls[1]["messages"][-1]["content"])      # the retry names the problem
        self.assertEqual(recaps.current(doc, self.facts)["g1"], {"headline": "A wins it late", "recap": "A won 6 to 4."})
        # Nothing to do the second time: no client needed, no call made.
        self.assertEqual(recaps.ensure(doc, self.facts, client=FakeClient([]), log=lambda *_: None), (0, {}))

    def test_two_bad_drafts_are_dropped(self):
        doc = {"schema_version": 1, "games": {}}
        bad = {"headline": "A wins", "recap": "A won by 99."}
        written, skipped = recaps.ensure(doc, self.facts, client=FakeClient([bad, bad]), log=lambda *_: None)
        self.assertEqual(written, 0)
        self.assertIn("g1", skipped)
        self.assertEqual(doc["games"], {})

    def test_changed_facts_make_a_recap_stale(self):
        doc = {"schema_version": 1, "games": {"g1": {"hash": recaps.facts_hash(self.facts["g1"]), "headline": "h", "recap": "r"}}}
        self.assertEqual(recaps.missing(doc, self.facts), [])
        changed = {"g1": dict(self.facts["g1"], turns=13)}
        self.assertEqual(recaps.missing(doc, changed), ["g1"])
        self.assertEqual(recaps.current(doc, changed), {})


if __name__ == "__main__":
    unittest.main()
