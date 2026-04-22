#!/bin/sh
set -e
echo "DATABASE_URL=$DATABASE_URL"
alembic upgrade head
echo "Migration complete. Starting uvicorn on port ${PORT:-8000}."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
