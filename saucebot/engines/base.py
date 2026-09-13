"""Engine contract shared by every reverse-image backend.

Nothing in this module knows about Discord. An engine turns an image into a
list of ``SourceHit``; everything downstream consumes only that.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

DEFAULT_EXCLUDED_DOMAINS: frozenset[str] = frozenset({"cdn.discordapp.com", "media.discordapp.net"})


@dataclass(frozen=True)
class SourceHit:
    """One page on which the searched image was found."""

    url: str
    title: str
    site: str


class EngineError(Exception):
    """The engine could not complete a search."""


class BadKeyError(EngineError):
    """The API rejected the configured key."""


class QuotaError(EngineError):
    """The API's own quota is exhausted."""


class ImageSearchEngine(Protocol):
    async def search(self, image_url: str, image_bytes: bytes) -> list[SourceHit]:
        """Return pages where the image appears, best first. Empty means no source."""
        ...


class NullEngine:
    """Engine that never finds anything. Placeholder until a real engine is wired."""

    async def search(self, image_url: str, image_bytes: bytes) -> list[SourceHit]:
        return []


def hostname_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def is_excluded(url: str, excluded: frozenset[str]) -> bool:
    host = hostname_of(url)
    return any(host == domain or host.endswith("." + domain) for domain in excluded)


def filter_excluded_domains(hits: list[SourceHit], excluded: frozenset[str]) -> list[SourceHit]:
    """Drop hits whose host is an excluded domain or a subdomain of one."""
    return [hit for hit in hits if not is_excluded(hit.url, excluded)]
