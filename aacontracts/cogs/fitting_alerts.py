"""Publish queued fitting revisions to the configured Discord channel."""
from collections import Counter
from io import BytesIO
import logging

import discord
from asgiref.sync import sync_to_async
from discord.ext import commands, tasks
from django.conf import settings
from django.urls import reverse
from eve_sde.models import ItemType

from .. import app_settings
from ..fitting_alerts import item_changes, seed_snapshots
from ..models import FittingChange, GlobalConfig

logger = logging.getLogger(__name__)
_SECTION_NAMES = {
    "HiSlot": "High slots",
    "MedSlot": "Mid slots",
    "LoSlot": "Low slots",
    "RigSlot": "Rigs",
    "SubSystemSlot": "Subsystems",
    "ServiceSlot": "Service slots",
    "DroneBay": "Drones",
    "FighterBay": "Fighters",
    "Cargo": "Cargo",
}


@sync_to_async
def pending_changes(channel_id):
    seed_snapshots()
    return list(FittingChange.objects.filter(
        channel_id=channel_id, message_id__isnull=True,
    ).select_related("fitting").order_by("id")[:20])


@sync_to_async
def ping_group_names():
    return set(GlobalConfig.get().fitting_ping_groups.values_list("name", flat=True))


def fitting_ping_roles(guild, names):
    candidates = [role for role in guild.roles if role.id != guild.id and role.name in names]
    counts = Counter(role.name for role in candidates)
    return [role for role in candidates if counts[role.name] == 1]


@sync_to_async
def render_change(change, role_mentions=""):
    doctrines = change.fitting.doctrines.order_by("name").values_list("name", flat=True)
    changes = list(item_changes(change.before, change.after))
    names = dict(ItemType.objects.filter(
        pk__in={type_id for _, type_id, _, _ in changes},
    ).values_list("pk", "name_en"))
    escape = discord.utils.escape_markdown
    header = [
        f"**Fitting updated: {escape(change.after['name'])}**",
    ]
    if doctrines:
        header.append("Doctrines: " + ", ".join(map(escape, doctrines)))
    path = reverse("fittings:view_fit", args=[change.fitting_id])
    header.append(f"Open in Alliance Auth: <{settings.SITE_URL.rstrip('/')}{path}>")
    details = []
    if change.before["name"] != change.after["name"]:
        details.append(f"Renamed from {escape(change.before['name'])}")
    if change.before["description"] != change.after["description"]:
        details.append("Description updated")
    for flag, type_id, old_quantity, new_quantity in changes:
        section = _SECTION_NAMES.get(flag, flag)
        name = names.get(type_id, f"Item {type_id}")
        details.append(f"• {section}: {escape(name)} {old_quantity} → {new_quantity}")
    full_text = "\n".join(header + details)
    prefix = f"{role_mentions}\n" if role_mentions else ""
    if len(prefix + full_text) <= 1950:
        return prefix + full_text, None
    summary = prefix + "\n".join([header[0], header[-1], "See the attachment for the full change."])
    return summary if len(summary) <= 2000 else role_mentions, full_text


class FittingAlerts(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.publish.start()

    def cog_unload(self):
        self.publish.cancel()

    @tasks.loop(seconds=60)
    async def publish(self):
        try:
            channel_id = int(app_settings.AACONTRACTS_FITTING_ALERT_CHANNEL_ID)
            pending = await pending_changes(channel_id)
            if not pending:
                return
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            roles = fitting_ping_roles(channel.guild, await ping_group_names())
            role_mentions = " ".join(role.mention for role in roles)
            allowed = discord.AllowedMentions(everyone=False, users=False, roles=roles, replied_user=False)
            for change in pending:
                content, attachment = await render_change(change, role_mentions)
                kwargs = {"allowed_mentions": allowed}
                if attachment:
                    kwargs["file"] = discord.File(
                        BytesIO(attachment.encode("utf-8")), filename=f"fitting-change-{change.pk}.txt",
                    )
                message = await channel.send(content, **kwargs)
                await FittingChange.objects.filter(pk=change.pk).aupdate(message_id=message.id)
        except Exception:
            logger.exception("Could not publish queued fitting alerts")

    @publish.before_loop
    async def wait_for_discord(self):
        await self.bot.wait_until_ready()


def setup(bot):
    bot.add_cog(FittingAlerts(bot))
