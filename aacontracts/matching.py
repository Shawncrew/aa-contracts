"""Match live contracts to ShipFits and compute per-location availability.

Live contract state comes from corptools. A contract is matched to a fit when
the fit's admin-set ``match_name`` appears in the contract title; the longest
match_name wins, so "NC Loki Links" beats a looser "Loki".
"""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    return _WS.sub(" ", (text or "").strip().lower())


def enabled_doctrine_ids():
    """Doctrine ids globally enabled in the catalog."""
    from .models import DoctrineConfig

    return set(DoctrineConfig.objects.filter(enabled=True).values_list("doctrine_id", flat=True))


def enabled_fits_qs():
    """Active ShipFits.

    A fit is active when its doctrine is enabled (doctrine-wide toggle) OR it is
    individually enabled (``ShipFit.enabled``). Either control activates a fit.
    """
    from django.db.models import Q

    from .models import ShipFit

    return ShipFit.objects.filter(
        Q(fitting__doctrines__id__in=enabled_doctrine_ids()) | Q(enabled=True)
    ).distinct()


def build_matchers():
    """Active fits (enabled doctrine) with a match_name, longest match_name first."""
    rows = []
    for fit in enabled_fits_qs().exclude(match_name="").select_related("fitting"):
        rows.append((_norm(fit.match_name), fit))
    rows.sort(key=lambda r: len(r[0]), reverse=True)
    return rows


def match_title(title: str, matchers):
    """Return the ShipFit whose match_name best matches ``title``, or None."""
    t = _norm(title)
    if not t:
        return None
    for name, fit in matchers:
        if name and name in t:
            return fit
    return None


def live_contracts_qs():
    """corptools contracts that are currently live and assigned to the alliance."""
    from django.utils import timezone

    from . import app_settings
    from corptools.models import CorporateContract

    qs = CorporateContract.objects.filter(
        assignee_id__in=app_settings.AACONTRACTS_ALLIANCE_IDS,
        status="outstanding",
    )
    if app_settings.AACONTRACTS_CONTRACT_TYPE:
        qs = qs.filter(contract_type=app_settings.AACONTRACTS_CONTRACT_TYPE)
    if app_settings.AACONTRACTS_REQUIRE_NOT_EXPIRED:
        qs = qs.filter(date_expired__gt=timezone.now())
    if app_settings.AACONTRACTS_EXCLUDE_ACCEPTED:
        qs = qs.filter(acceptor_id=0)
    return qs


def live_contracts():
    """One representative row per real contract (deduped across corp copies)."""
    from django.db.models import Min

    return list(
        live_contracts_qs()
        .values("contract_id")
        .annotate(
            title=Min("title"),
            start_location_id=Min("start_location_id"),
            issuer_id=Min("issuer_id"),
            pk_id=Min("id"),
        )
    )


def availability_by_location():
    """``{location_id: {ship_fit_id: count}}`` of live contracts matched per fit.

    Keyed by raw EVE location id (contract start location); the caller maps those
    to configured Locations.
    """
    matchers = build_matchers()
    result: dict[int, dict[int, int]] = {}
    for c in live_contracts():
        fit = match_title(c["title"], matchers)
        if fit is None:
            continue
        loc = c["start_location_id"] or 0
        result.setdefault(loc, {}).setdefault(fit.id, 0)
        result[loc][fit.id] += 1
    return result
