"""upload_provider —— 包装 UploaderClient 接受外部 BleakClient。

行为：
  - 连上后 start_notify(a3a40003)；不主动发起任何上传
  - GUI 通过 bus 事件 "upload:request" 发来 (kind, payload, future) 请求上传
  - upload 期间：on_start 触发 bus.emit("upload:begin")，结束触发 "upload:end"
  - 同时支持 list/delete 操作

bus 事件接口（GUI / 外部代码用）：
  emit("upload:request", {
      "kind":   "file" | "pack" | "list" | "delete",
      "args":   {...},
      "future": concurrent.futures.Future
  })
  future 会在工作线程拿到 result（文件名列表 / None / Exception）
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from concurrent.futures import Future as ConcFuture
from typing import Any, Optional

from ...constants import UPLOAD_STATUS_UUID
from ..base import Provider, ProviderContext

logger = logging.getLogger(__name__)


from ...dynapp_uploader import UploaderClient, UploadError


class UploadProvider(Provider):
    name = "upload"

    def __init__(self) -> None:
        self._unsubs: list = []
        self._uploader: UploaderClient | None = None
        self._busy = False

    def subscriptions(self) -> list[str]:
        # UploaderClient 自己 start_notify(STATUS_UUID)，但 core 注册到 bus 不冲突；
        # 这里返回空让 UploaderClient.connect() 独占 status notify 路由
        return []

    async def on_start(self, ctx: ProviderContext) -> None:
        cli = ctx.client
        if cli is None:
            return
        self._uploader = UploaderClient(external_client=cli)
        await self._uploader.connect()

        def _on_request(payload: object) -> None:
            asyncio.create_task(self._handle_request(ctx, payload))
        self._unsubs.append(ctx.bus.on("upload:request", _on_request))

    async def on_stop(self, ctx: ProviderContext) -> None:
        for u in self._unsubs:
            try: u()
            except Exception: pass
        self._unsubs.clear()
        if self._uploader is not None:
            try:
                await self._uploader.disconnect()
            except Exception:
                pass
            self._uploader = None

    async def _handle_request(self, ctx: ProviderContext, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        kind = payload.get("kind")
        args = payload.get("args") or {}
        fut: ConcFuture | None = payload.get("future")  # type: ignore[assignment]

        if self._uploader is None:
            self._set_result(fut, UploadError("uploader not ready"))
            return
        if self._busy:
            self._set_result(fut, UploadError("another upload in progress"))
            return

        self._busy = True
        ctx.bus.emit("upload:begin", kind)
        try:
            if kind == "pack":
                def on_step(filename: str, idx: int, total: int) -> None:
                    ctx.bus.emit("upload:step", (filename, idx, total))
                await self._uploader.upload_app_pack(
                    args["app_id"], args["pack_dir"],
                    display_name=args.get("display_name"),
                    on_step=on_step,
                    on_progress=self._make_progress_emitter(ctx))
                self._set_result(fut, None)
            elif kind == "list":
                names = await self._uploader.list_apps()
                self._set_result(fut, names)
            elif kind == "delete":
                await self._uploader.delete_app(args["app_id"])
                self._set_result(fut, None)
            else:
                self._set_result(fut, UploadError(f"unknown kind: {kind}"))
        except Exception as e:
            ctx.bus.emit("log", ("warn", self.name, f"{kind} failed: {e}"))
            self._set_result(fut, e)
        finally:
            self._busy = False
            ctx.bus.emit("upload:end", kind)

    def _make_progress_emitter(self, ctx: ProviderContext):
        def _cb(sent: int, total: int) -> None:
            ctx.bus.emit("upload:progress", (sent, total))
        return _cb

    @staticmethod
    def _set_result(fut: ConcFuture | None, val: Any) -> None:
        if fut is None or fut.done():
            return
        if isinstance(val, Exception):
            fut.set_exception(val)
        else:
            fut.set_result(val)
