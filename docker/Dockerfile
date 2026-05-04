FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /opt/harness

COPY pyproject.toml ./
RUN uv sync --no-dev

COPY harness/ ./harness/
COPY workflows/ ./workflows/
COPY prompts/ ./prompts/
COPY contracts/ ./contracts/

ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["uv", "run", "harness"]
