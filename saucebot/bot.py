"""The bot object: intents, shared services, and extension loading."""

from __future__ import annotations

import discord
from discord.ext import commands

from saucebot.engines.base import ImageSearchEngine

EXTENSIONS: tuple[str, ...] = ("saucebot.exts.sauce",)


def build_intents() -> discord.Intents:
    """Default intents plus the privileged message-content intent (needed for attachments)."""
    intents = discord.Intents.default()
    intents.message_content = True
    return intents


class SauceBot(commands.Bot):
    def __init__(self, *, command_prefix: str, engine: ImageSearchEngine) -> None:
        super().__init__(command_prefix=command_prefix, intents=build_intents())
        self.engine = engine

    async def setup_hook(self) -> None:
        for name in EXTENSIONS:
            await self.load_extension(name)
