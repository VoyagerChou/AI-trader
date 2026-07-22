ARG BASE_IMAGE=python:3.12-slim-bookworm
FROM ${BASE_IMAGE}

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# Cloud defaults: bind streamable-http to all interfaces on the platform-supplied
# port. Override any of these on the platform side; stdio still works locally
# because pipx/uvx invocations don't inherit these.
ENV AI_TRADER_MCP_TRANSPORT=streamable-http \
    AI_TRADER_MCP_HOST=0.0.0.0 \
    AI_TRADER_MCP_PORT=7800 \
    PYTHONUNBUFFERED=1

EXPOSE 7800

CMD ["ai-trader-mcp"]
