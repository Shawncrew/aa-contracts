"""Turn a contract into a hull name + class.

Two signals, in order of trust:

1. Synced item rows. When corptools has pulled a contract's items, exactly one
   included item is a ship (the hull). That's ground truth.
2. The contract title. corptools fetches items lazily, so most live contracts
   have none yet. Doctrine contracts hold one fitted hull and name it in the
   title, so we read the hull from the title: an alias (``HFI``), else a ship
   name that appears literally (``NC Maelstrom``). The first ship name in the
   title wins, which matches how fleets write them ("NC Guardian Zealot" is a
   Guardian for the Zealot fleet).

Ship names and their classes come from django-eveuniverse (inventory category
6 = Ship), so nothing about hull classes is hard-coded here.
"""
from __future__ import annotations

import re
from typing import Optional

_WORD = re.compile(r"[a-z0-9]+")

UNIDENTIFIED = "Unidentified"


def _tokens(text: str) -> list[str]:
    return _WORD.findall((text or "").lower())


def _contiguous_pos(hay: list[str], needle: list[str]) -> Optional[int]:
    """Start index where ``needle`` occurs as a contiguous run in ``hay``."""
    if not needle:
        return None
    last = len(hay) - len(needle)
    for i in range(last + 1):
        if hay[i : i + len(needle)] == needle:
            return i
    return None


def ship_catalog() -> dict[str, tuple[str, str]]:
    """``name_lower -> (name, class)`` for every ship hull known to eveuniverse."""
    from eveuniverse.models import EveType

    from . import app_settings

    catalog: dict[str, tuple[str, str]] = {}
    rows = EveType.objects.filter(
        eve_group__eve_category_id=app_settings.AACONTRACTS_SHIP_CATEGORY_ID
    ).values_list("name", "eve_group__name")
    for name, group in rows:
        catalog[name.lower()] = (name, group or "Ship")
    return catalog


def ship_type_index() -> dict[int, tuple[str, str]]:
    """``type_id -> (name, class)`` for every ship hull known to eveuniverse."""
    from eveuniverse.models import EveType

    from . import app_settings

    rows = EveType.objects.filter(
        eve_group__eve_category_id=app_settings.AACONTRACTS_SHIP_CATEGORY_ID
    ).values_list("id", "name", "eve_group__name")
    return {tid: (name, group or "Ship") for tid, name, group in rows}


def classify_title(
    title: str, catalog: dict[str, tuple[str, str]], aliases: dict[str, str]
) -> Optional[tuple[str, str]]:
    """Resolve ``(hull_name, class)`` from a contract title, or ``None``."""
    tokens = _tokens(title)
    if not tokens:
        return None
    token_set = set(tokens)

    # 1. Aliases (doctrine abbreviations / known misspellings).
    for key, ship in aliases.items():
        parts = key.split()
        matched = (
            parts[0] in token_set
            if len(parts) == 1
            else _contiguous_pos(tokens, parts) is not None
        )
        if matched:
            cls = catalog.get(ship.lower(), (ship, "Ship"))[1]
            return ship, cls

    # 2. A ship name appearing literally in the title; earliest start wins,
    #    then the longer (more specific) name.
    best = None
    best_pos = None
    best_len = 0
    for name_lower, (name, cls) in catalog.items():
        parts = name_lower.split()
        pos = _contiguous_pos(tokens, parts)
        if pos is None:
            continue
        if best is None or pos < best_pos or (pos == best_pos and len(parts) > best_len):
            best, best_pos, best_len = (name, cls), pos, len(parts)
    return best
