FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so source changes do not bust the pip cache layer.
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir .

# Application source
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY data ./data

RUN chmod +x /app/scripts/start.sh \
  && useradd --create-home --shell /bin/sh app \
  && chown -R app:app /app

USER app

CMD ["/app/scripts/start.sh"]
