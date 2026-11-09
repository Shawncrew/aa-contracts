"""Build the per-location seeding report (dashboard + Discord share this)."""
from __future__ import annotations

from django.core.cache import cache
from django.utils import timezone

from . import app_settings, pricing
from .matching import _norm, availability_by_location
from .models import GlobalConfig, Location, SeedTarget, ShipFit


REPORT_CACHE_KEY = "aacontracts:report"


def invalidate_report():
    """Drop the cached dashboard report so the next load rebuilds it.

    Called after any admin change (catalog, locations, targets, settings) so
    edits show immediately instead of waiting out the cache window.
    """
    cache.delete(REPORT_CACHE_KEY)


def candidate_locations():
    """Stations/structures where alliance contracts exist, for the location picker.

    Returns ``[{location_id, name}]`` sorted by name, resolved from corptools'
    EveLocation names so users pick by name instead of typing a raw id.
    """
    from corptools.models import CorporateContract

    rows = (
        CorporateContract.objects.filter(assignee_id__in=app_settings.AACONTRACTS_ALLIANCE_IDS)
        .exclude(start_location_id=None)
        .values_list(
            "start_location_id",
            "start_location_name__location_name",
            "start_location_name__system__name",
        )
        .distinct()
    )
    out: dict[int, dict] = {}
    for lid, name, system in rows:
        if lid and lid not in out:
            out[lid] = {"location_id": lid, "name": name or f"Location {lid}", "system": system or ""}
    return sorted(out.values(), key=lambda x: x["name"])


def location_system_map():
    """``{location_id: system_name}`` for the candidate stations."""
    return {c["location_id"]: c["system"] for c in candidate_locations()}


def _fits_by_doctrine():
    """``{doctrine_id: [ShipFit, ...]}`` limited to globally-enabled doctrines."""
    from .matching import enabled_doctrine_ids

    enabled = enabled_doctrine_ids()
    out: dict[int, list] = {}
    qs = ShipFit.objects.filter(
        fitting__doctrines__id__in=enabled
    ).distinct().select_related("fitting").prefetch_related("fitting__doctrines")
    for sf in qs:
        for d in sf.fitting.doctrines.all():
            if d.id in enabled:
                out.setdefault(d.id, []).append(sf)
    return out


def _doctrine_names():
    from fittings.models import Doctrine

    return dict(Doctrine.objects.values_list("id", "name"))


def participation_report() -> dict:
    """Who is seeding: each main character and the contracts they have up.

    Rows are every member of the suppliers group (the configured ping group),
    plus any other main character with live alliance contracts, ranked by how
    many contracts they have up. Each row carries a per-ship-type breakdown.
    """
    from collections import Counter

    from . import matching

    cfg = GlobalConfig.get()
    live = matching.live_contracts()
    issuer_ids = {c["issuer_id"] for c in live}
    mains = matching.resolve_mains(issuer_ids)
    names = matching.resolve_names(issuer_ids)
    matchers = matching.build_matchers()

    agg: dict = {}

    def bucket(name):
        return agg.setdefault(name, {"total": 0, "ships": Counter(), "in_group": False})

    # Seed every suppliers-group member's main at zero so non-seeders still show.
    group = cfg.suppliers_group or cfg.ping_group
    if group is not None:
        members = group.user_set.select_related("profile__main_character").all()
        for user in members:
            prof = getattr(user, "profile", None)
            mc = getattr(prof, "main_character", None) if prof else None
            if mc and mc.character_name:
                bucket(mc.character_name)["in_group"] = True

    # Tally live contracts by issuer's main, broken down by ship type.
    for c in live:
        iid = c["issuer_id"]
        main = mains.get(iid) or names.get(iid) or f"char {iid}"
        fit = matching.match_title(c["title"], matchers)
        ship = fit.match_name if (fit and fit.match_name) else (c["title"] or "Unknown").strip()
        b = bucket(main)
        b["total"] += 1
        b["ships"][ship or "Unknown"] += 1

    participants = [
        {
            "main_name": name,
            "total": v["total"],
            "in_group": v["in_group"],
            "ships": [{"name": n, "count": ct} for n, ct in v["ships"].most_common()],
        }
        for name, v in agg.items()
    ]
    participants.sort(key=lambda p: (-p["total"], p["main_name"].lower()))
    return {
        "participants": participants,
        "total_contracts": len(live),
        "group_name": group.name if group is not None else None,
    }


