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


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.data = self.tmp / "data"
        shutil.copytree(FIXTURES / "data", self.data)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def run_import(self, *args):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = imp.main(["--data", str(self.data), "--raw", str(FIXTURES / "replays"), "--tz", TZ, *args])
        return code, out.getvalue()

    def games(self):
        return {g["id"]: g for g in json.loads((self.data / "games.json").read_text())["games"]}

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
        self.assertIn("3 new, 1 linked", out)
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
        self.assertEqual(g["settings"]["expansion"], None)
        self.assertEqual(g["settings"]["vp_to_win"], None)

    def test_date_uses_time_zone(self):
        self.run_import("--write")
        self.assertEqual(self.by_tsid()["-Rfix0007"]["date"], "2026-01-16")

    def test_rerun_changes_nothing(self):
        self.run_import("--write")
        first = (self.data / "games.json").read_text()
        code, out = self.run_import("--write")
        self.assertEqual(code, 0, out)
        self.assertIn("0 new, 0 linked to hand-entered games, 0 updated, 0 removed, 4 unchanged", out)
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
        self.assertIn("0 removed, 3 unchanged", out)

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
        self.assertIsNone(guest["rating_change"])
        self.assertEqual(self.stats["summary"]["games_with_guests"], 1)

    def test_guests_count_as_opponents(self):
        ben = next(p for p in self.stats["players"] if p["id"] == "ben")
        # Ben finished 2nd of 4 behind a guest winner in -Rfix0002: beat 2 of 3 opponents there.
        g = next(g for g in self.stats["games"] if g["twosheep_id"] == "-Rfix0002")
        self.assertEqual(next(r["rank"] for r in g["players"] if r["player"] == "ben"), 2)
        self.assertEqual(ben["games"], 4)
        self.assertEqual(ben["wins"], 0)

    def test_guest_starts_from_prior_each_game(self):
        # A guest's update must not leak: the same id "guest-1" in two games is two different people.
        players = {"schema_version": 1, "players": [{"id": "ana", "name": "Ana", "color_slot": 1}]}
        game = lambda gid, d: {"id": gid, "date": d, "winner": "guest-1", "players": [
            {"player": "guest-1", "vp": 10}, {"player": "ana", "vp": 5}, {"player": "guest-2", "vp": 4}]}
        from openskill.models import PlackettLuce
        m = PlackettLuce()
        ana = m.rate([[m.rating()], [m.rating()], [m.rating()]], ranks=[1, 2, 3])[1][0]
        expected = m.rate([[m.rating()], [ana], [m.rating()]], ranks=[1, 2, 3])[1][0]
        two = build.compute_views(players, {"games": [game("g1", "2026-01-01"), game("g2", "2026-01-02")]})["views"]["all"]
        got = two["players"][0]["rating"]
        self.assertAlmostEqual(got["mu"], expected.mu, places=3)
        self.assertAlmostEqual(got["sigma"], expected.sigma, places=3)

    def test_rejects_reserved_ids_and_all_guest_games(self):
        players = {"players": [{"id": "guest-9", "name": "X", "color_slot": 1}]}
        errors, _ = build.validate(players, {"games": [{"id": "g", "date": "2026-01-01", "winner": "guest-1",
                                                        "players": [{"player": "guest-1", "vp": 10},
                                                                    {"player": "guest-2", "vp": 3}]}]})
        self.assertTrue(any("reserved" in e for e in errors))
        self.assertTrue(any("every player is a guest" in e for e in errors))

    def test_duplicate_twosheep_id_rejected(self):
        players = {"players": [{"id": "ana", "name": "A", "color_slot": 1}, {"id": "ben", "name": "B", "color_slot": 2}]}
        g = lambda gid: {"id": gid, "date": "2026-01-01", "twosheep_id": "-X", "winner": "ana",
                         "players": [{"player": "ana", "vp": 10}, {"player": "ben", "vp": 3}]}
        errors, _ = build.validate(players, {"games": [g("a"), g("b")]})
        self.assertTrue(any("twosheep_id -X is already used" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
