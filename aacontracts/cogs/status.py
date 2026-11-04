"""Discord status cog for aa-contracts.

Channel layout (top to bottom), persistent and edited each cycle:

1. One **block per location** — only fits with a target or stock, grouped by
   doctrine, each on its own line (🔴/🟢  avail/target  name). No pings.
2. A **shortage summary** — one short ship per line, grouped by location; pings
   the configured group when a new shortage appears.
3. A **fit-mismatch alerts** block — one contract per line, issuer by name only
   (no @-ping for now).

Every block is wrapped across as many Discord messages as it needs (never
exceeding the ~2000-char message limit) and tracked in the DiscordMessage model
so each message is edited in place. Heavy work runs in Celery
(``tasks.update_status``); the cog renders the cached results.
"""
import logging

import discord
from asgiref.sync import sync_to_async
from discord.ext import commands, tasks

from django.core.cache import cache

from .. import app_settings

logger = logging.getLogger(__name__)

_MSG_LIMIT = 1950  # leave headroom under Discord's 2000-char limit


def _fmt_isk(v):
    if v is None:
        return ""
    v = float(v)
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}b"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.0f}m"
    return f"{v:,.0f}"


def _fmt_m(v):
    """Price rounded to the nearest million, e.g. 45,300,000 -> '45m'."""
    if v is None:
        return "?"
    return f"{round(float(v) / 1_000_000):,}m"


def _pack(lines, limit=_MSG_LIMIT):
    """Pack lines into message-sized chunks without splitting a line."""
    chunks, cur, n = [], [], 0
    for ln in lines:
        ln = ln[:limit]
        add = len(ln) + 1
        if cur and n + add > limit:
            chunks.append("\n".join(cur))
            cur, n = [ln], len(ln) + 1
        else:
            cur.append(ln)
            n += add
    if cur:
        chunks.append("\n".join(cur))
    return chunks


# --------------------------------------------------------------------------- #
#  Rendering (returns lists of lines)
# --------------------------------------------------------------------------- #
def _get_report():
    report = cache.get("aacontracts:report")
    if report is None:
        from .. import queries

        report = queries.build_report(use_cache=True)
    return report


def _tier(available, target):
    """🟢 at/above target · 🟡 some stock but below · 🔴 none on contract."""
    if available >= target:
        return "🟢"
    if available > 0:
        return "🟡"
    return "🔴"


def _location_lines(entry):
    shown = [
        r
        for doc in entry["doctrines"]
        for r in doc["rows"]
        if r["target"] > 0 or r["available"] > 0
    ]
    # Header dot reflects the worst tier at this location.
    if any(r["available"] == 0 and r["target"] > 0 for r in shown):
        dot = f"🔴 {entry['short_count']} short"
    elif any(0 < r["available"] < r["target"] for r in shown):
        dot = f"🟡 {entry['short_count']} low"
    else:
        dot = "🟢 stocked"
    head = f"__**{entry['name']}**__"
    if entry["system_name"]:
        head += f"  ·  {entry['system_name']}"
    head += "  ·  " + dot
    lines = [head]
    for doc in entry["doctrines"]:
        rows = [r for r in doc["rows"] if r["target"] > 0 or r["available"] > 0]
        if not rows:
            continue
        lines.append(f"**{doc['doctrine_name']}**")
        for r in rows:
            flag = _tier(r["available"], r["target"])
            lines.append(f"{flag} `{r['available']:>3}/{r['target']:<3}` {r['name']}")
    if len(lines) == 1:
        lines.append("_no targets set_")
    return lines


@sync_to_async
def _location_sections():
    from ..models import Location

    report = _get_report()
    enabled = {loc.id for loc in Location.objects.filter(enabled=True)}
    return [
        (f"loc:{e['id']}", _location_lines(e))
        for e in report["locations"] if e["id"] in enabled
    ]


@sync_to_async
def _shortage_lines(role_mention):
    report = _get_report()
    sig, body = set(), []
    for loc in report["locations"]:
        shorts = []
        seen = set()  # a named ship spans several doctrines/fits — list it once per location
        for doc in loc["doctrines"]:
            for r in doc["rows"]:
                key = (r["name"] or "").strip().lower()
                if r["shortage"] > 0 and key not in seen:
                    seen.add(key)
                    shorts.append((r["name"], r["shortage"], r.get("price")))
                    sig.add(f"{loc['id']}:{key}")
        if shorts:
            body.append(f"__**{loc['name']}**__")
            body += [
                f"• {name} — **{s}** short @ {_fmt_m(price)}"
                for name, s, price in shorts
            ]
            body.append("")
    if not body:
        return [], set()
    head = "📉 **Contract shortage — please restock**"
    if role_mention:
        head += f"  ·  {role_mention}"
    return [head, ""] + body, sig


@sync_to_async
def _alerts_lines():
    from ..models import FitAlert

    alerts = list(FitAlert.objects.select_related("ship_fit", "location"))
    if not alerts:
        return []
    lines = ["⚠️ **Contract fit mismatches** — please fix or recontract:", ""]
    for a in alerts:
        who = a.issuer_name or f"char {a.issuer_id}"
        loc = f" @ {a.location.name}" if a.location else ""
        lines.append(f"• {who} — `{a.title}`{loc}: {a.detail}")
    return lines


