"""Create/update the ShipFit catalog from aa-fittings."""
from django.core.management.base import BaseCommand

from ... import catalog


class Command(BaseCommand):
    help = "Sync the ShipFit catalog from aa-fittings fittings."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-match-names", action="store_true",
            help="Re-seed every match name from the fit name (overwrites admin edits).",
        )

    def handle(self, *args, **options):
        res = catalog.sync_fits(reset_match_names=options["reset_match_names"])
        self.stdout.write(self.style.SUCCESS(
            f"Fits: {res['total_fits']} total, {res['created']} created, {res['updated']} updated."
        ))
