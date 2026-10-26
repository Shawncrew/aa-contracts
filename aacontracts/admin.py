from django.contrib import admin

from .models import (
    DoctrineConfig, FitAlert, GlobalConfig, Location, LocationDoctrine,
    PriceSnapshot, SeedTarget, ShipFit,
)


@admin.register(DoctrineConfig)
class DoctrineConfigAdmin(admin.ModelAdmin):
    list_display = ["doctrine", "enabled"]
    list_editable = ["enabled"]


@admin.register(GlobalConfig)
class GlobalConfigAdmin(admin.ModelAdmin):
    list_display = ["__str__", "price_markup_percent", "price_basis", "discord_enabled", "discord_channel_id"]


@admin.register(ShipFit)
class ShipFitAdmin(admin.ModelAdmin):
    list_display = ["match_name", "hull_name", "enabled", "custom_price", "jita_price", "price_updated"]
    list_display_links = ["hull_name"]
    list_editable = ["match_name", "enabled", "custom_price"]
    search_fields = ["match_name", "hull_name"]
    list_filter = ["enabled"]


class LocationDoctrineInline(admin.TabularInline):
    model = LocationDoctrine
    extra = 0


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ["name", "system_name", "location_id", "enabled", "order"]
    list_editable = ["enabled", "order"]
    inlines = [LocationDoctrineInline]


@admin.register(SeedTarget)
class SeedTargetAdmin(admin.ModelAdmin):
    list_display = ["location", "ship_fit", "target"]
    list_filter = ["location"]
    search_fields = ["ship_fit__match_name"]


@admin.register(FitAlert)
class FitAlertAdmin(admin.ModelAdmin):
    list_display = ["contract_id", "ship_fit", "issuer_name", "location", "last_seen"]
    search_fields = ["issuer_name", "title"]


@admin.register(PriceSnapshot)
class PriceSnapshotAdmin(admin.ModelAdmin):
    list_display = ["ship_fit", "timestamp", "jita_price", "final_price"]
    list_filter = ["ship_fit"]
