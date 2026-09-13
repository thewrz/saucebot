"""The manual ``?sauce`` command: search an attached image or a linked message's image."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from saucebot.budget import DailyBudget
from saucebot.engines.base import (
    EngineError,
    ImageSearchEngine,
    SourceHit,
    filter_excluded_domains,
)

if TYPE_CHECKING:
    from saucebot.bot import SauceBot

log = logging.getLogger(__name__)

MESSAGE_LINK = re.compile(
    r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/channels/(\d+)/(\d+)/(\d+)/?$"
)


@dataclass(frozen=True)
class MessageRef:
    guild_id: int
    channel_id: int
    message_id: int


def parse_message_link(text: str) -> MessageRef | None:
    match = MESSAGE_LINK.match(text.strip())
    if match is None:
        return None
    guild_id, channel_id, message_id = (int(group) for group in match.groups())
    return MessageRef(guild_id=guild_id, channel_id=channel_id, message_id=message_id)


def first_image_attachment(message: discord.Message) -> discord.Attachment | None:
    for attachment in message.attachments:
        if (attachment.content_type or "").startswith("image/"):
            return attachment
    return None


@dataclass(frozen=True)
class LookupResult:
    """Outcome of one search: found / not_found / over_budget / error."""

    status: str
    hit: SourceHit | None = None


async def lookup_source(
    engine: ImageSearchEngine,
    budget: DailyBudget,
    excluded_domains: frozenset[str],
    image_url: str,
    image_bytes: bytes,
) -> LookupResult:
    """Spend one unit of budget on a search and return the best non-excluded hit."""
    if not await budget.acquire():
        log.info("daily search budget exhausted; skipping %s", image_url)
        return LookupResult(status="over_budget")
    try:
        hits = await engine.search(image_url, image_bytes)
    except EngineError:
        log.exception("engine failed searching %s", image_url)
        return LookupResult(status="error")
    hits = filter_excluded_domains(hits, excluded_domains)
    if not hits:
        return LookupResult(status="not_found")
    return LookupResult(status="found", hit=hits[0])


class Sauce(commands.Cog):
    def __init__(self, bot: SauceBot) -> None:
        self.bot = bot

    @commands.command(name="sauce")
    @commands.guild_only()
    async def sauce(self, ctx: commands.Context, ref_url: str | None = None) -> None:
        target = ctx.message
        allowed = self.bot.config.command.allowed_channel_ids
        if allowed and ctx.channel.id not in allowed:
            return
        if ref_url is not None:
            ref = parse_message_link(ref_url)
            if ref is None or ctx.guild is None or ref.guild_id != ctx.guild.id:
                await ctx.reply("That isn't a message link from this server.")
                return
            fetched = await self._fetch_message(ctx.guild, ref, ctx.author)
            if fetched is None:
                await ctx.reply("I can't see that message.")
                return
            target = fetched
        attachment = first_image_attachment(target)
        if attachment is None:
            await ctx.reply("Attach an image or link a message that has one.")
            return
        await self._lookup(ctx, attachment)

    async def _fetch_message(
        self, guild: discord.Guild, ref: MessageRef, author: discord.Member
    ) -> discord.Message | None:
        channel = guild.get_channel_or_thread(ref.channel_id)
        if channel is None or not hasattr(channel, "fetch_message"):
            return None
        if not await self._can_read_source(channel, author):
            return None
        try:
            return await channel.fetch_message(ref.message_id)
        except discord.HTTPException:
            return None

    async def _can_read_source(
        self, channel: discord.abc.GuildChannel, author: discord.Member
    ) -> bool:
        try:
            permissions = channel.permissions_for(author)
        except (discord.ClientException, AttributeError):
            return False
        if not permissions.view_channel or not permissions.read_message_history:
            return False
        if not isinstance(channel, discord.Thread) or not channel.is_private():
            return True
        if permissions.manage_threads:
            return True
        try:
            return await channel.fetch_member(author.id) is not None
        except (discord.NotFound, discord.HTTPException, AttributeError):
            return False

    async def _lookup(self, ctx: commands.Context, attachment: discord.Attachment) -> None:
        try:
            image_bytes = await attachment.read()
        except discord.HTTPException:
            log.exception("could not read attachment on message %s", ctx.message.id)
            await ctx.reply("I couldn't read that image.")
            return
        async with ctx.typing():
            result = await lookup_source(
                self.bot.engine,
                self.bot.budget,
                self.bot.config.all_excluded_domains,
                attachment.url,
                image_bytes,
            )
        messages = {
            "over_budget": "Today's search budget is spent. Try again tomorrow.",
            "error": "Search failed. Check the logs.",
            "not_found": "No source found.",
        }
        if result.status == "found" and result.hit is not None:
            await ctx.reply(f"Source: {result.hit.url}")
            return
        await ctx.reply(messages[result.status])


async def setup(bot: SauceBot) -> None:
    await bot.add_cog(Sauce(bot))
