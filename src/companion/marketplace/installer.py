"""installer —— 解 .mpkg + 推 app 到 ESP32 + 落 plugin/ 到用户数据目录。

设计：
  - 不直接持有 BleakClient；通过 bus("upload:request") 调度上传，复用 UploadProvider
  - 解 .mpkg 后：
      * app 部分（manifest.json + main.js + 可选 icon.bin + 可选 assets/）
        写到一个临时目录，用现有 upload_app_pack 的 pack_dir 形式上传
      * plugin/ 部分写到 %APPDATA%/esp32-companion-user/plugins/<slug>/

用户精简版：plugin 落点改为用户数据目录（exe 内部 read-only，无法写仓库）。
线程：本模块函数都是同步的，调用方应在工作线程跑（GUI 用 after 桥回主线程）。
"""
from __future__ import annotations

import io
import json
import logging
import shutil
import tempfile
import zipfile
from concurrent.futures import Future as ConcFuture
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from .. import app_paths
from . import registry

logger = logging.getLogger(__name__)


class InstallerError(Exception):
    pass


def _plugins_dir() -> Path:
    return app_paths.user_plugins_root()


@dataclass
class ParsedMpkg:
    manifest: dict[str, Any]
    entry_name: str
    main_js: bytes
    icon_bin: Optional[bytes]
    assets: dict[str, bytes] = field(default_factory=dict)   # 'name.bin' -> bytes
    plugin_files: dict[str, bytes] = field(default_factory=dict)  # 'plugin/x.py' -> bytes
    readme: Optional[str] = None

    @property
    def app_id(self) -> str:
        return self.manifest["id"]

    @property
    def has_plugin(self) -> bool:
        return bool(self.plugin_files)


def parse_mpkg(data: bytes) -> ParsedMpkg:
    if len(data) > 16 * 1024 * 1024:
        raise InstallerError("包过大（>16MB），拒绝处理")
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise InstallerError(f"不是合法 zip：{e}") from e

    names = set(z.namelist())
    if "manifest.json" not in names:
        raise InstallerError("包根目录缺少 manifest.json")
    try:
        manifest = json.loads(z.read("manifest.json"))
    except Exception as e:
        raise InstallerError(f"manifest.json 解析失败：{e}") from e

    if not isinstance(manifest, dict) or "id" not in manifest:
        raise InstallerError("manifest.json 缺少 id 字段")

    entry = manifest.get("entry") or "main.js"
    if entry not in names:
        raise InstallerError(f"包内缺少入口脚本 {entry}")
    main_js = z.read(entry)

    icon_bin: Optional[bytes] = None
    if "icon.bin" in names:
        icon_bin = z.read("icon.bin")

    assets: dict[str, bytes] = {}
    for n in names:
        if n.startswith("assets/") and not n.endswith("/"):
            base = n[len("assets/"):]
            if "/" in base:
                continue  # 仅支持单层 assets
            assets[base] = z.read(n)

    plugin_files: dict[str, bytes] = {}
    for n in names:
        if n.startswith("plugin/") and not n.endswith("/"):
            # 防 zip-slip
            if ".." in n.split("/"):
                raise InstallerError(f"plugin 路径含 .. 拒绝：{n}")
            plugin_files[n] = z.read(n)

    readme = None
    if "README.md" in names:
        try:
            readme = z.read("README.md").decode("utf-8")
        except Exception:
            pass

    return ParsedMpkg(
        manifest=manifest,
        entry_name=entry,
        main_js=main_js,
        icon_bin=icon_bin,
        assets=assets,
        plugin_files=plugin_files,
        readme=readme,
    )


def write_pack_dir(parsed: ParsedMpkg, dst: Path) -> None:
    """把 parsed 的 app 部分（不含 plugin）写成 upload_app_pack 期望的目录。

        <dst>/
          ├── manifest.json
          ├── main.js
          ├── icon.bin       (可选)
          └── assets/        (可选)
    """
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "manifest.json").write_bytes(
        json.dumps(parsed.manifest, ensure_ascii=False, indent=2).encode("utf-8")
    )
    (dst / parsed.entry_name).write_bytes(parsed.main_js)
    if parsed.icon_bin is not None:
        (dst / "icon.bin").write_bytes(parsed.icon_bin)
    if parsed.assets:
        adir = dst / "assets"
        adir.mkdir(exist_ok=True)
        for name, data in parsed.assets.items():
            (adir / name).write_bytes(data)


