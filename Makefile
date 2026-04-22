PYTHON ?= python3

.PHONY: install run migrate seed test

install:
	$(PYTHON) -m pip install -e ".[dev]"

run:
	uvicorn app.main:app --reload

migrate:
	alembic upgrade head

seed:
	$(PYTHON) scripts/seed_sample_data.py

test:
	pytest

