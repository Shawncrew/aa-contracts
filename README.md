# aa-contracts

An [Alliance Auth](https://gitlab.com/allianceauth/allianceauth) plugin that shows,
on one page, **which ships are currently up on your alliance's contracts and how many
of each** — grouped by hull and by hull class.

It does **not** talk to ESI itself. It reads the contract data that
[corptools](https://github.com/pvyParts/allianceauth-corptools) already syncs, so the
only requirement is that corptools is installed and pulling corporate contracts for
corps that can see the alliance contracts.

## What it shows

- Headline tiles: identified hulls, distinct ship types, most-stocked hull, live contract count.
- A sortable, filterable table of every hull with its class and contract count.
- A breakdown by hull class.
- A JSON feed of the same numbers at `/contracts/data.json`.

### How a contract becomes a ship

1. **Synced item rows** (ground truth). When corptools has pulled a contract's items,
   the one included ship item is the hull.
2. **The contract title.** corptools fetches items lazily, so most live contracts have
   none yet. Doctrine contracts hold one fitted hull and name it in the title, so the
   hull is read from the title — a configured alias (e.g. `HFI`), otherwise a ship name
   that appears literally. Ship names and classes come from
   [django-eveuniverse](https://gitlab.com/ErikKalkoken/django-eveuniverse)
   (inventory category 6).

### Why "live" ≠ corptools "outstanding"

corptools only updates a contract's `status` when it next re-syncs that contract, so
expired or already-taken contracts linger as `outstanding` for months. By default this
plugin counts a contract only if it is **not expired** (`date_expired` in the future)
and **not accepted** (`acceptor_id == 0`). The method card on the page shows both the
live count and the raw "outstanding" count for context.

## Install

```bash
pip install git+https://github.com/Shawncrew/aa-contracts.git
```

Add the app and configure it in your Alliance Auth `local.py`:

```python
INSTALLED_APPS += ["aacontracts"]

# Required: the alliance (or corp) id(s) whose contracts to show.
AACONTRACTS_ALLIANCE_IDS = [1727758877]
```

Then migrate and restart:

```bash
python manage.py migrate aacontracts
python manage.py collectstatic --noinput
# restart gunicorn
```

Grant the **Can view the alliance contracts dashboard**
(`aacontracts.view_contracts`) permission to a group or user. A **Contracts** item
then appears in the sidebar.

## Settings

All optional except `AACONTRACTS_ALLIANCE_IDS`.

| Setting | Default | Meaning |
|---|---|---|
| `AACONTRACTS_ALLIANCE_IDS` | `[1727758877]` | Assignee id(s) that count as "the alliance". Corp ids work too. |
| `AACONTRACTS_REQUIRE_NOT_EXPIRED` | `True` | Only count contracts whose `date_expired` is in the future. |
| `AACONTRACTS_EXCLUDE_ACCEPTED` | `True` | Only count unaccepted contracts (`acceptor_id == 0`). |
| `AACONTRACTS_CONTRACT_TYPE` | `""` | Restrict to a contract type, e.g. `"item_exchange"`. Blank = any. |
| `AACONTRACTS_CACHE_SECONDS` | `300` | Cache the aggregated page for N seconds. `0` disables. |
| `AACONTRACTS_SHIP_ALIASES` | `{}` | Title abbreviation/nickname → hull name, merged over the built-ins (`HFI`, `NAPOC`, `CFI`, …). |

Example alias override:

```python
AACONTRACTS_SHIP_ALIASES = {
    "nid": "Nightmare",
    "sabre fleet": "Sabre",
}
```

## Verify from the shell

```bash
python manage.py contracts_report --no-cache
```

## Permissions

| Codename | Grants |
|---|---|
| `aacontracts.view_contracts` | See the dashboard and the JSON feed. |
| `aacontracts.manage_contracts` | Reserved for future admin/detail views. |

## License

MIT
