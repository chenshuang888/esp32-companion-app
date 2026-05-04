"""主窗口 + 侧边栏 + page 路由 + 关闭拦截（用户精简版）。

只保留「市场」「音乐」两页，去掉调试入口（home/upload/notify/log + 刷新插件按钮）。
"""

from __future__ import annotations

import logging
from typing import Optional

import customtkinter as ctk

from .. import branding, config as cfg
from ..bus import EventBus
from ..runner import AsyncRunner
from .pages.marketplace import MarketplacePage
from .pages.music import MusicPage
from .theme import (
    COLOR_ACCENT, COLOR_BG, COLOR_MUTED, COLOR_PANEL, COLOR_PANEL_HI,
    COLOR_SIDEBAR, COLOR_TEXT, CTK_APPEARANCE, CTK_THEME, SIDEBAR_W,
    WINDOW_H, WINDOW_W, enable_windows_dpi_awareness,
)
from .widgets import StatusDot

logger = logging.getLogger(__name__)


PAGE_DEFS = [
    ("marketplace", "市场", MarketplacePage),
    ("music",       "音乐", MusicPage),
]


class CompanionApp:
    def __init__(self, bus: EventBus, runner: AsyncRunner,
                  cfg_data: dict, on_quit_request,
                  plugin_manager=None) -> None:
        self.bus = bus
        self.runner = runner
        self.cfg = cfg_data
        self._on_quit_request = on_quit_request
        self._pm = plugin_manager

        enable_windows_dpi_awareness()
        ctk.set_appearance_mode(CTK_APPEARANCE)
        ctk.set_default_color_theme(CTK_THEME)

        self.root = ctk.CTk()
        self.root.title(branding.WINDOW_TITLE)
        self.root.geometry(f"{WINDOW_W}x{WINDOW_H}")
        self.root.configure(fg_color=COLOR_BG)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._pages: dict[str, ctk.CTkFrame] = {}
        self._buttons: dict[str, ctk.CTkButton] = {}
        self._connected_addr: Optional[str] = None
        self._build()
        self._show("marketplace")

        bus.on("connect",    lambda a: self.root.after(0, self._update_conn, True, a))
        bus.on("disconnect", lambda _: self.root.after(0, self._update_conn, False, ""))

    # ------------------------------------------------------------------
    # build
    # ------------------------------------------------------------------

    def _collect_page_defs(self) -> list[tuple[str, str, object]]:
        """合并内置 + 插件 GUI 页。"""
        out: list[tuple[str, str, object]] = []
        for key, label, cls in PAGE_DEFS:
            out.append((key, label, cls))
        if self._pm is None:
            return out
        for pid, title, plugin in self._pm.get_gui_pages():
            def make(master, app, p=plugin):
                return p.make_gui_page(master, app)
            out.append((pid, title, make))
        return out

    def _build(self) -> None:
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        # 侧边栏
        side = ctk.CTkFrame(self.root, fg_color=COLOR_SIDEBAR,
                              width=SIDEBAR_W, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.grid_rowconfigure(99, weight=1)
        self._sidebar = side

        ctk.CTkLabel(side, text=branding.APP_NAME,
                      text_color=COLOR_ACCENT,
                      font=ctk.CTkFont(size=20, weight="bold")) \
            .grid(row=0, column=0, padx=20, pady=(20, 4), sticky="w")
        ctk.CTkLabel(side, text=branding.APP_SUBTITLE,
                      text_color=COLOR_MUTED,
                      font=ctk.CTkFont(size=11)) \
            .grid(row=1, column=0, padx=20, pady=(0, 16), sticky="w")

        # 内容区
        self._content = ctk.CTkFrame(self.root, fg_color=COLOR_BG, corner_radius=0)
        self._content.grid(row=0, column=1, sticky="nsew")
        self._content.grid_rowconfigure(0, weight=1)
        self._content.grid_columnconfigure(0, weight=1)

        # 底部连接状态
        self._side_status = StatusDot(side, text="未连接")
        self._side_status.grid(row=98, column=0, padx=20, pady=(8, 16), sticky="sw")

        # 若 BLE 已连接（如重建 widget 之后），立即恢复状态
        if self._connected_addr:
            self._side_status.set(f"已连接 {self._connected_addr[:12]}", COLOR_ACCENT)

        self._populate_pages()

    def _populate_pages(self) -> None:
        for btn in self._buttons.values():
            try: btn.destroy()
            except Exception: pass
        self._buttons.clear()
        for page in self._pages.values():
            try:
                page.grid_forget()
                page.destroy()
            except Exception: pass
        self._pages.clear()

        for i, (key, label, factory) in enumerate(self._collect_page_defs()):
            btn = ctk.CTkButton(self._sidebar, text=label, anchor="w",
                                  fg_color="transparent",
                                  hover_color=COLOR_PANEL_HI,
                                  text_color=COLOR_TEXT,
                                  corner_radius=8, height=36,
                                  command=lambda k=key: self._show(k))
            btn.grid(row=2 + i, column=0, padx=12, pady=4, sticky="ew")
            self._buttons[key] = btn

            try:
                page = factory(self._content, self)
            except Exception as e:
                logger.warning("page %s build failed: %s", key, e)
                continue
            self._pages[key] = page

    def reload_plugin_pages(self) -> None:
        """市场装好新扩展后调用，把新扩展页**追加**到侧边栏（不动已存在的页面）。

        若 BLE 当前已连接，新插件会错过 on_connect；这里给新插件补发一次。
        """
        if self._pm is None:
            return
        before = set(self._pm.get_all().keys())
        self._pm.discover_and_load()
        after = self._pm.get_all()
        new_ids = set(after.keys()) - before

        # 收集所有当前应有的页面定义
        target_defs = self._collect_page_defs()
        existing = set(self._pages.keys())
        added = 0
        for i, (key, label, factory) in enumerate(target_defs):
            if key in existing:
                continue
            btn = ctk.CTkButton(self._sidebar, text=label, anchor="w",
                                  fg_color="transparent",
                                  hover_color=COLOR_PANEL_HI,
                                  text_color=COLOR_TEXT,
                                  corner_radius=8, height=36,
                                  command=lambda k=key: self._show(k))
            btn.grid(row=2 + i, column=0, padx=12, pady=4, sticky="ew")
            self._buttons[key] = btn
            try:
                page = factory(self._content, self)
            except Exception as e:
                logger.warning("page %s build failed: %s", key, e)
                continue
            self._pages[key] = page
            added += 1
        if added:
            logger.info("added %d new plugin page(s)", added)

        # 给新插件补一次 on_connect（若 BLE 当前已连接）
        if new_ids and self._connected_addr:
            addr = self._connected_addr
            for pid in new_ids:
                p = after.get(pid)
                if p is None:
                    continue
                try:
                    coro = p.on_connect(addr)
                    if coro is not None and hasattr(coro, "__await__"):
                        # 在 AsyncRunner 的事件循环上跑
                        self.runner.submit(coro)
                except Exception as e:
                    logger.warning("plugin %s on_connect (post-install) failed: %s", pid, e)

    def _show(self, key: str) -> None:
        for k, page in self._pages.items():
            if k == key:
                page.grid(row=0, column=0, sticky="nsew")
            else:
                page.grid_forget()
        for k, btn in self._buttons.items():
            btn.configure(fg_color=COLOR_PANEL if k == key else "transparent")

    def _update_conn(self, ok: bool, addr: str) -> None:
        if ok:
            self._connected_addr = addr
            self._side_status.set(f"已连接 {addr[:12]}", COLOR_ACCENT)
        else:
            self._connected_addr = None
            self._side_status.set("未连接")

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        self.root.withdraw()
        self._on_quit_request("hide")

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def quit_app(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass

    def mainloop(self) -> None:
        self.root.mainloop()
