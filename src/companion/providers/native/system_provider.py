"""system_provider —— psutil 1Hz 采样 + 写 8a5c000a。

ESP 反向请求（订阅 8a5c000c）触发立即推送一帧。
upload 期间退避（不抢带宽）。
"""

from __future__ import annotations

import asyncio
import logging
import time as _time

import psutil

from ...constants import (
    SYSTEM_BATTERY_ABSENT, SYSTEM_CHAR_UUID, SYSTEM_CHARGING_ABSENT,
    SYSTEM_CPU_TEMP_INVALID, SYSTEM_PUSH_INTERVAL_S, SYSTEM_REQ_CHAR_UUID,
)
from ...platform.packers import pack_system
from ..base import Provider, ProviderContext

logger = logging.getLogger(__name__)


def _read_cpu_temp_x10() -> int:
    getter = getattr(psutil, "sensors_temperatures", None)
    if getter is None:
        return SYSTEM_CPU_TEMP_INVALID
    try:
        temps = getter()
    except Exception:
        return SYSTEM_CPU_TEMP_INVALID
    if not temps:
        return SYSTEM_CPU_TEMP_INVALID
    for key in ("coretemp", "cpu_thermal", "k10temp", "acpitz"):
        entries = temps.get(key)
        if entries and entries[0].current is not None:
            return max(-32767, min(32767, int(round(float(entries[0].current) * 10))))
    for entries in temps.values():
        if entries and entries[0].current is not None:
            return max(-32767, min(32767, int(round(float(entries[0].current) * 10))))
    return SYSTEM_CPU_TEMP_INVALID


class SystemProvider(Provider):
    name = "system"

    def __init__(self) -> None:
        self._unsubs: list = []
        self._loop_task: asyncio.Task | None = None
        self._push_lock = asyncio.Lock()
        self._last_net_ts: float | None = None
        self._last_net_recv = 0
        self._last_net_sent = 0
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

    def subscriptions(self) -> list[str]:
        return [SYSTEM_REQ_CHAR_UUID]

    async def on_start(self, ctx: ProviderContext) -> None:
        def _on_req(_payload: object) -> None:
            asyncio.create_task(self._push(ctx))
        self._unsubs.append(
            ctx.bus.on(f"notify:{SYSTEM_REQ_CHAR_UUID.lower()}", _on_req))
        self._loop_task = asyncio.create_task(self._run_loop(ctx))

    async def on_stop(self, ctx: ProviderContext) -> None:
        for u in self._unsubs:
            try: u()
            except Exception: pass
        self._unsubs.clear()
        if self._loop_task:
            self._loop_task.cancel()
            try: await self._loop_task
            except (asyncio.CancelledError, Exception): pass
            self._loop_task = None

    async def _run_loop(self, ctx: ProviderContext) -> None:
        try:
            await asyncio.sleep(SYSTEM_PUSH_INTERVAL_S)
        except asyncio.CancelledError:
            return
        while True:
            try:
                if not ctx.quiesce_during_upload():
                    await self._push(ctx)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("system loop")
            try:
                await asyncio.sleep(SYSTEM_PUSH_INTERVAL_S)
            except asyncio.CancelledError:
                return

    def _sample_sync(self) -> bytes:
        cpu  = int(round(psutil.cpu_percent(interval=None)))
        mem  = int(round(psutil.virtual_memory().percent))
        try:
            disk = int(round(psutil.disk_usage("C:\\").percent))
        except Exception:
            disk = 0
        bat_pct  = SYSTEM_BATTERY_ABSENT
        charging = SYSTEM_CHARGING_ABSENT
        try:
            bat = psutil.sensors_battery()
        except Exception:
            bat = None
        if bat is not None:
            bat_pct  = max(0, min(100, int(round(bat.percent))))
            charging = 1 if bat.power_plugged else 0
        cpu_temp = _read_cpu_temp_x10()
        try:
            uptime = int(_time.time() - psutil.boot_time())
        except Exception:
            uptime = 0
        down_kbps = up_kbps = 0
        try:
            io = psutil.net_io_counters()
            now = _time.time()
            if self._last_net_ts is not None:
                dt = now - self._last_net_ts
                if dt > 0.1:
                    d_recv = max(0, io.bytes_recv - self._last_net_recv)
                    d_sent = max(0, io.bytes_sent - self._last_net_sent)
                    down_kbps = min(0xFFFF, int(d_recv / dt / 1024))
                    up_kbps   = min(0xFFFF, int(d_sent / dt / 1024))
            self._last_net_ts = now
            self._last_net_recv = io.bytes_recv
            self._last_net_sent = io.bytes_sent
        except Exception:
            pass
        return pack_system(cpu, mem, disk, bat_pct, charging, cpu_temp,
                            uptime, down_kbps, up_kbps)

    async def _push(self, ctx: ProviderContext) -> None:
        async with self._push_lock:
            try:
                data = await asyncio.to_thread(self._sample_sync)
            except Exception as e:
                ctx.bus.emit("log", ("warn", self.name, f"sample failed: {e}"))
                return
            try:
                await ctx.write(SYSTEM_CHAR_UUID, data, response=True)
            except Exception as e:
                ctx.bus.emit("log", ("warn", self.name, f"push failed: {e}"))
