"""Background work: sync fits, refresh prices (with history), verify fits, and
cache the report the Discord cog renders.

These run in the Celery workers (which have DB + network), off the Discord bot's
event loop. The cog enqueues ``update_status`` each cycle and only reads the
cached results.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from . import catalog, matching, pricing, queries
from .models import FitAlert, GlobalConfig, Location, ShipFit

logger = logging.getLogger(__name__)

_PRICE_STALE_SECONDS = 1800  # refresh prices at most this often from the status loop


def _resolve_names(ids):
    """``eve_id -> name`` for characters/entities, via corptools' name cache."""
    ids = [i for i in ids if i]
    if not ids:
        return {}
    try:
        from corptools.models import EveName

        return dict(EveName.objects.filter(eve_id__in=ids).values_list("eve_id", "name"))
    except Exception:  # pragma: no cover - corptools name model optional
        return {}


@shared_task
def sync_fits_task(reset_match_names=False):
    return catalog.sync_fits(reset_match_names=reset_match_names)


@shared_task
def refresh_prices_task(snapshot=True):
    return pricing.refresh_all_prices(snapshot=snapshot)


@shared_task
def verify_fits_task():
    """Reconcile live matched contracts against their fits; update FitAlert rows."""
    from corptools.models import CorporateContractItem

    matchers = matching.build_matchers()
    live = matching.live_contracts()
    loc_by_eve = {loc.location_id: loc for loc in Location.objects.all()}

    matched = []
    for c in live:
        fit = matching.match_title(c["title"], matchers)
        if fit is not None:
            matched.append((c, fit))

    cids = [c["contract_id"] for c, _ in matched]
    # Included item counts per real contract, deduped across corp copies by record_id.
    item_counts: dict[int, dict[int, int]] = {}
    seen_records: set[tuple] = set()
    if cids:
        rows = CorporateContractItem.objects.filter(
            contract__contract_id__in=cids, is_included=True
        ).values_list("contract__contract_id", "record_id", "type_name_id", "quantity")
        for cid, rec, tid, qty in rows.iterator():
            key = (cid, rec)
            if key in seen_records:
                continue
            seen_records.add(key)
            d = item_counts.setdefault(cid, {})
            d[tid] = d.get(tid, 0) + int(qty or 1)

    names = _resolve_names({c["issuer_id"] for c, _ in matched})

    mismatches = []
    for c, fit in matched:
        counts = item_counts.get(c["contract_id"])
        if not counts:
            continue  # items not synced yet — can't verify, don't alert
        ok, detail = catalog.verify_contract_items(counts, fit)
        if ok:
            continue
        mismatches.append({
            "contract_id": c["contract_id"],
            "fit": fit,
            "location": loc_by_eve.get(c["start_location_id"]),
            "issuer_id": c["issuer_id"],
            "issuer_name": names.get(c["issuer_id"], ""),
            "title": c["title"],
            "detail": detail,
        })

    keep_ids = {m["contract_id"] for m in mismatches}
    with transaction.atomic():
        FitAlert.objects.exclude(contract_id__in=keep_ids).delete()
        for m in mismatches:
            FitAlert.objects.update_or_create(
                contract_id=m["contract_id"],
                defaults={
                    "ship_fit": m["fit"],
                    "location": m["location"],
                    "issuer_id": m["issuer_id"],
                    "issuer_name": m["issuer_name"],
                    "title": m["title"],
                    "detail": m["detail"],
                    "last_seen": timezone.now(),
                },
            )
    return {"matched": len(matched), "mismatches": len(mismatches)}


@shared_task
def update_status():
    """Orchestrator the Discord cog enqueues each cycle: prices, report, alerts."""
    # Refresh prices at most every _PRICE_STALE_SECONDS.
    newest = ShipFit.objects.filter(enabled=True).order_by("-price_updated").values_list(
        "price_updated", flat=True
    ).first()
    stale = newest is None or (timezone.now() - newest).total_seconds() > _PRICE_STALE_SECONDS
    if stale:
        try:
            pricing.refresh_all_prices(snapshot=True)
        except Exception:
            logger.exception("aa-contracts price refresh failed")

    report = queries.build_report(use_cache=False)
    cache.set("aacontracts:report", report, 300)

    try:
        verify_fits_task()
    except Exception:
        logger.exception("aa-contracts fit verification failed")
    return {"locations": len(report["locations"])}
