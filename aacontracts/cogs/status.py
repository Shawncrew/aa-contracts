"""Discord status cog for aa-contracts.

Keeps one persistent message per location in the status channel, edited every
cycle, plus one "Alerts" message for contract fit mismatches. Heavy work runs in
Celery (``tasks.update_status``); this cog only enqueues it and renders the
cached results, so the bot's event loop stays light.

Pings fire on *transition* (a location newly going short, a new mismatch
appearing) by recreating that message, since Discord does not notify on edits.
"""
import logging

import discord
from asgiref.sync import sync_to_async
from discord.ext import commands, tasks

from django.core.cache import cache

from .. import app_settings

logger = logging.getLogger(__name__)

_ISK = 1_000_000


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
        "alerts_message_id": cfg.alerts_message_id,
    }


@sync_to_async
def _location_rows():
    """List of (Location, message_id, text, is_short) for enabled locations."""
    from ..models import Location

    report = cache.get("aacontracts:report")
    if report is None:
        from .. import queries

        report = queries.build_report(use_cache=True)
    loc_objs = {loc.id: loc for loc in Location.objects.filter(enabled=True)}
    out = []
    for entry in report["locations"]:
        loc = loc_objs.get(entry["id"])
        if loc is None:
            continue
        out.append({
            "loc_pk": loc.id,
            "message_id": loc.discord_message_id,
            "text": _render_location(entry, report["markup"]),
            "short": entry["short_count"] > 0,
        })
    return out


def _render_location(entry, markup) -> str:
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
    body = "\n".join(lines)
    return body[:1990]


@sync_to_async
def _save_location_message(loc_pk, message_id):
    from ..models import Location

    Location.objects.filter(pk=loc_pk).update(discord_message_id=message_id)


@sync_to_async
def _save_alerts_message(message_id):
    from ..models import GlobalConfig

    cfg = GlobalConfig.get()
    cfg.alerts_message_id = message_id
    cfg.save(update_fields=["alerts_message_id"])


@sync_to_async
def _alerts_payload():
    """(text, {issuer_id,...}) for the alerts message, with Discord mentions."""
    from allianceauth.services.modules.discord.models import DiscordUser
    from allianceauth.authentication.models import CharacterOwnership

    from ..models import FitAlert

    alerts = list(FitAlert.objects.select_related("ship_fit", "location"))
    if not alerts:
        return None, set()

    # issuer character_id -> discord uid
    issuer_ids = {a.issuer_id for a in alerts}
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

    lines = ["__**⚠️ Contract fit mismatches**__"]
    for a in alerts[:40]:
        who = mention.get(a.issuer_id) or (a.issuer_name or f"char {a.issuer_id}")
        loc = f" @ {a.location.name}" if a.location else ""
        lines.append(f"• {who} — `{a.title}`{loc}: {a.detail}"[:300])
    if len(alerts) > 40:
        lines.append(f"…and {len(alerts) - 40} more")
    text = "\n".join(lines)[:1990]
    return text, {a.contract_id for a in alerts}


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

    async def _refresh(self):
        cfg = await _load_config()
        if not cfg["enabled"] or not cfg["channel_id"]:
            return

        # Keep heavy work in Celery.
        try:
            from ..tasks import update_status

            update_status.delay()
        except Exception:
            logger.exception("aa-contracts: could not enqueue update_status")

        # Adjust loop interval to config once.
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

        # Per-location status messages.
        for row in await _location_rows():
            text = row["text"]
            short = row["short"]
            ping_key = f"aacontracts:short:{row['loc_pk']}"
            was_short = cache.get(ping_key, False)
            body = text
            if short and role_mention:
                body = f"{role_mention}\n{text}"[:1990]
            try:
                msg_id = row["message_id"]
                # Recreate (re-ping) when a location newly goes short; else edit.
                if msg_id and not (short and not was_short):
                    try:
                        msg = await channel.fetch_message(msg_id)
                        await msg.edit(content=body, allowed_mentions=allowed)
                    except discord.NotFound:
                        msg = await channel.send(body, allowed_mentions=allowed)
                        await _save_location_message(row["loc_pk"], msg.id)
                else:
                    if msg_id:
                        try:
                            old = await channel.fetch_message(msg_id)
                            await old.delete()
                        except discord.NotFound:
                            pass
                    msg = await channel.send(body, allowed_mentions=allowed)
                    await _save_location_message(row["loc_pk"], msg.id)
            except Exception:
                logger.exception("aa-contracts: failed updating location %s", row["loc_pk"])
            cache.set(ping_key, short, 86400)

        # Alerts message.
        text, alert_ids = await _alerts_payload()
        last_ids = cache.get("aacontracts:alert_ids", set())
        new_alerts = bool(alert_ids - set(last_ids))
        alerts_mid = cfg["alerts_message_id"]
        try:
            if text is None:
                if alerts_mid:
                    try:
                        m = await channel.fetch_message(alerts_mid)
                        await m.edit(content="✅ No contract fit mismatches.")
                    except discord.NotFound:
                        pass
            elif alerts_mid and not new_alerts:
                try:
                    m = await channel.fetch_message(alerts_mid)
                    await m.edit(content=text, allowed_mentions=allowed)
                except discord.NotFound:
                    m = await channel.send(text, allowed_mentions=allowed)
                    await _save_alerts_message(m.id)
            else:
                if alerts_mid:
                    try:
                        old = await channel.fetch_message(alerts_mid)
                        await old.delete()
                    except discord.NotFound:
                        pass
                m = await channel.send(text, allowed_mentions=allowed)
                await _save_alerts_message(m.id)
            cache.set("aacontracts:alert_ids", alert_ids, 86400)
        except Exception:
            logger.exception("aa-contracts: failed updating alerts message")


def setup(bot):
    bot.add_cog(ContractsStatus(bot))
