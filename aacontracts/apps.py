from django.apps import AppConfig

from . import __version__


class AaContractsConfig(AppConfig):
    name = "aacontracts"
    label = "aacontracts"
    verbose_name = f"Contracts v{__version__}"
    default_auto_field = "django.db.models.BigAutoField"