def install_plugin_locally(parsed: ParsedMpkg, slug: str) -> tuple[Optional[str], list[str]]:
    """把 plugin/ 解到用户数据目录的 plugins/<slug>/，返回 (plugin_dir_name, 文件清单)。

    文件清单是相对 user_plugins_root() 的路径，便于卸载时定位。
    没有 plugin 时返回 (None, [])。
    """
    if not parsed.plugin_files:
        return None, []

    plugins_root = _plugins_dir()
    plugin_root = plugins_root / slug
    if plugin_root.exists():
        # 同 slug 重装：删旧目录
        shutil.rmtree(plugin_root)
    plugin_root.mkdir(parents=True)

    written: list[str] = []
    for full_name, data in parsed.plugin_files.items():
        # full_name 形如 'plugin/plugin.py' 或 'plugin/sub/foo.py'
        rel = full_name[len("plugin/"):]
        target = plugin_root / rel
        # 防 zip-slip 二次校验
        try:
            target.resolve().relative_to(plugin_root.resolve())
        except ValueError:
            raise InstallerError(f"plugin 路径越界：{full_name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        written.append(str(target.relative_to(plugins_root)).replace("\\", "/"))

    return slug, written


def uninstall_plugin_locally(slug: str) -> None:
    """按 registry 记录删 user_plugins_root()/<slug>/。

    安全策略：
      - 仅删 registry 里登记的 plugin_files
      - 文件全删完后，如果目录空了再删目录
      - 用户手改/手加的文件**不会**被误删
    """
    info = registry.get(slug)
    if info is None:
        return
    files = info.get("plugin_files") or []
    plugin_dir_name = info.get("plugin_dir_name")

    plugins_root = _plugins_dir()
    for relpath in files:
        try:
            (plugins_root / relpath).unlink()
        except FileNotFoundError:
            pass
        except Exception as e:
            logger.warning("删 plugin 文件失败 %s: %s", relpath, e)

    if plugin_dir_name:
        d = plugins_root / plugin_dir_name
        if d.exists():
            # 自下而上删空目录
            for sub in sorted([p for p in d.rglob("*") if p.is_dir()], key=lambda x: -len(x.parts)):
                try:
                    sub.rmdir()
                except OSError:
                    pass
            try:
                d.rmdir()
            except OSError:
                # 还有用户改过的文件 → 保留目录
                logger.info("plugin 目录非空，保留：%s", d)


def make_temp_pack_dir(parsed: ParsedMpkg) -> Path:
    """构造临时目录给 upload_app_pack 用。返回路径，调用方负责清理。"""
    tmp = Path(tempfile.mkdtemp(prefix=f"mpkg_{parsed.app_id}_"))
    write_pack_dir(parsed, tmp)
    return tmp


def request_upload_via_bus(bus, parsed: ParsedMpkg, pack_dir: Path) -> ConcFuture:
    """把上传请求发给 UploadProvider；返回 Future 等结果。"""
    fut: ConcFuture = ConcFuture()
    bus.emit_threadsafe("upload:request", {
        "kind": "pack",
        "args": {
            "app_id": parsed.app_id,
            "pack_dir": str(pack_dir),
            "display_name": parsed.manifest.get("name"),
        },
        "future": fut,
    })
    return fut


def request_delete_via_bus(bus, app_id: str) -> ConcFuture:
    fut: ConcFuture = ConcFuture()
    bus.emit_threadsafe("upload:request", {
        "kind": "delete",
        "args": {"app_id": app_id},
        "future": fut,
    })
    return fut


def request_list_via_bus(bus) -> ConcFuture:
    fut: ConcFuture = ConcFuture()
    bus.emit_threadsafe("upload:request", {
        "kind": "list",
        "args": {},
        "future": fut,
    })
    return fut
