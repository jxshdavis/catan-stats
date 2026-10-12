"""Tests for scripts/import_twosheep.py and guest handling in scripts/build.py.

Runs on the synthetic fixtures in tests/fixtures/twosheep/, copied to a temporary
folder so nothing in data/ is touched:

    python -m unittest discover -s tests
"""

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402
import import_twosheep as imp  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "twosheep"
TZ = "America/Los_Angeles"


class ImportCase(unittest.TestCase):
    """A fresh copy of the fixture data in a temporary folder for each test."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "data"
        self.replay_stats = self.tmp / "replay_stats"  # empty unless a test writes decoded replays
        shutil.copytree(FIXTURES / "data", self.data)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_import(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = imp.main(["--data", str(self.data), "--raw", str(FIXTURES / "replays"), "--tz", TZ,
                             "--replay-stats", str(self.replay_stats), *args])
        return code, out.getvalue()

    def games(self):
        return {g["id"]: g for g in json.loads((self.data / "games.json").read_text())["games"]}


class ImportTest(ImportCase):
    def by_tsid(self):
        return {g.get("twosheep_id"): g for g in self.games().values()}

    def test_dry_run_writes_nothing(self):
        before = (self.data / "games.json").read_text()
        code, out = self.run_import()
        self.assertEqual(code, 0, out)
        self.assertIn("Dry run", out)
        self.assertEqual((self.data / "games.json").read_text(), before)

    def test_filters_and_counts(self):
        code, out = self.run_import("--write")
        self.assertEqual(code, 0, out)
        self.assertIn("4 new, 1 linked", out)
        self.assertIn("1 unfinished", out)
        self.assertIn("1 2 players", out)
        self.assertIn("1 0 winners marked", out)
        ids = set(self.by_tsid())
        self.assertNotIn("-Rfix0004", ids)
        self.assertNotIn("-Rfix0005", ids)
        self.assertNotIn("-Rfix0006", ids)

    def test_links_hand_entered_game_and_only_fills_empty_fields(self):
        self.run_import("--write")
        g = self.games()["2026-01-10-a"]
        self.assertEqual(g["twosheep_id"], "-Rfix0001")
        self.assertEqual(list(g)[:5], ["id", "date", "platform", "source", "twosheep_id"])
        self.assertEqual(g["source"], "manual: end-of-game stats screen")
        self.assertEqual(g["settings"], {"vp_to_win": 14, "expansion": "seafarers", "scenario": "new_shores",
                                         "notes": "typed in by hand"})
        self.assertEqual(g["turns"], 60)
        rows = {r["player"]: r for r in g["players"]}
        self.assertEqual({p: r["seat"] for p, r in rows.items()}, {"ben": 1, "ana": 2, "cat": 3})
        self.assertEqual(rows["ben"]["game_color"], "white")  # was empty: filled
        self.assertEqual(rows["cat"]["game_color"], "blue")   # disagreed: kept
        self.assertIn("vp_breakdown", rows["ana"])

    def test_conflicts_are_reported(self):
        _, out = self.run_import()
        self.assertIn("2026-01-10-a: cat game_color is blue, TwoSheep says green", out)

    def test_guests_and_ids(self):
        self.run_import("--write")
        g = self.by_tsid()["-Rfix0002"]
        self.assertEqual(g["id"], "2026-01-10-b")  # after the hand-entered game that evening
        self.assertEqual([r["player"] for r in g["players"]], ["guest-1", "ana", "guest-2", "ben"])
        self.assertEqual([r["seat"] for r in g["players"]], [1, 2, 3, 4])
        self.assertEqual(g["winner"], "guest-1")
        self.assertEqual(g["settings"]["scenario"], "four_islands")
        self.assertEqual(g["source"], imp.SOURCE)

    def test_second_account_and_base_game(self):
        self.run_import("--write")
        g = self.by_tsid()["-Rfix0003"]
        self.assertEqual(g["winner"], "cat")  # matched through Cat's older account
        self.assertEqual(g["settings"]["expansion"], "base")  # no map number means TwoSheep's default, base 4p
        self.assertEqual(g["settings"]["vp_to_win"], 10)  # no target in the summary means TwoSheep's default

    def test_date_uses_time_zone(self):
        self.run_import("--write")
        self.assertEqual(self.by_tsid()["-Rfix0007"]["date"], "2026-01-16")

    def test_rerun_changes_nothing(self):
        self.run_import("--write")
        first = (self.data / "games.json").read_text()
        code, out = self.run_import("--write")
        self.assertEqual(code, 0, out)
        self.assertIn("0 new, 0 linked to hand-entered games, 0 updated, 0 removed, 5 unchanged", out)
        self.assertEqual((self.data / "games.json").read_text(), first)

    def test_new_account_turns_guest_into_player(self):
        self.run_import("--write")
        players = json.loads((self.data / "players.json").read_text())
        next(p for p in players["players"] if p["id"] == "dan")["twosheep_accounts"] = [imp.account_key("uid-dan")]
        (self.data / "players.json").write_text(json.dumps(players, indent=2))
        code, out = self.run_import("--write")
        self.assertEqual(code, 0, out)
        self.assertIn("updated 2026-01-10-b: players", out)
        g = self.by_tsid()["-Rfix0002"]
        self.assertEqual([r["player"] for r in g["players"]], ["guest-1", "ana", "dan", "ben"])
        self.assertEqual(g["winner"], "guest-1")

    def give_account(self, pid, uid):
        players = json.loads((self.data / "players.json").read_text())
        p = next(p for p in players["players"] if p["id"] == pid)
        p["twosheep_accounts"] = p.get("twosheep_accounts", []) + [imp.account_key(uid)]
        (self.data / "players.json").write_text(json.dumps(players, indent=2))

    def test_two_accounts_of_one_person_drops_imported_game(self):
        self.run_import("--write")
        self.assertIn("-Rfix0002", self.by_tsid())
        self.give_account("ana", "uid-dan")  # Dan's account turns out to be Ana's alt, and both played -Rfix0002
        code, out = self.run_import("--write")
        self.assertEqual(code, 0, out)
        self.assertIn("removed 2026-01-10-b: two accounts of ana in one game", out)
        self.assertNotIn("-Rfix0002", self.by_tsid())
        code, out = self.run_import("--write")  # and it stays out
        self.assertIn("0 removed, 4 unchanged", out)

    def test_two_accounts_in_hand_entered_game_is_only_flagged(self):
        self.run_import("--write")
        self.give_account("ana", "uid-cat")  # both played the hand-entered game -Rfix0001 links to
        players = json.loads((self.data / "players.json").read_text())
        cat = next(p for p in players["players"] if p["id"] == "cat")
        cat["twosheep_accounts"].remove(imp.account_key("uid-cat"))
        (self.data / "players.json").write_text(json.dumps(players, indent=2))
        code, out = self.run_import("--write")
        self.assertEqual(code, 0, out)
        self.assertIn("2026-01-10-a: its TwoSheep summary is now excluded (two accounts of ana in one game)", out)
        self.assertIn("2026-01-10-a", self.games())

    def players(self):
        return {p["id"]: p for p in json.loads((self.data / "players.json").read_text())["players"]}

    def test_aliases_collect_every_name_most_used_first(self):
        before = (self.data / "players.json").read_text()
        _, out = self.run_import()
        self.assertIn("cat: OldCat", out)
        self.assertEqual((self.data / "players.json").read_text(), before)  # dry run
        self.run_import("--write")
        players = self.players()
        # CatanCat is in 4 summaries (skipped games count too), OldCat in 1.
        self.assertEqual(players["cat"]["aliases"], ["CatanCat", "OldCat"])
        self.assertEqual(players["ana"]["aliases"], ["AnaPlays"])
        self.assertEqual(players["dan"]["aliases"], [])  # no account yet, so nothing to collect
        self.assertNotIn("Stranger", (self.data / "players.json").read_text())  # guests' names stay out
        _, out = self.run_import("--write")
        self.assertNotIn("new TwoSheep names", out)

    def test_alias_order_prefers_games_on_the_site(self):
        doc = {"players": [{"id": "ana", "aliases": [], "twosheep_accounts": [imp.account_key("uid-ana")]}]}
        rec = lambda rid, name: {"replay_id": rid, "fields": {"p": {"uid-ana": {"n": name}}}}
        summaries = [rec("r1", "OftenOffSite"), rec("r2", "OftenOffSite"), rec("r3", "OftenOffSite"), rec("r4", "OnSite")]
        imp.sync_aliases(doc, summaries, on_site={"r4"})
        self.assertEqual(doc["players"][0]["aliases"], ["OnSite", "OftenOffSite"])

    def test_display_name(self):
        self.assertEqual(build.display_name({"id": "a", "aliases": ["brickpump", "WheatGod"], "initials": "JD"}),
                         "brickpump (JD)")
        self.assertEqual(build.display_name({"id": "a", "name": "Ana", "aliases": ["x"], "initials": "AB"}), "Ana (AB)")
        self.assertEqual(build.display_name({"id": "a", "aliases": ["x"]}), "x")
        self.assertEqual(build.display_name({"id": "a", "aliases": ["brickpump"], "initials": "JD"}, "initials"), "JD")
        self.assertEqual(build.display_name({"id": "a", "aliases": ["x"]}, "initials"), "x")  # no initials to show
        stats = build.compute_views({"players": [{"id": "a", "aliases": ["secret"], "initials": "AB", "color_slot": 1},
                                                 {"id": "b", "aliases": ["other"], "color_slot": 2}]},
                                    {"games": [{"id": "g", "date": "2026-01-01", "winner": "a", "players": [
                                        {"player": "a", "vp": 10}, {"player": "b", "vp": 5}]}]}, "initials")
        self.assertEqual({p["id"]: p["name"] for p in stats["views"]["all"]["players"]}, {"a": "AB", "b": "other"})
        errors, _ = build.validate({"players": [{"id": "a", "color_slot": 1, "aliases": []},
                                                {"id": "b", "color_slot": 2, "name": "B", "initials": "TOOLONG"}]},
                                   {"games": []})
        self.assertTrue(any("needs a name or at least one alias" in e for e in errors))
        self.assertTrue(any("initials must be 1 to 4" in e for e in errors))

    def test_hand_added_alias_is_kept(self):
        players = json.loads((self.data / "players.json").read_text())
        next(p for p in players["players"] if p["id"] == "ben")["aliases"] = ["Benny", "BenB"]
        (self.data / "players.json").write_text(json.dumps(players, indent=2))
        self.run_import("--write")
        self.assertEqual(self.players()["ben"]["aliases"], ["BenB", "Benny"])

    def test_no_raw_account_ids_written(self):
        self.run_import("--write")
        text = (self.data / "games.json").read_text() + (self.data / "players.json").read_text()
        self.assertNotIn("uid-", text)

    def test_accounts_listing(self):
        code, out = self.run_import("--accounts")
        self.assertEqual(code, 0, out)
        self.assertIn(imp.account_key("uid-zed"), out)
        self.assertIn("Stranger", out)


class GuestStatsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        data = cls.tmp / "data"
        shutil.copytree(FIXTURES / "data", data)
        with contextlib.redirect_stdout(io.StringIO()):
            imp.main(["--data", str(data), "--raw", str(FIXTURES / "replays"), "--tz", TZ, "--write"])
        players = json.loads((data / "players.json").read_text())
        games = json.loads((data / "games.json").read_text())
        errors, _ = build.validate(players, games)
        assert not errors, errors
        cls.stats = build.compute_views(players, games)["views"]["all"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def test_guests_are_not_listed(self):
        ids = {p["id"] for p in self.stats["players"]}
        self.assertFalse(any(build.is_guest(i) for i in ids))
        self.assertFalse(any(build.is_guest(h["player"]) or build.is_guest(h["opponent"])
                             for h in self.stats["head_to_head"]))

    def test_aliases_reach_the_site(self):
        cat = next(p for p in self.stats["players"] if p["id"] == "cat")
        self.assertEqual(cat["aliases"], ["CatanCat", "OldCat"])

    def test_guest_rows_on_game(self):
        g = next(g for g in self.stats["games"] if g["twosheep_id"] == "-Rfix0002")
        self.assertEqual(g["n_guests"], 2)
        guest = next(r for r in g["players"] if r["player"] == "guest-1")
        self.assertTrue(guest["guest"])
        self.assertIsNone(guest["above_expected"])
        self.assertEqual(self.stats["summary"]["games_with_guests"], 1)

    def test_guests_count_as_opponents(self):
        ben = next(p for p in self.stats["players"] if p["id"] == "ben")
        # Ben finished 2nd of 4 behind a guest winner in -Rfix0002: beat 2 of 3 opponents there.
        g = next(g for g in self.stats["games"] if g["twosheep_id"] == "-Rfix0002")
        self.assertEqual(next(r["rank"] for r in g["players"] if r["player"] == "ben"), 2)
        self.assertEqual(ben["games"], 5)
        self.assertEqual(ben["wins"], 0)

    def test_wins_above_expected(self):
        # A loss at a 3-seat table with guests costs 1/3; a win at a 6-seat table earns 5/6.
        players = {"schema_version": 1, "players": [{"id": "ana", "name": "Ana", "color_slot": 1},
                                                    {"id": "ben", "name": "Ben", "color_slot": 2}]}
        g1 = {"id": "g1", "date": "2026-01-01", "winner": "guest-1", "players": [
            {"player": "guest-1", "vp": 10}, {"player": "ana", "vp": 5}, {"player": "guest-2", "vp": 4}]}
        g2 = {"id": "g2", "date": "2026-01-02", "winner": "ana", "players": [{"player": "ana", "vp": 10}]
              + [{"player": f"guest-{i}", "vp": 3} for i in range(1, 5)] + [{"player": "ben", "vp": 9}]}
        view = build.compute_views(players, {"games": [g1, g2]})["views"]["all"]
        ana, ben = (next(p for p in view["players"] if p["id"] == k) for k in ("ana", "ben"))
        self.assertAlmostEqual(ana["expected_wins"], 1 / 3 + 1 / 6, places=3)
        self.assertAlmostEqual(ana["above_expected"], 1 - 1 / 3 - 1 / 6, places=3)
        # Wins under chance: P(0) = 2/3 * 5/6 = 0.556, P(1) = 0.389, P(2) = 0.056, so the 95% band is 0 to 2 wins.
        self.assertEqual(ana["luck_band"], [-0.5, 1.5])
        self.assertEqual([h["above_expected"] for h in ana["standing_history"]], [-0.333, 0.5])
        self.assertAlmostEqual(ben["above_expected"], -1 / 6, places=3)
        self.assertEqual((ana["leaderboard_rank"], ben["leaderboard_rank"]), (1, 2))
        row = next(r for r in view["games"][0]["players"] if r["player"] == "ana")
        self.assertAlmostEqual(row["above_expected"], 5 / 6, places=3)

    def test_player_colors(self):
        # Most used color wins; a tie goes to the more recent one; a taken favorite falls to the next most used.
        players = {"players": [{"id": k, "name": k, "color_slot": i} for i, k in enumerate(("ana", "ben", "cat"), start=1)]}
        seat = lambda pid, c: {"player": pid, "game_color": c, "vp": 5}
        games = [{"id": "g1", "date": "2026-01-01", "players": [seat("ana", "red"), seat("ben", "red"), seat("cat", "blue")]},
                 {"id": "g2", "date": "2026-01-02", "players": [seat("ana", "red"), seat("ben", "green"), seat("cat", "white")]},
                 {"id": "g3", "date": "2026-01-03", "players": [seat("ana", "pink"), seat("ben", "red"), seat("cat", "teal")]}]
        colors = build.player_colors(players, games)
        self.assertEqual(colors["ana"], "red")    # 2 red, chooses first (ties on games played go by id)
        self.assertEqual(colors["ben"], "green")  # red is taken, green is next
        self.assertEqual(colors["cat"], "teal")   # blue, white, teal once each: most recent

    def test_recent_form_and_movement(self):
        # Ben wins the last two 4-seat games: +1.0 over his last 4, on fire, and he passes Ana in the last game.
        players = {"players": [{"id": k, "name": k, "color_slot": i} for i, k in enumerate(("ana", "ben"), start=1)]}
        def game(i, winner):
            return {"id": f"g{i}", "date": f"2026-01-0{i}", "winner": winner,
                    "players": [{"player": "ana", "vp": 10 if winner == "ana" else 5},
                                {"player": "ben", "vp": 10 if winner == "ben" else 5},
                                {"player": "guest-1", "vp": 10 if winner == "guest-1" else 4},
                                {"player": "guest-2", "vp": 10 if winner == "guest-2" else 3}]}
        view = build.compute_views(players, {"games": [game(1, "ana"), game(2, "guest-1"), game(3, "guest-2"),
                                                       game(4, "ben"), game(5, "ben")]})["views"]["all"]
        ana, ben = (next(p for p in view["players"] if p["id"] == k) for k in ("ana", "ben"))
        self.assertEqual((ben["leaderboard_rank"], ben["rank_prev"], ben["rank_recent_ago"]), (1, 2, 2))
        self.assertEqual((ana["leaderboard_rank"], ana["rank_prev"]), (2, 1))
        self.assertEqual([g["won"] for g in ben["recent"]["games"]], [False, False, True, True])
        self.assertAlmostEqual(ben["recent"]["above"], 1.0, places=3)
        self.assertEqual(ben["recent"]["streak"], 2)
        self.assertTrue(ben["recent"]["on_fire"])
        self.assertFalse(ana["recent"]["on_fire"])

    def test_ties_go_to_table_vp_share(self):
        # Equal wins above expected: the higher average share of the table's VP ranks first.
        players = {"schema_version": 1, "players": [{"id": k, "name": k, "color_slot": i}
                                                    for i, k in enumerate(("ana", "ben", "cat"), start=1)]}
        g = {"id": "g1", "date": "2026-01-01", "winner": "cat", "players": [
            {"player": "cat", "vp": 10}, {"player": "ana", "vp": 4}, {"player": "ben", "vp": 8}]}
        view = build.compute_views(players, {"games": [g]})["views"]["all"]
        self.assertEqual([p["id"] for p in view["players"]], ["cat", "ben", "ana"])

    def test_rejects_reserved_ids_and_all_guest_games(self):
        players = {"players": [{"id": "guest-9", "name": "X", "color_slot": 1}]}
        errors, _ = build.validate(players, {"games": [{"id": "g", "date": "2026-01-01", "winner": "guest-1",
                                                        "players": [{"player": "guest-1", "vp": 10},
                                                                    {"player": "guest-2", "vp": 3}]}]})
        self.assertTrue(any("reserved" in e for e in errors))
        self.assertTrue(any("every player is a guest" in e for e in errors))
        errors, _ = build.validate({"players": [{"id": "ana", "name": "Ana", "color_slot": 1}]},
                                   {"games": [{"id": "g", "date": "2026-01-01", "winner": "ana",
                                               "players": [{"player": "ana", "vp": 10}, {"player": "guest-1", "vp": 4},
                                                           {"player": "guest-2", "vp": 3}]}]})
        self.assertTrue(any("only one group member" in e for e in errors))

    def test_duplicate_twosheep_id_rejected(self):
        players = {"players": [{"id": "ana", "name": "A", "color_slot": 1}, {"id": "ben", "name": "B", "color_slot": 2}]}
        g = lambda gid: {"id": gid, "date": "2026-01-01", "twosheep_id": "-X", "winner": "ana",
                         "players": [{"player": "ana", "vp": 10}, {"player": "ben", "vp": 3}]}
        errors, _ = build.validate(players, {"games": [g("a"), g("b")]})
        self.assertTrue(any("twosheep_id -X is already used" in e for e in errors))


class BotSeatTest(ImportCase):
    """-Rfix0008: a TwoSheep bot took seat 1 and the humans' own seat numbers start at 1 (like 2025-01-15-b).
    The bot keeps its seat, counts in n, and its VP comes from the decoded replay."""

    def setUp(self):
        super().setUp()
        self.replay_stats.mkdir()
        rec = decoded_replay("-Rfix0008", [(None, 5), ("uid-ana", 6), ("uid-ben", 6), ("uid-cat", 10)])
        (self.replay_stats / "-Rfix0008.json").write_text(json.dumps(rec))

    def game(self):
        return next(g for g in self.games().values() if g.get("twosheep_id") == "-Rfix0008")

    def test_bot_seat_and_seat_fill(self):
        code, out = self.run_import("--write")
        self.assertEqual(code, 0, out)
        g = self.game()
        self.assertEqual(g["n_seats"], 4)
        self.assertEqual([(r["player"], r["seat"], r["vp"]) for r in g["players"]],
                         [("bot-1", 1, 5), ("ana", 2, 6), ("ben", 3, 6), ("cat", 4, 10)])
        self.assertEqual(list(g)[list(g).index("settings") + 1], "n_seats")
        code, out = self.run_import("--write")
        self.assertIn("0 updated", out)  # the bot's VP from the replay survives a re-import

    def test_event_logs_are_exported_with_a_seat_map(self):
        rec = decoded_replay("-Rfix0008", [(None, 5), ("uid-ana", 6), ("uid-ben", 6), ("uid-cat", 10)])
        rec.update(v2_events(4))
        (self.replay_stats / "-Rfix0008.json").write_text(json.dumps(rec))
        code, out = self.run_import("--write")
        self.assertEqual(code, 0, out)
        self.assertIn("1 with per-action logs", out)
        ev = json.loads((self.data / "replay_events.json").read_text())["games"]
        gid = self.game()["id"]
        self.assertEqual(ev[gid]["seats"], ["bot-1", "ana", "ben", "cat"])
        self.assertEqual(ev[gid]["robber_events"][0]["mover"], 2)  # seats stay 1-based numbers
        self.assertEqual(set(ev[gid]) - {"twosheep_id", "decoder_version", "seats"}, set(imp.EVENT_KEYS))
        self.assertNotIn("uid-", (self.data / "replay_events.json").read_text())

    def test_bot_without_replay_has_no_vp(self):
        shutil.rmtree(self.replay_stats)
        self.run_import("--write")
        bot = self.game()["players"][0]
        self.assertEqual((bot["player"], bot["vp"]), ("bot-1", None))

    def test_bot_counts_in_n_but_is_never_listed(self):
        self.run_import("--write")
        players = json.loads((self.data / "players.json").read_text())
        games = json.loads((self.data / "games.json").read_text())
        games["games"] = [g for g in games["games"] if g.get("twosheep_id") == "-Rfix0008"]
        errors, _ = build.validate(players, games)
        self.assertEqual(errors, [])
        stats = build.compute_views(players, games)["views"]["all"]
        g = stats["games"][0]
        self.assertEqual((g["n_players"], g["n_bots"]), (4, 1))
        self.assertNotIn("bot-1", [r["player"] for r in g["players"]])
        ana = next(p for p in stats["players"] if p["id"] == "ana")
        self.assertAlmostEqual(ana["expected_wins"], 0.25)
        # Ana tied Ben for 2nd, beat the bot, lost to Cat: (1 + 0.5 + 0) / 3
        self.assertAlmostEqual(ana["beat_rate"], 0.5)
        self.assertFalse(any(build.is_bot(h["player"]) or build.is_bot(h["opponent"]) for h in stats["head_to_head"]))
        no_bot = build.compute_views(players, {"games": [
            {**games["games"][0], "players": games["games"][0]["players"][1:], "n_seats": 3}]})["views"]["all"]
        # The bot's seat makes the fair share 1/4 rather than 1/3.
        self.assertAlmostEqual(next(p for p in no_bot["players"] if p["id"] == "ana")["expected_wins"], 1 / 3, places=3)


def decoded_replay(rid, seats, turns=50):
    """A synthetic record in the format scripts/twosheep_replay.py writes. seats: [(account, vp)]."""
    players = []
    for i, (acct, vp) in enumerate(seats):
        players.append({
            "seat": i + 1, "account": acct, "color": "red", "vp": vp,
            "vp_breakdown": {"settlements": vp, "cities": 0, "vp_cards": 0, "largest_army": 0, "longest_road": 0,
                             "islands": 0},
            "dev_cards_bought": {k: 0 for k in ["knight", "victory_point", "monopoly", "road_building", "year_of_plenty"]},
            "dev_cards_played": {k: 0 for k in ["knight", "victory_point", "monopoly", "road_building", "year_of_plenty"]},
            "resources_from_dice": 40 + i, "production": {"wood": 40 + i, "brick": 0, "sheep": 0, "wheat": 0, "ore": 0},
            "gold_from_dice": 0, "expected_from_dice": 40.0, "blocked_by_robber": 1, "opening_dots": 20, "rolls": 10,
            "sevens_rolled": 2, "robber_moves": 2, "steals": 2, "stolen_from": 1,
            "steals_by_victim": {str(len(seats) - i): 2}, "discards": 0, "cards_discarded": 0,
            "monopoly_cards": 0, "monopoly_lost": 0, "trades": 1, "trade_partners": {str(len(seats) - i): 1},
            "trade_cards_given": 1, "trade_cards_received": 1, "bank_trades": 0, "bank_cards_given": 0,
            "bank_cards_received": 0, "built": {"settlement": 1, "city": 0, "road": 2, "ship": 0},
            "longest_road_length": 3, "max_hand": 8, "fog_discovered": 0,
        })
    return {
        "replay_id": rid, "decoder_version": 1, "decoded_at": "2026-01-20T00:00:00+00:00", "turns": turns,
        "dice": {str(k): (turns if k == 8 else 0) for k in range(2, 13)}, "roll_order": [8] * turns,
        "players": players,
        "timeline": {"turn": [0, turns], "vp": [[2] * len(seats), [vp for _, vp in seats]],
                     "cards_from_dice": [[0] * len(seats), [40 + i for i in range(len(seats))]]},
        "notes": [],
    }


def v2_events(n):
    """Minimal decoder v2 per-action logs for an n-seat game."""
    return {
        "decoder_version": 2, "n_seats": n,
        "states": [{"action_index": 9, "roll_index": 0, "kind": "roll", "actor": 1, "vp": [2] * n, "hand": [3] * n}],
        "roll_log": [{"roll_index": 0, "action_index": 9, "roller": 1, "total": 8, "a_raw": [1] * n, "short": [0] * n}],
        "robber_events": [{"action_index": 12, "roll_index": 1, "mover": 2, "cause": "seven", "pre_roll": False,
                           "pirate": False, "hex": [0, 1], "prior_hex": [0, 0], "candidates": [], "public_vp": [2] * n,
                           "hand": [3] * n, "eligible": [1], "victim": 1, "card": "wood"}],
        "trade_events": [], "dev_events": [], "discard_events": [], "monopoly_events": [], "opening_picks": [],
        "vp_events": [{"action_index": 50, "roll_index": 49, "own_turn": 0, "phase": "end", "actor": None,
                       "action": "reveal", "changes": [], "board_vp": [2] * n}],
    }


class ReplayImportTest(ImportCase):
    """Decoded replays: set the replay fields, replacing hand-entered values and reporting each one, and write data/replays.json."""

    def write_replay(self, rec):
        self.replay_stats.mkdir(exist_ok=True)
        (self.replay_stats / f"{rec['replay_id']}.json").write_text(json.dumps(rec))

    def replays(self):
        return json.loads((self.data / "replays.json").read_text())["games"]

    def setUp(self):
        super().setUp()
        # -Rfix0001 is linked to the hand-entered game, which already has turns = 60
        self.write_replay(decoded_replay("-Rfix0001", [("uid-ben", 10), ("uid-ana", 14), ("uid-cat", 8)], turns=61))
        # -Rfix0002 has two guests, matched to rows by seat
        self.write_replay(decoded_replay("-Rfix0002", [("uid-zed", 13), ("uid-ana", 9), ("uid-dan", 9),
                                                       ("uid-ben", 11)]))

    def test_replay_fills_and_replaces_hand_entered_values(self):
        code, out = self.run_import("--write")
        self.assertEqual(code, 0, out)
        g = self.games()["2026-01-10-a"]
        self.assertEqual(g["turns"], 61)  # the replay wins over the hand-entered 60
        self.assertIn("corrected 2026-01-10-a: turns was 60, now 61 from the replay", out)
        self.assertEqual(g["dice"]["counts"]["8"], 61)
        ben = next(r for r in g["players"] if r["player"] == "ben")
        self.assertEqual(ben["resources_from_dice"], 40)
        ana = next(r for r in g["players"] if r["player"] == "ana")
        self.assertEqual(ana["vp_breakdown"]["settlements"], 14)
        self.assertIn("ana vp_breakdown was", out)
        self.assertNotIn("the replay says", out)

    def test_replays_json_uses_player_ids(self):
        self.run_import("--write")
        reps = self.replays()
        self.assertEqual(set(reps), {"2026-01-10-a", "2026-01-10-b"})
        guests = reps["2026-01-10-b"]
        self.assertEqual(set(guests["players"]), {"guest-1", "ana", "guest-2", "ben"})
        self.assertEqual(guests["players"]["guest-1"]["steals_by_victim"], {"ben": 2})
        self.assertEqual(guests["timeline"]["vp"]["ben"], [2, 11])
        text = (self.data / "replays.json").read_text()
        self.assertNotIn("uid-", text)  # raw account ids never land in data/

    def test_vp_mismatch_is_not_imported(self):
        self.write_replay(decoded_replay("-Rfix0001", [("uid-ben", 10), ("uid-ana", 13), ("uid-cat", 8)]))
        code, out = self.run_import("--write")
        self.assertEqual(code, 0, out)
        self.assertNotIn("2026-01-10-a", self.replays())
        self.assertIn("2026-01-10-a: the decoded replay's players or VP don't match this game", out)

    def test_rerun_is_stable(self):
        self.run_import("--write")
        first = [(self.data / f).read_text() for f in ("games.json", "replays.json")]
        self.run_import("--write")
        self.assertEqual([(self.data / f).read_text() for f in ("games.json", "replays.json")], first)

    def test_build_uses_replays(self):
        self.run_import("--write")
        out = self.tmp / "dist"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(build.build(data_dir=self.data, out_dir=out), 0)
        stats = json.loads((out / "data" / "stats.json").read_text())
        ana = next(p for p in stats["views"]["all"]["players"] if p["id"] == "ana")
        self.assertEqual(ana["replay"]["games"], 2)
        self.assertEqual(ana["replay"]["avg_steals"], 2)
        self.assertEqual(stats["timelines"]["2026-01-10-b"]["vp"]["ben"][:3], [2, 2, 2])
        self.assertEqual(len(stats["timelines"]["2026-01-10-b"]["vp"]["ben"]), 51)
        self.assertIn("guest-1", stats["game_replays"]["2026-01-10-b"])

    def test_two_seats_never_share_a_row(self):
        # Typed seats that disagree with TwoSheep can put a guest's seat on a member's row with equal VP.
        game = {"players": [{"player": "jd", "seat": 2, "vp": 8}, {"player": "guest-1", "seat": 1, "vp": 8},
                            {"player": "ana", "seat": 3, "vp": 10}]}
        rec = decoded_replay("-X", [("uid-jd", 8), ("uid-guest", 8), ("uid-ana", 10)])
        owner = {imp.account_key("uid-jd"): "jd", imp.account_key("uid-ana"): "ana"}
        self.assertIsNone(imp.replay_seats(game, rec, owner))

    def test_rows_without_seats_keep_their_fields(self):
        # A TwoSheep bot in the game leaves every seat unknown; refreshing must not drop replay fields.
        existing = {"players": [{"player": "ana", "seat": None, "game_color": "red", "vp": 9, "resources_from_dice": 50},
                                {"player": "ben", "seat": None, "game_color": "blue", "vp": 10, "resources_from_dice": 40}],
                    "winner": "ben", "settings": {}}
        new = {"players": [{"player": "ana", "seat": None, "game_color": "red", "vp": 9},
                           {"player": "ben", "seat": None, "game_color": "blue", "vp": 10}],
               "winner": "ben", "date": None, "settings": {"vp_to_win": None, "expansion": None, "scenario": None}}
        imp.refresh_imported(existing, new)
        self.assertEqual([r["resources_from_dice"] for r in existing["players"]], [50, 40])

    def test_bad_replays_json_is_rejected(self):
        self.run_import("--write")
        reps = json.loads((self.data / "replays.json").read_text())
        reps["games"]["2026-01-10-a"]["timeline"]["vp"]["ben"].append(3)
        errors, _ = build.validate(json.loads((self.data / "players.json").read_text()),
                                   json.loads((self.data / "games.json").read_text()), reps)
        self.assertTrue(any("timeline.vp needs one value per turn" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
