"""Refresh Jita 4-4 prices (Fuzzwork) for every enabled fit, with history."""
from django.core.management.base import BaseCommand

from ... import pricing


class Command(BaseCommand):
    help = "Fetch Jita 4-4 prices from Fuzzwork and recompute every fit's price."

    def add_arguments(self, parser):
        parser.add_argument("--no-snapshot", action="store_true", help="Don't record price history.")

    def handle(self, *args, **options):
        n = pricing.refresh_all_prices(snapshot=not options["no_snapshot"])
        self.stdout.write(self.style.SUCCESS(f"Priced {n} fits."))
