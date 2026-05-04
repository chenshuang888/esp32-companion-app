"""marketplace 模块配置（用户版）：URL 锁死生产，缓存目录走 app_paths。"""
from __future__ import annotations

import json
from typing import Any

from .. import app_paths, branding

CACHE_DIR = app_paths.cache_dir()
CONFIG_FILE = app_paths.base_dir() / "marketplace.json"
DEFAULT_BASE_URL = branding.MARKETPLACE_URL
DEFAULT_TIMEOUT = 8.0


def load() -> dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {"base_url": DEFAULT_BASE_URL}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"base_url": DEFAULT_BASE_URL}


def save(_cfg: dict[str, Any]) -> None:
    # 用户版不允许持久化非默认 URL
    return


def get_base_url() -> str:
    # 锁死生产，不读用户文件
    return DEFAULT_BASE_URL


def set_base_url(_url: str) -> None:
    # noop：保持签名兼容，行为禁用
    return
