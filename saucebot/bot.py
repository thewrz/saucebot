"""The bot object: intents, shared services, and extension loading."""

from __future__ import annotations

import discord
from discord.ext import commands

from saucebot.budget import DailyBudget
from saucebot.config import Config
from saucebot.engines.base import ImageSearchEngine

EXTENSIONS: tuple[str, ...] = ("saucebot.exts.sauce", "saucebot.exts.watcher")


def build_intents() -> discord.Intents:
    """Default intents plus the privileged message-content intent (needed for attachments)."""
    intents = discord.Intents.default()
    intents.message_content = True
    return intents


class SauceBot(commands.Bot):
    def __init__(
        self,
        *,
        command_prefix: str,
        engine: ImageSearchEngine,
        budget: DailyBudget,
        config: Config,
    ) -> None:
        super().__init__(
            command_prefix=command_prefix,
            intents=build_intents(),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self.engine = engine
        self.budget = budget
        self.config = config

    async def setup_hook(self) -> None:
        for name in EXTENSIONS:
            await self.load_extension(name)
