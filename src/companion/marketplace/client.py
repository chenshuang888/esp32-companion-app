"""marketplace HTTP 客户端：纯 requests + 短超时，不挂 asyncio。

API 与后端 esp32-marketplace 对齐：
  GET /api/packages?sort=&page=&pageSize=
  GET /api/packages/:slug
  GET /api/packages/:slug/download   → 302 → MinIO 预签名 URL
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import requests

from . import config


class MarketplaceError(Exception):
    """市场 API 调用失败。"""


@dataclass
class PackageCard:
    slug: str
    name: str
    description: str
    category: str
    tags: list[str]
    download_count: int
    star_count: int
    needs_plugin: bool
    author_username: Optional[str]
    latest_version: Optional[str]
    latest_scan_status: Optional[str]
    updated_at: str
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> "PackageCard":
        lv = d.get("latestVersion") or {}
        author = d.get("author") or {}
        return cls(
            slug=d["slug"],
            name=d.get("name", d["slug"]),
            description=d.get("description") or "",
            category=d.get("category") or "misc",
            tags=list(d.get("tags") or []),
            download_count=int(d.get("downloadCount") or 0),
            star_count=int(d.get("starCount") or 0),
            needs_plugin=bool(d.get("needsPlugin")),
            author_username=author.get("username"),
            latest_version=lv.get("version"),
            latest_scan_status=lv.get("scanStatus"),
            updated_at=d.get("updatedAt") or "",
            raw=d,
        )


class MarketplaceClient:
    def __init__(self, base_url: Optional[str] = None, timeout: float = config.DEFAULT_TIMEOUT) -> None:
        self.base_url = (base_url or config.get_base_url()).rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def _api(self, path: str) -> str:
        return f"{self.base_url}/api{path}"

    def list_packages(
        self,
        *,
        q: Optional[str] = None,
        category: Optional[str] = None,
        sort: str = "new",
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[int, list[PackageCard]]:
        params: dict[str, Any] = {"sort": sort, "page": page, "pageSize": page_size}
        if q:
            params["q"] = q
        if category:
            params["category"] = category
        try:
            r = self.session.get(self._api("/packages"), params=params, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as e:
            raise MarketplaceError(f"无法连接市场 ({self.base_url}): {e}") from e
        d = r.json()
        items = [PackageCard.from_api(x) for x in d.get("items", [])]
        return int(d.get("total") or 0), items

    def detail(self, slug: str) -> dict[str, Any]:
        try:
            r = self.session.get(self._api(f"/packages/{slug}"), timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as e:
            raise MarketplaceError(f"获取详情失败: {e}") from e
        return r.json()

    def download_mpkg(
        self,
        slug: str,
        *,
        version: Optional[str] = None,
        on_progress=None,
    ) -> bytes:
        """下载 .mpkg 字节流（自动跟随 302 到 MinIO）。

        on_progress(downloaded_bytes, total_or_None)
        """
        params = {}
        if version:
            params["version"] = version
        url = self._api(f"/packages/{slug}/download")
        try:
            r = self.session.get(url, params=params, timeout=self.timeout, stream=True, allow_redirects=True)
            r.raise_for_status()
        except requests.RequestException as e:
            raise MarketplaceError(f"下载失败: {e}") from e

        total_str = r.headers.get("Content-Length")
        total = int(total_str) if total_str and total_str.isdigit() else None
        chunks: list[bytes] = []
        downloaded = 0
        for chunk in r.iter_content(chunk_size=8192):
            if not chunk:
                continue
            chunks.append(chunk)
            downloaded += len(chunk)
            if on_progress is not None:
                try:
                    on_progress(downloaded, total)
                except Exception:
                    pass
        return b"".join(chunks)
