from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

from saucebot.budget import DailyBudget
from saucebot.config import parse_config
from saucebot.engines.base import SourceHit
from saucebot.exts.watcher import Cooldown, Watcher, identities_of, image_attachments, should_watch

WATCHED_CHANNEL = 111
WATCHED_USER = 222


def config(**watch_overrides):
    watch = {"channel_ids": [WATCHED_CHANNEL], "user_ids": [WATCHED_USER]}
    watch.update(watch_overrides)
    return parse_config({"watch": watch, "response": {"templates": ["{source_url}"]}})


def attachment(content_type: str | None = "image/png", *, url: str = "https://cdn/x.png"):
    return SimpleNamespace(
        content_type=content_type, url=url, read=AsyncMock(return_value=b"image")
    )


def message(
    *,
    channel_id: int = WATCHED_CHANNEL,
    author_id: int = WATCHED_USER,
    author_name: str = "poster",
    is_bot: bool = False,
    webhook_id: int | None = None,
    attachments: list | None = None,
):
    author = SimpleNamespace(
        id=author_id,
        name=author_name,
        global_name=None,
        display_name=author_name,
        bot=is_bot,
        mention=f"<@{author_id}>",
    )
    return SimpleNamespace(
        id=999,
        channel=SimpleNamespace(id=channel_id, send=AsyncMock()),
        author=author,
        webhook_id=webhook_id,
        attachments=attachments if attachments is not None else [attachment()],
        reply=AsyncMock(),
    )


@dataclass
class StubEngine:
    hits: list[SourceHit] | None = None
    error: Exception | None = None
    calls: int = 0

    async def search(self, image_url: str, image_bytes: bytes) -> list[SourceHit]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return list(self.hits or [])


def bot(tmp_path, engine, *, response=None, budget_limit: int = 5, command_valid: bool = False):
    raw = {"watch": {"channel_ids": [WATCHED_CHANNEL], "user_ids": [WATCHED_USER]}}
    raw["response"] = response or {"templates": ["{source_url}"]}
    return SimpleNamespace(
        config=parse_config(raw),
        engine=engine,
        budget=DailyBudget(tmp_path / "budget.json", max_per_day=budget_limit),
        get_context=AsyncMock(return_value=SimpleNamespace(valid=command_valid)),
    )


def test_watches_a_targeted_user_in_a_targeted_channel() -> None:
    assert should_watch(message(), config()) is True


def test_ignores_other_channels() -> None:
    assert should_watch(message(channel_id=999), config()) is False


def test_ignores_untargeted_users() -> None:
    assert should_watch(message(author_id=999), config()) is False


def test_an_empty_user_list_watches_everyone() -> None:
    assert should_watch(message(author_id=999), config(user_ids=[])) is True


def test_ignores_bots() -> None:
    assert should_watch(message(is_bot=True), config(user_ids=[])) is False


def test_ignores_webhooks() -> None:
    assert should_watch(message(webhook_id=5), config(user_ids=[])) is False


def test_ignores_messages_without_images() -> None:
    assert should_watch(message(attachments=[]), config()) is False
    assert should_watch(message(attachments=[attachment("video/mp4")]), config()) is False


def test_image_attachments_respects_the_limit() -> None:
    msg = message(attachments=[attachment(), attachment(), attachment("text/plain"), attachment()])
    assert len(image_attachments(msg, limit=2)) == 2


def test_image_attachments_skips_unknown_content_types() -> None:
    msg = message(attachments=[attachment(None), attachment("image/gif")])
    assert len(image_attachments(msg, limit=5)) == 1


def test_identities_include_name_display_name_and_nick() -> None:
    member = SimpleNamespace(
        name="username", global_name="Display Name", display_name="Server Nick"
    )
    assert identities_of(member) == ["username", "Display Name", "Server Nick"]


def test_identities_tolerate_a_user_without_a_global_name() -> None:
    member = SimpleNamespace(name="username", global_name=None, display_name="username")
    assert identities_of(member) == ["username"]


def test_cooldown_blocks_a_second_callout_inside_the_window() -> None:
    now = {"t": 1000.0}
    cooldown = Cooldown(seconds=60, clock=lambda: now["t"])
    assert cooldown.check_and_stamp(1) is True
    assert cooldown.check_and_stamp(1) is False
    now["t"] = 1059.0
    assert cooldown.check_and_stamp(1) is False
    now["t"] = 1060.0
    assert cooldown.check_and_stamp(1) is True


