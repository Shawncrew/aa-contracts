"""Settings for aa-contracts, overridable from Alliance Auth's local.py.

Live contract state is read from corptools; fits/doctrines from aa-fittings;
prices from Fuzzwork's Jita 4-4 aggregates. Runtime, editable configuration
(markup, Discord channel, ping group) lives in the GlobalConfig DB row, not
here — these are deploy-time defaults and constants.
"""
from django.conf import settings


def _int_list(value):
    out = []
    for v in value or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


# Assignee id(s) that count as "the alliance". Default Northern Coalition.
AACONTRACTS_ALLIANCE_IDS = _int_list(
    getattr(settings, "AACONTRACTS_ALLIANCE_IDS", [1727758877])
)

# Live-contract filters (corptools leaves expired/taken contracts "outstanding").
AACONTRACTS_REQUIRE_NOT_EXPIRED = bool(
    getattr(settings, "AACONTRACTS_REQUIRE_NOT_EXPIRED", True)
)
AACONTRACTS_EXCLUDE_ACCEPTED = bool(
    getattr(settings, "AACONTRACTS_EXCLUDE_ACCEPTED", True)
)
AACONTRACTS_CONTRACT_TYPE = (
    getattr(settings, "AACONTRACTS_CONTRACT_TYPE", "") or ""
).strip()

AACONTRACTS_SHIP_CATEGORY_ID = int(getattr(settings, "AACONTRACTS_SHIP_CATEGORY_ID", 6))

# Cache the aggregated dashboard for this many seconds (0 disables).
AACONTRACTS_CACHE_SECONDS = int(getattr(settings, "AACONTRACTS_CACHE_SECONDS", 120))

# --- Fuzzwork Jita 4-4 pricing -------------------------------------------
# Jita IV - Moon 4 - Caldari Navy Assembly Plant.
AACONTRACTS_JITA_STATION_ID = int(getattr(settings, "AACONTRACTS_JITA_STATION_ID", 60003760))
AACONTRACTS_FUZZWORK_URL = (
    getattr(settings, "AACONTRACTS_FUZZWORK_URL", "https://market.fuzzwork.co.uk/aggregates/")
).strip()
# How many type_ids per Fuzzwork request (keeps URLs sane).
AACONTRACTS_FUZZWORK_BATCH = int(getattr(settings, "AACONTRACTS_FUZZWORK_BATCH", 300))
AACONTRACTS_HTTP_TIMEOUT = int(getattr(settings, "AACONTRACTS_HTTP_TIMEOUT", 30))

# Default Discord status channel (NC.) used when GlobalConfig has none set yet.
AACONTRACTS_DEFAULT_DISCORD_CHANNEL_ID = getattr(
    settings, "AACONTRACTS_DEFAULT_DISCORD_CHANNEL_ID", None
)

# aadiscordbot cog(s) this plugin registers.
AACONTRACTS_DISCORD_BOT_COGS = getattr(
    settings, "AACONTRACTS_DISCORD_BOT_COGS", ["aacontracts.cogs.status"]
)
