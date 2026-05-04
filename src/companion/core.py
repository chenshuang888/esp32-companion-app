"""Companion 核心 —— BleakClient 单例 + 扫描/连接/重连 + provider 注册。

设计要点：
  - 唯一 BleakClient，所有 provider 共享
  - 所有 write_gatt_char 经过 self._write_lock 串行化
  - 连接成功后遍历 provider 的 subscriptions() 一次性 start_notify
  - 断开/重连由 watchdog 任务驱动；provider 在 on_disconnect/on_connect 回调里自适应
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from bleak import BleakClient, BleakScanner

from .bus import EventBus
from .constants import RECONNECT_DELAY_S, SCAN_TIMEOUT_S
from .providers.base import Provider, ProviderContext

logger = logging.getLogger(__name__)


class Companion:
    def __init__(
        self,
        device_name: str,
        bus: EventBus,
        device_address: Optional[str] = None,
    ) -> None:
        self._device_name = device_name
        self._device_address = device_address
        self._bus = bus

        self._client: Optional[BleakClient] = None
        self._connected_addr: Optional[str] = None
        self._providers: list[Provider] = []
        self._write_lock = asyncio.Lock()
        self._stopped = asyncio.Event()
        self._upload_quiesce = False   # bus("upload:begin/end") 翻转

        bus.on("upload:begin", lambda _: self._set_quiesce(True))
        bus.on("upload:end",   lambda _: self._set_quiesce(False))

    # ------------------------------------------------------------------
    # Provider 注册（在 start 之前调一次）
    # ------------------------------------------------------------------

    def register(self, provider: Provider) -> None:
        self._providers.append(provider)

    # ------------------------------------------------------------------
    # 公共状态
    # ------------------------------------------------------------------

    @property
    def client(self) -> Optional[BleakClient]:
        return self._client

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.is_connected

    @property
    def connected_address(self) -> Optional[str]:
        return self._connected_addr if self.is_connected else None

    @property
    def upload_in_progress(self) -> bool:
        return self._upload_quiesce

    def make_context(self) -> ProviderContext:
        return ProviderContext(
            client_getter=lambda: self._client,
            bus=self._bus,
            write=self.write_gatt_char,
            is_connected=lambda: self.is_connected,
            quiesce_during_upload=lambda: self._upload_quiesce,
        )

    # ------------------------------------------------------------------
    # 串行化写
    # ------------------------------------------------------------------

    async def write_gatt_char(self, uuid: str, data: bytes,
                               response: bool = True) -> None:
        if self._client is None or not self._client.is_connected:
            raise RuntimeError("not connected")
        async with self._write_lock:
            await self._client.write_gatt_char(uuid, data, response=response)

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    async def run(self) -> None:
        ctx = self.make_context()
        while not self._stopped.is_set():
            try:
                await self._connect_once()
                await self._on_connect_providers(ctx)
                await self._stay_connected_loop()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("session ended: %s", e)
                self._bus.emit("log", ("warn", "core", f"session ended: {e}"))
            finally:
                await self._on_disconnect_providers(ctx)
                await self._teardown_client()
            if self._stopped.is_set():
                break
            self._bus.emit("log", ("info", "core",
                f"reconnect in {RECONNECT_DELAY_S:.0f}s"))
            try:
                await asyncio.wait_for(self._stopped.wait(),
                                        timeout=RECONNECT_DELAY_S)
                break
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stopped.set()

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------

    def _set_quiesce(self, on: bool) -> None:
        self._upload_quiesce = on
        self._bus.emit("log", ("info", "core",
            f"upload quiesce {'ON' if on else 'OFF'}"))

    async def _connect_once(self) -> None:
        addr = self._device_address
        if not addr:
            self._bus.emit("log", ("info", "core",
                f"scan for {self._device_name!r}..."))
            device = await BleakScanner.find_device_by_name(
                self._device_name, timeout=SCAN_TIMEOUT_S)
            if device is None:
                raise RuntimeError(
                    f"{SCAN_TIMEOUT_S:.0f}s 内未发现 {self._device_name}")
            addr = device.address

        self._bus.emit("log", ("info", "core", f"connecting {addr}..."))
        cli = BleakClient(addr)
        await cli.connect()
        if not cli.is_connected:
            raise RuntimeError("BleakClient connect returned but not connected")
        self._client = cli
        self._connected_addr = addr
        self._bus.emit("log", ("info", "core", f"connected {addr}"))
        self._bus.emit("connect", addr)

    async def _on_connect_providers(self, ctx: ProviderContext) -> None:
        # 1. start_notify for all subscriptions
        for p in self._providers:
            for uuid in p.subscriptions():
                event = f"notify:{uuid.lower()}"
                # 闭包绑定：每个 uuid 一个独立 emitter
                def make_cb(ev: str):
                    def _cb(_handle: int, data: bytearray) -> None:
                        self._bus.emit(ev, bytes(data))
                    return _cb
                try:
                    await self._client.start_notify(uuid, make_cb(event))
                except Exception as e:
                    self._bus.emit("log", ("warn", p.name,
                        f"start_notify {uuid[:8]}.. failed: {e}"))

        # 2. provider 自己挂 bus 监听并初始化
        for p in self._providers:
            try:
                await p.on_start(ctx)
                self._bus.emit("log", ("info", p.name, "started"))
            except Exception as e:
                self._bus.emit("log", ("err", p.name, f"start failed: {e}"))

    async def _on_disconnect_providers(self, ctx: ProviderContext) -> None:
        for p in self._providers:
            try:
                await p.on_stop(ctx)
            except Exception as e:
                self._bus.emit("log", ("warn", p.name, f"stop failed: {e}"))

    async def _stay_connected_loop(self) -> None:
        while not self._stopped.is_set():
            if self._client is None or not self._client.is_connected:
                raise RuntimeError("connection lost")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=2.0)
                return
            except asyncio.TimeoutError:
                pass

    async def _teardown_client(self) -> None:
        if self._client is None:
            return
        try:
            if self._client.is_connected:
                await self._client.disconnect()
        except Exception:
            pass
        self._bus.emit("disconnect", None)
        self._client = None
        self._connected_addr = None
