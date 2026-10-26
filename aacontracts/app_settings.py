"""Settings for aa-contracts, overridable from Alliance Auth's local.py.

Everything the plugin reads comes from corptools' already-synced contract
tables, so there is no ESI config here — only what counts as "the alliance",
how to decide a contract is live, and how to name hulls from titles.
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


# Entities a contract must be *assigned to* to count as "on alliance contract".
# Normally your alliance id(s); corp ids also work (e.g. a holding corp).
# Default is Northern Coalition. — override in local.py:
#   AACONTRACTS_ALLIANCE_IDS = [1727758877]
AACONTRACTS_ALLIANCE_IDS = _int_list(
    getattr(settings, "AACONTRACTS_ALLIANCE_IDS", [1727758877])
)

# Only count contracts that are still live. corptools marks a contract
# "outstanding" until it next re-syncs that contract's status, so expired or
# already-taken contracts linger for months. These two filters drop them:
#   - require date_expired in the future
#   - require the contract to be unaccepted (acceptor_id == 0)
AACONTRACTS_REQUIRE_NOT_EXPIRED = bool(
    getattr(settings, "AACONTRACTS_REQUIRE_NOT_EXPIRED", True)
)
AACONTRACTS_EXCLUDE_ACCEPTED = bool(
    getattr(settings, "AACONTRACTS_EXCLUDE_ACCEPTED", True)
)

# Restrict to a contract type, e.g. "item_exchange". Blank = any type.
AACONTRACTS_CONTRACT_TYPE = (
    getattr(settings, "AACONTRACTS_CONTRACT_TYPE", "") or ""
).strip()

# EVE inventory category id for ships. Never needs changing.
AACONTRACTS_SHIP_CATEGORY_ID = int(
    getattr(settings, "AACONTRACTS_SHIP_CATEGORY_ID", 6)
)

# Cache the aggregated dashboard for this many seconds (0 disables). The source
# data only moves when corptools re-syncs, so a short cache spares the DB.
AACONTRACTS_CACHE_SECONDS = int(getattr(settings, "AACONTRACTS_CACHE_SECONDS", 300))

# Abbreviation / nickname -> canonical hull name, used only when a contract has
# no synced item rows and its title doesn't literally contain a ship name.
# Keys are matched case-insensitively against the title's words (a single word)
# or as a phrase (multiple words). Your overrides are merged over these.
AACONTRACTS_DEFAULT_SHIP_ALIASES = {
    "hfi": "Hurricane Fleet Issue",
    "napoc": "Apocalypse Navy Issue",
    "cfi": "Cyclone Fleet Issue",
    "retri": "Retribution",
    "munin": "Muninn",
    "maelstron": "Maelstrom",      # common misspelling seen in titles
    "potifex": "Pontifex",         # common misspelling seen in titles
    "claymoire": "Claymore",       # common misspelling seen in titles
}
AACONTRACTS_SHIP_ALIASES = {
    **AACONTRACTS_DEFAULT_SHIP_ALIASES,
    **{
        str(k).strip().lower(): str(v).strip()
        for k, v in getattr(settings, "AACONTRACTS_SHIP_ALIASES", {}).items()
    },
}
