# syntax=docker/dockerfile:1

FROM ghcr.io/astral-sh/uv:0.12.10@sha256:2bb3ebca0a796a155094a27773d290c4b074572e6107f171d88d086682fd2500 AS uv

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea AS builder
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /build
COPY uv.lock pyproject.toml ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim@sha256:78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/build/.venv/bin:$PATH" \
    SAUCEBOT_CONFIG=/app/config.toml \
    SAUCEBOT_DATA_DIR=/app/data
COPY --from=builder /build /build
WORKDIR /app
COPY saucebot/ ./saucebot/
RUN useradd --create-home --uid 10001 saucebot \
    && mkdir -p /app/data \
    && chown -R saucebot:saucebot /app
USER saucebot
ENTRYPOINT ["python", "-m", "saucebot"]
