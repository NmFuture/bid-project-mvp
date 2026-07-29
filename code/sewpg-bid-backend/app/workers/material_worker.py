from __future__ import annotations

from app.services.job_queue import MATERIAL_QUEUE_KEY
from app.workers.redis_worker import run_worker


def main() -> None:
    run_worker(MATERIAL_QUEUE_KEY, worker_name="Material")


if __name__ == "__main__":
    main()
