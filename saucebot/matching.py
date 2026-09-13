"""Decide whether the person who posted an image is the person who made it.

Pure string work: no Discord types, no HTTP. The bot stays silent when a hit
looks like the poster's own page, which is the difference between a joke and
an insult.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from urllib.parse import urlsplit

from rapidfuzz import fuzz

from saucebot.engines.base import SourceHit

_DECORATION = re.compile(r"[\s._\-@]+")
_TRAILING_DIGITS = re.compile(r"\d+$")
_TITLE_SPLIT = re.compile(r"[^0-9A-Za-z]+")

# Hosts whose URL path carries the author's handle, and the path index it sits at.
_HANDLE_AT_INDEX: dict[str, int] = {
    "twitter.com": 0,
    "x.com": 0,
    "instagram.com": 0,
    "tiktok.com": 0,
    "deviantart.com": 0,
}
_HANDLE_AFTER_SEGMENT: dict[str, tuple[str, ...]] = {
    "reddit.com": ("u", "user"),
    "bsky.app": ("profile",),
}
# Public host-to-strategy metadata for callers that need to inspect supported profiles.
PROFILE_HOSTS: dict[str, str] = {
    **{host: "path_index" for host in _HANDLE_AT_INDEX},
    **{host: "after_segment" for host in _HANDLE_AFTER_SEGMENT},
    "tumblr.com": "subdomain",
}

# Paths on the above hosts that are content, not profiles.
_NOT_A_HANDLE = frozenset({"p", "reel", "status", "art", "explore", "i", "web", "home", "video"})


def normalise(value: str) -> str:
    """Lowercase, drop decoration and a trailing number, so `DJ_Freaq2024` -> `djfreaq`."""
    collapsed = _DECORATION.sub("", value.strip().lower())
    return _TRAILING_DIGITS.sub("", collapsed)


def handle_from_url(url: str) -> str:
    """Pull the author's handle out of a profile-style URL. Empty when there isn't one."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https"):
        return ""
    host = (parts.hostname or "").lower().removeprefix("www.")
    segments = [segment for segment in parts.path.split("/") if segment]

    if host.endswith(".tumblr.com"):
        return host.removesuffix(".tumblr.com")

    for suffix, index in _HANDLE_AT_INDEX.items():
        if host == suffix or host.endswith("." + suffix):
            if len(segments) <= index:
                return ""
            candidate = segments[index].lstrip("@")
            return "" if candidate.lower() in _NOT_A_HANDLE else candidate

    for suffix, markers in _HANDLE_AFTER_SEGMENT.items():
        if host == suffix or host.endswith("." + suffix):
            for marker in markers:
                if marker in segments:
                    position = segments.index(marker)
                    if position + 1 < len(segments):
                        return segments[position + 1]
            return ""
    return ""


def title_candidates(title: str) -> list[str]:
    """Normalised name-shaped fragments of a page title.

    Each word, plus each adjacent pair joined, so a title like
    "Art by DJ Freaq - DeviantArt" yields the candidate "djfreaq" and matches a
    poster called ``DJ_Freaq``. Collapsing the whole title into one string
    instead would score ~48 against a 7-character name and never match.
    """
    words = [word for word in _TITLE_SPLIT.split(title) if word]
    pairs = [words[index] + words[index + 1] for index in range(len(words) - 1)]
    candidates = [normalise(fragment) for fragment in (*words, *pairs)]
    return [candidate for candidate in candidates if candidate]


def is_self_post(identities: Iterable[str], hit: SourceHit, threshold: int) -> bool:
    """True when any of the poster's names looks like the author of this hit."""
    candidates = [normalise(identity) for identity in identities]
    candidates = [candidate for candidate in candidates if candidate]
    if not candidates:
        return False

    handle = normalise(handle_from_url(hit.url))
    fragments = title_candidates(hit.title)
    for candidate in candidates:
        if handle and fuzz.ratio(candidate, handle) >= threshold:
            return True
        if any(fuzz.ratio(candidate, fragment) >= threshold for fragment in fragments):
            return True
    return False


def first_non_self_hit(
    hits: Sequence[SourceHit], identities: Iterable[str], threshold: int
) -> SourceHit | None:
    """The best hit that isn't the poster's own page, or None if they all are."""
    names = list(identities)
    for hit in hits:
        if not is_self_post(names, hit, threshold):
            return hit
    return None
