from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from saucebot.budget import DailyBudget
from saucebot.config import parse_config
from saucebot.engines.base import NullEngine
from saucebot.exts.sauce import MessageRef, Sauce, first_image_attachment, parse_message_link


@pytest.mark.parametrize(
    "link",
    [
        "https://discord.com/channels/1/2/3",
        "https://ptb.discord.com/channels/1/2/3",
        "https://canary.discord.com/channels/1/2/3/",
        "https://discordapp.com/channels/1/2/3",
        "  https://discord.com/channels/1/2/3  ",
    ],
)
def test_parses_every_discord_host_variant(link: str) -> None:
    assert parse_message_link(link) == MessageRef(guild_id=1, channel_id=2, message_id=3)


@pytest.mark.parametrize(
    "link",
    [
        "http://discord.com/channels/1/2/3",
        "https://evil.com/channels/1/2/3",
        "https://discord.com/channels/1/2",
        "https://discord.com/channels/a/b/c",
        "3",
    ],
)
def test_rejects_non_message_links(link: str) -> None:
    assert parse_message_link(link) is None


def attachment(content_type: str | None) -> SimpleNamespace:
    return SimpleNamespace(content_type=content_type, url="https://cdn/x")


def test_first_image_attachment_skips_video_and_unknown_types() -> None:
    message = SimpleNamespace(
        attachments=[attachment("video/mp4"), attachment(None), attachment("image/png")]
    )
    assert first_image_attachment(message) is message.attachments[2]


def test_first_image_attachment_returns_none_without_images() -> None:
    assert first_image_attachment(SimpleNamespace(attachments=[attachment("text/plain")])) is None


async def test_sauce_refuses_cross_guild_link_before_fetch_or_search(tmp_path: Path) -> None:
    class FailingEngine:
        async def search(self, image_url: str, image_bytes: bytes) -> list[object]:
            raise AssertionError("cross-guild links must not reach the engine")

    async def unexpected_fetch(*args: object, **kwargs: object) -> object:
        raise AssertionError("cross-guild links must not fetch a message")

    replies: list[str] = []

    async def reply(content: str) -> None:
        replies.append(content)

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1, get_channel_or_thread=unexpected_fetch),
        message=SimpleNamespace(id=99, attachments=[]),
        reply=reply,
    )

    config = parse_config(
        {"watch": {"channel_ids": [1]}, "response": {"templates": ["{source_url}"]}}
    )
    cog = Sauce(
        SimpleNamespace(
            engine=FailingEngine(),
            budget=DailyBudget(path=tmp_path / "budget.json", max_per_day=1),
            config=config,
        )
    )
    await cog.sauce.callback(cog, ctx, "https://discord.com/channels/2/3/4")

    assert replies == ["That isn't a message link from this server."]


async def test_sauce_is_silent_in_a_disallowed_channel(tmp_path: Path) -> None:
    replies: list[str] = []

    async def reply(content: str) -> None:
        replies.append(content)

    ctx = SimpleNamespace(
        guild=SimpleNamespace(id=1),
        channel=SimpleNamespace(id=99),
        message=SimpleNamespace(id=100, attachments=[]),
        reply=reply,
    )
    config = parse_config(
        {
            "watch": {"channel_ids": [1]},
            "response": {"templates": ["{source_url}"]},
            "command": {"allowed_channel_ids": [42]},
        }
    )
    cog = Sauce(
        SimpleNamespace(
            engine=NullEngine(),
            budget=DailyBudget(path=tmp_path / "budget.json", max_per_day=1),
            config=config,
        )
    )

    await cog.sauce.callback(cog, ctx)

    assert replies == []


@asynccontextmanager
async def _typing():
    yield


def _configured_bot(engine):
    return SimpleNamespace(
        engine=engine,
        budget=SimpleNamespace(acquire=AsyncMock(return_value=True)),
        config=parse_config(
            {"watch": {"channel_ids": [1]}, "response": {"templates": ["{source_url}"]}}
        ),
    )


def _replying_context(channel: object, *, author_id: int = 7) -> tuple[SimpleNamespace, list[str]]:
    replies: list[str] = []

    async def reply(content: str) -> None:
        replies.append(content)

    ctx = SimpleNamespace(
        author=SimpleNamespace(id=author_id),
        guild=SimpleNamespace(id=1, get_channel_or_thread=lambda channel_id: channel),
        message=SimpleNamespace(id=99, attachments=[]),
        reply=reply,
        typing=_typing,
    )
    return ctx, replies


