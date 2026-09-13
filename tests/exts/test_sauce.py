from types import SimpleNamespace

import pytest

from saucebot.exts.sauce import MessageRef, first_image_attachment, parse_message_link


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


async def test_sauce_refuses_cross_guild_link_before_fetch_or_search() -> None:
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

    from saucebot.exts.sauce import Sauce

    cog = Sauce(SimpleNamespace(engine=FailingEngine()))
    await cog.sauce.callback(cog, ctx, "https://discord.com/channels/2/3/4")

    assert replies == ["That isn't a message link from this server."]
