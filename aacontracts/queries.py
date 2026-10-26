"""Read live alliance contracts from corptools and aggregate them by hull.

corptools stores one copy of a contract per corp that can see it, so every
count here dedupes by ``contract_id``.
"""
from __future__ import annotations

from django.core.cache import cache
from django.db.models import Min
from django.utils import timezone

from . import app_settings, classify


def _base_queryset():
    from corptools.models import CorporateContract

    qs = CorporateContract.objects.filter(
        assignee_id__in=app_settings.AACONTRACTS_ALLIANCE_IDS,
        status="outstanding",
    )
    if app_settings.AACONTRACTS_CONTRACT_TYPE:
        qs = qs.filter(contract_type=app_settings.AACONTRACTS_CONTRACT_TYPE)
    return qs


def _live_queryset():
    qs = _base_queryset()
    if app_settings.AACONTRACTS_REQUIRE_NOT_EXPIRED:
        qs = qs.filter(date_expired__gt=timezone.now())
    if app_settings.AACONTRACTS_EXCLUDE_ACCEPTED:
        qs = qs.filter(acceptor_id=0)
    return qs


def _item_hulls(contract_ids, type_index):
    """``contract_id -> (hull_name, class)`` from synced ship item rows."""
    from corptools.models import CorporateContractItem

    hulls: dict[int, tuple[str, str]] = {}
    rows = (
        CorporateContractItem.objects.filter(
            contract__contract_id__in=contract_ids,
            is_included=True,
            type_name_id__in=list(type_index.keys()),
        )
        .values_list("contract__contract_id", "type_name_id")
    )
    for cid, type_id in rows:
        if cid not in hulls and type_id in type_index:
            hulls[cid] = type_index[type_id]
    return hulls


def build_summary():
    """Aggregate the current live alliance contracts by hull.

    Returns a dict with ``ships`` (rows), ``by_class`` (rows) and ``totals``.
    """
    cache_key = "aacontracts:summary"
    ttl = app_settings.AACONTRACTS_CACHE_SECONDS
    if ttl:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    catalog = classify.ship_catalog()
    type_index = classify.ship_type_index()
    aliases = app_settings.AACONTRACTS_SHIP_ALIASES

    # One representative row per real contract (titles are identical across
    # the per-corp copies, so Min() just picks one).
    live = list(
        _live_queryset()
        .values("contract_id")
        .annotate(title=Min("title"))
    )
    contract_ids = [r["contract_id"] for r in live]
    item_hulls = _item_hulls(contract_ids, type_index)

    ships: dict[str, dict] = {}
    classified = 0
    unidentified = 0
    for row in live:
        cid = row["contract_id"]
        hull = item_hulls.get(cid)
        if hull is None:
            hull = classify.classify_title(row["title"], catalog, aliases)
        if hull is None:
            unidentified += 1
            ship_name, ship_class = classify.UNIDENTIFIED, classify.UNIDENTIFIED
        else:
            ship_name, ship_class = hull
            classified += 1
        bucket = ships.setdefault(
            ship_name, {"ship": ship_name, "ship_class": ship_class, "contracts": 0}
        )
        bucket["contracts"] += 1

    ship_rows = sorted(
        ships.values(), key=lambda r: (-r["contracts"], r["ship"])
    )

    by_class: dict[str, dict] = {}
    for r in ship_rows:
        c = by_class.setdefault(
            r["ship_class"],
            {"ship_class": r["ship_class"], "contracts": 0, "types": 0},
        )
        c["contracts"] += r["contracts"]
        c["types"] += 1
    class_rows = sorted(
        by_class.values(), key=lambda r: (-r["contracts"], r["ship_class"])
    )

    stale_outstanding = (
        _base_queryset().values("contract_id").distinct().count()
    )

    result = {
        "ships": ship_rows,
        "by_class": class_rows,
        "totals": {
            "live_total": len(live),
            "classified": classified,
            "unidentified": unidentified,
            "ship_types": len([r for r in ship_rows if r["ship"] != classify.UNIDENTIFIED]),
            "with_item_data": len(item_hulls),
            "stale_outstanding": stale_outstanding,
            "captured": timezone.now().isoformat(),
        },
    }
    if ttl:
        cache.set(cache_key, result, ttl)
    return result
