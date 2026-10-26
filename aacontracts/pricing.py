"""Jita 4-4 pricing via Fuzzwork, fit valuation, markup and history.

A fit's computed price = hull + every fitted item, each at the configured Jita
4-4 figure, times (1 + markup). An admin ``custom_price`` on a ShipFit overrides
the whole thing (see ``ShipFit.effective_price``).
"""
from __future__ import annotations

import json
import logging
import urllib.request
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from . import app_settings
from .models import GlobalConfig, PriceSnapshot, ShipFit, TypePrice

logger = logging.getLogger(__name__)

_BASIS_FIELD = {
    "sell_percentile": ("sell", "percentile"),
    "sell_min": ("sell", "min"),
    "buy_percentile": ("buy", "percentile"),
    "buy_max": ("buy", "max"),
}


def _dec(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def fetch_fuzzwork_prices(type_ids, basis="sell_percentile") -> dict[int, Decimal]:
    """Return ``{type_id: unit_price}`` from Fuzzwork Jita 4-4 aggregates."""
    side, field = _BASIS_FIELD.get(basis, ("sell", "percentile"))
    ids = sorted({int(t) for t in type_ids if t})
    out: dict[int, Decimal] = {}
    batch = max(1, app_settings.AACONTRACTS_FUZZWORK_BATCH)
    for i in range(0, len(ids), batch):
        chunk = ids[i : i + batch]
        url = (
            f"{app_settings.AACONTRACTS_FUZZWORK_URL}?station="
            f"{app_settings.AACONTRACTS_JITA_STATION_ID}&types="
            + ",".join(str(t) for t in chunk)
        )
        req = urllib.request.Request(url, headers={"User-Agent": "aa-contracts/0.2 (AllianceAuth)"})
        with urllib.request.urlopen(req, timeout=app_settings.AACONTRACTS_HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for tid_str, agg in data.items():
            price = _dec(agg.get(side, {}).get(field))
            out[int(tid_str)] = price
    return out


def refresh_type_prices(type_ids, basis=None) -> dict[int, Decimal]:
    """Fetch prices and upsert them into the TypePrice cache."""
    if basis is None:
        basis = GlobalConfig.get().price_basis
    prices = fetch_fuzzwork_prices(type_ids, basis=basis)
    for tid, price in prices.items():
        TypePrice.objects.update_or_create(type_id=tid, defaults={"price": price})
    return prices


def fit_component_type_ids(fit: ShipFit) -> set[int]:
    """Hull + every fitted item type for one fit."""
    ids = {int(fit.hull_type_id)}
    for tid in fit.fitting.items.values_list("type_id", flat=True):
        if tid:
            ids.add(int(tid))
    return ids


def compute_fit_jita_price(fit: ShipFit, prices: dict[int, Decimal]) -> Decimal:
    """Raw fit value (no markup) from a type_id -> unit price map."""
    total = prices.get(int(fit.hull_type_id), Decimal("0"))
    for tid, qty in fit.fitting.items.values_list("type_id", "quantity"):
        if tid:
            total += prices.get(int(tid), Decimal("0")) * _dec(qty or 1)
    return total


def apply_markup(jita_price: Decimal, markup_percent: Decimal) -> Decimal:
    return (jita_price * (Decimal("1") + (markup_percent / Decimal("100")))).quantize(Decimal("1."))


def refresh_all_prices(snapshot=True) -> int:
    """Price every enabled fit: fetch the types it needs, compute, cache, snapshot.

    Returns the number of fits priced.
    """
    cfg = GlobalConfig.get()
    fits = list(ShipFit.objects.filter(enabled=True).select_related("fitting"))
    if not fits:
        return 0

    needed: set[int] = set()
    for fit in fits:
        needed |= fit_component_type_ids(fit)

    prices = refresh_type_prices(needed, basis=cfg.price_basis)
    # Fall back to anything already cached for types Fuzzwork didn't return.
    cached = dict(TypePrice.objects.values_list("type_id", "price"))
    cached.update({k: v for k, v in prices.items()})

    now = timezone.now()
    snapshots = []
    for fit in fits:
        jita = compute_fit_jita_price(fit, cached)
        fit.jita_price = jita
        fit.price_updated = now
        fit.save(update_fields=["jita_price", "price_updated"])
        if snapshot:
            final = fit.custom_price if fit.custom_price is not None else apply_markup(
                jita, cfg.price_markup_percent
            )
            snapshots.append(
                PriceSnapshot(ship_fit=fit, timestamp=now, jita_price=jita, final_price=final)
            )
    if snapshots:
        PriceSnapshot.objects.bulk_create(snapshots)
    return len(fits)


def final_price(fit: ShipFit, markup_percent=None) -> Decimal | None:
    """The price shown/charged: custom override, else Jita+markup."""
    if fit.custom_price is not None:
        return fit.custom_price
    if fit.jita_price is None:
        return None
    if markup_percent is None:
        markup_percent = GlobalConfig.get().price_markup_percent
    return apply_markup(fit.jita_price, markup_percent)
