"""time_provider —— 响应 ESP 端 CTS NOTIFY 反向请求，把 PC 当前时间写到 0x2A2B。

行为：
  - 连接成功后立即推一次（覆盖设备开机的 1970 时间）
  - ESP 端订阅 CTS char 时会触发一次 NOTIFY（1B seq），收到就重新推
  - 不主动周期推，避免抢 connection interval 带宽
"""

from __future__ import annotations

import logging

from ...constants import CTS_CHAR_UUID
from ...platform.packers import pack_cts
from ..base import Provider, ProviderContext

logger = logging.getLogger(__name__)


class TimeProvider(Provider):
    name = "time"

    def __init__(self) -> None:
        self._unsubs: list = []

    def subscriptions(self) -> list[str]:
        return [CTS_CHAR_UUID]

    async def on_start(self, ctx: ProviderContext) -> None:
        # 连上后第一次推
        await self._push(ctx)
        self._unsubs.append(
            ctx.bus.on(f"notify:{CTS_CHAR_UUID.lower()}",
                        lambda data: ctx.bus.emit("_time_req", data)))
        # 把同步事件桥接到 async 推送
        async def _on_req(_: object) -> None:
            await self._push(ctx)
        # 用 asyncio task 触发
        import asyncio
        def _schedule(_payload: object) -> None:
            asyncio.create_task(_on_req(_payload))
        self._unsubs.append(ctx.bus.on("_time_req", _schedule))

    async def on_stop(self, ctx: ProviderContext) -> None:
        for u in self._unsubs:
            try: u()
            except Exception: pass
        self._unsubs.clear()

    async def _push(self, ctx: ProviderContext) -> None:
        try:
            await ctx.write(CTS_CHAR_UUID, pack_cts(), response=True)
            ctx.bus.emit("log", ("info", self.name, "CTS pushed"))
        except Exception as e:
            ctx.bus.emit("log", ("warn", self.name, f"push failed: {e}"))
