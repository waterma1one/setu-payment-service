FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
COPY scripts ./scripts
COPY data ./data

RUN pip install --no-cache-dir -e "."

RUN chmod +x /app/scripts/start.sh
CMD ["/app/scripts/start.sh"]

