"""Marketplace 页（用户精简版）：浏览市场 + 一键安装/卸载/更新。

数据流同开发版，市场地址锁死生产，UI 去顶部 URL 输入行 + 文案改用户向。
"""
from __future__ import annotations

import logging
import shutil
import threading
from concurrent.futures import Future as ConcFuture
from pathlib import Path
from tkinter import messagebox
from typing import Optional

import customtkinter as ctk

from ... import branding, marketplace
from ...marketplace import (
    InstallerError, MarketplaceClient, MarketplaceError, PackageCard, parse_mpkg,
)
from ..theme import (
    COLOR_ACCENT, COLOR_ACCENT2, COLOR_ERR, COLOR_MUTED, COLOR_OK, COLOR_PANEL,
    COLOR_PANEL_HI, COLOR_TEXT, COLOR_WARN,
)
from ..widgets import Card

logger = logging.getLogger(__name__)


class MarketplacePage(ctk.CTkFrame):
    def __init__(self, master, app) -> None:
        super().__init__(master, fg_color="transparent")
        self._app = app
        self._client = MarketplaceClient()
        self._items: list[PackageCard] = []
        self._installed: dict[str, dict] = {}
        self._busy_slug: Optional[str] = None
        self._connected = False
        self._build()

        # 复用 upload:* 事件做进度反馈
        app.bus.on("upload:progress", lambda p: self.after(0, self._on_progress, p))
        app.bus.on("upload:step",     lambda p: self.after(0, self._on_step, p))
        app.bus.on("upload:end",      lambda _: self.after(0, self._on_upload_end))
        app.bus.on("upload:begin",    lambda _: self.after(0, self._on_upload_begin))
        app.bus.on("connect",    lambda _: self.after(0, self._on_conn, True))
        app.bus.on("disconnect", lambda _: self.after(0, self._on_conn, False))

        self.after(100, self._refresh_all)

    def _on_conn(self, ok: bool) -> None:
        self._connected = ok

    def _reload_plugin_pages(self) -> None:
        """让主 app 重扫扩展目录，新装的扩展立刻可用。"""
        try:
            self._app.reload_plugin_pages()
        except Exception as e:
            logger.warning("reload_plugin_pages failed: %s", e)

    # =============================================================
    # UI
    # =============================================================

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        # 顶部：简介 + 刷新
        top = Card(self)
        top.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 8))
        top.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(top,
                      text="浏览社区动态 App，一键装到设备",
                      text_color=COLOR_TEXT, anchor="w",
                      font=ctk.CTkFont(size=14, weight="bold")) \
            .grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 0))
        ctk.CTkLabel(top,
                      text="带「需要桌面扩展」标签的 App 会自动把桌面端配套一并装好。",
                      text_color=COLOR_MUTED, anchor="w") \
            .grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
        ctk.CTkButton(top, text="刷新", width=80, fg_color=COLOR_ACCENT2,
                       command=self._refresh_all) \
            .grid(row=0, column=1, rowspan=2, padx=(4, 14), pady=10, sticky="e")

        # 状态行
        self._status_lbl = ctk.CTkLabel(self, text="正在加载…",
                                         text_color=COLOR_MUTED, anchor="w")
        self._status_lbl.grid(row=1, column=0, sticky="ew", padx=24, pady=(4, 4))

        # 列表（可滚动）
        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._scroll.grid(row=2, column=0, sticky="nsew", padx=14, pady=(4, 12))
        self._scroll.grid_columnconfigure(0, weight=1)

        # 进度条（默认隐藏）
        self._prog_card = Card(self)
        self._prog_label = ctk.CTkLabel(self._prog_card, text="",
                                         text_color=COLOR_TEXT, anchor="w")
        self._prog_label.grid(row=0, column=0, sticky="ew", padx=14, pady=(10, 4))
        self._prog_bar = ctk.CTkProgressBar(self._prog_card)
        self._prog_bar.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 10))
        self._prog_bar.set(0)
        self._prog_card.grid_columnconfigure(0, weight=1)
        # 不 grid 到主，等 _on_upload_begin 再显示

    # =============================================================
    # 数据刷新
    # =============================================================

    def _save_url(self) -> None:
        # 用户版禁用，保留方法签名兼容
        return

    def _refresh_all(self) -> None:
        self._installed = marketplace.registry.list_installed()
        self._set_status("加载中…", COLOR_MUTED)
        threading.Thread(target=self._fetch_packages_worker, daemon=True).start()

    def _fetch_packages_worker(self) -> None:
        try:
            total, items = self._client.list_packages(sort="new", page_size=50)
        except MarketplaceError as e:
            self.after(0, lambda: self._set_status(str(e), COLOR_ERR))
            self.after(0, lambda: self._render_items([]))
            return
        self.after(0, lambda: self._set_status(
            f"市场共 {total} 个 App，本地已装 {len(self._installed)} 个", COLOR_OK))
        self.after(0, lambda: self._render_items(items))

    def _set_status(self, text: str, color: str) -> None:
        self._status_lbl.configure(text=text, text_color=color)

    def _render_items(self, items: list[PackageCard]) -> None:
        self._items = items
        # 清空旧 widget
        for w in self._scroll.winfo_children():
            w.destroy()

        # 合并：市场列表 + 本地孤儿（市场没有但本地有的）
        seen = {p.slug for p in items}
        orphan_slugs = [s for s in self._installed.keys() if s not in seen]

        row = 0
        for pkg in items:
            self._render_card(row, pkg, orphan=False)
            row += 1
        for slug in orphan_slugs:
            self._render_orphan(row, slug)
            row += 1

        if not items and not orphan_slugs:
            empty = ctk.CTkLabel(self._scroll, text="（市场暂无内容）",
                                  text_color=COLOR_MUTED)
            empty.grid(row=0, column=0, padx=20, pady=20)

    def _render_card(self, row: int, pkg: PackageCard, *, orphan: bool) -> None:
        installed = self._installed.get(pkg.slug)
        latest = pkg.latest_version or "?"
        is_installed = installed is not None
        is_outdated = is_installed and installed.get("version") != latest

        card = Card(self._scroll)
        card.grid(row=row, column=0, sticky="ew", pady=6, padx=4)
        card.grid_columnconfigure(1, weight=1)

        # 左：图标占位（首字母）
        icon = ctk.CTkLabel(card,
                             text=pkg.name[:1].upper(),
                             width=44, height=44,
                             corner_radius=8,
                             fg_color=COLOR_ACCENT2,
                             text_color=COLOR_TEXT,
                             font=ctk.CTkFont(size=20, weight="bold"))
        icon.grid(row=0, column=0, rowspan=3, padx=(14, 10), pady=12)

        # 标题行
        title_row = ctk.CTkFrame(card, fg_color="transparent")
        title_row.grid(row=0, column=1, sticky="ew", padx=4, pady=(12, 0))
        ctk.CTkLabel(title_row, text=pkg.name, text_color=COLOR_TEXT,
                      font=ctk.CTkFont(size=15, weight="bold"), anchor="w") \
            .pack(side="left")
        ctk.CTkLabel(title_row, text=f"  v{latest}", text_color=COLOR_MUTED, anchor="w") \
            .pack(side="left")
        if pkg.needs_plugin:
            ctk.CTkLabel(title_row, text=f"  {branding.TERM_NEEDS_PC}", text_color=COLOR_WARN, anchor="w") \
                .pack(side="left")
        if is_outdated:
            ctk.CTkLabel(title_row, text=f"  ▲ 可更新 (本地 v{installed['version']})",
                          text_color=COLOR_WARN, anchor="w").pack(side="left")
        elif is_installed:
            ctk.CTkLabel(title_row, text="  ✓ 已安装", text_color=COLOR_OK, anchor="w") \
                .pack(side="left")

        # 描述
        desc = pkg.description or "（无描述）"
        if len(desc) > 80:
            desc = desc[:80] + "…"
        ctk.CTkLabel(card, text=desc, text_color=COLOR_MUTED, anchor="w",
                      justify="left", wraplength=520) \
            .grid(row=1, column=1, sticky="ew", padx=4, pady=(0, 4))

        # 元数据
        meta_text = f"@{pkg.author_username or '?'}  ·  {pkg.category}  ·  ⬇ {pkg.download_count}  ·  ★ {pkg.star_count}"
        if pkg.latest_scan_status:
            meta_text += f"  ·  扫描:{pkg.latest_scan_status}"
        ctk.CTkLabel(card, text=meta_text, text_color=COLOR_MUTED, anchor="w") \
            .grid(row=2, column=1, sticky="ew", padx=4, pady=(0, 12))

        # 右：操作按钮列
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.grid(row=0, column=2, rowspan=3, padx=(8, 14), pady=12, sticky="e")

        if is_outdated:
            btn = ctk.CTkButton(actions, text="更新", width=80, fg_color=COLOR_WARN,
                                 command=lambda s=pkg.slug, v=latest: self._on_install(s, v))
            btn.pack(pady=2)
            uninst = ctk.CTkButton(actions, text="卸载", width=80, fg_color=COLOR_ERR,
                                     command=lambda s=pkg.slug: self._on_uninstall(s))
            uninst.pack(pady=2)
        elif is_installed:
            ctk.CTkButton(actions, text="重装", width=80, fg_color=COLOR_PANEL_HI,
                            command=lambda s=pkg.slug, v=latest: self._on_install(s, v)) \
                .pack(pady=2)
            ctk.CTkButton(actions, text="卸载", width=80, fg_color=COLOR_ERR,
                            command=lambda s=pkg.slug: self._on_uninstall(s)) \
                .pack(pady=2)
        else:
            ctk.CTkButton(actions, text="安装", width=80, fg_color=COLOR_ACCENT,
                            command=lambda s=pkg.slug, v=latest: self._on_install(s, v)) \
                .pack(pady=2)

    def _render_orphan(self, row: int, slug: str) -> None:
        info = self._installed.get(slug, {})
        card = Card(self._scroll)
        card.grid(row=row, column=0, sticky="ew", pady=6, padx=4)
        card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(card, text="⚠", width=44, height=44,
                       fg_color=COLOR_WARN, text_color=COLOR_TEXT,
                       corner_radius=8,
                       font=ctk.CTkFont(size=22, weight="bold")) \
            .grid(row=0, column=0, rowspan=2, padx=(14, 10), pady=12)
        ctk.CTkLabel(card, text=f"{slug}（{branding.TERM_ORPHAN}）",
                       text_color=COLOR_TEXT, anchor="w",
                       font=ctk.CTkFont(size=14, weight="bold")) \
            .grid(row=0, column=1, sticky="ew", padx=4, pady=(12, 0))
        ctk.CTkLabel(card, text=f"当前已安装 v{info.get('version', '?')}",
                       text_color=COLOR_MUTED, anchor="w") \
            .grid(row=1, column=1, sticky="ew", padx=4, pady=(0, 12))
        ctk.CTkButton(card, text="卸载", width=80, fg_color=COLOR_ERR,
                        command=lambda s=slug: self._on_uninstall(s)) \
            .grid(row=0, column=2, rowspan=2, padx=(8, 14), pady=12, sticky="e")

    # =============================================================
    # 安装 / 卸载
    # =============================================================

    def _on_install(self, slug: str, version: str) -> None:
        if self._busy_slug:
            messagebox.showwarning("忙碌", f"正在处理 {self._busy_slug}，请稍候")
            return
        if not self._connected:
            messagebox.showwarning("未连接", "请先连接 ESP32 设备（侧边栏底部状态点变绿即已连接）")
            return

        ok = messagebox.askokcancel(
            "确认安装",
            f"将下载并安装 {slug} v{version} 到设备。\n"
            f"若该 App 需要桌面扩展，会自动一并装到本地（重启程序生效）。\n\n"
            "继续？"
        )
        if not ok:
            return

        self._busy_slug = slug
        self._set_status(f"下载 {slug} v{version} 中…", COLOR_ACCENT)
        threading.Thread(
            target=self._install_worker, args=(slug, version), daemon=True
        ).start()

    def _install_worker(self, slug: str, version: str) -> None:
        tmp_dir: Optional[Path] = None
        try:
            data = self._client.download_mpkg(
                slug, version=version,
                on_progress=lambda d, t: self.after(0, self._on_download_progress, d, t),
            )
            self.after(0, lambda: self._set_status(f"解析 {slug}…", COLOR_ACCENT))
            parsed = parse_mpkg(data)

            # plugin 部分先落盘
            plugin_dir_name = None
            plugin_files: list[str] = []
            if parsed.has_plugin:
                self.after(0, lambda: self._set_status(f"安装{branding.TERM_PC_PLUGIN}…", COLOR_ACCENT))
                plugin_dir_name, plugin_files = marketplace.install_plugin_locally(parsed, slug)

            # app 部分写临时目录交给 UploadProvider 推送
            tmp_dir = marketplace.make_temp_pack_dir(parsed)
            self.after(0, lambda: self._set_status(f"上传 {slug} 到设备…", COLOR_ACCENT))
            fut = marketplace.request_upload_via_bus(self._app.bus, parsed, tmp_dir)
            fut.result(timeout=300)

            marketplace.registry.add(
                slug,
                version=version,
                has_plugin=parsed.has_plugin,
                plugin_files=plugin_files,
                plugin_dir_name=plugin_dir_name,
                base_url=self._client.base_url,
            )

            self.after(0, lambda: self._set_status(
                f"✅ {slug} v{version} 安装成功"
                + (f"（含{branding.TERM_PC_PLUGIN}，已加载；如未生效请断开重连一次）" if parsed.has_plugin else ""),
                COLOR_OK))
            self.after(0, self._refresh_all)
            if parsed.has_plugin:
                # 主 app 重扫插件目录，新装的扩展立刻在侧边栏出现
                self.after(0, self._reload_plugin_pages)
        except (MarketplaceError, InstallerError) as e:
            self.after(0, lambda: self._set_status(f"❌ {e}", COLOR_ERR))
        except Exception as e:
            logger.exception("install failed")
            self.after(0, lambda: self._set_status(f"❌ 安装失败：{e}", COLOR_ERR))
        finally:
            if tmp_dir and tmp_dir.exists():
                try:
                    shutil.rmtree(tmp_dir)
                except Exception:
                    pass
            self._busy_slug = None

    def _on_uninstall(self, slug: str) -> None:
        if self._busy_slug:
            messagebox.showwarning("忙碌", f"正在处理 {self._busy_slug}")
            return
        info = self._installed.get(slug, {})
        if not messagebox.askokcancel(
            "确认卸载",
            f"将从设备删除 {slug}（v{info.get('version', '?')}），"
            f"并清理本地{branding.TERM_PC_PLUGIN}（若有）。\n\n继续？"
        ):
            return
        if not self._connected:
            messagebox.showwarning("未连接", "请先连接 ESP32 设备再卸载")
            return

        self._busy_slug = slug
        self._set_status(f"卸载 {slug} 中…", COLOR_WARN)
        threading.Thread(
            target=self._uninstall_worker, args=(slug,), daemon=True
        ).start()

    def _uninstall_worker(self, slug: str) -> None:
        try:
            fut = marketplace.request_delete_via_bus(self._app.bus, slug)
            try:
                fut.result(timeout=30)
            except Exception as e:
                logger.warning("device delete %s failed (continuing): %s", slug, e)

            marketplace.uninstall_plugin_locally(slug)
            marketplace.registry.remove(slug)

            self.after(0, lambda: self._set_status(
                f"✅ {slug} 已卸载（{branding.TERM_PC_PLUGIN}变更需重启程序生效）", COLOR_OK))
            self.after(0, self._refresh_all)
        except Exception as e:
            logger.exception("uninstall failed")
            self.after(0, lambda: self._set_status(f"❌ 卸载失败：{e}", COLOR_ERR))
        finally:
            self._busy_slug = None

    # =============================================================
    # 进度反馈
    # =============================================================

    def _on_download_progress(self, downloaded: int, total: Optional[int]) -> None:
        if total:
            pct = downloaded * 100 // total
            self._set_status(f"下载中… {pct}%  ({downloaded // 1024}/{total // 1024} KB)",
                              COLOR_ACCENT)
        else:
            self._set_status(f"下载中… {downloaded // 1024} KB", COLOR_ACCENT)

    def _on_upload_begin(self) -> None:
        self._prog_card.grid(row=3, column=0, sticky="ew", padx=20, pady=(4, 12))
        self._prog_bar.set(0)
        self._prog_label.configure(text="上传中…")

    def _on_upload_end(self) -> None:
        self._prog_card.grid_remove()

    def _on_step(self, payload) -> None:
        if isinstance(payload, tuple) and len(payload) == 3:
            filename, idx, total = payload
            self._prog_label.configure(text=f"[{idx}/{total}] {filename}")
            self._prog_bar.set(0)

    def _on_progress(self, payload) -> None:
        if isinstance(payload, tuple) and len(payload) == 2:
            sent, total = payload
            if total > 0:
                self._prog_bar.set(sent / total)
