# Triage agent container — driven by AgentCore Runtime over HTTP.
# Build context is the repo root:
#
#   docker build -f src/triage/agent/Dockerfile -t triage-agent:dev .

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

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY agent/AGENT.md /app/agent/AGENT.md

RUN groupadd --system app && useradd --system --gid app --home /app app && chown -R app:app /app
USER app

EXPOSE 8080

CMD ["python", "-m", "triage.agent.runtime"]
