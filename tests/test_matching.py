import pytest

from saucebot.engines.base import SourceHit
from saucebot.matching import (
    PROFILE_HOSTS,
    first_non_self_hit,
    handle_from_url,
    is_self_post,
    normalise,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("@Freaq", "freaq"),
        ("DJ_Freaq", "djfreaq"),
        ("dj.freaq", "djfreaq"),
        ("dj-freaq", "djfreaq"),
        ("Freaq2024", "freaq"),
        ("  Freaq  ", "freaq"),
        ("", ""),
        ("1234", ""),
    ],
)
def test_normalise_strips_decoration_and_trailing_digits(raw: str, expected: str) -> None:
    assert normalise(raw) == expected


def test_profile_hosts_exposes_each_extraction_strategy() -> None:
    assert PROFILE_HOSTS == {
        "twitter.com": "path_index",
        "x.com": "path_index",
        "instagram.com": "path_index",
        "tiktok.com": "path_index",
        "deviantart.com": "path_index",
        "reddit.com": "after_segment",
        "bsky.app": "after_segment",
        "tumblr.com": "subdomain",
    }


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://twitter.com/pisuke_/status/1119375369423876096", "pisuke_"),
        ("https://x.com/pisuke_/status/1119375369423876096", "pisuke_"),
        ("https://www.reddit.com/u/spez/", "spez"),
        ("https://reddit.com/user/spez/comments/abc/title/", "spez"),
        ("https://www.instagram.com/p/abc/", ""),
        ("https://www.instagram.com/someartist/", "someartist"),
        ("https://www.tiktok.com/@someartist/video/123", "someartist"),
        ("https://bsky.app/profile/artist.bsky.social/post/abc", "artist.bsky.social"),
        ("https://www.deviantart.com/pantherd1945/art/Thing-123", "pantherd1945"),
        ("https://someartist.tumblr.com/post/123", "someartist"),
        ("https://www.facebook.com/pythonlang/", ""),
        ("https://example.com/some/page", ""),
        ("not a url", ""),
        ("https://twitter.com/", ""),
    ],
)
def test_handle_extraction_per_site(url: str, expected: str) -> None:
    assert handle_from_url(url) == expected


def hit(url: str = "https://example.com/x", title: str = "", site: str = "") -> SourceHit:
    return SourceHit(url=url, title=title, site=site)


def test_matching_handle_is_a_self_post() -> None:
    assert is_self_post(["Freaq"], hit("https://twitter.com/freaq_/status/1"), 80) is True


def test_different_handle_is_not_a_self_post() -> None:
    assert is_self_post(["Freaq"], hit("https://twitter.com/someoneelse/status/1"), 80) is False


def test_display_name_in_the_page_title_is_a_self_post() -> None:
    assert is_self_post(["djfreaq"], hit(title="Art by DJ Freaq - DeviantArt"), 80) is True


def test_site_name_alone_never_matches() -> None:
    assert is_self_post(["Reddit"], hit(site="Reddit"), 80) is False


def test_a_hit_with_no_handle_and_no_title_never_matches() -> None:
    assert is_self_post(["anyone"], hit(), 80) is False


def test_an_empty_identity_never_matches() -> None:
    assert is_self_post(["", "   "], hit("https://twitter.com/someone/status/1"), 80) is False


def test_threshold_is_inclusive() -> None:
    identity, handle_hit = "abcdefghij", hit("https://twitter.com/abcdefghix/status/1")
    assert is_self_post([identity], handle_hit, 90) is True
    assert is_self_post([identity], handle_hit, 91) is False


def test_any_identity_matching_is_enough() -> None:
    identities = ["someusername", "Server Nickname", "freaq"]
    assert is_self_post(identities, hit("https://twitter.com/freaq/status/1"), 80) is True


def test_first_non_self_hit_skips_the_posters_own_pages() -> None:
    hits = [
        hit("https://twitter.com/freaq/status/1"),
        hit("https://knowyourmeme.com/memes/thing"),
    ]
    chosen = first_non_self_hit(hits, ["freaq"], 80)
    assert chosen is not None
    assert chosen.url == "https://knowyourmeme.com/memes/thing"


def test_first_non_self_hit_returns_none_when_every_hit_is_the_poster() -> None:
    hits = [
        hit("https://twitter.com/freaq/status/1"),
        hit("https://www.deviantart.com/freaq/art/X"),
    ]
    assert first_non_self_hit(hits, ["freaq"], 80) is None


def test_first_non_self_hit_on_an_empty_list() -> None:
    assert first_non_self_hit([], ["freaq"], 80) is None
