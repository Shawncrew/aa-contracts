"""Build the per-location seeding report (dashboard + Discord share this)."""
from __future__ import annotations

from django.core.cache import cache
from django.utils import timezone

from . import app_settings, pricing
from .matching import availability_by_location
from .models import GlobalConfig, Location, SeedTarget, ShipFit


def _fits_by_doctrine():
    """``{doctrine_id: [ShipFit, ...]}`` for enabled fits."""
    out: dict[int, list] = {}
    qs = ShipFit.objects.filter(enabled=True).select_related("fitting").prefetch_related(
        "fitting__doctrines"
    )
    for sf in qs:
        for d in sf.fitting.doctrines.all():
            out.setdefault(d.id, []).append(sf)
    return out


def _doctrine_names():
    from fittings.models import Doctrine

    return dict(Doctrine.objects.values_list("id", "name"))


def build_report(use_cache=True) -> dict:
    """Per-location, per-doctrine rows with available / target / shortage / price."""
    cfg = GlobalConfig.get()
    cache_key = "aacontracts:report"
    if use_cache and app_settings.AACONTRACTS_CACHE_SECONDS:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    availability = availability_by_location()        # {eve_loc_id: {fit_id: count}}
    fits_by_doc = _fits_by_doctrine()
    doc_names = _doctrine_names()
    markup = cfg.price_markup_percent

    # Targets: {(location_id, fit_id): target}
    targets = {
        (t.location_id, t.ship_fit_id): t.target
        for t in SeedTarget.objects.all()
    }

    locations = []
    for loc in Location.objects.filter(enabled=True).prefetch_related("doctrines"):
        avail = availability.get(loc.location_id, {})
        loc_doctrines = []
        loc_short = 0
        for ld in loc.doctrines.filter(enabled=True):
            rows = []
            doc_short = 0
            for sf in sorted(fits_by_doc.get(ld.doctrine_id, []), key=lambda f: (f.hull_name, f.match_name)):
                available = avail.get(sf.id, 0)
                target = targets.get((loc.id, sf.id), 0)
                shortage = max(0, target - available)
                if shortage > 0:
                    doc_short += 1
                price = pricing.final_price(sf, markup)
                rows.append({
                    "fit_id": sf.id,
                    "hull": sf.hull_name,
                    "name": sf.match_name or sf.hull_name,
                    "available": available,
                    "target": target,
                    "shortage": shortage,
                    "price": price,
                })
            if rows:
                loc_doctrines.append({
                    "doctrine_id": ld.doctrine_id,
                    "doctrine_name": doc_names.get(ld.doctrine_id, f"Doctrine {ld.doctrine_id}"),
                    "rows": rows,
                    "short_count": doc_short,
                })
                loc_short += doc_short
        locations.append({
            "id": loc.id,
            "location": loc,
            "name": loc.name,
            "system_name": loc.system_name,
            "doctrines": loc_doctrines,
            "short_count": loc_short,
        })

    result = {
        "locations": locations,
        "markup": float(markup),
        "generated": timezone.now().isoformat(),
    }
    if use_cache and app_settings.AACONTRACTS_CACHE_SECONDS:
        cache.set(cache_key, result, app_settings.AACONTRACTS_CACHE_SECONDS)
    return result
