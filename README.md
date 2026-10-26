# aa-contracts

An [Alliance Auth](https://gitlab.com/allianceauth/allianceauth) plugin for managing and
monitoring **doctrine ship seeding on alliance contracts**: which fits should be stocked
where, how many are up versus the target, what each should cost, and a live Discord status
report with shortage pings and fit-mismatch alerts.

It reads live contract state from [corptools](https://github.com/pvyParts/allianceauth-corptools)
and fit/doctrine definitions from [aa-fittings](https://gitlab.com/colcrunch/fittings); it does
not talk to ESI itself. Prices come from [Fuzzwork](https://www.fuzzwork.co.uk/) (Jita 4-4).

## Features

1. **Ship-type catalog from your fittings.** Every aa-fittings *fit* becomes a trackable
   "ship type". Because the same hull appears in several doctrines with different fits, each
   fit has an editable **match name** — the contract title it's seeded under — so contracts
   map to the right fit by their description. Manage it all on the *Ship types* page.
2. **Pricing.** Jita 4-4 fit value (hull + every fitted module) from Fuzzwork, plus a global
   markup %, with an optional per-fit custom price override. Shown in the catalog and dashboard.
3. **Locations.** Add the stations/citadels you seed at. Enable or disable each doctrine per
   location; only enabled doctrines appear on the dashboard and in reports. Set a per-fit
   **target** at each location — shortage = target − contracts up there.
4. **Discord status.** One message per location in a status channel, edited every minute, with
   🔴/🟢 per fit. When a location goes short it pings a configurable auth group (via its linked
   Discord role).
5. **Fit verification.** Each contract's items are reconciled against its aa-fittings fit. A
   single "Alerts" message in the same channel lists mismatches and pings the contract issuer.
6. **Price history.** Every price refresh records a snapshot per fit (`/contracts/fit/<id>/history.json`).

## Requirements

corptools (syncing corporate contracts), aa-fittings (with your doctrines/fits), django-eveuniverse,
and allianceauth-discordbot (for the status cog).

## Install

```bash
pip install git+https://github.com/Shawncrew/aa-contracts.git
```

`local.py`:

```python
INSTALLED_APPS += ["aacontracts"]
AACONTRACTS_ALLIANCE_IDS = [1727758877]      # assignee id(s) that count as "the alliance"
```

```bash
python manage.py migrate aacontracts
python manage.py collectstatic --noinput
# restart web + workers + discordbot
```

Then:

```bash
python manage.py contracts_sync_fits        # build the catalog from aa-fittings
python manage.py contracts_refresh_prices   # pull Jita 4-4 prices
```

Grant **`aacontracts.view_contracts`** (dashboard) / **`aacontracts.manage_contracts`** (admin
pages) to groups. A **Contracts** item appears in the sidebar.

### Configure

- *Ship types* page: set each fit's match name, enable the ones you seed, optional custom price.
- *Locations* page: add stations, tick doctrines, set targets per fit.
- *Settings* page: markup %, price basis, and Discord (enable, channel id, ping group, interval).

## Settings (local.py)

| Setting | Default | Meaning |
|---|---|---|
| `AACONTRACTS_ALLIANCE_IDS` | `[1727758877]` | Assignee id(s) that count as the alliance. |
| `AACONTRACTS_REQUIRE_NOT_EXPIRED` | `True` | Count only unexpired contracts. |
| `AACONTRACTS_EXCLUDE_ACCEPTED` | `True` | Count only unaccepted contracts. |
| `AACONTRACTS_JITA_STATION_ID` | `60003760` | Fuzzwork station for pricing (Jita 4-4). |
| `AACONTRACTS_CACHE_SECONDS` | `120` | Dashboard report cache. |

Everything else (markup, Discord channel/group, interval, price basis) is edited in-app on the
Settings page and stored in the database.

### Scheduling

The Discord cog enqueues the heavy work (price refresh, report build, fit verification) each
cycle, so with the cog enabled no cron is required. To also run it without Discord, add a beat
schedule for `aacontracts.tasks.update_status`, or run the management commands from cron.

## Permissions

| Codename | Grants |
|---|---|
| `aacontracts.view_contracts` | Dashboard, JSON, price history. |
| `aacontracts.manage_contracts` | Ship types, locations, settings pages. |

## License

MIT
