FROM ghcr.io/astral-sh/uv:python3.13-trixie

COPY ./skidc/pyproject.toml /skidc/pyproject.toml
COPY ./skidc/uv.lock /skidc/uv.lock
WORKDIR /skidc
RUN uv sync --frozen --no-install-project

COPY ./skidc /skidc
RUN uv sync --frozen

ENV PYTHONUNBUFFERED=1
