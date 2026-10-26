"""Views for aa-contracts: a dashboard page and a JSON feed of the same data."""
from __future__ import annotations

from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.shortcuts import render

from . import __version__, app_settings, queries


@login_required
@permission_required("aacontracts.view_contracts")
def index(request):
    summary = queries.build_summary()
    max_contracts = max((r["contracts"] for r in summary["ships"]), default=0)
    context = {
        "page_title": "Alliance Contracts",
        "version": __version__,
        "totals": summary["totals"],
        "ships": summary["ships"],
        "by_class": summary["by_class"],
        "max_contracts": max_contracts,
        "max_class": max((r["contracts"] for r in summary["by_class"]), default=0),
        "alliance_ids": app_settings.AACONTRACTS_ALLIANCE_IDS,
        "configured": bool(app_settings.AACONTRACTS_ALLIANCE_IDS),
    }
    return render(request, "aacontracts/contracts.html", context)


@login_required
@permission_required("aacontracts.view_contracts")
def data(request):
    """The dashboard's numbers as JSON, for scripts or external charting."""
    return JsonResponse(queries.build_summary())