# --------------------------------------------------------------------------- #
#  Section <-> message-id persistence
# --------------------------------------------------------------------------- #
@sync_to_async
def _get_section(section):
    from ..models import DiscordMessage

    return list(
        DiscordMessage.objects.filter(section=section).order_by("seq")
        .values_list("message_id", flat=True)
    )


@sync_to_async
def _set_section(section, ids):
    from django.db import transaction

    from ..models import DiscordMessage

    with transaction.atomic():
        DiscordMessage.objects.filter(section=section).delete()
        DiscordMessage.objects.bulk_create(
            [DiscordMessage(section=section, seq=i, message_id=mid) for i, mid in enumerate(ids)]
        )


@sync_to_async
def _stale_location_sections(active):
    from ..models import DiscordMessage

    secs = set(
        DiscordMessage.objects.filter(section__startswith="loc:").values_list("section", flat=True)
    )
    return [s for s in secs if s not in active]


@sync_to_async
def _legacy_message_ids():
    from ..models import GlobalConfig, Location

    locs = list(Location.objects.exclude(discord_message_id=None).values_list("discord_message_id", flat=True))
    cfg = GlobalConfig.get()
    extra = [m for m in (cfg.shortage_message_id, cfg.alerts_message_id) if m]
    return locs + extra


@sync_to_async
def _clear_legacy():
    from ..models import GlobalConfig, Location

    Location.objects.exclude(discord_message_id=None).update(discord_message_id=None)
    cfg = GlobalConfig.get()
    cfg.shortage_message_id = None
    cfg.alerts_message_id = None
    cfg.save(update_fields=["shortage_message_id", "alerts_message_id"])


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
    }


# --------------------------------------------------------------------------- #
#  Cog
# --------------------------------------------------------------------------- #
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

    async def _sync_section(self, channel, section, chunks, allowed, recreate=False):
        """Make the section's messages match ``chunks`` (edit, add, or remove)."""
        existing = await _get_section(section)
        if recreate:
            for mid in existing:
                try:
                    await (await channel.fetch_message(mid)).delete()
                except discord.NotFound:
                    pass
            existing = []
        new_ids = []
        for i, chunk in enumerate(chunks):
            if i < len(existing):
                try:
                    msg = await channel.fetch_message(existing[i])
                    await msg.edit(content=chunk, allowed_mentions=allowed)
                    new_ids.append(existing[i])
                    continue
                except discord.NotFound:
                    pass
            msg = await channel.send(chunk, allowed_mentions=allowed)
            new_ids.append(msg.id)
        for mid in existing[len(chunks):]:
            try:
                await (await channel.fetch_message(mid)).delete()
            except discord.NotFound:
                pass
        await _set_section(section, new_ids)

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

        # One-time cleanup of the previous single-message layout.
        legacy = await _legacy_message_ids()
        if legacy:
            for mid in legacy:
                try:
                    await (await channel.fetch_message(mid)).delete()
                except discord.NotFound:
                    pass
            await _clear_legacy()

        role_mention = ""
        if cfg["ping_group"]:
            role = discord.utils.get(channel.guild.roles, name=cfg["ping_group"])
            if role:
                role_mention = role.mention
        # Only role mentions may ping; individual user pings stay disabled.
        allowed = discord.AllowedMentions(everyone=False, roles=True, users=False)

        # 1. Per-location blocks.
        active = set()
        for key, lines in await _location_sections():
            active.add(key)
            try:
                await self._sync_section(channel, key, _pack(lines), allowed)
            except Exception:
                logger.exception("aa-contracts: failed location %s", key)
        # Remove blocks for locations that are gone/disabled.
        for stale in await _stale_location_sections(active):
            try:
                await self._sync_section(channel, stale, [], allowed)
            except Exception:
                logger.exception("aa-contracts: failed clearing %s", stale)

        # 2. Shortage summary (pings the group on a new shortage).
        try:
            short_lines, sig = await _shortage_lines(role_mention)
            last = cache.get("aacontracts:short_sig", set())
            new_short = bool(sig - set(last))
            chunks = _pack(short_lines) if short_lines else ["✅ All configured locations are stocked."]
            await self._sync_section(
                channel, "shortage", chunks, allowed,
                recreate=bool(short_lines and new_short and role_mention),
            )
            cache.set("aacontracts:short_sig", sig, 86400)
        except Exception:
            logger.exception("aa-contracts: failed shortage summary")

        # 3. Fit-mismatch alerts (names only, no ping).
        try:
            alert_lines = await _alerts_lines()
            chunks = _pack(alert_lines) if alert_lines else ["✅ No contract fit mismatches."]
            await self._sync_section(channel, "alerts", chunks, allowed)
        except Exception:
            logger.exception("aa-contracts: failed alerts block")


def setup(bot):
    bot.add_cog(ContractsStatus(bot))
