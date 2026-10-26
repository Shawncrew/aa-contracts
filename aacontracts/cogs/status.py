"""Discord status cog for aa-contracts.

Channel layout (top to bottom), all persistent messages edited each cycle:

1. One message per location — 🔴/🟢 per fit, available/target. No pings.
2. A **shortage summary** — pings the configured group, listing the short ships
   per location ("Home — NC Napoc ×3, Heretic ×5").
3. A **fit-mismatch alerts** message — pings each contract's issuer (resolved via
   their main's linked Discord account) with what doesn't match aa-fittings.

Heavy work runs in Celery (``tasks.update_status``); this cog enqueues it and
renders the cached results. Pings fire only on transition (a new shortage or a
new mismatch) by recreating that one message, since Discord does not notify on
edits.
"""
import logging

import discord
from asgiref.sync import sync_to_async
from discord.ext import commands, tasks

from django.core.cache import cache

from .. import app_settings

logger = logging.getLogger(__name__)


def _fmt_isk(v):
    if v is None:
        return "—"
    v = float(v)
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}b"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.0f}m"
    return f"{v:,.0f}"


@sync_to_async
def _load_config():
    from ..models import GlobalConfig

    cfg = GlobalConfig.get()
    channel_id = cfg.discord_channel_id or app_settings.AACONTRACTS_DEFAULT_DISCORD_CHANNEL_ID
    return {
        "enabled": cfg.discord_enabled,
        "channel_id": int(channel_id) if channel_id else None,
        "interval": cfg.discord_update_seconds or 60,
        "ping_group": cfg.ping_group.name if cfg.ping_group_id else None,
        "shortage_message_id": cfg.shortage_message_id,
        "alerts_message_id": cfg.alerts_message_id,
    }


def _get_report():
    report = cache.get("aacontracts:report")
    if report is None:
        from .. import queries

        report = queries.build_report(use_cache=True)
    return report


def _render_location(entry) -> str:
    lines = [f"__**{entry['name']}**__" + (f" · {entry['system_name']}" if entry["system_name"] else "")]
    for doc in entry["doctrines"]:
        lines.append(f"**{doc['doctrine_name']}**")
        for r in doc["rows"]:
            flag = "🔴" if r["shortage"] > 0 else "🟢"
            price = _fmt_isk(r["price"])
            lines.append(
                f"{flag} `{r['available']:>3}/{r['target']:<3}` {r['name']}"
                + (f"  ({price})" if r["price"] else "")
            )
    return "\n".join(lines)[:1990]


@sync_to_async
def _location_rows():
    from ..models import Location

    report = _get_report()
    loc_objs = {loc.id: loc for loc in Location.objects.filter(enabled=True)}
    out = []
    for entry in report["locations"]:
        loc = loc_objs.get(entry["id"])
        if loc is None:
            continue
        out.append({"loc_pk": loc.id, "message_id": loc.discord_message_id, "text": _render_location(entry)})
    return out


@sync_to_async
def _shortage_payload(role_mention):
    """(text, signature) for the shortage summary, or (None, set()) if stocked."""
    report = _get_report()
    lines = []
    sig = set()
    for loc in report["locations"]:
        shorts = []
        for doc in loc["doctrines"]:
            for r in doc["rows"]:
                if r["shortage"] > 0:
                    shorts.append(f"{r['name']} ×{r['shortage']}")
                    sig.add(f"{loc['id']}:{r['fit_id']}")
        if shorts:
            lines.append(f"**{loc['name']}** — " + ", ".join(shorts))
    if not lines:
        return None, set()
    head = (role_mention + " " if role_mention else "") + "📉 **Contract shortage — please restock:**"
    return (head + "\n" + "\n".join(lines))[:1990], sig


@sync_to_async
def _alerts_payload():
    """(text, contract_ids) for the fit-mismatch alerts, with issuer mentions."""
    from allianceauth.authentication.models import CharacterOwnership
    from allianceauth.services.modules.discord.models import DiscordUser

    from ..models import FitAlert

    alerts = list(FitAlert.objects.select_related("ship_fit", "location"))
    if not alerts:
        return None, set()

    issuer_ids = {a.issuer_id for a in alerts}
    # issuer character -> owning auth user -> that user's Discord account
    own = dict(
        CharacterOwnership.objects.filter(character__character_id__in=issuer_ids)
        .values_list("character__character_id", "user_id")
    )
    uids = dict(
        DiscordUser.objects.filter(user_id__in=own.values()).values_list("user_id", "uid")
    )
    mention = {}
    for cid in issuer_ids:
        uid = uids.get(own.get(cid))
        mention[cid] = f"<@{uid}>" if uid else None

    lines = ["⚠️ **Contract fit mismatches** (please fix or recontract):"]
    for a in alerts[:40]:
        who = mention.get(a.issuer_id) or (a.issuer_name or f"char {a.issuer_id}")
        loc = f" @ {a.location.name}" if a.location else ""
        lines.append(f"• {who} — `{a.title}`{loc}: {a.detail}"[:320])
    if len(alerts) > 40:
        lines.append(f"…and {len(alerts) - 40} more")
    return "\n".join(lines)[:1990], {a.contract_id for a in alerts}


