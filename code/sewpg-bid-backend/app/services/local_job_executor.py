from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable


logger = logging.getLogger(__name__)
_JOBS: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = queue.Queue()


def _run_jobs() -> None:
    while True:
        function, args, kwargs = _JOBS.get()
        try:
            function(*args, **kwargs)
        except Exception:
            logger.exception("Local background job failed")
        finally:
            _JOBS.task_done()


_WORKER = threading.Thread(target=_run_jobs, daemon=True, name="local-background-job")
_WORKER.start()


def submit_local_job(function: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Serialize background jobs when Redis is unavailable."""

    _JOBS.put((function, args, kwargs))
