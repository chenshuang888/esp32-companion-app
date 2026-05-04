"""本地已安装清单（用户版）：%APPDATA%/esp32-companion-user/plugins/.marketplace_meta/_registry.json"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Optional

from .. import app_paths


def _meta_dir() -> Path:
    return app_paths.marketplace_meta_dir()


def _registry_file() -> Path:
    return _meta_dir() / "_registry.json"


def _load_all() -> dict[str, Any]:
    f = _registry_file()
    if not f.exists():
        return {"version": 1, "installed": {}}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "installed": {}}


def _save_all(data: dict[str, Any]) -> None:
    _registry_file().write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def list_installed() -> dict[str, dict[str, Any]]:
    return _load_all().get("installed", {})


def get(slug: str) -> Optional[dict[str, Any]]:
    return list_installed().get(slug)


def add(
    slug: str,
    *,
    version: str,
    has_plugin: bool,
    plugin_files: list[str],
    plugin_dir_name: Optional[str],
    base_url: str,
) -> None:
    data = _load_all()
    data.setdefault("installed", {})[slug] = {
        "slug": slug,
        "version": version,
        "installed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "has_plugin": has_plugin,
        "plugin_files": plugin_files,
        "plugin_dir_name": plugin_dir_name,
        "marketplace_url": f"{base_url.rstrip('/')}/packages/{slug}",
    }
    _save_all(data)


def remove(slug: str) -> None:
    data = _load_all()
    data.get("installed", {}).pop(slug, None)
    _save_all(data)


def meta_dir() -> Path:
    return _meta_dir()
