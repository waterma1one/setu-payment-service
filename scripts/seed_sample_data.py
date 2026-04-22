from __future__ import annotations

import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.schemas import EventIn
from app.services.event_ingestion import ingest_event


DATA_PATH = ROOT / "data" / "sample_events.json"
BATCH_LOG_EVERY = 500


async def main() -> None:
    with DATA_PATH.open() as handle:
        raw_events = json.load(handle)

    total = len(raw_events)
    print(f"Seeding {total} events…")

    # Each ingest_event call manages its own internal transaction and may leave an
    # implicit auto-begin on the session afterwards. Opening a fresh session per event
    # avoids that leak. SQLAlchemy's connection pool means this is not 10,355 TCP
    # connections — connections are borrowed from and returned to the pool each time.
    for i, raw_event in enumerate(raw_events, start=1):
        payload = EventIn(
            event_id=raw_event["event_id"],
            event_type=raw_event["event_type"],
            transaction_id=raw_event["transaction_id"],
            merchant_id=raw_event["merchant_id"],
            merchant_name=raw_event["merchant_name"],
            amount=raw_event["amount"],
            currency=raw_event["currency"],
            timestamp=raw_event["timestamp"],
        )
        async with SessionLocal() as session:
            await ingest_event(session, payload)

        if i % BATCH_LOG_EVERY == 0:
            print(f"  {i}/{total} events processed")

    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(main())
