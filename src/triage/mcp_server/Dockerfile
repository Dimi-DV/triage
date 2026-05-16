# MCP server container — runs the FastMCP app over Streamable HTTP for
# AgentCore Gateway to call. Build context is the repo root:
#
#   docker build -f src/triage/mcp_server/Dockerfile -t mcp-server:dev .
#
# Stage 1 — install deps with uv into a venv from the locked pyproject.toml.
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

RUN pip install --no-cache-dir uv==0.5.13

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

RUN uv sync --frozen --no-dev

# Stage 2 — minimal runtime image.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    TRIAGE_MCP_TRANSPORT=streamable-http

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Run as a non-root user; ECS task role still gates IAM regardless.
RUN groupadd --system app && useradd --system --gid app --home /app app && chown -R app:app /app
USER app

EXPOSE 8080

CMD ["python", "-m", "triage.mcp_server"]
