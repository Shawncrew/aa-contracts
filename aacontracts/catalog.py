"""Sync the ShipFit catalog from aa-fittings, and verify contract contents.

A ShipFit mirrors one aa-fittings ``Fitting``. We create/update one per fit,
seed ``match_name`` from the fit name (admins refine it to the real contract
title on the catalog page), and record the hull for pricing/display.
"""
from __future__ import annotations

import logging
import re

from .models import ShipFit

logger = logging.getLogger(__name__)


def _clean(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip())


def _hull_names(hull_ids):
    from eveuniverse.models import EveType

    return dict(
        EveType.objects.filter(id__in=list(hull_ids)).values_list("id", "name")
    )


def sync_fits(reset_match_names=False) -> dict:
    """Create/update a ShipFit for every aa-fittings Fitting.

    Returns counts. ``match_name`` is only seeded on creation (so admin edits
    survive re-syncs) unless ``reset_match_names`` is given.
    """
    from fittings.models import Doctrine, Fitting

    from .models import DoctrineConfig

    # Ensure a config row exists for every doctrine (disabled by default).
    for d in Doctrine.objects.all():
        DoctrineConfig.objects.get_or_create(doctrine=d)

    fits = list(Fitting.objects.all())
    hull_ids = {f.ship_type_type_id for f in fits if f.ship_type_type_id}
    names = _hull_names(hull_ids)

    created = updated = 0
    for f in fits:
        hull_id = f.ship_type_type_id
        hull_name = names.get(hull_id, "")
        obj, was_created = ShipFit.objects.get_or_create(
            fitting=f,
            defaults={
                "hull_type_id": hull_id or 0,
                "hull_name": hull_name,
                "match_name": _clean(f.name),
            },
        )
        if was_created:
            created += 1
            continue
        changed = False
        if obj.hull_type_id != (hull_id or 0):
            obj.hull_type_id = hull_id or 0
            changed = True
        if hull_name and obj.hull_name != hull_name:
            obj.hull_name = hull_name
            changed = True
        if reset_match_names:
            obj.match_name = _clean(f.name)
            changed = True
        if changed:
            obj.save()
            updated += 1
    return {"total_fits": len(fits), "created": created, "updated": updated}


def expected_items(fit: ShipFit) -> dict[int, int]:
    """Expected contract contents for a fit: hull + fitted items, type_id -> qty."""
    expected: dict[int, int] = {}
    if fit.hull_type_id:
        expected[int(fit.hull_type_id)] = expected.get(int(fit.hull_type_id), 0) + 1
    for tid, qty in fit.fitting.items.values_list("type_id", "quantity"):
        if tid:
            expected[int(tid)] = expected.get(int(tid), 0) + int(qty or 1)
    return expected


def verify_contract_items(contract_counts: dict[int, int], fit: ShipFit):
    """Compare a contract's included items against the fit.

    ``contract_counts`` is ``type_id -> quantity`` of the contract's included
    items. Returns ``(ok, detail)`` where detail names the first few
    discrepancies, or "" when they match.
    """
    from eveuniverse.models import EveType

    expected = expected_items(fit)
    missing = {}   # in fit, not (enough) in contract
    extra = {}     # in contract, not (expected) in fit
    for tid, qty in expected.items():
        have = contract_counts.get(tid, 0)
        if have < qty:
            missing[tid] = qty - have
    for tid, qty in contract_counts.items():
        exp = expected.get(tid, 0)
        if qty > exp:
            extra[tid] = qty - exp

    if not missing and not extra:
        return True, ""

    ids = list(missing) + list(extra)
    names = dict(EveType.objects.filter(id__in=ids).values_list("id", "name"))

    def fmt(d):
        parts = []
        for tid, qty in list(d.items())[:6]:
            parts.append(f"{names.get(tid, tid)} ×{qty}")
        if len(d) > 6:
            parts.append(f"+{len(d) - 6} more")
        return ", ".join(parts)

    bits = []
    if missing:
        bits.append("missing " + fmt(missing))
    if extra:
        bits.append("extra " + fmt(extra))
    return False, "; ".join(bits)
