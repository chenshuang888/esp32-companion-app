"""notify_provider —— 写 8a5c0004 通知 char。

数据来源：
  - Windows toast 中心轮询（白名单微信/QQ/Teams）
  - GUI Notify 页手动输入

通过 bus 事件 "notify:manual" 接收 GUI 推来的 (title, body, category)。
"""

from __future__ import annotations

import asyncio
import logging

from ...constants import (
    NOTIFY_CAT_GENERIC, NOTIFY_CHAR_UUID,
)
from ...platform.packers import pack_notify
from ...platform.toast import ToastWatcher
from ..base import Provider, ProviderContext

logger = logging.getLogger(__name__)


class NotifyProvider(Provider):
    name = "notify"

    def __init__(self) -> None:
        self._unsubs: list = []
        self._toast: ToastWatcher | None = None
        self._ctx: ProviderContext | None = None

    async def on_start(self, ctx: ProviderContext) -> None:
        self._ctx = ctx

        def _on_manual(payload: object) -> None:
            try:
                title, body, category = payload  # type: ignore[misc]
            except Exception:
                return
            asyncio.create_task(self._push(ctx, title, body, int(category)))
        self._unsubs.append(ctx.bus.on("notify:manual", _on_manual))

        async def _on_toast(std: str, category: int, title: str, body: str) -> None:
            await self._push(ctx, title, body, category, source=std)

        self._toast = ToastWatcher(_on_toast)
        try:
            await self._toast.start()
        except Exception as e:
            ctx.bus.emit("log", ("warn", self.name, f"toast start failed: {e}"))

    async def on_stop(self, ctx: ProviderContext) -> None:
        for u in self._unsubs:
            try: u()
            except Exception: pass
        self._unsubs.clear()
        if self._toast is not None:
            try: await self._toast.stop()
            except Exception: pass
            self._toast = None
        self._ctx = None

    async def _push(self, ctx: ProviderContext, title: str, body: str,
                     category: int, source: str = "manual") -> None:
        try:
            data = pack_notify(title, body, category=category)
            await ctx.write(NOTIFY_CHAR_UUID, data, response=True)
            preview = (body or "").replace("\n", " ")[:40]
            ctx.bus.emit("log", ("info", self.name,
                f"[{source}] \"{title}\" \"{preview}\""))
        except Exception as e:
            ctx.bus.emit("log", ("warn", self.name, f"push failed: {e}"))
