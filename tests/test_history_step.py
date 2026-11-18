"""Tests for the History step in scripts/build.py (add_history), with stand-in scripts in a temporary folder.
The real scripts/history.py only runs on the real data, so it is never run here.

    python -m unittest discover -s tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import build  # noqa: E402

GOOD = """import argparse, pathlib
ap = argparse.ArgumentParser(); ap.add_argument("--data"); ap.add_argument("--stats"); ap.add_argument("--out")
a = ap.parse_args()
pathlib.Path(a.out).write_text("window.HISTORY = {\\"v\\": 2};\\n", encoding="utf-8")
print("wrote 1 beat")
"""
BAD = """import sys
print("history_data.py: beat-x: premise failed: something changed")
sys.exit(1)
"""


class AddHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.data, self.out = base / "data", base / "dist"
        self.data.mkdir()
        (self.out / "data").mkdir(parents=True)
        self.good, self.bad = base / "good.py", base / "bad.py"
        self.good.write_text(GOOD)
        self.bad.write_text(BAD)

    def tearDown(self):
        self.tmp.cleanup()

    def test_skipped_without_eras(self):
        self.assertEqual(build.add_history(self.data, self.out, self.good), "skipped")
        self.assertFalse((self.out / "data" / "history.js").exists())

    def test_built_saves_the_good_copy(self):
        (self.data / "history_eras.json").write_text("{}")
        self.assertEqual(build.add_history(self.data, self.out, self.good), "built")
        built = (self.out / "data" / "history.js").read_text()
        self.assertIn("window.HISTORY", built)
        self.assertEqual((self.data / "history.js").read_text(), built)
        self.assertFalse((self.out / "data" / "history.tmp.js").exists())

    def test_failure_keeps_the_last_good_copy(self):
        (self.data / "history_eras.json").write_text("{}")
        (self.data / "history.js").write_text("window.HISTORY = {\"old\": true};\n")
        self.assertEqual(build.add_history(self.data, self.out, self.bad), "kept")
        self.assertIn("old", (self.out / "data" / "history.js").read_text())
        self.assertIn("old", (self.data / "history.js").read_text())

    def test_failure_without_a_copy(self):
        (self.data / "history_eras.json").write_text("{}")
        self.assertEqual(build.add_history(self.data, self.out, self.bad), "missing")
        self.assertFalse((self.out / "data" / "history.js").exists())


if __name__ == "__main__":
    unittest.main()
