"""Entry point: ``python -m saucebot``."""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from saucebot.bot import SauceBot
from saucebot.config import load_config
from saucebot.engines.base import NullEngine
from saucebot.errors import ConfigError
from saucebot.secrets import load_secrets

log = logging.getLogger("saucebot")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )


async def run() -> None:
    load_dotenv()
    secrets = load_secrets(os.environ)
    config = load_config(os.environ.get("SAUCEBOT_CONFIG", "config.toml"))
    bot = SauceBot(command_prefix=config.command.prefix, engine=NullEngine())
    async with bot:
        await bot.start(secrets.discord_token)


def main() -> int:
    configure_logging()
    try:
        asyncio.run(run())
    except ConfigError as exc:
        log.error("startup failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
