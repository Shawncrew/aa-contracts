"""Views: dashboard (view_contracts) and management pages (manage_contracts)."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from . import __version__, catalog, pricing, queries
from .forms import GlobalConfigForm, LocationForm
from .models import (
    GlobalConfig, Location, LocationDoctrine, PriceSnapshot, SeedTarget, ShipFit,
)


# --------------------------------------------------------------------------- #
#  Dashboard
# --------------------------------------------------------------------------- #
@login_required
@permission_required("aacontracts.view_contracts")
def index(request):
    report = queries.build_report()
    return render(request, "aacontracts/dashboard.html", {
        "page_title": "Alliance Contracts",
        "version": __version__,
        "report": report,
        "can_manage": request.user.has_perm("aacontracts.manage_contracts"),
    })


@login_required
@permission_required("aacontracts.view_contracts")
def data(request):
    report = queries.build_report()
    out = {"generated": report["generated"], "markup": report["markup"], "locations": []}
    for loc in report["locations"]:
        out["locations"].append({
            "name": loc["name"],
            "short_count": loc["short_count"],
            "doctrines": [
                {
                    "doctrine": d["doctrine_name"],
                    "ships": [
                        {k: (float(r[k]) if k == "price" and r[k] is not None else r[k])
                         for k in ("name", "hull", "available", "target", "shortage", "price")}
                        for r in d["rows"]
                    ],
                }
                for d in loc["doctrines"]
            ],
        })
    return JsonResponse(out)


# --------------------------------------------------------------------------- #
#  Catalog (ship types / fits): naming, pricing overrides, enable
# --------------------------------------------------------------------------- #
@login_required
@permission_required("aacontracts.manage_contracts")
def ship_catalog(request):
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "sync":
            res = catalog.sync_fits()
            messages.success(request, f"Synced fits from aa-fittings: {res}.")
            return redirect("aacontracts:catalog")
        if action == "refresh_prices":
            pricing_refresh(request)
            return redirect("aacontracts:catalog")
        # Save edited rows.
        changed = 0
        for fit in ShipFit.objects.all():
            prefix = str(fit.id)
            if f"match_name_{prefix}" not in request.POST:
                continue
            match_name = request.POST.get(f"match_name_{prefix}", "").strip()
            enabled = f"enabled_{prefix}" in request.POST
            raw_price = request.POST.get(f"custom_price_{prefix}", "").strip()
            custom_price = None
            if raw_price:
                try:
                    custom_price = Decimal(raw_price.replace(",", ""))
                except (InvalidOperation, ValueError):
                    custom_price = fit.custom_price
            dirty = False
            if fit.match_name != match_name:
                fit.match_name = match_name
                dirty = True
            if fit.enabled != enabled:
                fit.enabled = enabled
                dirty = True
            if fit.custom_price != custom_price:
                fit.custom_price = custom_price
                dirty = True
            if dirty:
                fit.save()
                changed += 1
        messages.success(request, f"Saved {changed} ship type(s).")
        return redirect("aacontracts:catalog")

    cfg = GlobalConfig.get()
    # Group fits by doctrine for display.
    from fittings.models import Doctrine

    doc_names = dict(Doctrine.objects.values_list("id", "name"))
    fits = ShipFit.objects.select_related("fitting").prefetch_related("fitting__doctrines").all()
    by_doc: dict = {}
    no_doc = []
    for sf in fits:
        docs = list(sf.fitting.doctrines.all())
        row = {"fit": sf, "price": pricing.final_price(sf, cfg.price_markup_percent)}
        if not docs:
            no_doc.append(row)
        for d in docs:
            by_doc.setdefault(d.id, {"name": doc_names.get(d.id, f"Doctrine {d.id}"), "rows": []})
            by_doc[d.id]["rows"].append(row)
    groups = sorted(by_doc.values(), key=lambda g: g["name"])
    if no_doc:
        groups.append({"name": "(no doctrine)", "rows": no_doc})

    return render(request, "aacontracts/catalog.html", {
        "page_title": "Contract ship types",
        "groups": groups,
        "config": cfg,
    })


def pricing_refresh(request):
    try:
        from .tasks import refresh_prices_task

        refresh_prices_task.delay()
        messages.info(request, "Price refresh queued (Jita 4-4 via Fuzzwork).")
    except Exception:
        # Fall back to running inline if Celery isn't available.
        n = pricing.refresh_all_prices()
        messages.success(request, f"Refreshed prices for {n} fits.")


# --------------------------------------------------------------------------- #
#  Settings
# --------------------------------------------------------------------------- #
@login_required
@permission_required("aacontracts.manage_contracts")
def settings_view(request):
    cfg = GlobalConfig.get()
    if request.method == "POST":
        form = GlobalConfigForm(request.POST, instance=cfg)
        if form.is_valid():
            form.save()
            messages.success(request, "Settings saved.")
            return redirect("aacontracts:settings")
    else:
        form = GlobalConfigForm(instance=cfg)
    return render(request, "aacontracts/settings.html", {
        "page_title": "Contracts settings", "form": form,
    })


# --------------------------------------------------------------------------- #
#  Locations
# --------------------------------------------------------------------------- #
@login_required
@permission_required("aacontracts.manage_contracts")
def locations(request):
    if request.method == "POST":
        form = LocationForm(request.POST)
        if form.is_valid():
            loc = form.save()
            messages.success(request, f"Added location {loc.name}.")
            return redirect("aacontracts:location_edit", pk=loc.pk)
    else:
        form = LocationForm()
    return render(request, "aacontracts/locations.html", {
        "page_title": "Contract locations",
        "locations": Location.objects.all(),
        "form": form,
    })


@login_required
@permission_required("aacontracts.manage_contracts")
def location_edit(request, pk):
    loc = get_object_or_404(Location, pk=pk)
    from fittings.models import Doctrine

    if request.method == "POST":
        action = request.POST.get("action")
        if action == "delete":
            loc.delete()
            messages.success(request, "Location deleted.")
            return redirect("aacontracts:locations")
        if action == "details":
            form = LocationForm(request.POST, instance=loc)
            if form.is_valid():
                form.save()
                messages.success(request, "Location updated.")
            return redirect("aacontracts:location_edit", pk=pk)
        # Doctrine toggles.
        enabled_doc_ids = {int(x) for x in request.POST.getlist("doctrine")}
        for d in Doctrine.objects.all():
            ld, _ = LocationDoctrine.objects.get_or_create(location=loc, doctrine=d)
            want = d.id in enabled_doc_ids
            if ld.enabled != want:
                ld.enabled = want
                ld.save()
        # Targets.
        for key, val in request.POST.items():
            if not key.startswith("target_"):
                continue
            try:
                fit_id = int(key[len("target_"):])
                target = max(0, int(val or 0))
            except ValueError:
                continue
            SeedTarget.objects.update_or_create(
                location=loc, ship_fit_id=fit_id, defaults={"target": target}
            )
        messages.success(request, "Saved doctrines and targets.")
        return redirect("aacontracts:location_edit", pk=pk)

    # GET: build doctrine -> fits with current enabled/target.
    enabled_docs = set(
        LocationDoctrine.objects.filter(location=loc, enabled=True).values_list("doctrine_id", flat=True)
    )
    targets = {
        t.ship_fit_id: t.target for t in SeedTarget.objects.filter(location=loc)
    }
    fits = ShipFit.objects.filter(enabled=True).select_related("fitting").prefetch_related("fitting__doctrines")
    doc_names = dict(Doctrine.objects.values_list("id", "name"))
    by_doc: dict = {}
    for sf in fits:
        for d in sf.fitting.doctrines.all():
            by_doc.setdefault(d.id, {"id": d.id, "name": doc_names.get(d.id, ""), "enabled": d.id in enabled_docs, "rows": []})
            by_doc[d.id]["rows"].append({"fit": sf, "target": targets.get(sf.id, 0)})
    groups = sorted(by_doc.values(), key=lambda g: g["name"])

    return render(request, "aacontracts/location_edit.html", {
        "page_title": f"Location · {loc.name}",
        "loc": loc,
        "form": LocationForm(instance=loc),
        "groups": groups,
    })


# --------------------------------------------------------------------------- #
#  Price history
# --------------------------------------------------------------------------- #
@login_required
@permission_required("aacontracts.view_contracts")
def price_history(request, pk):
    fit = get_object_or_404(ShipFit, pk=pk)
    points = list(
        PriceSnapshot.objects.filter(ship_fit=fit).order_by("timestamp")
        .values("timestamp", "jita_price", "final_price")
    )
    return JsonResponse({
        "fit": fit.match_name or fit.hull_name,
        "points": [
            {
                "t": p["timestamp"].isoformat(),
                "jita": float(p["jita_price"]),
                "final": float(p["final_price"]),
            }
            for p in points
        ],
    })
