"""The passive listener: search images posted by watched users, call out reposts.

Every branch that decides *not* to act is an early return, and every failure is
logged and swallowed — the channel must never see a traceback or an API error.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from saucebot.config import Config, ResponseMode
from saucebot.engines.base import SourceHit
from saucebot.exts.sauce import lookup_source
from saucebot.matching import first_non_self_hit
from saucebot.responses import render

if TYPE_CHECKING:
    from saucebot.bot import SauceBot

log = logging.getLogger(__name__)

# The call-out may only ping the poster, never a role and never the server.
SAFE_MENTIONS = discord.AllowedMentions(everyone=False, roles=False, users=True, replied_user=True)


class Cooldown:
    """Per-user quiet period, so one person's posting spree can't spam the channel."""

    def __init__(self, seconds: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._seconds = seconds
        self._clock = clock
        self._last: dict[int, float] = {}

    def check_and_stamp(self, user_id: int) -> bool:
        """True if a call-out is allowed now; records the time when it is."""
        now = self._clock()
        previous = self._last.get(user_id)
        if previous is not None and now - previous < self._seconds:
            return False
        self._last[user_id] = now
        return True


def should_watch(message: discord.Message, config: Config) -> bool:
    """Whether this message is in scope for the watcher."""
    if message.author.bot or message.webhook_id is not None:
        return False
    if message.channel.id not in config.watch.channel_ids:
        return False
    if config.watch.user_ids and message.author.id not in config.watch.user_ids:
        return False
    return bool(image_attachments(message, limit=1))


def image_attachments(message: discord.Message, limit: int) -> list[discord.Attachment]:
    """Up to ``limit`` attachments that are actually images."""
    images = [a for a in message.attachments if (a.content_type or "").startswith("image/")]
    return images[:limit]


def identities_of(member: discord.abc.User) -> list[str]:
    """The names this person is known by, de-duplicated, most specific last."""
    names = [
        member.name,
        getattr(member, "global_name", None),
        getattr(member, "display_name", None),
    ]
    seen: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
    return seen


class Watcher(commands.Cog):
    def __init__(self, bot: SauceBot) -> None:
        self.bot = bot
        self.cooldown = Cooldown(bot.config.watch.min_seconds_between_callouts)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        config = self.bot.config
        if not should_watch(message, config):
            return
        if not self.cooldown.check_and_stamp(message.author.id):
            log.debug("cooldown active for %s; skipping", message.author.id)
            return
        try:
            await self._inspect(message, config)
        except Exception:
            # The listener must never propagate: a traceback here would be logged
            # by discord.py but could also leave the channel silently unprocessed.
            log.exception(
                "watcher failed on message %s in channel %s", message.id, message.channel.id
            )

    async def _inspect(self, message: discord.Message, config: Config) -> None:
        identities = identities_of(message.author)
        for attachment in image_attachments(message, config.search.max_attachments_per_message):
            try:
                image_bytes = await attachment.read()
            except discord.HTTPException:
                log.warning("could not read attachment on message %s", message.id)
                continue
            result = await lookup_source(
                self.bot.engine,
                self.bot.budget,
                config.all_excluded_domains,
                attachment.url,
                image_bytes,
            )
            if result.status == "over_budget":
                return
            if result.status != "found" or result.hit is None:
                continue
            hit = first_non_self_hit([result.hit], identities, config.match.self_match_threshold)
            if hit is None:
                log.info("message %s looks like the poster's own work; staying quiet", message.id)
                continue
            await self._call_out(message, hit, config)
            return

    async def _call_out(self, message: discord.Message, hit: SourceHit, config: Config) -> None:
        text = render(config.response.templates, hit, message.author.mention)
        # Keep everyone/roles disabled while binding user mentions to this poster only.
        allowed_mentions = SAFE_MENTIONS.merge(discord.AllowedMentions(users=[message.author]))
        try:
            if config.response.mode is ResponseMode.REPLY:
                await message.reply(text, allowed_mentions=allowed_mentions)
            else:
                await message.channel.send(text, allowed_mentions=allowed_mentions)
        except discord.HTTPException:
            log.exception("could not post the call-out for message %s", message.id)


async def setup(bot: SauceBot) -> None:
    await bot.add_cog(Watcher(bot))
