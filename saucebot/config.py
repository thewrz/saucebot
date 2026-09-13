"""Operator-tunable behaviour, loaded from TOML and validated before the bot connects.

This is the only module that reads TOML. Everything else receives a ``Config``.
"""

from __future__ import annotations

import string
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from saucebot.engines.base import DEFAULT_EXCLUDED_DOMAINS
from saucebot.errors import ConfigError

ALLOWED_PLACEHOLDERS: frozenset[str] = frozenset({"user", "source_url", "title", "author", "site"})
KNOWN_ENGINES: frozenset[str] = frozenset({"serpapi_lens"})

Snowflake = Annotated[int, Field(gt=0)]


class ResponseMode(StrEnum):
    REPLY = "reply"
    MENTION = "mention"


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WatchConfig(_Section):
    channel_ids: frozenset[Snowflake] = Field(min_length=1)
    user_ids: frozenset[Snowflake] = frozenset()
    min_seconds_between_callouts: int = Field(default=60, ge=0)


class SearchConfig(_Section):
    engine: str = "serpapi_lens"
    max_searches_per_day: int = Field(default=8, ge=1)
    max_attachments_per_message: int = Field(default=3, ge=1)
    excluded_domains: frozenset[str] = frozenset()

    @field_validator("engine")
    @classmethod
    def engine_must_be_known(cls, value: str) -> str:
        if value not in KNOWN_ENGINES:
            raise ValueError(f"engine must be one of {sorted(KNOWN_ENGINES)}, got {value!r}")
        return value

    @field_validator("excluded_domains")
    @classmethod
    def normalise_domains(cls, value: frozenset[str]) -> frozenset[str]:
        return frozenset(
            domain.strip().lower().removeprefix("www.") for domain in value if domain.strip()
        )


class MatchConfig(_Section):
    self_match_threshold: int = Field(default=80, ge=0, le=100)


class ResponseConfig(_Section):
    mode: ResponseMode = ResponseMode.REPLY
    templates: tuple[str, ...] = Field(min_length=1)

    @field_validator("templates")
    @classmethod
    def templates_use_only_known_placeholders(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for template in value:
            try:
                fields = {name for _, name, _, _ in string.Formatter().parse(template) if name}
            except ValueError as exc:
                raise ValueError(f"template {template!r} is malformed: {exc}") from exc
            unknown = fields - ALLOWED_PLACEHOLDERS
            if unknown:
                raise ValueError(
                    f"template {template!r} uses unknown placeholder(s) "
                    f"{sorted(unknown)}; allowed: {sorted(ALLOWED_PLACEHOLDERS)}"
                )
        return value

    @model_validator(mode="after")
    def mention_mode_needs_the_user_placeholder(self) -> ResponseConfig:
        if self.mode is ResponseMode.MENTION and not all("{user}" in t for t in self.templates):
            raise ValueError(
                'mode = "mention" requires every template to contain the {user} placeholder, '
                "otherwise the poster is never notified"
            )
        return self


class CommandConfig(_Section):
    prefix: str = Field(default="?", min_length=1, max_length=5)
    allowed_channel_ids: frozenset[Snowflake] = frozenset()


class Config(_Section):
    watch: WatchConfig
    search: SearchConfig = SearchConfig()
    match: MatchConfig = MatchConfig()
    response: ResponseConfig
    command: CommandConfig = CommandConfig()

    @property
    def all_excluded_domains(self) -> frozenset[str]:
        return self.search.excluded_domains | DEFAULT_EXCLUDED_DOMAINS


def parse_config(raw: dict[str, Any]) -> Config:
    """Validate an already-parsed TOML mapping. Raises ConfigError naming the bad key."""
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(_describe(exc)) from exc


def load_config(path: str | Path) -> Config:
    """Read and validate config.toml. Raises ConfigError naming the file or the bad key."""
    path = Path(path)
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"config file {path} is not valid TOML: {exc}") from exc
    try:
        return parse_config(raw)
    except ConfigError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _describe(exc: ValidationError) -> str:
    problems = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"]) or "config"
        problems.append(f"{location}: {error['msg']}")
    return "; ".join(problems)
