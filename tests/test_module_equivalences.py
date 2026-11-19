"""Run with python tests/test_module_equivalences.py."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import unittest


PATH = Path(__file__).resolve().parents[1] / "aacontracts" / "module_equivalences.py"
spec = importlib.util.spec_from_file_location("module_equivalences", PATH)
modules = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = modules
spec.loader.exec_module(modules)


def module_signature(**changes):
    item = {
        "pk": 1, "group_id": 328, "group__category_id": 7,
        "variation_parent_type_id": 100, "published": True,
        "is_dynamic_type": False, "mass": 1, "volume": 5,
        "capacity": None, "portion_size": 1,
    }
    item.update(changes)
    return modules._signature(item, [(6, 30), (50, 16), (987, -55)], [(5231, True)])


class ModuleEquivalenceTests(unittest.TestCase):
    def setUp(self):
        equal = module_signature()
        self.rules = modules.ModuleEquivalences(
            signatures={1: equal, 2: equal, 3: equal},
            strict_signatures={1: ("faction-a",), 2: ("faction-b",), 3: ("faction-a",)},
            faction_sensitive_types={99},
            known_types={1, 2, 3, 99, 1000},
        )

    def test_equivalent_surplus_satisfies_a_missing_module(self):
        self.assertEqual(self.rules.missing_items({1: 2}, {1: 1, 2: 1}), {})

    def test_one_item_cannot_cover_two_requirements(self):
        self.assertEqual(self.rules.missing_items({1: 2}, {2: 1}), {1: 1})
        missing = self.rules.missing_items({1: 1, 3: 1}, {2: 1})
        self.assertEqual(sum(missing.values()), 1)

    def test_exact_items_are_reserved_before_substitution(self):
        self.assertEqual(self.rules.missing_items({1: 1, 2: 1}, {2: 1}), {1: 1})
        self.assertEqual(self.rules.missing_items({1: 1, 2: 1}, {2: 1, 3: 1}), {})

    def test_synchronizer_keeps_faction_differences(self):
        self.assertEqual(self.rules.missing_items({1: 1, 99: 1}, {2: 1, 99: 1}), {1: 1})
        self.assertEqual(self.rules.missing_items({1: 1}, {2: 1, 99: 1}), {1: 1})
        self.assertEqual(self.rules.missing_items({1: 1, 99: 1}, {3: 1, 99: 1}), {})

    def test_unknown_context_keeps_faction_differences(self):
        self.assertEqual(self.rules.missing_items({1: 1}, {2: 1, 999: 1}), {1: 1})

    def test_hulls_and_unknown_items_remain_exact(self):
        self.assertEqual(self.rules.missing_items({1000: 1}, {2: 1}), {1000: 1})
        self.assertEqual(modules.ModuleEquivalences().missing_items({5: 1}, {6: 1}), {5: 1})
        self.assertEqual(modules.ModuleEquivalences().missing_items({5: 1}, {5: 1}), {})

    def test_verification_never_mutates_supplied_counts(self):
        expected, actual = {1: 2}, {2: 3}
        original = deepcopy((expected, actual))
        self.rules.missing_items(expected, actual)
        self.assertEqual((expected, actual), original)

    def test_signature_includes_fitting_cost_and_effects(self):
        base = module_signature()
        self.assertNotEqual(base, module_signature(variation_parent_type_id=101))
        self.assertNotEqual(base, module_signature(volume=10))
        self.assertNotEqual(base, module_signature(group_id=999))
        self.assertIsNone(module_signature(is_dynamic_type=True))
        self.assertIsNone(module_signature(published=False))
        self.assertIsNone(module_signature(**{"group__category_id": 6}))

    def test_superior_or_inferior_stats_are_not_identical(self):
        base = self.rules.signatures[1]
        changed = list(base)
        changed[-2] = ((6, 30), (50, 15), (987, -55))
        self.rules.signatures[2] = tuple(changed)
        self.assertEqual(self.rules.missing_items({1: 1}, {2: 1}), {1: 1})
        changed[-2] = base[-2]
        changed[-1] = ((5231, False),)
        self.rules.signatures[2] = tuple(changed)
        self.assertEqual(self.rules.missing_items({1: 1}, {2: 1}), {1: 1})


if __name__ == "__main__":
    unittest.main()
