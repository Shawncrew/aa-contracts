"""Recognize interchangeable modules using CCP's imported static item data."""
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import math
import re


_FACTION_COUNTER = re.compile(r"^rigSet\w+Module$")
_FACTION_COUNTER_EFFECT = re.compile(r"^rigSet\w+BonusModAddSetRigGroup$")
# These classify an item's market tier. They do not change its performance.
_TIER_ATTRIBUTES = {"metaLevelOld", "metaLevel", "metaGroupID"}


@dataclass
class ModuleEquivalences:
    signatures: dict = field(default_factory=dict)
    strict_signatures: dict = field(default_factory=dict)
    faction_sensitive_types: set = field(default_factory=set)
    known_types: set = field(default_factory=set)

    def missing_items(self, expected, actual):
        """Reserve exact items first, then allocate equivalent surplus once."""
        remaining = Counter({type_id: max(0, count) for type_id, count in actual.items()})
        missing = {}
        for type_id, required in expected.items():
            used = min(required, remaining[type_id])
            remaining[type_id] -= used
            if used < required:
                missing[type_id] = required - used
        if not missing:
            return missing

        context = set(expected) | set(actual)
        # Faction counters affect Synchronizer rigs. Keep those counters when
        # any required or supplied item can use them, including cargo refits.
        strict = bool(context & self.faction_sensitive_types) or not context <= self.known_types
        signatures = self.strict_signatures if strict else self.signatures
        surplus = Counter()
        for type_id, count in remaining.items():
            signature = signatures.get(type_id)
            if signature is not None:
                surplus[signature] += count
        for type_id, required in list(missing.items()):
            signature = signatures.get(type_id)
            if signature is None:
                continue
            used = min(required, surplus[signature])
            surplus[signature] -= used
            if used == required:
                del missing[type_id]
            else:
                missing[type_id] -= used
        return missing


def _signature(item, attributes, effects):
    # Hulls, ammunition, drones and dynamically rolled Abyssal modules keep
    # their exact type requirements. Records without stats or effects do too.
    if (
        item["group__category_id"] != 7 or not item["published"]
        or item["is_dynamic_type"] or not attributes or not effects
        or any(not math.isfinite(value) for _, value in attributes)
    ):
        return None
    return (
        item["group_id"], item["variation_parent_type_id"] or item["pk"],
        item["mass"], item["volume"], item["capacity"], item["portion_size"],
        tuple(sorted(attributes)), tuple(sorted(effects)),
    )


def load_module_equivalences(type_ids):
    """Read the needed SDE rows once for a whole contract verification batch."""
    from django.apps import apps

    if not apps.is_installed("eve_sde"):
        return ModuleEquivalences()

    from eve_sde.models import ItemType, TypeDogma, TypeEffect

    items = list(ItemType.objects.filter(pk__in=type_ids).values(
        "pk", "group_id", "group__category_id", "variation_parent_type_id",
        "published", "is_dynamic_type", "mass", "volume", "capacity", "portion_size",
    ))
    attributes, strict_attributes = defaultdict(list), defaultdict(list)
    effects, strict_effects = defaultdict(list), defaultdict(list)
    result = ModuleEquivalences(known_types={item["pk"] for item in items})

    for type_id, attribute_id, name, default, value in TypeDogma.objects.filter(
        item_type_id__in=type_ids,
    ).values_list(
        "item_type_id", "dogma_attribute_id", "dogma_attribute__name",
        "dogma_attribute__default_value", "value",
    ):
        if name.startswith("rigSet") and not _FACTION_COUNTER.fullmatch(name):
            result.faction_sensitive_types.add(type_id)
        if name not in _TIER_ATTRIBUTES and value != default:
            strict_attributes[type_id].append((attribute_id, value))
            if not _FACTION_COUNTER.fullmatch(name):
                attributes[type_id].append((attribute_id, value))

    for type_id, effect_id, name, is_default in TypeEffect.objects.filter(
        item_type_id__in=type_ids,
    ).values_list("item_type_id", "dogma_effect_id", "dogma_effect__name", "is_default"):
        faction_counter = _FACTION_COUNTER_EFFECT.fullmatch(name)
        if "rigset" in name.lower() and not faction_counter:
            result.faction_sensitive_types.add(type_id)
        strict_effects[type_id].append((effect_id, is_default))
        if not faction_counter:
            effects[type_id].append((effect_id, is_default))

    for item in items:
        type_id = item["pk"]
        result.signatures[type_id] = _signature(item, attributes[type_id], effects[type_id])
        result.strict_signatures[type_id] = _signature(item, strict_attributes[type_id], strict_effects[type_id])
    return result
