"""线程安全事件总线。

事件类型:
  "connect"          —— ESP 连上后触发，payload = mac
  "disconnect"       —— 断开时触发，payload = None
  "notify:<uuid>"    —— 任意 characteristic 收到 notify，payload = bytes
  "log"              —— provider/core 推日志行，payload = (level, name, msg)
  "upload:begin"     —— 上传开始，其它高频 provider 应该退避
  "upload:end"       —— 上传结束/失败
  其它 provider 自定 string

线程模型：
  emit() 假定调用方在 asyncio 工作线程，直接同步派发回调（回调本身可能 schedule 协程）
  emit_threadsafe() 给 bleak notify cb 等任意线程用，转成 asyncio.run_coroutine_threadsafe
  GUI 端订阅时通过 register_tk(root) 拿到一个会用 root.after(0,...) 派发的 EventBus
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


Listener = Callable[[Any], None]


class EventBus:
    def __init__(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._loop = loop
        self._listeners: dict[str, list[Listener]] = {}

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def on(self, event: str, fn: Listener) -> Callable[[], None]:
        self._listeners.setdefault(event, []).append(fn)
        def _unsub() -> None:
            try:
                self._listeners[event].remove(fn)
            except (KeyError, ValueError):
                pass
        return _unsub

    def emit(self, event: str, payload: Any = None) -> None:
        for fn in list(self._listeners.get(event, ())):
            try:
                fn(payload)
            except Exception:
                logger.exception("event listener for %s crashed", event)

    def emit_threadsafe(self, event: str, payload: Any = None) -> None:
        if self._loop is None or self._loop.is_closed():
            return
        try:
            self._loop.call_soon_threadsafe(self.emit, event, payload)
        except RuntimeError:
            pass
