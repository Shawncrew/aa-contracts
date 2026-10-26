"""Unit tests for title classification.

classify_title takes the catalog and aliases as plain dicts, and classify.py
has no import-time Django dependency, so these run with no Django or database:

    python tests/test_classify.py
    python -m pytest tests/test_classify.py
"""
import importlib.util
import os
import unittest

_CLASSIFY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "aacontracts",
    "classify.py",
)
_spec = importlib.util.spec_from_file_location("aacontracts_classify", _CLASSIFY_PATH)
classify = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(classify)


# A tiny stand-in for the eveuniverse ship catalog: name_lower -> (name, class)
CATALOG = {
    "hurricane fleet issue": ("Hurricane Fleet Issue", "Combat Battlecruiser"),
    "apocalypse navy issue": ("Apocalypse Navy Issue", "Battleship"),
    "cyclone fleet issue": ("Cyclone Fleet Issue", "Combat Battlecruiser"),
    "maelstrom": ("Maelstrom", "Battleship"),
    "muninn": ("Muninn", "Heavy Assault Cruiser"),
    "zealot": ("Zealot", "Heavy Assault Cruiser"),
    "guardian": ("Guardian", "Logistics Cruiser"),
    "heretic": ("Heretic", "Interdictor"),
    "retribution": ("Retribution", "Assault Frigate"),
    "loki": ("Loki", "Strategic Cruiser"),
    "rapier": ("Rapier", "Force Recon Ship"),
}

ALIASES = {
    "hfi": "Hurricane Fleet Issue",
    "napoc": "Apocalypse Navy Issue",
    "cfi": "Cyclone Fleet Issue",
    "retri": "Retribution",
    "maelstron": "Maelstrom",
}


class ClassifyTitleTests(unittest.TestCase):
    def c(self, title):
        return classify.classify_title(title, CATALOG, ALIASES)

    def test_alias_abbreviation(self):
        self.assertEqual(self.c("NC HFI")[0], "Hurricane Fleet Issue")
        self.assertEqual(self.c("NC NAPOC")[0], "Apocalypse Navy Issue")
        self.assertEqual(self.c("CFI NC Dec 2025")[0], "Cyclone Fleet Issue")

    def test_literal_ship_name(self):
        self.assertEqual(self.c("NC Maelstrom")[0], "Maelstrom")
        self.assertEqual(self.c("Highway Loki LL ModeCovops")[0], "Loki")
        self.assertEqual(self.c("Highway TP Rapier")[0], "Rapier")

    def test_misspelling_alias(self):
        self.assertEqual(self.c("NC Maelstron")[0], "Maelstrom")

    def test_first_ship_name_wins(self):
        # "NC Guardian Zealot Doctrine" is a Guardian for the Zealot fleet.
        self.assertEqual(self.c("NC Guardian Zealot Doctrine")[0], "Guardian")
        self.assertEqual(self.c("NC Heretic Zealot")[0], "Heretic")

    def test_class_is_returned(self):
        self.assertEqual(self.c("NC Maelstrom")[1], "Battleship")
        self.assertEqual(self.c("NC HFI")[1], "Combat Battlecruiser")

    def test_unmatched_title(self):
        self.assertIsNone(self.c("PVP"))
        self.assertIsNone(self.c("Station Startup Files"))
        self.assertIsNone(self.c(""))


if __name__ == "__main__":
    unittest.main()
