"""Provider 基类。

每个 provider 负责某一类 BLE 通道（一组 characteristic + 业务），
通过 ProviderContext 调 BLE 写、监听 bus 事件。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from bleak import BleakClient

from ..bus import EventBus


@dataclass
class ProviderContext:
    client_getter: Callable[[], Optional[BleakClient]]
    bus: EventBus
    write: Callable[..., Awaitable[None]]   # async write_gatt_char(uuid, data, response=True)
    is_connected: Callable[[], bool]
    quiesce_during_upload: Callable[[], bool]

    @property
    def client(self) -> Optional[BleakClient]:
        return self.client_getter()


class Provider:
    name: str = "provider"

    def subscriptions(self) -> list[str]:
        """返回本 provider 关心的 NOTIFY characteristic UUID 列表。
        core 会统一 start_notify 并通过 bus.emit("notify:<uuid>", bytes) 路由回来。"""
        return []

    async def on_start(self, ctx: ProviderContext) -> None:
        """连接成功后调用一次。可在这里 ctx.bus.on(...) 挂监听 + 起后台 task。"""
        pass

    async def on_stop(self, ctx: ProviderContext) -> None:
        """断开/退出时调用，清理后台 task 与监听。"""
        pass
