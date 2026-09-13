import textwrap
from pathlib import Path

import pytest

from saucebot.config import Config, ResponseMode, load_config, parse_config
from saucebot.errors import ConfigError

VALID = {
    "watch": {"channel_ids": [111], "user_ids": [222], "min_seconds_between_callouts": 60},
    "search": {
        "engine": "serpapi_lens",
        "max_searches_per_day": 8,
        "max_attachments_per_message": 3,
        "excluded_domains": ["example.com"],
    },
    "match": {"self_match_threshold": 80},
    "response": {"mode": "reply", "templates": ["Stolen meme! {source_url}"]},
    "command": {"prefix": "?", "allowed_channel_ids": []},
}


def with_change(section: str, key: str, value: object) -> dict:
    raw = {name: dict(body) for name, body in VALID.items()}
    raw[section][key] = value
    return raw


def test_parses_a_valid_config() -> None:
    config = parse_config(VALID)
    assert config.watch.channel_ids == frozenset({111})
    assert config.response.mode is ResponseMode.REPLY
    assert config.response.templates == ("Stolen meme! {source_url}",)


def test_defaults_apply_to_a_minimal_config() -> None:
    config = parse_config(
        {"watch": {"channel_ids": [111]}, "response": {"templates": ["{source_url}"]}}
    )
    assert config.search.max_searches_per_day == 8
    assert config.watch.min_seconds_between_callouts == 60
    assert config.match.self_match_threshold == 80
    assert config.search.max_attachments_per_message == 3
    assert config.command.prefix == "?"
    assert config.watch.user_ids == frozenset()


def test_discord_cdn_is_always_excluded_even_when_unconfigured() -> None:
    config = parse_config(VALID)
    assert "cdn.discordapp.com" in config.all_excluded_domains
    assert "media.discordapp.net" in config.all_excluded_domains
    assert "example.com" in config.all_excluded_domains


@pytest.mark.parametrize(
    ("raw", "expected_key"),
    [
        (with_change("watch", "channel_ids", []), "channel_ids"),
        (with_change("match", "self_match_threshold", 101), "self_match_threshold"),
        (with_change("match", "self_match_threshold", -1), "self_match_threshold"),
        (with_change("response", "mode", "shout"), "mode"),
        (with_change("response", "templates", []), "templates"),
        (with_change("search", "max_searches_per_day", 0), "max_searches_per_day"),
        (
            with_change("search", "max_attachments_per_message", 0),
            "max_attachments_per_message",
        ),
        (with_change("command", "prefix", ""), "prefix"),
        (with_change("search", "engine", "saucenao"), "engine"),
    ],
)
def test_invalid_values_raise_naming_the_key(raw: dict, expected_key: str) -> None:
    with pytest.raises(ConfigError, match=expected_key):
        parse_config(raw)


def test_unknown_placeholder_is_rejected_and_named() -> None:
    raw = with_change("response", "templates", ["{source_url} posted at {timestamp}"])
    with pytest.raises(ConfigError, match="timestamp"):
        parse_config(raw)


def test_every_allowed_placeholder_is_accepted() -> None:
    template = "{user} {source_url} {title} {author} {site}"
    config = parse_config(with_change("response", "templates", [template]))
    assert config.response.templates == (template,)


def test_mention_mode_requires_a_user_placeholder() -> None:
    raw = with_change("response", "mode", "mention")
    with pytest.raises(ConfigError, match="user"):
        parse_config(raw)


def test_mention_mode_accepts_templates_that_mention() -> None:
    raw = with_change("response", "mode", "mention")
    raw["response"]["templates"] = ["{user} stolen! {source_url}"]
    assert parse_config(raw).response.mode is ResponseMode.MENTION


def test_mention_mode_rejects_an_escaped_user_placeholder() -> None:
    raw = with_change("response", "mode", "mention")
    raw["response"]["templates"] = ["{{user}} stolen! {source_url}"]
    with pytest.raises(ConfigError, match="user"):
        parse_config(raw)


def test_mention_mode_accepts_a_real_user_placeholder_with_escaped_braces() -> None:
    raw = with_change("response", "mode", "mention")
    template = "{{user}} says {user} stole it: {source_url}"
    raw["response"]["templates"] = [template]
    assert parse_config(raw).response.templates == (template,)


def test_malformed_template_braces_are_rejected() -> None:
    with pytest.raises(ConfigError, match="template"):
        parse_config(with_change("response", "templates", ["{source_url"]))


@pytest.mark.parametrize(
    "template",
    ["{}", "{0}", "{source_url:{timestamp}}", "{user!z}", "{user!r}"],
)
def test_unsupported_template_syntax_is_rejected(template: str) -> None:
    with pytest.raises(ConfigError, match=r"response\.templates.*invalid syntax"):
        parse_config(with_change("response", "templates", [template]))


@pytest.mark.parametrize("template", ["{{literal}} {source_url}", "Use {{ and }}: {site}"])
def test_escaped_literal_braces_are_accepted(template: str) -> None:
    config = parse_config(with_change("response", "templates", [template]))
    assert config.response.templates == (template,)


def test_load_config_reads_a_file(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        textwrap.dedent(
            """
            [watch]
            channel_ids = [111]

            [response]
            templates = ["Stolen meme! {source_url}"]
            """
        )
    )
    assert isinstance(load_config(path), Config)


def test_load_config_names_a_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"nope\.toml"):
        load_config(tmp_path / "nope.toml")


def test_load_config_reports_malformed_toml(tmp_path: Path) -> None:
    path = tmp_path / "bad.toml"
    path.write_text("[watch\n")
    with pytest.raises(ConfigError, match=r"bad\.toml"):
        load_config(path)


def test_shipped_example_config_is_valid() -> None:
    assert isinstance(load_config(Path(__file__).parent.parent / "config.example.toml"), Config)
