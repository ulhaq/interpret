"""Standalone background worker, run alongside the web process.

Runs the product loop(s), the email outbox, GDPR retention, billing cleanup,
and trial reminder loops. Keeping these out of the web process means
horizontal scaling of the API does not cause duplicate job runs or duplicate
emails. Overlapping workers (a scale-up, a deploy) are safe too: each job's
iteration takes a lock (`try_job_lock`), and the outbox claims emails with
SKIP LOCKED.

Usage:
    uv run python worker.py
    # or via docker-compose worker service
"""

import asyncio
import logging
import signal

from src.bootstrap import bootstrap
from src.foundation.core.database import ASYNC_SESSION_LOCAL, drain_after_commit
from src.foundation.core.logging import setup_logging
from src.foundation.core.realtime import close_broker
from src.foundation.core.telemetry import setup_telemetry
from src.foundation.services.email_outbox import run_email_outbox_loop
from src.foundation.services.gdpr import run_gdpr_retention_loop
from src.products import MODULES

setup_logging("worker")
setup_telemetry("worker")
log = logging.getLogger(__name__)


async def main() -> None:
    log.info("Worker starting")
    bootstrap()

    loop = asyncio.get_running_loop()
    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    worker_loops = [
        *(*module.worker_loops for module in MODULES),
        run_email_outbox_loop,
        run_gdpr_retention_loop,
    ]
    tasks = [asyncio.create_task(run(ASYNC_SESSION_LOCAL)) for run in worker_loops]

    await stop.wait()
    log.info("Worker shutting down")
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    # Realtime events of the last committed iterations.
    await drain_after_commit()
    await close_broker()
    log.info("Worker stopped")


if __name__ == "__main__":
    asyncio.run(main())
