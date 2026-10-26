"""Print the per-location seeding report to the console."""
from django.core.management.base import BaseCommand

from ... import queries


class Command(BaseCommand):
    help = "Print ships on alliance contracts per location (available / target / shortage)."

    def handle(self, *args, **options):
        report = queries.build_report(use_cache=False)
        if not report["locations"]:
            self.stdout.write("No locations configured.")
            return
        for loc in report["locations"]:
            self.stdout.write(self.style.MIGRATE_HEADING(
                f"== {loc['name']} ({loc['short_count']} short) =="
            ))
            for doc in loc["doctrines"]:
                self.stdout.write(f"  {doc['doctrine_name']}")
                for r in doc["rows"]:
                    flag = "SHORT" if r["shortage"] else ""
                    price = f"{r['price']:,.0f}" if r["price"] else "-"
                    self.stdout.write(
                        f"    {r['name']:<28} {r['available']:>3}/{r['target']:<3} "
                        f"short={r['shortage']:<3} {price:>15} {flag}"
                    )
