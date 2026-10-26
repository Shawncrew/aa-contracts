"""Unit tests for the pure matcher (no Django needed).

    python tests/test_matching.py
"""
import importlib.util
import os
import unittest

_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "aacontracts", "matching.py"
)
_spec = importlib.util.spec_from_file_location("aacontracts_matching", _PATH)
matching = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(matching)


def make_matchers(pairs):
    """pairs: list of (match_name, fit_label). Mimics build_matchers() output."""
    rows = [(matching._norm(name), label) for name, label in pairs]
    rows.sort(key=lambda r: len(r[0]), reverse=True)
    return rows


class MatchTitleTests(unittest.TestCase):
    def setUp(self):
        self.m = make_matchers([
            ("NC HFI", "hfi"),
            ("NC Loki Links", "loki_links"),
            ("NC Loki NM", "loki_nm"),
            ("Loki", "loki_plain"),
            ("NC Maelstrom", "mael"),
        ])

    def test_exact(self):
        self.assertEqual(matching.match_title("NC HFI", self.m), "hfi")

    def test_substring_in_longer_title(self):
        self.assertEqual(matching.match_title("NC Maelstrom Oct 26", self.m), "mael")

    def test_longest_match_wins(self):
        # "NC Loki Links" must beat the looser "Loki".
        self.assertEqual(matching.match_title("NC Loki Links 2026", self.m), "loki_links")
        self.assertEqual(matching.match_title("NC Loki NM fleet", self.m), "loki_nm")

    def test_falls_back_to_loose(self):
        self.assertEqual(matching.match_title("Highway Loki DPS", self.m), "loki_plain")

    def test_no_match(self):
        self.assertIsNone(matching.match_title("Some random contract", self.m))
        self.assertIsNone(matching.match_title("", self.m))


if __name__ == "__main__":
    unittest.main()
