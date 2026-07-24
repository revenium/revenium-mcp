# syntax=docker/dockerfile:1.7

# --- Stage 1: builder ----------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv==0.11.6

WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# Install the locked dependency set plus the project into /opt/venv.
# --locked makes the build fail if pyproject.toml and uv.lock diverge, so
# the image always runs exactly the versions CI tested — a floating
# resolution here once picked up a fastmcp release that rejected every
# hosted request with 421.
RUN uv sync --locked --no-dev --no-editable

# --- Stage 2: runtime ----------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRANSPORT_MODE=http \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    PATH="/opt/venv/bin:$PATH"

# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system --gid 1000 mcp \
    && useradd  --system --uid 1000 --gid mcp --home-dir /home/mcp --shell /usr/sbin/nologin --create-home mcp

COPY --from=builder /opt/venv /opt/venv

USER mcp
WORKDIR /home/mcp

RUN mkdir -p .cache

VOLUME ["/home/mcp/.cache"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl --fail --silent "http://localhost:${MCP_PORT}/health" || exit 1

CMD ["revenium-mcp"]
