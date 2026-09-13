"""Entry point: ``python -m saucebot``."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import aiohttp
from dotenv import load_dotenv

from saucebot.bot import SauceBot
from saucebot.budget import DailyBudget
from saucebot.config import load_config
from saucebot.engines.serpapi_lens import SerpApiLensEngine
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
    budget = DailyBudget(
        path=Path(os.environ.get("SAUCEBOT_DATA_DIR", "data")) / "budget.json",
        max_per_day=config.search.max_searches_per_day,
    )
    async with aiohttp.ClientSession() as session:
        engine = SerpApiLensEngine(session=session, api_key=secrets.serpapi_api_key)
        bot = SauceBot(
            command_prefix=config.command.prefix,
            engine=engine,
            budget=budget,
            config=config,
        )
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
