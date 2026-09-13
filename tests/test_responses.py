import random

from saucebot.engines.base import SourceHit
from saucebot.responses import author_label, render


def hit(
    url: str = "https://knowyourmeme.com/memes/x", title: str = "Meme", site: str = "KYM"
) -> SourceHit:
    return SourceHit(url=url, title=title, site=site)


def test_author_label_prefers_the_url_handle() -> None:
    assert author_label(hit(url="https://twitter.com/pisuke_/status/1")) == "pisuke_"


def test_author_label_falls_back_to_the_site_name() -> None:
    assert author_label(hit(url="https://example.com/page", site="Example Site")) == "Example Site"


def test_author_label_is_empty_when_there_is_nothing_to_say() -> None:
    assert author_label(SourceHit(url="https://example.com/p", title="", site="")) == ""


def test_renders_every_placeholder() -> None:
    template = "{user} {source_url} {title} {author} {site}"
    text = render([template], hit(url="https://twitter.com/pisuke_/status/1"), "<@1>")
    assert text == "<@1> https://twitter.com/pisuke_/status/1 Meme pisuke_ KYM"


def test_a_template_may_omit_placeholders() -> None:
    assert render(["Stolen meme!"], hit(), "<@1>") == "Stolen meme!"


def test_picks_from_the_template_list_deterministically_with_a_seeded_rng() -> None:
    templates = ["one {source_url}", "two {source_url}", "three {source_url}"]
    chosen = {render(templates, hit(), "<@1>", rng=random.Random(seed)) for seed in range(20)}
    assert len(chosen) == 3


def test_everyone_and_here_in_a_title_are_defanged() -> None:
    text = render(["{title} {source_url}"], hit(title="@everyone look @here"), "<@1>")
    assert "@everyone" not in text
    assert "@here" not in text
    assert "everyone" in text


def test_a_role_mention_in_a_title_is_defanged() -> None:
    text = render(["{title}"], hit(title="see <@&12345>"), "<@1>")
    assert "<@&12345>" not in text


def test_the_user_mention_itself_survives() -> None:
    assert render(["{user} busted"], hit(), "<@123456789>") == "<@123456789> busted"
