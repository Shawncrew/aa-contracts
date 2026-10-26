"""Data model for aa-contracts.

Catalog, locations, targets, pricing and alerts for contract seeding. The
plugin still reads *live contract state* from corptools (see ``matching.py`` /
``queries.py``); these models hold only the configuration and derived history
that corptools doesn't.
"""
from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import Group
from django.db import models
from django.utils import timezone


class General(models.Model):
    """Owns the app's permissions (managed = False, so no table)."""

    class Meta:
        managed = False
        default_permissions = ()
        permissions = (
            ("view_contracts", "Can view the alliance contracts dashboard"),
            ("manage_contracts", "Can manage contract locations, doctrines, prices and settings"),
        )


class GlobalConfig(models.Model):
    """Single-row app configuration (use ``GlobalConfig.get()``)."""

    singleton = models.PositiveSmallIntegerField(primary_key=True, default=1)

    # Pricing
    price_markup_percent = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0"),
        help_text="Percent added to every computed Jita 4-4 fit price (e.g. 5 = +5%).",
    )
    price_basis = models.CharField(
        max_length=20, default="sell_percentile",
        choices=[
            ("sell_percentile", "Jita sell — percentile (robust)"),
            ("sell_min", "Jita sell — lowest order"),
            ("buy_percentile", "Jita buy — percentile (robust)"),
            ("buy_max", "Jita buy — highest order"),
            ("sell_buy_split", "Jita split — avg of lowest sell & highest buy"),
        ],
        help_text="Which Fuzzwork Jita 4-4 figure to price items at.",
    )

    # Discord status reporting
    discord_channel_id = models.BigIntegerField(
        null=True, blank=True, help_text="Channel the per-location status messages are posted in."
    )
    ping_group = models.ForeignKey(
        Group, null=True, blank=True, on_delete=models.SET_NULL,
        help_text="Auth group pinged (via its linked Discord role) when a location is short.",
    )
    discord_update_seconds = models.PositiveIntegerField(default=60)
    discord_enabled = models.BooleanField(default=False)

    # Persistent ids of the two summary messages posted after the location
    # statuses: the shortage summary (pings the group) and the fit-mismatch
    # alerts (pings issuers).
    shortage_message_id = models.BigIntegerField(null=True, blank=True)
    alerts_message_id = models.BigIntegerField(null=True, blank=True)

    def save(self, *args, **kwargs):
        self.singleton = 1
        super().save(*args, **kwargs)

    @classmethod
    def get(cls) -> "GlobalConfig":
        obj, _ = cls.objects.get_or_create(singleton=1)
        return obj

    def __str__(self):
        return "Contracts configuration"


class DoctrineConfig(models.Model):
    """Global on/off for an aa-fittings doctrine.

    A fit is tracked (priced, matched, shown) when at least one doctrine it
    belongs to is enabled here. Per-location seeding is then chosen separately
    via LocationDoctrine.
    """

    doctrine = models.OneToOneField(
        "fittings.Doctrine", on_delete=models.CASCADE, related_name="aacontracts_config"
    )
    enabled = models.BooleanField(default=False)

    def __str__(self):
        return f"doctrine {self.doctrine_id} ({'on' if self.enabled else 'off'})"


class ShipFit(models.Model):
    """One trackable fit, mirroring an aa-fittings ``Fitting``.

    The Fitting is the source of truth for the hull, the fit's items and which
    doctrines it belongs to. We add a contract-title match string, an enabled
    flag, pricing overrides and a cached computed price.
    """

    fitting = models.OneToOneField(
        "fittings.Fitting", on_delete=models.CASCADE, related_name="aacontracts_shipfit"
    )
    hull_type_id = models.IntegerField(db_index=True)
    hull_name = models.CharField(max_length=128, blank=True)

    match_name = models.CharField(
        max_length=256, blank=True, db_index=True,
        help_text="Contract title this fit is seeded under (matched case-insensitively). "
                  "Set this to the contract description you use for this fit.",
    )
    # Individual opt-in, independent of the doctrine-wide toggle. A fit is
    # active when its doctrine is enabled OR this is set.
    enabled = models.BooleanField(default=False)

    custom_price = models.DecimalField(
        max_digits=20, decimal_places=2, null=True, blank=True,
        help_text="Override the computed price for this fit. Blank = use Jita 4-4 + markup.",
    )

    # Cached computed values (filled by the pricing task).
    jita_price = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    price_updated = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["hull_name", "match_name"]

    @property
    def effective_price(self):
        """Admin override if set, else the latest computed Jita+markup price."""
        if self.custom_price is not None:
            return self.custom_price
        return self.jita_price

    def __str__(self):
        return self.match_name or self.hull_name or f"fit {self.fitting_id}"


class Location(models.Model):
    """A station or citadel where contracts should be seeded."""

    name = models.CharField(max_length=128)
    location_id = models.BigIntegerField(
        db_index=True, help_text="EVE station/structure id (matches contract start location)."
    )
    system_name = models.CharField(max_length=64, blank=True)
    enabled = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    # Persistent id of this location's status message in the Discord channel.
    discord_message_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class LocationDoctrine(models.Model):
    """Enables one aa-fittings doctrine at one location."""

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="doctrines")
    doctrine = models.ForeignKey("fittings.Doctrine", on_delete=models.CASCADE)
    enabled = models.BooleanField(default=True)

    class Meta:
        unique_together = [("location", "doctrine")]

    def __str__(self):
        return f"{self.location} / doctrine {self.doctrine_id} ({'on' if self.enabled else 'off'})"


class SeedTarget(models.Model):
    """How many of a fit should be seeded at a location."""

    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name="targets")
    ship_fit = models.ForeignKey(ShipFit, on_delete=models.CASCADE, related_name="targets")
    target = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("location", "ship_fit")]

    def __str__(self):
        return f"{self.location} / {self.ship_fit}: {self.target}"


class PriceSnapshot(models.Model):
    """Historical price point for a fit (feature: price history)."""

    ship_fit = models.ForeignKey(ShipFit, on_delete=models.CASCADE, related_name="price_history")
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    jita_price = models.DecimalField(max_digits=20, decimal_places=2)
    final_price = models.DecimalField(max_digits=20, decimal_places=2)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [models.Index(fields=["ship_fit", "timestamp"])]


class TypePrice(models.Model):
    """Cached Jita 4-4 unit price per EVE type, from Fuzzwork."""

    type_id = models.BigIntegerField(primary_key=True)
    price = models.DecimalField(max_digits=20, decimal_places=2)
    updated = models.DateTimeField(auto_now=True)


class FitAlert(models.Model):
    """A live contract whose items don't match its fit (feature: fit verification)."""

    contract_id = models.BigIntegerField(db_index=True)
    ship_fit = models.ForeignKey(
        ShipFit, null=True, blank=True, on_delete=models.SET_NULL, related_name="alerts"
    )
    location = models.ForeignKey(
        Location, null=True, blank=True, on_delete=models.SET_NULL, related_name="alerts"
    )
    issuer_id = models.BigIntegerField()
    issuer_name = models.CharField(max_length=128, blank=True)
    title = models.CharField(max_length=256, blank=True)
    detail = models.TextField(blank=True)
    first_seen = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["issuer_name", "contract_id"]
