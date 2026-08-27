FROM python:3.12.14-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY apps ./apps
COPY config ./config
COPY manage.py ./
RUN pip install .

RUN addgroup --system serviceflow && adduser --system --ingroup serviceflow serviceflow
USER serviceflow

EXPOSE 8000
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
