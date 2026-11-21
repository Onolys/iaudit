#!/usr/bin/env python3
"""Unit tests for next_prod_tag.py. Run: python3 scripts/ci/test_next_prod_tag.py"""
import subprocess
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import next_prod_tag as m  # noqa: E402


class NextTag(unittest.TestCase):
    def test_first_of_day(self):
        self.assertEqual(m.next_tag("2026-11-21", []), "prod-2026-11-21.1")

    def test_other_days_ignored(self):
        self.assertEqual(m.next_tag("2026-11-21", ["prod-2026-11-20.7", "v1.0.0"]), "prod-2026-11-21.1")

    def test_highest_plus_one_not_count(self):
        tags = ["prod-2026-11-21.1", "prod-2026-11-21.9", "prod-2026-11-21.10"]
        self.assertEqual(m.next_tag("2026-11-21", tags), "prod-2026-11-21.11")

    def test_gap_uses_highest(self):
        self.assertEqual(m.next_tag("2026-11-21", ["prod-2026-11-21.3"]), "prod-2026-11-21.4")

    def test_ref_forms_and_junk(self):
        tags = ["refs/tags/prod-2026-11-21.2", "prod-2026-11-21.2^{}", "prod-2026-11-21.x", "xprod-2026-11-21.50", "prod-2026-11-21.5-rc"]
        self.assertEqual(m.next_tag("2026-11-21", tags), "prod-2026-11-21.3")

    def test_bad_date(self):
        with self.assertRaises(ValueError):
            m.next_tag("2026-1-21", [])

    def test_cli(self):
        r = subprocess.run([sys.executable, str(HERE / "next_prod_tag.py"), "--date", "2026-11-21"],
                           input="prod-2026-11-21.1\nrefs/tags/prod-2026-11-21.2\n", capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (0, "prod-2026-11-21.3\n"))
        bad = subprocess.run([sys.executable, str(HERE / "next_prod_tag.py"), "--date", "nope"], input="", capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
