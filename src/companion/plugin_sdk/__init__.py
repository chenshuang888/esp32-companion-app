"""plugin_sdk —— 给插件作者的稳定接口。

设计目的：
  让"PC 端配套动态 app 的服务"不再写进 companion 主程序，而是放到一个独立目录里
  作为插件加载。每个插件 = 一个 Python class 继承 Plugin。

接口稳定承诺：
  本文件暴露的 Plugin 基类是"插件 ↔ 主程序"的契约。除非确实必要，不要改字段
  签名。新增字段 / 方法时保持向后兼容（默认值给 None / pass）。

插件作者最小例子::

    # plugins/foo/plugin.py
    from companion.plugin_sdk import Plugin

    class FooPlugin(Plugin):
        plugin_id = "foo"
        title     = "Foo"            # 空字符串 = 不在侧边栏出现
        bind_app  = "foo_pkg"         # None = 通用服务（接收所有消息）

        async def on_message(self, msg):
            self.log.info("got: %s", msg)
            await self.tx("ack", body={"ok": True})

平台注入：
  实例化时由 PluginManager 注入 bus / log / 内部 _tx 函数。
  插件代码里直接用 self.bus / self.log / self.tx(...) 即可，不要去碰底层。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from ..bus import EventBus


class Plugin:
    """所有插件的基类。子类只需要：
       1) 设置类属性（plugin_id / title / bind_app）
       2) 覆盖需要的生命周期 / on_message / make_gui_page
    """

    # —— 子类必填 ——
    plugin_id: str = ""              # 唯一 id（如 "gomoku"）
    title:     str = ""              # 侧边栏显示名；空 = 无 GUI 页
    # —— 子类可选 ——
    bind_app:  Optional[str] = None  # 绑死动态 app id；None = 通用（接收所有消息）

    # —— 平台注入（PluginManager 实例化时设置；子类不要覆盖）——
    bus: EventBus
    log: logging.Logger
    _tx_to:           Callable[[str, str, Any], None]
    _is_connected_fn: Callable[[], bool]

    def __init__(self) -> None:
        # 异步任务表，便于 unload 时统一取消
        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------
    # 生命周期（按需覆盖）
    # ------------------------------------------------------------------

    def on_load(self) -> None:
        """实例化后调用一次（同步，BLE 还未连接）。"""

    def on_unload(self) -> None:
        """卸载时调用（同步资源清理；async 资源应该在 on_disconnect 里清）。"""

    async def on_connect(self, addr: str) -> None:
        """BLE 连上设备后调用（每次重连都会调）。"""

    async def on_disconnect(self) -> None:
        """BLE 断开时调用（每次断都会调）。"""

    async def on_message(self, msg: dict) -> None:
        """收到 from=bind_app 的消息（已过滤）；通用插件（bind_app=None）收所有。
        msg 形如 {"from": "...", "type": "...", "body": {...}}。"""

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    def tx(self, mtype: str, body: Any = None) -> None:
        """发消息给 self.bind_app。bind_app=None 时报错。"""
        if not self.bind_app:
            self.log.warning("tx() requires bind_app; use tx_to() for arbitrary target")
            return
        self._tx_to(self.bind_app, mtype, body)

    def tx_to(self, app_id: str, mtype: str, body: Any = None) -> None:
        """发消息给任意 app id。"""
        self._tx_to(app_id, mtype, body)

    def is_connected(self) -> bool:
        return self._is_connected_fn()

    def create_task(self, coro) -> asyncio.Task:
        """创建后台 task；插件 unload 时自动取消。"""
        task = asyncio.create_task(coro)
        self._tasks.append(task)
        return task

    def _cancel_all_tasks(self) -> None:
        """PluginManager 在 unload 时调，业务不要直接调。"""
        for t in self._tasks:
            if not t.done():
                t.cancel()
        self._tasks.clear()

    # ------------------------------------------------------------------
    # GUI（可选）
    # ------------------------------------------------------------------

    def make_gui_page(self, master, app):
        """返回 ctk.CTkFrame 实例；None 表示本插件不提供 GUI 页。
        注意：title 为空时 PluginManager 不会调本方法。"""
        return None
