"""Capture a real SerpApi Lens response into tests/fixtures/.

Usage:
    SERPAPI_API_KEY=... uv run python scripts/capture_serpapi_fixture.py <image-url> <fixture-name>

Trims the result list to five entries and shortens icon/thumbnail URLs so the
fixture stays readable. Refresh the fixtures with this rather than hand-editing.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp

from saucebot.engines.serpapi_lens import SERPAPI_ENDPOINT

FIXTURES = Path(__file__).parent.parent / "tests" / "fixtures"
KEEP_METADATA = ("id", "status", "created_at", "total_time_taken")


async def capture(image_url: str, name: str) -> int:
    api_key = os.environ.get("SERPAPI_API_KEY")
    if not api_key:
        print("SERPAPI_API_KEY is not set", file=sys.stderr)
        return 1
    params = {
        "engine": "google_lens",
        "type": "exact_matches",
        "url": image_url,
        "api_key": api_key,
    }
    async with (
        aiohttp.ClientSession() as session,
        session.get(SERPAPI_ENDPOINT, params=params) as response,
    ):
        payload = await response.json(content_type=None)
        print(f"HTTP {response.status}")

    payload["search_metadata"] = {
        key: value
        for key, value in payload.get("search_metadata", {}).items()
        if key in KEEP_METADATA
    }
    if "exact_matches" in payload:
        payload["exact_matches"] = payload["exact_matches"][:5]
        for match in payload["exact_matches"]:
            if "source_icon" in match:
                match["source_icon"] = "https://serpapi.com/images/i/TRIMMED"
            if "thumbnail" in match:
                match["thumbnail"] = "https://serpapi.com/images/url/TRIMMED"

    destination = FIXTURES / f"{name}.json"
    destination.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"wrote {destination} ({len(payload.get('exact_matches', []))} matches)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(asyncio.run(capture(sys.argv[1], sys.argv[2])))
