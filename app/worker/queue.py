"""In-process async job queue with a fixed pool of background workers.

The webhook handler enqueues jobs and returns immediately (202); workers drain
the queue concurrently. Simple and dependency-free — swap for Redis/Celery/SQS
if you need cross-process durability.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from app.models import Job

log = logging.getLogger(__name__)

JobProcessor = Callable[[Job], Awaitable[None]]


class JobQueue:
    def __init__(self, processor: JobProcessor, concurrency: int = 2) -> None:
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._processor = processor
        self._concurrency = max(1, concurrency)
        self._workers: list[asyncio.Task] = []

    async def start(self) -> None:
        self._workers = [
            asyncio.create_task(self._run(i), name=f"worker-{i}")
            for i in range(self._concurrency)
        ]
        log.info("started %d background worker(s)", self._concurrency)

    async def enqueue(self, job: Job) -> None:
        await self._queue.put(job)
        log.info("enqueued run %s for %s#%d", job.run_id, job.full_name, job.issue_number)

    async def _run(self, idx: int) -> None:
        while True:
            job = await self._queue.get()
            try:
                await self._processor(job)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - one bad job must not kill the worker
                log.exception("worker-%d failed processing run %s", idx, job.run_id)
            finally:
                self._queue.task_done()

    async def stop(self) -> None:
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        log.info("workers stopped")
