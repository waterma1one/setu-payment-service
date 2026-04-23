from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import SessionLocal
from app.schemas import EventIn
from app.services.event_ingestion import ingest_event


DATA_PATH = ROOT / "data" / "sample_events.json"
BATCH_LOG_EVERY = 250
# Cap concurrent per-transaction workers to the size of the default SQLAlchemy pool
# (pool_size=5 + max_overflow=10) so we don't stall waiting for connections.
MAX_CONCURRENCY = 10


async def _ingest_group(events: list[dict], counter: list[int], total: int) -> None:
    # Events for the same transaction must be applied serially — the state machine
    # depends on the preceding state. Events for different transactions are
    # independent and safe to interleave across sessions.
    for raw in events:
        payload = EventIn(
            event_id=raw["event_id"],
            event_type=raw["event_type"],
            transaction_id=raw["transaction_id"],
            merchant_id=raw["merchant_id"],
            merchant_name=raw["merchant_name"],
            amount=raw["amount"],
            currency=raw["currency"],
            timestamp=raw["timestamp"],
        )
        async with SessionLocal() as session:
            await ingest_event(session, payload)
        counter[0] += 1
        if counter[0] % BATCH_LOG_EVERY == 0:
            print(f"  {counter[0]}/{total} events processed", flush=True)


async def main() -> None:
    with DATA_PATH.open() as handle:
        raw_events = json.load(handle)

    total = len(raw_events)
    print(f"Seeding {total} events (concurrency={MAX_CONCURRENCY})…", flush=True)

    groups: dict[str, list[dict]] = defaultdict(list)
    for raw in raw_events:
        groups[raw["transaction_id"]].append(raw)

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    counter = [0]

    async def run(txn_events: list[dict]) -> None:
        async with semaphore:
            await _ingest_group(txn_events, counter, total)

    await asyncio.gather(*(run(events) for events in groups.values()))
    print(f"Seed complete: {counter[0]}/{total} events processed.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
