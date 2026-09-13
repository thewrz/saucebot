# saucebot

Discord bot that reverse-image-searches images posted in a channel and, when it
finds where the image came from, calls the poster out with the source. Fork of
[sowwic/saucebot](https://github.com/sowwic/saucebot), rebuilt on discord.py 2.x.

## Setup

1. Create a bot at https://discord.com/developers/applications, enable the
   **Message Content Intent** under *Bot → Privileged Gateway Intents*, and invite
   it with the *Read Messages*, *Send Messages*, and *Read Message History*
   permissions.
2. Get a SerpApi key at https://serpapi.com (the free plan is 250 searches a month).
3. `cp .env.example .env` and fill in `DISCORD_TOKEN` and `SERPAPI_API_KEY`.
4. `uv sync` then `uv run python -m saucebot`.

## Commands

- `?sauce` with an image attached — search that image.
- `?sauce <message link>` — search the first image on a message in this server.

## Development

`scripts/verify.sh` runs lint, format check, tests, and a dependency audit; CI
runs the same script.

## License

MIT for this fork's changes (see `LICENSE`). Upstream carried no license.