@sync_to_async
def _save_location_message(loc_pk, message_id):
    from ..models import Location

    Location.objects.filter(pk=loc_pk).update(discord_message_id=message_id)


@sync_to_async
def _save_cfg_message(field, message_id):
    from ..models import GlobalConfig

    cfg = GlobalConfig.get()
    setattr(cfg, field, message_id)
    cfg.save(update_fields=[field])


class ContractsStatus(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._interval_set = False
        self.refresh.start()

    def cog_unload(self):
        self.refresh.cancel()

    @tasks.loop(seconds=60)
    async def refresh(self):
        try:
            await self._refresh()
        except Exception:
            logger.exception("aa-contracts status refresh failed")

    @refresh.before_loop
    async def _before(self):
        await self.bot.wait_until_ready()

    async def _edit_or_recreate(self, channel, message_id, text, allowed, recreate, save_field):
        """Edit the persistent message, or delete+resend it (to fire a ping)."""
        if message_id and not recreate:
            try:
                msg = await channel.fetch_message(message_id)
                await msg.edit(content=text, allowed_mentions=allowed)
                return message_id
            except discord.NotFound:
                pass
        if message_id and recreate:
            try:
                old = await channel.fetch_message(message_id)
                await old.delete()
            except discord.NotFound:
                pass
        msg = await channel.send(text, allowed_mentions=allowed)
        if save_field:
            await _save_cfg_message(save_field, msg.id)
        return msg.id

    async def _refresh(self):
        cfg = await _load_config()
        if not cfg["enabled"] or not cfg["channel_id"]:
            return

        try:
            from ..tasks import update_status

            update_status.delay()
        except Exception:
            logger.exception("aa-contracts: could not enqueue update_status")

        if not self._interval_set and cfg["interval"] != 60:
            self.refresh.change_interval(seconds=max(10, int(cfg["interval"])))
            self._interval_set = True

        channel = self.bot.get_channel(cfg["channel_id"])
        if channel is None:
            logger.warning("aa-contracts: channel %s not found", cfg["channel_id"])
            return

        role_mention = ""
        if cfg["ping_group"]:
            role = discord.utils.get(channel.guild.roles, name=cfg["ping_group"])
            if role:
                role_mention = role.mention

        allowed = discord.AllowedMentions(everyone=False, roles=True, users=True)

        # 1. Per-location status messages (no pings).
        for row in await _location_rows():
            try:
                mid = row["message_id"]
                if mid:
                    try:
                        msg = await channel.fetch_message(mid)
                        await msg.edit(content=row["text"], allowed_mentions=allowed)
                        continue
                    except discord.NotFound:
                        pass
                msg = await channel.send(row["text"], allowed_mentions=allowed)
                await _save_location_message(row["loc_pk"], msg.id)
            except Exception:
                logger.exception("aa-contracts: failed updating location %s", row["loc_pk"])

        # 2. Shortage summary (pings the group), after the locations.
        try:
            short_text, short_sig = await _shortage_payload(role_mention)
            last_sig = cache.get("aacontracts:short_sig", set())
            new_short = bool(short_sig - set(last_sig))
            mid = cfg["shortage_message_id"]
            if short_text is None:
                if mid:
                    try:
                        m = await channel.fetch_message(mid)
                        await m.edit(content="✅ All configured locations are stocked.")
                    except discord.NotFound:
                        pass
            else:
                await self._edit_or_recreate(
                    channel, mid, short_text, allowed,
                    recreate=bool(new_short and role_mention), save_field="shortage_message_id",
                )
            cache.set("aacontracts:short_sig", short_sig, 86400)
        except Exception:
            logger.exception("aa-contracts: failed updating shortage summary")

        # 3. Fit-mismatch alerts (pings issuers), after the shortage summary.
        try:
            alerts_text, alert_ids = await _alerts_payload()
            last_ids = cache.get("aacontracts:alert_ids", set())
            new_alerts = bool(alert_ids - set(last_ids))
            mid = cfg["alerts_message_id"]
            if alerts_text is None:
                if mid:
                    try:
                        m = await channel.fetch_message(mid)
                        await m.edit(content="✅ No contract fit mismatches.")
                    except discord.NotFound:
                        pass
            else:
                await self._edit_or_recreate(
                    channel, mid, alerts_text, allowed,
                    recreate=bool(new_alerts), save_field="alerts_message_id",
                )
            cache.set("aacontracts:alert_ids", alert_ids, 86400)
        except Exception:
            logger.exception("aa-contracts: failed updating alerts message")


def setup(bot):
    bot.add_cog(ContractsStatus(bot))
