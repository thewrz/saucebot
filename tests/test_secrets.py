import pytest

from saucebot.errors import ConfigError
from saucebot.secrets import Secrets, load_secrets


def test_loads_both_secrets() -> None:
    env = {"DISCORD_TOKEN": "d", "SERPAPI_API_KEY": "s", "OTHER": "x"}
    assert load_secrets(env) == Secrets(discord_token="d", serpapi_api_key="s")


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, "DISCORD_TOKEN, SERPAPI_API_KEY"),
        ({"DISCORD_TOKEN": "d"}, "SERPAPI_API_KEY"),
        ({"DISCORD_TOKEN": "", "SERPAPI_API_KEY": "s"}, "DISCORD_TOKEN"),
    ],
)
def test_missing_or_empty_secrets_are_named(env: dict[str, str], expected: str) -> None:
    with pytest.raises(ConfigError, match=expected):
        load_secrets(env)