def build_report(use_cache=True) -> dict:
    """Per-location, per-doctrine rows with available / target / shortage / price."""
    cfg = GlobalConfig.get()
    cache_key = REPORT_CACHE_KEY
    if use_cache and app_settings.AACONTRACTS_CACHE_SECONDS:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    availability = availability_by_location()        # {eve_loc_id: {norm_match_name: count}}
    fits_by_doc = _fits_by_doctrine()
    doc_names = _doctrine_names()
    markup = cfg.price_markup_percent

    # Targets: {(location_id, fit_id): target}
    targets = {
        (t.location_id, t.ship_fit_id): t.target
        for t in SeedTarget.objects.all()
    }

    # Individually-enabled fits (ShipFit.enabled=True) are tracked independently
    # of the doctrine toggles — the "enable a single ship instead of a whole
    # doctrine" path. They have no doctrine group to render under, so they get a
    # synthetic "Individual ships" group per location.
    individual_fits = sorted(
        ShipFit.objects.filter(enabled=True).select_related("fitting"),
        key=lambda f: (f.hull_name, f.match_name),
    )

    def _row(sf, avail, loc_markup):
        # Availability is keyed by match name, so every fit sharing a name
        # (NM Hyena / Rokh - Hyena) draws from the same contract pool.
        available = avail.get(_norm(sf.match_name), 0) if sf.match_name else 0
        target = targets.get((loc.id, sf.id), 0)
        # Tier: ok = at/above target, low = some but short, none = short with
        # nothing seeded at all. Shared by the dashboard and Discord colouring.
        if available >= target:
            tier = "ok"
        elif available > 0:
            tier = "low"
        else:
            tier = "none"
        return {
            "fit_id": sf.id,
            "hull": sf.hull_name,
            "name": sf.match_name or sf.hull_name,
            "available": available,
            "target": target,
            "shortage": max(0, target - available),
            "tier": tier,
            "price": pricing.final_price(sf, loc_markup),
        }

    locations = []
    for loc in Location.objects.filter(enabled=True).prefetch_related("doctrines"):
        avail = availability.get(loc.location_id, {})
        # Effective markup here: the greater of the global markup and this
        # location's minimum, so remote stations can be priced higher.
        loc_markup = max(markup, loc.min_markup_percent or 0)
        loc_doctrines = []
        loc_short = 0
        for ld in loc.doctrines.filter(enabled=True):
            rows = []
            doc_short = 0
            for sf in sorted(fits_by_doc.get(ld.doctrine_id, []), key=lambda f: (f.hull_name, f.match_name)):
                r = _row(sf, avail, loc_markup)
                if r["shortage"] > 0:
                    doc_short += 1
                rows.append(r)
            if rows:
                loc_doctrines.append({
                    "doctrine_id": ld.doctrine_id,
                    "doctrine_name": doc_names.get(ld.doctrine_id, f"Doctrine {ld.doctrine_id}"),
                    "rows": rows,
                    "short_count": doc_short,
                })
                loc_short += doc_short

        # Individual ships: those not already shown under an enabled doctrine
        # here, that have a target set or stock on contract at this location.
        shown = {r["fit_id"] for d in loc_doctrines for r in d["rows"]}
        indiv_rows, indiv_short = [], 0
        for sf in individual_fits:
            if sf.id in shown:
                continue
            r = _row(sf, avail, loc_markup)
            if r["target"] == 0 and r["available"] == 0:
                continue
            if r["shortage"] > 0:
                indiv_short += 1
            indiv_rows.append(r)
        if indiv_rows:
            loc_doctrines.append({
                "doctrine_id": None,
                "doctrine_name": "Individual ships",
                "rows": indiv_rows,
                "short_count": indiv_short,
            })
            loc_short += indiv_short

        locations.append({
            "id": loc.id,
            "location": loc,
            "name": loc.name,
            "system_name": loc.system_name,
            "doctrines": loc_doctrines,
            "short_count": loc_short,
            "markup": float(loc_markup),
        })

    result = {
        "locations": locations,
        "markup": float(markup),
        "generated": timezone.now().isoformat(),
    }
    if use_cache and app_settings.AACONTRACTS_CACHE_SECONDS:
        cache.set(cache_key, result, app_settings.AACONTRACTS_CACHE_SECONDS)
    return result
