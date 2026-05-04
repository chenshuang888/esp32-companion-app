"""weather_provider —— 响应 ESP 反向天气请求 + 启动时主动推一次。

ESP 端订阅 8a5c000b NOTIFY 时触发 1B seq 反向请求，收到就拉天气写到 8a5c0002。
"""

from __future__ import annotations

import asyncio
import logging

from ...constants import WEATHER_CHAR_UUID, WEATHER_REQ_CHAR_UUID
from ...platform.geoip_weather import get_weather
from ...platform.packers import pack_weather
from ..base import Provider, ProviderContext

logger = logging.getLogger(__name__)


class WeatherProvider(Provider):
    name = "weather"

    def __init__(self) -> None:
        self._unsubs: list = []
        self._task: asyncio.Task | None = None

    def subscriptions(self) -> list[str]:
        return [WEATHER_REQ_CHAR_UUID]

    async def on_start(self, ctx: ProviderContext) -> None:
        def _on_req(_payload: object) -> None:
            asyncio.create_task(self._push(ctx, force=False))
        self._unsubs.append(
            ctx.bus.on(f"notify:{WEATHER_REQ_CHAR_UUID.lower()}", _on_req))
        # 连上后稍等再推一次（让 ESP 完成 GATT 注册）
        self._task = asyncio.create_task(self._initial_push(ctx))

    async def on_stop(self, ctx: ProviderContext) -> None:
        for u in self._unsubs:
            try: u()
            except Exception: pass
        self._unsubs.clear()
        if self._task:
            self._task.cancel()
            try: await self._task
            except (asyncio.CancelledError, Exception): pass
            self._task = None

    async def _initial_push(self, ctx: ProviderContext) -> None:
        try:
            await asyncio.sleep(2.0)
            await self._push(ctx, force=False)
        except asyncio.CancelledError:
            return

    async def _push(self, ctx: ProviderContext, force: bool) -> None:
        if ctx.quiesce_during_upload():
            return
        try:
            snap = await get_weather(force=force)
        except Exception as e:
            ctx.bus.emit("log", ("warn", self.name, f"fetch failed: {e}"))
            return
        try:
            data = pack_weather(snap.temp_c, snap.temp_min, snap.temp_max,
                                 snap.humidity, snap.wmo, snap.city, snap.desc())
            await ctx.write(WEATHER_CHAR_UUID, data, response=True)
            ctx.bus.emit("log", ("info", self.name,
                f"{snap.city} {snap.temp_c:.1f}°C {snap.desc()}"))
        except Exception as e:
            ctx.bus.emit("log", ("warn", self.name, f"push failed: {e}"))
