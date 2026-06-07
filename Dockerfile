FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir uv

COPY ./skidc/pyproject.toml /skidc/pyproject.toml
COPY ./skidc/uv.lock /skidc/uv.lock
WORKDIR /skidc
RUN uv sync --frozen --no-install-project -i https://mirrors.aliyun.com/pypi/simple/

COPY ./skidc /skidc
RUN uv sync --frozen -i https://mirrors.aliyun.com/pypi/simple/
