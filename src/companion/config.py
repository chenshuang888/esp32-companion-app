"""持久化配置（用户版）：%APPDATA%/esp32-companion-user/config.json。"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from . import app_paths, branding

logger = logging.getLogger(__name__)

CONFIG_PATH: Path = app_paths.config_file()

DEFAULT: dict[str, Any] = {
    "device_name": branding.DEFAULT_DEVICE_NAME,
    "device_address": None,
    "providers": {
        "time":    True,
        "weather": True,
        "notify":  True,
        "system":  True,
        "media":   True,
        "bridge":  True,
        "upload":  True,
    },
    "music_folder": str(Path.home() / "Music" / "ESP32"),
}


def load() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return dict(DEFAULT)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("config load failed: %s; using defaults", e)
        return dict(DEFAULT)
    merged = dict(DEFAULT)
    if isinstance(data, dict):
        merged.update(data)
        if isinstance(data.get("providers"), dict):
            merged["providers"] = {**DEFAULT["providers"], **data["providers"]}
    return merged


def save(cfg: dict[str, Any]) -> None:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("config save failed: %s", e)