@pytest.mark.parametrize(
    "permissions",
    [
        pytest.param(
            SimpleNamespace(view_channel=False, read_message_history=True, manage_threads=False),
            id="missing-view-channel",
        ),
        pytest.param(
            SimpleNamespace(view_channel=True, read_message_history=False, manage_threads=False),
            id="missing-read-history",
        ),
    ],
)
async def test_linked_message_requires_caller_read_permissions_before_fetch_or_search(
    permissions: SimpleNamespace,
) -> None:
    channel = SimpleNamespace(permissions_for=lambda member: permissions)

    async def unexpected_fetch(*args: object, **kwargs: object) -> object:
        raise AssertionError("an unauthorized caller must not fetch the source message")

    channel.fetch_message = unexpected_fetch
    ctx, replies = _replying_context(channel)

    class FailingEngine:
        async def search(self, image_url: str, image_bytes: bytes) -> list[object]:
            raise AssertionError("an unauthorized caller must not reach the engine")

    from saucebot.exts.sauce import Sauce

    cog = Sauce(_configured_bot(FailingEngine()))
    await cog.sauce.callback(cog, ctx, "https://discord.com/channels/1/2/3")

    assert replies == ["I can't see that message."]


async def test_linked_message_with_caller_read_permissions_fetches_and_searches() -> None:
    permissions = SimpleNamespace(
        view_channel=True, read_message_history=True, manage_threads=False
    )
    image = attachment("image/png")
    image.read = AsyncMock(return_value=b"image")
    channel = SimpleNamespace(permissions_for=lambda member: permissions)
    channel.fetch_message = AsyncMock(return_value=SimpleNamespace(attachments=[image]))
    ctx, replies = _replying_context(channel)

    class EmptyEngine:
        async def search(self, image_url: str, image_bytes: bytes) -> list[object]:
            assert image_url == image.url
            assert image_bytes == b"image"
            return []

    from saucebot.exts.sauce import Sauce

    cog = Sauce(_configured_bot(EmptyEngine()))
    await cog.sauce.callback(cog, ctx, "https://discord.com/channels/1/2/3")

    channel.fetch_message.assert_awaited_once_with(3)
    assert replies == ["No source found."]


async def test_private_thread_nonmember_cannot_borrow_bot_access() -> None:
    permissions = SimpleNamespace(
        view_channel=True, read_message_history=True, manage_threads=False
    )
    channel = MagicMock(spec=discord.Thread)
    channel.is_private.return_value = True
    channel.permissions_for.return_value = permissions
    channel.fetch_member = AsyncMock(
        side_effect=discord.NotFound(
            SimpleNamespace(status=404, reason="Not Found"), "not a member"
        )
    )
    channel.fetch_message = AsyncMock(
        side_effect=AssertionError("a private-thread nonmember must not fetch the source message")
    )
    ctx, replies = _replying_context(channel)

    class FailingEngine:
        async def search(self, image_url: str, image_bytes: bytes) -> list[object]:
            raise AssertionError("a private-thread nonmember must not reach the engine")

    from saucebot.exts.sauce import Sauce

    cog = Sauce(_configured_bot(FailingEngine()))
    await cog.sauce.callback(cog, ctx, "https://discord.com/channels/1/2/3")

    channel.fetch_member.assert_awaited_once_with(7)
    assert replies == ["I can't see that message."]


async def test_private_thread_member_can_fetch_linked_message() -> None:
    permissions = SimpleNamespace(
        view_channel=True, read_message_history=True, manage_threads=False
    )
    channel = MagicMock(spec=discord.Thread)
    channel.is_private.return_value = True
    channel.permissions_for.return_value = permissions
    channel.fetch_member = AsyncMock(return_value=SimpleNamespace(id=7))
    image = attachment("image/png")
    image.read = AsyncMock(return_value=b"image")
    channel.fetch_message = AsyncMock(return_value=SimpleNamespace(attachments=[image]))
    ctx, replies = _replying_context(channel)

    class EmptyEngine:
        async def search(self, image_url: str, image_bytes: bytes) -> list[object]:
            return []

    from saucebot.exts.sauce import Sauce

    cog = Sauce(_configured_bot(EmptyEngine()))
    await cog.sauce.callback(cog, ctx, "https://discord.com/channels/1/2/3")

    channel.fetch_member.assert_awaited_once_with(7)
    channel.fetch_message.assert_awaited_once_with(3)
    assert replies == ["No source found."]
