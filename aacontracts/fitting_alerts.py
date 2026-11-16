"""Capture complete AA Fittings saves and persist their Discord notifications."""
from collections import Counter
import logging
import re

from django.db import DatabaseError, transaction
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from fittings.models import Fitting

from . import app_settings
from .middleware import fitting_editor_name
from .models import FittingChange, FittingSnapshot

logger = logging.getLogger(__name__)
_SLOT_NUMBER = re.compile(r"Slot\d+$")


def snapshot(fit):
    # EFT rearrangements within a rack don't change the fitting. Keep cargo,
    # drones and fighters separate so moving an item between sections counts.
    items = Counter()
    for flag, type_id, quantity in fit.items.values_list("flag", "type_id", "quantity"):
        items[_SLOT_NUMBER.sub("Slot", flag), type_id] += quantity
    return {
        "name": fit.name,
        "description": fit.description or "",
        "items": [[flag, type_id, count] for (flag, type_id), count in sorted(items.items())],
    }


def item_changes(before, after):
    old = {(flag, type_id): quantity for flag, type_id, quantity in before["items"]}
    new = {(flag, type_id): quantity for flag, type_id, quantity in after["items"]}
    for flag, type_id in sorted(old.keys() | new.keys()):
        old_quantity = old.get((flag, type_id), 0)
        new_quantity = new.get((flag, type_id), 0)
        if old_quantity != new_quantity:
            yield flag, type_id, old_quantity, new_quantity


def capture(fitting_id, *, using="default"):
    channel_id = app_settings.AACONTRACTS_FITTING_ALERT_CHANNEL_ID
    if not channel_id:
        return

    with transaction.atomic(using=using):
        fit = Fitting.objects.using(using).select_for_update().filter(pk=fitting_id).first()
        if fit is None:
            return
        current = snapshot(fit)
        previous, created = FittingSnapshot.objects.using(using).get_or_create(
            fitting_id=fitting_id, defaults={"state": current},
        )
        if created or previous.state == current:
            return

        # Editor attribution belongs to the notification, not the fit state
        # used to detect changes.
        editor = fitting_editor_name(fitting_id)
        FittingChange.objects.using(using).create(
            fitting_id=fitting_id, channel_id=channel_id,
            before=previous.state, after={**current, "edited_by": editor} if editor else current,
        )
        previous.state = current
        previous.save(using=using, update_fields=["state"])


def seed_snapshots():
    """Establish a baseline for all fits that haven't been seen yet."""
    untracked = Fitting.objects.exclude(pk__in=FittingSnapshot.objects.values("fitting_id"))
    for fitting_id in untracked.values_list("pk", flat=True).iterator():
        capture(fitting_id)


def record_lifecycle_change(fitting_id, name, channel_id, *, using, added):
    state = {"name": name}
    FittingChange.objects.using(using).create(
        fitting_id=fitting_id, channel_id=channel_id,
        before=None if added else state, after=state if added else None,
    )


@receiver(post_save, sender="fittings.Fitting", dispatch_uid="aacontracts.capture_fitting_alert")
def fitting_saved(sender, instance, created, raw, using, **kwargs):
    channel_id = app_settings.AACONTRACTS_FITTING_ALERT_CHANNEL_ID
    if raw or not channel_id:
        return
    try:
        if created:
            # AA Fittings adds items after the initial save. Announce the name
            # now and let the baseline scan capture the fit's items.
            with transaction.atomic(using=using):
                record_lifecycle_change(instance.pk, instance.name, channel_id, using=using, added=True)
        else:
            capture(instance.pk, using=using)
    except DatabaseError:
        logger.exception("Could not capture Discord alert for fitting %s", instance.pk)


@receiver(pre_delete, sender="fittings.Fitting", dispatch_uid="aacontracts.capture_fitting_removal")
def fitting_deleting(sender, instance, using, **kwargs):
    channel_id = app_settings.AACONTRACTS_FITTING_ALERT_CHANNEL_ID
    if not channel_id:
        return
    try:
        # Django runs pre_delete inside the delete transaction. Lock the
        # fitting so concurrent deletes cannot both queue the same removal.
        with transaction.atomic(using=using):
            name = (
                sender.objects.using(using).select_for_update()
                .filter(pk=instance.pk).values_list("name", flat=True).first()
            )
            if name is not None:
                record_lifecycle_change(instance.pk, name, channel_id, using=using, added=False)
    except DatabaseError:
        logger.exception("Could not capture Discord removal alert for fitting %s", instance.pk)
