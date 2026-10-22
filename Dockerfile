FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic
COPY config ./config

RUN pip install --upgrade pip && pip install .

RUN mkdir -p /app/data
VOLUME ["/app/data"]
EXPOSE 8000

CMD ["sh", "-c", "pmo init-db && pmo serve --host 0.0.0.0 --port 8000"]
