"""统一管理用户数据目录。

打包成 exe 后路径要从"用 __file__ 倒推 tools/"换成"用户级数据目录"，
所有读写持久化数据的模块都通过这里拿路径。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_DIR_NAME = "esp32-companion-user"


def _base() -> Path:
    if sys.platform == "win32":
        b = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        b = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    p = Path(b) / APP_DIR_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def base_dir() -> Path:
    return _base()


def config_file() -> Path:
    return _base() / "config.json"


def user_plugins_root() -> Path:
    p = _base() / "plugins"
    p.mkdir(parents=True, exist_ok=True)
    return p


def marketplace_meta_dir() -> Path:
    p = user_plugins_root() / ".marketplace_meta"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    p = _base() / "cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def log_file() -> Path:
    return _base() / "app.log"