def test_cooldown_is_per_user() -> None:
    cooldown = Cooldown(seconds=60, clock=lambda: 1000.0)
    assert cooldown.check_and_stamp(1) is True
    assert cooldown.check_and_stamp(2) is True


def test_a_zero_cooldown_never_blocks() -> None:
    cooldown = Cooldown(seconds=0, clock=lambda: 1000.0)
    assert cooldown.check_and_stamp(1) is True
    assert cooldown.check_and_stamp(1) is True


async def test_successful_nonself_hit_replies_once(tmp_path) -> None:
    engine = StubEngine(hits=[SourceHit("https://source.example/post", "Source", "Source")])
    msg = message()
    cog = Watcher(bot(tmp_path, engine))

    await cog.on_message(msg)

    msg.reply.assert_awaited_once()
    msg.channel.send.assert_not_awaited()
    assert msg.reply.await_args.args == ("https://source.example/post",)
    assert engine.calls == 1


async def test_valid_command_is_not_processed_by_watcher(tmp_path) -> None:
    engine = StubEngine(hits=[SourceHit("https://source.example/post", "Source", "Source")])
    msg = message()
    runtime = bot(tmp_path, engine, command_valid=True)

    await Watcher(runtime).on_message(msg)

    runtime.get_context.assert_awaited_once_with(msg)
    assert engine.calls == 0
    msg.attachments[0].read.assert_not_awaited()
    msg.reply.assert_not_awaited()
    msg.channel.send.assert_not_awaited()


async def test_no_hits_are_silent(tmp_path) -> None:
    engine = StubEngine(hits=[])
    msg = message()
    await Watcher(bot(tmp_path, engine)).on_message(msg)

    msg.reply.assert_not_awaited()
    msg.channel.send.assert_not_awaited()


async def test_self_hit_is_silent(tmp_path) -> None:
    engine = StubEngine(
        hits=[SourceHit("https://instagram.com/poster/p/123", "poster", "Instagram")]
    )
    msg = message()
    await Watcher(bot(tmp_path, engine)).on_message(msg)

    msg.reply.assert_not_awaited()
    msg.channel.send.assert_not_awaited()


async def test_over_budget_is_silent_and_does_not_call_engine(tmp_path) -> None:
    engine = StubEngine(hits=[SourceHit("https://source.example/post", "Source", "Source")])
    msg = message()
    await Watcher(bot(tmp_path, engine, budget_limit=0)).on_message(msg)

    assert engine.calls == 0
    msg.reply.assert_not_awaited()
    msg.channel.send.assert_not_awaited()


async def test_multiple_attachments_produce_at_most_one_callout(tmp_path) -> None:
    engine = StubEngine(hits=[SourceHit("https://source.example/post", "Source", "Source")])
    msg = message(attachments=[attachment(), attachment()])
    await Watcher(bot(tmp_path, engine)).on_message(msg)

    assert engine.calls == 1
    msg.reply.assert_awaited_once()


async def test_unexpected_engine_error_is_swallowed_without_chat_error(tmp_path) -> None:
    engine = StubEngine(error=RuntimeError("unexpected engine failure"))
    msg = message()
    await Watcher(bot(tmp_path, engine)).on_message(msg)

    msg.reply.assert_not_awaited()
    msg.channel.send.assert_not_awaited()


async def test_mention_mode_sends_to_channel_and_binds_allowed_user_to_poster(tmp_path) -> None:
    engine = StubEngine(hits=[SourceHit("https://source.example/<@999>", "Source", "Source")])
    msg = message()
    response = {"mode": "mention", "templates": ["{user} source {source_url}"]}
    await Watcher(bot(tmp_path, engine, response=response)).on_message(msg)

    msg.reply.assert_not_awaited()
    msg.channel.send.assert_awaited_once()
    kwargs = msg.channel.send.await_args.kwargs
    allowed = kwargs["allowed_mentions"]
    assert allowed.everyone is False
    assert allowed.roles is False
    assert allowed.replied_user is True
    assert allowed.users == [msg.author]
    assert "<@999>" in msg.channel.send.await_args.args[0]


async def test_reply_mode_passes_allowed_mentions(tmp_path) -> None:
    engine = StubEngine(hits=[SourceHit("https://source.example/post", "Source", "Source")])
    msg = message()
    await Watcher(bot(tmp_path, engine)).on_message(msg)

    allowed = msg.reply.await_args.kwargs["allowed_mentions"]
    assert allowed.everyone is False
    assert allowed.roles is False
    assert allowed.users == [msg.author]
