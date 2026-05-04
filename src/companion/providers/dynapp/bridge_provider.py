"""bridge_provider —— 动态 app JSON 通道（哑总线）。

职责（重构后只剩两件事）：
  1. a3a30003 notify → 解 utf-8 JSON → 派发给 PluginManager
  2. 监听 bus "bridge:tx" → 编码 JSON → a3a30002 write

业务（weather / music / notif / gomoku 等）全部移到 plugins/。
本文件不再持有任何特定 app 的逻辑。

bus 协议：
  emit("bridge:tx", (to_app: str, mtype: str, body: any|None))
       由插件调 self.tx() / self.tx_to() 间接产生
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from ...constants import BRIDGE_MAX_PAYLOAD, BRIDGE_RX_UUID, BRIDGE_TX_UUID
from ..base import Provider, ProviderContext

logger = logging.getLogger(__name__)


class BridgeProvider(Provider):
    name = "bridge"

    def __init__(self, plugin_manager) -> None:
        # 类型: PluginManager（避免循环 import 不写注解）
        self._pm = plugin_manager
        self._unsubs: list = []
        self._ctx: Optional[ProviderContext] = None

    def subscriptions(self) -> list[str]:
        return [BRIDGE_TX_UUID]

    async def on_start(self, ctx: ProviderContext) -> None:
        self._ctx = ctx

        # 1. a3a30003 notify → JSON 解码 → 派给 plugin manager
        def _on_notify(payload: object) -> None:
            data = payload if isinstance(payload, (bytes, bytearray)) else b""
            asyncio.create_task(self._on_recv(bytes(data)))
        self._unsubs.append(
            ctx.bus.on(f"notify:{BRIDGE_TX_UUID.lower()}", _on_notify))

        # 2. plugin 调 self.tx() → emit("bridge:tx", (to, type, body)) → BLE write
        def _on_tx(payload: object) -> None:
            if not isinstance(payload, tuple) or len(payload) != 3:
                return
            to_app, mtype, body = payload
            asyncio.create_task(self._send(str(to_app), str(mtype), body))
        self._unsubs.append(ctx.bus.on("bridge:tx", _on_tx))

    async def on_stop(self, ctx: ProviderContext) -> None:
        for u in self._unsubs:
            try: u()
            except Exception: pass
        self._unsubs.clear()
        self._ctx = None

    # ------------------------------------------------------------------
    # 收 / 发
    # ------------------------------------------------------------------

    async def _on_recv(self, data: bytes) -> None:
        try:
            msg = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return
        if not isinstance(msg, dict):
            return
        try:
            self._pm.dispatch_message(msg)
        except Exception as e:
            logger.warning("dispatch_message failed: %s", e)

    async def _send(self, to_app: str, mtype: str, body: Any) -> None:
        if self._ctx is None or not self._ctx.is_connected():
            return
        msg: dict[str, Any] = {"to": to_app, "type": mtype}
        if body is not None:
            msg["body"] = body
        payload = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        if len(payload) > BRIDGE_MAX_PAYLOAD:
            self._ctx.bus.emit("log", ("warn", self.name,
                f"payload {len(payload)}B > {BRIDGE_MAX_PAYLOAD}, dropped"))
            return
        try:
            await self._ctx.write(BRIDGE_RX_UUID, payload, response=False)
        except Exception as e:
            self._ctx.bus.emit("log", ("warn", self.name, f"send: {e}"))
