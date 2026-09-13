"""Turn a hit into the line the bot posts.

Kept free of Discord types so it can be tested as pure string work. The caller
is still responsible for passing AllowedMentions when it sends the result.
"""

from __future__ import annotations

import random
import re
from collections.abc import Sequence

from saucebot.engines.base import SourceHit
from saucebot.matching import handle_from_url

# Text from a third-party page title must never ping the server.
_MASS_MENTION = re.compile(r"@(everyone|here)")
_ROLE_OR_USER_MENTION = re.compile(r"<@[!&]?\d+>")


def author_label(hit: SourceHit) -> str:
    """The handle behind the source, falling back to the site name."""
    return handle_from_url(hit.url) or hit.site


def _defang(text: str) -> str:
    """Strip anything in untrusted text that Discord would turn into a ping."""
    text = _MASS_MENTION.sub(r"\1", text)
    return _ROLE_OR_USER_MENTION.sub("", text).strip()


def render(
    templates: Sequence[str],
    hit: SourceHit,
    user_mention: str,
    rng: random.Random | None = None,
) -> str:
    """Fill one randomly chosen template. Missing placeholders render as empty."""
    chooser = rng or random
    template = chooser.choice(list(templates))
    values = {
        "user": user_mention,
        "source_url": hit.url,
        "title": _defang(hit.title),
        "author": _defang(author_label(hit)),
        "site": _defang(hit.site),
    }
    return template.format_map(_Defaulting(values)).strip()


class _Defaulting(dict):
    """format_map helper: an unknown placeholder renders as empty, never raises."""

    def __missing__(self, key: str) -> str:
        return ""
