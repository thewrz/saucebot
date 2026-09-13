from saucebot.engines.base import (
    DEFAULT_EXCLUDED_DOMAINS,
    NullEngine,
    SourceHit,
    filter_excluded_domains,
)


def hit(url: str) -> SourceHit:
    return SourceHit(url=url, title="t", site="s")


def test_default_exclusions_cover_discord_cdn_hosts() -> None:
    assert frozenset({"cdn.discordapp.com", "media.discordapp.net"}) == DEFAULT_EXCLUDED_DOMAINS


def test_filter_drops_exact_and_subdomain_matches_only() -> None:
    hits = [
        hit("https://cdn.discordapp.com/attachments/1/2/a.png"),
        hit("https://images.media.discordapp.net/x.png"),
        hit("https://notdiscordapp.com/a.png"),
        hit("https://example.com/meme"),
    ]
    kept = filter_excluded_domains(hits, DEFAULT_EXCLUDED_DOMAINS)
    assert [h.url for h in kept] == ["https://notdiscordapp.com/a.png", "https://example.com/meme"]


def test_filter_is_case_insensitive_and_tolerates_bad_urls() -> None:
    hits = [hit("HTTPS://CDN.DISCORDAPP.COM/a"), hit("not a url")]
    assert filter_excluded_domains(hits, DEFAULT_EXCLUDED_DOMAINS) == [hit("not a url")]


async def test_null_engine_never_finds_anything() -> None:
    assert await NullEngine().search("https://x/y.png", b"bytes") == []
