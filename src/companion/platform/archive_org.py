"""archive.org 免费音乐搜索 + 下载（CC0 / Public Domain 范围）。

API 路径：
  搜索:   https://archive.org/advancedsearch.php?q=...&output=json
  元数据: https://archive.org/metadata/{identifier}
  直链:   https://archive.org/download/{identifier}/{file_name}

不需要 API key，全 JSON。
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)

SEARCH_URL  = "https://archive.org/advancedsearch.php"
META_URL    = "https://archive.org/metadata/{identifier}"
DOWNLOAD_URL = "https://archive.org/download/{identifier}/{file}"

USER_AGENT = "ESP32-Companion/1.0 (offline music sync)"


@dataclass
class TrackHit:
    identifier: str       # archive.org 条目 id
    title: str            # 条目标题
    creator: str          # 作者/上传者（可能为空）
    file_name: Optional[str] = None   # 该条目下选中的 mp3 文件名
    file_size: int = 0                # 文件字节数（估算）

    @property
    def display_title(self) -> str:
        return self.title or self.identifier

    @property
    def display_artist(self) -> str:
        return self.creator or "Unknown"


# ---------------------------------------------------------------------------
# 搜索
# ---------------------------------------------------------------------------

def search(keyword: str, limit: int = 20) -> list[TrackHit]:
    """按关键词搜索，返回最多 limit 个候选。

    限制 collection 为 audio_music（archive.org 公开音乐集合，免费可下载）
    + opensource_audio（用户上传的 CC 协议音乐）。
    """
    if not keyword.strip():
        return []
    query = (
        f'mediatype:(audio) '
        f'AND ({keyword}) '
        f'AND collection:(audio_music OR opensource_audio OR netlabels)'
    )
    params = {
        "q":       query,
        "fl[]":    ["identifier", "title", "creator"],
        "rows":    str(limit),
        "output":  "json",
        "sort[]":  "downloads desc",
    }
    try:
        r = requests.get(SEARCH_URL, params=params,
                          headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning("archive search failed: %s", e)
        return []

    hits = []
    for doc in (data.get("response", {}).get("docs") or []):
        ident = doc.get("identifier")
        if not ident: continue
        title = doc.get("title") or ""
        if isinstance(title, list): title = title[0] if title else ""
        creator = doc.get("creator") or ""
        if isinstance(creator, list): creator = creator[0] if creator else ""
        hits.append(TrackHit(identifier=ident, title=str(title), creator=str(creator)))
    return hits


# ---------------------------------------------------------------------------
# 拿到 mp3 直链
# ---------------------------------------------------------------------------

_AUDIO_EXTS = (".mp3",)   # 只挑 mp3，少操心解码兼容


def resolve_mp3(hit: TrackHit) -> Optional[TrackHit]:
    """对一个条目调 metadata 接口，挑出第一个 mp3 文件，填充 file_name + file_size。"""
    try:
        r = requests.get(META_URL.format(identifier=hit.identifier),
                          headers={"User-Agent": USER_AGENT}, timeout=15)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        logger.warning("archive metadata failed: %s", e)
        return None
    files = data.get("files") or []
    # 优先挑 VBR/最小的 mp3 版本（不要原始 wav）
    candidates = []
    for f in files:
        name = f.get("name") or ""
        if not name.lower().endswith(_AUDIO_EXTS): continue
        size = 0
        try: size = int(f.get("size") or 0)
        except (TypeError, ValueError): size = 0
        candidates.append((name, size))
    if not candidates: return None
    # 选体积最小但 > 100KB 的，避免 1KB 占位文件
    candidates.sort(key=lambda x: (x[1] if x[1] > 100_000 else 1 << 30, len(x[0])))
    name, size = candidates[0]
    hit.file_name = name
    hit.file_size = size
    return hit


def search_with_mp3(keyword: str, limit: int = 15) -> list[TrackHit]:
    """search() + 对每个 hit resolve_mp3，过滤掉无 mp3 的。GUI 用这一个就够了。"""
    resolved: list[TrackHit] = []
    for h in search(keyword, limit=limit):
        r = resolve_mp3(h)
        if r and r.file_name:
            resolved.append(r)
    return resolved


# ---------------------------------------------------------------------------
# 下载
# ---------------------------------------------------------------------------

_FILENAME_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


# ---------------------------------------------------------------------------
# 推荐歌单：每个分类用一个关键词搜，每类挑 N 首小体积曲目
# ---------------------------------------------------------------------------

DEFAULT_PICKS = [
    ("piano",            5, "钢琴"),
    ("jazz",             5, "爵士"),
    ("classical guitar", 4, "吉他"),
    ("ambient",          3, "环境音"),
    ("classical",        3, "古典"),
]

# 体积过滤：避开 < 200KB 的占位文件 + 避开 > 15MB 的长合集
PICK_MIN_SIZE = 200_000
PICK_MAX_SIZE = 15_000_000


def collect_recommendations(
        per_category_limit: int = 5,
        progress_cb: Optional[Callable[[str, int, int], None]] = None,
) -> list[TrackHit]:
    """按 DEFAULT_PICKS 收集 ~20 首推荐曲目。

    progress_cb(category, picked_in_category, total_picked) 每搜完一类回调一次。
    """
    out: list[TrackHit] = []
    seen_idents: set[str] = set()
    for kw, want, _label in DEFAULT_PICKS:
        target = min(want, per_category_limit) if per_category_limit > 0 else want
        # 多搜几个候选，挑能 resolve 出 mp3 + 体积合适的
        hits = search(kw, limit=target * 4)
        picked = 0
        for h in hits:
            if picked >= target: break
            if h.identifier in seen_idents: continue
            r = resolve_mp3(h)
            if not r or not r.file_name: continue
            if r.file_size and (r.file_size < PICK_MIN_SIZE or r.file_size > PICK_MAX_SIZE):
                continue
            out.append(r)
            seen_idents.add(r.identifier)
            picked += 1
        if progress_cb:
            try: progress_cb(kw, picked, len(out))
            except Exception: pass
    return out


def _safe_filename(name: str, fallback: str = "track") -> str:
    name = _FILENAME_BAD.sub("_", name).strip().strip(".")
    if not name:
        name = fallback
    if len(name) > 80:
        name = name[:80]
    return name


def download(hit: TrackHit, dest_folder: Path,
              progress_cb: Optional[Callable[[int, int], None]] = None,
              ) -> Optional[Path]:
    """下载到 dest_folder/<artist - title>.mp3，返回最终路径；失败返回 None。

    progress_cb(downloaded, total) 在下载进行时回调（chunk 64KB 一次）。
    """
    if not hit.file_name:
        return None
    dest_folder.mkdir(parents=True, exist_ok=True)
    fname_stem = _safe_filename(
        f"{hit.display_artist} - {hit.display_title}".strip(" -"))
    target = dest_folder / f"{fname_stem}.mp3"
    if target.exists():
        return target

    url = DOWNLOAD_URL.format(
        identifier=hit.identifier,
        file=urllib.parse.quote(hit.file_name))
    try:
        with requests.get(url, headers={"User-Agent": USER_AGENT},
                           stream=True, timeout=30) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or hit.file_size or 0)
            tmp = target.with_suffix(".mp3.part")
            done = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
                        done += len(chunk)
                        if progress_cb:
                            try: progress_cb(done, total)
                            except Exception: pass
            tmp.rename(target)
        return target
    except Exception as e:
        logger.warning("archive download failed: %s", e)
        try: target.with_suffix(".mp3.part").unlink(missing_ok=True)
        except Exception: pass
        return None
