"""Build the per-location seeding report (dashboard + Discord share this)."""
from __future__ import annotations

from django.core.cache import cache
from django.db.models import Max, Min, Value
from django.db.models.functions import NullIf
from django.utils import timezone

from . import app_settings, pricing
from .matching import _norm, availability_by_location
from .models import GlobalConfig, Location, SeedTarget, ShipFit


REPORT_CACHE_KEY = "aacontracts:report"


def _fill_color(available, target):
    """Sliding red→green scale by fill percentage (available / target).

    Returns ``(fill_pct, css_color)``. Hue runs 0° (red, nothing seeded) through
    60° (yellow, half) to 120° (green, at/above target), so the colour slides
    continuously rather than snapping between a few tiers. Rows with no target
    have nothing to measure against, so they get ``(None, None)`` (uncoloured).
    """
    if target <= 0:
        return None, None
    frac = max(0.0, min(1.0, available / target))
    hue = round(120 * frac)
    # Semi-transparent so it reads over the dark dashboard and keeps text legible.
    return round(frac * 100), f"hsla({hue}, 70%, 42%, 0.45)"


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


# Look-back windows for the historical participation tab (key, label, days).
PARTICIPATION_RANGES = [
    ("7d", "7 days", 7),
    ("30d", "30 days", 30),
    ("3m", "3 months", 90),
    ("6m", "6 months", 182),
    ("1y", "1 year", 365),
    ("2y", "2 years", 730),
    ("3y", "3 years", 1095),
    ("all", "All time", None),
]


def participation_range_days(key):
    """Days for a range key (None = all time); defaults to 30 days."""
    for k, _label, days in PARTICIPATION_RANGES:
        if k == key:
            return days
    return 30


def _seed_suppliers(agg):
    """Seed every suppliers-group member's main at zero so non-seeders show too.

    Returns the group used (suppliers group, else the ping group, else None).
    """
    from collections import Counter

    cfg = GlobalConfig.get()
    group = cfg.suppliers_group or cfg.ping_group
    if group is not None:
        for user in group.user_set.select_related("profile__main_character").all():
            prof = getattr(user, "profile", None)
            mc = getattr(prof, "main_character", None) if prof else None
            if mc and mc.character_name:
                agg.setdefault(mc.character_name, {"total": 0, "ships": Counter(), "in_group": False})["in_group"] = True
    return group


def _participants(agg):
    """Sort the aggregate into ranked participant rows (most contracts first)."""
    rows = [
        {
            "main_name": name,
            "total": v["total"],
            "in_group": v["in_group"],
            "ships": [{"name": n, "count": ct} for n, ct in v["ships"].most_common()],
        }
        for name, v in agg.items()
    ]
    # "Unknown" (unattributed contracts) always sorts last, not as a top supplier.
    rows.sort(key=lambda p: (p["main_name"] == "Unknown", -p["total"], p["main_name"].lower()))
    return rows


def _tally_by_main(contracts):
    """Aggregate ``[{issuer_id, title}, ...]`` into ``{main: {total, ships, in_group}}``.

    Credits each contract to the issuer's main character and classifies the ship
    type by title (matched fit name, else the raw title). Seeds the suppliers
    group first so members with nothing show at zero.
    """
    from collections import Counter

    from . import matching

    agg: dict = {}
    group = _seed_suppliers(agg)

    issuer_ids = {c["issuer_id"] for c in contracts}
    mains = matching.resolve_mains(issuer_ids)
    names = matching.resolve_names(issuer_ids)
    matchers = matching.build_matchers()

    for c in contracts:
        iid = c["issuer_id"]
        # Pool contracts with no reliable issuer as "Unknown".
        main = "Unknown" if not iid else (mains.get(iid) or names.get(iid) or f"char {iid}")
        fit = matching.match_title(c["title"], matchers)
        ship = fit.match_name if (fit and fit.match_name) else (c["title"] or "Unknown").strip()
        b = agg.setdefault(main, {"total": 0, "ships": Counter(), "in_group": False})
        b["total"] += 1
        b["ships"][ship or "Unknown"] += 1

    return _participants(agg), (group.name if group is not None else None)


def participation_report() -> dict:
    """Active participation: each main and the contracts they have up now.

    Rows are every member of the suppliers group plus any other main with live
    alliance contracts, ranked by contracts up, each with a ship-type breakdown.
    """
    from . import matching

    live = matching.live_contracts()
    participants, group_name = _tally_by_main(live)
    return {
        "participants": participants,
        "total_contracts": len(live),
        "group_name": group_name,
    }


def participation_historical(days=None) -> dict:
    """Historical participation: ships sold (finished alliance contracts) per main.

    ``days`` is the look-back window (None = all time). Contracts are deduped by
    id (corp copies duplicate rows) and dated by completion.
    """
    from datetime import timedelta

    from corptools.models import CorporateContract

    qs = CorporateContract.objects.filter(
        assignee_id__in=app_settings.AACONTRACTS_ALLIANCE_IDS,
        status="finished",
    )
    if days is not None:
        qs = qs.filter(date_completed__gte=timezone.now() - timedelta(days=days))

    # Older CorpTools rows may have a zero issuer_id but retain the EVE
    # character ID in issuer_name_id. Prefer a numeric ID from any copy.
    rows = qs.order_by().values("contract_id").annotate(
        title=Min(NullIf("title", Value(""))),
        first_issuer=Min(NullIf("issuer_id", Value(0))),
        last_issuer=Max("issuer_id"),
        first_saved_issuer=Min(NullIf("issuer_name_id", Value(0))),
        last_saved_issuer=Max("issuer_name_id"),
    )
    contracts = []
    for row in rows:
        issuer = 0
        if row["first_issuer"] is not None:
            if row["first_issuer"] == row["last_issuer"]:
                issuer = row["first_issuer"]
        elif row["first_saved_issuer"] == row["last_saved_issuer"]:
            issuer = row["first_saved_issuer"] or 0
        contracts.append({"issuer_id": issuer, "title": row["title"] or ""})
    participants, group_name = _tally_by_main(contracts)
    return {
        "participants": participants,
        "total_sold": len(contracts),
        "group_name": group_name,
        "days": days,
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
        fill_pct, color = _fill_color(available, target)
        return {
            "fit_id": sf.id,
            "hull": sf.hull_name,
            "name": sf.match_name or sf.hull_name,
            "available": available,
            "target": target,
            "shortage": max(0, target - available),
            "tier": tier,
            "fill_pct": fill_pct,
            "color": color,
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
