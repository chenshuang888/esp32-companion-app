"""asyncio 工作线程封装。

主线程跑 tkinter mainloop，AsyncRunner 在 daemon 线程里持有一个独立 event loop。
GUI → 后台：runner.submit(coro) -> Future
后台 → GUI：tkinter root.after(0, callback) 由 EventBus 在主线程触发
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import Future as ConcFuture
from typing import Any, Awaitable

logger = logging.getLogger(__name__)


class AsyncRunner:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        if self._loop is None:
            raise RuntimeError("AsyncRunner not started")
        return self._loop

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="companion-async",
                                         daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5.0)
        if self._loop is None:
            raise RuntimeError("AsyncRunner failed to start")

    def stop(self, timeout: float = 5.0) -> None:
        if self._loop is None or self._stopped.is_set():
            return
        self._stopped.set()
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except RuntimeError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def submit(self, coro: Awaitable[Any]) -> ConcFuture:
        if self._loop is None:
            raise RuntimeError("AsyncRunner not started")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for t in pending:
                    t.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                logger.exception("error draining tasks on shutdown")
            loop.close()
