"""Print the alliance-contracts hull summary to the console.

    python manage.py contracts_report

Useful for verifying the plugin's numbers on the server without the web UI.
"""
from django.core.cache import cache
from django.core.management.base import BaseCommand

from ... import app_settings, queries


class Command(BaseCommand):
    help = "Print a summary of ships currently on alliance contracts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-cache",
            action="store_true",
            help="Ignore the cached summary and recompute.",
        )

    def handle(self, *args, **options):
        if options["no_cache"]:
            cache.delete("aacontracts:summary")

        summary = queries.build_summary()
        t = summary["totals"]

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"Alliance contracts (assignee {app_settings.AACONTRACTS_ALLIANCE_IDS})"
            )
        )
        self.stdout.write(
            f"  live={t['live_total']}  classified={t['classified']}  "
            f"unidentified={t['unidentified']}  ship_types={t['ship_types']}"
        )
        self.stdout.write(
            f"  (corptools still lists {t['stale_outstanding']} as outstanding; "
            f"{t['with_item_data']} had synced item rows)"
        )
        self.stdout.write("")
        self.stdout.write(f"  {'SHIP':<28}{'CLASS':<26}{'CONTRACTS':>9}")
        for r in summary["ships"]:
            self.stdout.write(
                f"  {r['ship']:<28}{r['ship_class']:<26}{r['contracts']:>9}"
            )
