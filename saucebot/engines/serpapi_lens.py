"""SerpApi's Google Lens engine, restricted to exact matches.

Verified against the live API on 2026-09-12:

* Matches found -> HTTP 200 with a top-level ``exact_matches`` array.
* Nothing found -> HTTP 200, NO ``exact_matches`` key, and a top-level ``error``
  string ("Google Lens hasn't returned any results for this query."). That is an
  ordinary empty result, not a failure, so it maps to ``[]``.
* Bad key -> HTTP 401. Out of searches -> HTTP 429. Malformed request -> HTTP 400.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from saucebot.engines.base import BadKeyError, EngineError, QuotaError, SourceHit

log = logging.getLogger(__name__)

SERPAPI_ENDPOINT = "https://serpapi.com/search"
SEARCH_TIMEOUT_SECONDS = 60  # a Lens search takes 5-12s in practice


def parse_exact_matches(payload: dict[str, Any]) -> list[SourceHit]:
    """Turn a SerpApi Lens payload into hits. A payload with no matches yields []."""
    matches = payload.get("exact_matches") or []
    hits = []
    for match in matches:
        link = match.get("link")
        if not link:
            continue
        hits.append(
            SourceHit(url=link, title=match.get("title") or "", site=match.get("source") or "")
        )
    return hits


class SerpApiLensEngine:
    """Reverse-image search via SerpApi's Google Lens exact-match bucket."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        endpoint: str = SERPAPI_ENDPOINT,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._endpoint = endpoint

    async def search(self, image_url: str, image_bytes: bytes) -> list[SourceHit]:
        """Return pages where this exact image appears. image_bytes is unused here."""
        params = {
            "engine": "google_lens",
            "type": "exact_matches",
            "url": image_url,
            "api_key": self._api_key,
        }
        timeout = aiohttp.ClientTimeout(total=SEARCH_TIMEOUT_SECONDS)
        try:
            async with self._session.get(
                self._endpoint, params=params, timeout=timeout
            ) as response:
                payload = await self._read_json(response)
                self._raise_for_status(response.status, payload)
        except aiohttp.ClientError as exc:
            raise EngineError(f"SerpApi request failed: {exc}") from exc
        except TimeoutError as exc:
            raise EngineError(f"SerpApi timed out after {SEARCH_TIMEOUT_SECONDS}s") from exc
        return parse_exact_matches(payload)

    async def _read_json(self, response: aiohttp.ClientResponse) -> dict[str, Any]:
        try:
            payload = await response.json(content_type=None)
        except (ValueError, aiohttp.ClientError) as exc:
            raise EngineError(f"SerpApi returned a non-JSON body (HTTP {response.status})") from exc
        if not isinstance(payload, dict):
            raise EngineError(f"SerpApi returned an unexpected body (HTTP {response.status})")
        return payload

    @staticmethod
    def _raise_for_status(status: int, payload: dict[str, Any]) -> None:
        if status == 200:
            return
        message = payload.get("error") or f"HTTP {status}"
        if status == 401:
            raise BadKeyError(f"SerpApi rejected the API key: {message}")
        if status == 429:
            raise QuotaError(f"SerpApi quota exhausted: {message}")
        raise EngineError(f"SerpApi error (HTTP {status}): {message}")
