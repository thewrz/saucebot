"""Secrets come from the process environment (loaded from .env by the entry point)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from saucebot.errors import ConfigError

REQUIRED_VARIABLES: tuple[str, ...] = ("DISCORD_TOKEN", "SERPAPI_API_KEY")


@dataclass(frozen=True)
class Secrets:
    discord_token: str
    serpapi_api_key: str


def load_secrets(env: Mapping[str, str]) -> Secrets:
    missing = [name for name in REQUIRED_VARIABLES if not env.get(name)]
    if missing:
        raise ConfigError(f"missing required environment variable(s): {', '.join(missing)}")
    return Secrets(discord_token=env["DISCORD_TOKEN"], serpapi_api_key=env["SERPAPI_API_KEY"])
