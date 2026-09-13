import json
import logging
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

from saucebot.budget import DailyBudget
from saucebot.engines.base import BadKeyError, EngineError, QuotaError, SourceHit
from saucebot.engines.serpapi_lens import SerpApiLensEngine, parse_exact_matches
from saucebot.exts.sauce import lookup_source

FIXTURES = Path(__file__).parent.parent / "fixtures"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def test_parses_captured_exact_matches() -> None:
    hits = parse_exact_matches(fixture("serpapi_exact_matches"))
    assert len(hits) == 5
    assert hits[0] == SourceHit(
        url="https://www.facebook.com/pythonlang/?locale=bs_BA",
        title="Python (@pythonlang) - Facebook",
        site="Facebook",
    )
    assert hits[1].url == "https://github.com/pygraz"


def test_no_results_response_is_empty_not_an_error() -> None:
    # HTTP 200 carrying a top-level `error` string means Lens found nothing.
    assert parse_exact_matches(fixture("serpapi_no_results")) == []


def test_missing_exact_matches_key_is_empty() -> None:
    assert parse_exact_matches({"search_metadata": {"status": "Success"}}) == []


def test_results_missing_a_link_are_skipped() -> None:
    payload = {
        "exact_matches": [{"position": 1, "title": "t", "source": "s"}, {"link": "https://ok"}]
    }
    assert [h.url for h in parse_exact_matches(payload)] == ["https://ok"]


def test_absent_optional_fields_become_empty_strings() -> None:
    hits = parse_exact_matches({"exact_matches": [{"link": "https://ok"}]})
    assert hits == [SourceHit(url="https://ok", title="", site="")]


@pytest.fixture
async def serpapi(aiohttp_server):
    """A stub SerpApi whose behaviour each test selects with a query flag."""
    state: dict[str, object] = {"status": 200, "payload": fixture("serpapi_exact_matches")}

    async def handler(request: web.Request) -> web.Response:
        state["last_query"] = dict(request.query)
        return web.json_response(state["payload"], status=state["status"])

    app = web.Application()
    app.router.add_get("/search", handler)
    server = await aiohttp_server(app)
    return server, state


async def make_engine(
    server, api_key: str = "test-key"
) -> tuple[SerpApiLensEngine, aiohttp.ClientSession]:
    session = aiohttp.ClientSession()
    engine = SerpApiLensEngine(
        session=session, api_key=api_key, endpoint=str(server.make_url("/search"))
    )
    return engine, session


async def test_search_sends_the_required_parameters(serpapi) -> None:
    server, state = serpapi
    engine, session = await make_engine(server)
    async with session:
        await engine.search("https://cdn.example/image.png", b"")
    assert state["last_query"] == {
        "engine": "google_lens",
        "type": "exact_matches",
        "url": "https://cdn.example/image.png",
        "api_key": "test-key",
    }


async def test_search_returns_hits(serpapi) -> None:
    server, _ = serpapi
    engine, session = await make_engine(server)
    async with session:
        hits = await engine.search("https://cdn.example/image.png", b"")
    assert hits[0].site == "Facebook"


async def test_search_returns_empty_for_the_no_results_response(serpapi) -> None:
    server, state = serpapi
    state["payload"] = fixture("serpapi_no_results")
    engine, session = await make_engine(server)
    async with session:
        assert await engine.search("https://cdn.example/image.png", b"") == []


async def test_unauthorised_raises_bad_key(serpapi) -> None:
    server, state = serpapi
    state["status"] = 401
    state["payload"] = {"error": "Invalid API key."}
    engine, session = await make_engine(server)
    async with session:
        with pytest.raises(BadKeyError, match="HTTP 401"):
            await engine.search("https://cdn.example/image.png", b"")


async def test_rate_limited_raises_quota(serpapi) -> None:
    server, state = serpapi
    state["status"] = 429
    state["payload"] = {"error": "Your account has run out of searches."}
    engine, session = await make_engine(server)
    async with session:
        with pytest.raises(QuotaError, match="HTTP 429"):
            await engine.search("https://cdn.example/image.png", b"")


@pytest.mark.parametrize("status", [400, 500, 503])
async def test_other_failures_raise_engine_error(serpapi, status: int) -> None:
    server, state = serpapi
    state["status"] = status
    state["payload"] = {"error": "Missing query `url` parameter."}
    engine, session = await make_engine(server)
    async with session:
        with pytest.raises(EngineError, match=f"HTTP {status}"):
            await engine.search("https://cdn.example/image.png", b"")


async def test_non_json_body_raises_engine_error(aiohttp_server) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(text="<html>gateway error</html>", content_type="text/html")

    app = web.Application()
    app.router.add_get("/search", handler)
    server = await aiohttp_server(app)
    engine, session = await make_engine(server)
    async with session:
        with pytest.raises(EngineError):
            await engine.search("https://cdn.example/image.png", b"")


class FailingSession:
    def __init__(self, error: aiohttp.ClientError) -> None:
        self.error = error

    def get(self, *args, **kwargs):
        raise self.error


def client_error_with_key(api_key: str) -> aiohttp.ClientResponseError:
    url = f"https://serpapi.com/search?api_key={api_key}"
    request_info = aiohttp.RequestInfo(url=url, method="GET", headers={}, real_url=url)
    return aiohttp.ClientResponseError(
        request_info=request_info,
        history=(),
        status=503,
        message="upstream connection failed",
    )


async def test_lookup_logs_transport_traceback_without_api_key(tmp_path, caplog) -> None:
    api_key = "synthetic-transport-secret"
    engine = SerpApiLensEngine(
        session=FailingSession(client_error_with_key(api_key)), api_key=api_key
    )
    caplog.set_level(logging.ERROR, logger="saucebot.exts.sauce")

    result = await lookup_source(
        engine,
        DailyBudget(path=tmp_path / "budget.json", max_per_day=1),
        frozenset(),
        "https://cdn.example/image.png",
        b"",
    )

    assert result.status == "error"
    assert api_key not in caplog.text


async def test_lookup_logs_provider_error_without_api_key(aiohttp_server, tmp_path, caplog) -> None:
    api_key = "synthetic-provider-secret"

    async def handler(request: web.Request) -> web.Response:
        return web.json_response({"error": f"invalid key {api_key}"}, status=401)

    app = web.Application()
    app.router.add_get("/search", handler)
    server = await aiohttp_server(app)
    engine, session = await make_engine(server, api_key=api_key)
    caplog.set_level(logging.ERROR, logger="saucebot.exts.sauce")

    async with session:
        result = await lookup_source(
            engine,
            DailyBudget(path=tmp_path / "budget.json", max_per_day=1),
            frozenset(),
            "https://cdn.example/image.png",
            b"",
        )

    assert result.status == "error"
    assert api_key not in caplog.text
