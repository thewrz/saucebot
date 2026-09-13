import discord

from saucebot.bot import EXTENSIONS, SauceBot, build_intents
from saucebot.engines.base import NullEngine


def test_intents_are_default_plus_message_content_only() -> None:
    intents = build_intents()
    expected = build_intents().__class__.default()
    expected.message_content = True
    assert intents == expected


async def test_bot_disables_all_mentions_by_default() -> None:
    bot = SauceBot(command_prefix="?", engine=NullEngine())
    assert bot.allowed_mentions.to_dict() == discord.AllowedMentions.none().to_dict()
    await bot.close()


async def test_setup_hook_loads_every_declared_extension() -> None:
    bot = SauceBot(command_prefix="?", engine=NullEngine())
    await bot.setup_hook()
    assert set(bot.extensions) == set(EXTENSIONS)
    assert bot.get_cog("Sauce") is not None
    await bot.close()
