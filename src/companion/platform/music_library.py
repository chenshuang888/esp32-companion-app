"""platform.music_library —— 本地音乐文件夹管理（纯业务，无 UI）。

被 gui/pages/music.py 用。把"扫文件夹 / 加文件 / 删文件 / 解析文件名"这些
不依赖 tkinter 的逻辑从 GUI 抽离，便于单测，也便于未来 plugins/ 复用同套规则。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Iterable

SUPPORTED_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".m4a"}
MAX_TRACKS = 50  # 手表端歌单上限


def default_folder() -> Path:
    """默认音乐目录：~/Music/Watch。"""
    return Path(os.path.expanduser("~")) / "Music" / "Watch"


def ensure_folder(p: Path) -> Path:
    """确保目录存在并返回。"""
    p.mkdir(parents=True, exist_ok=True)
    return p


def scan(folder: Path) -> list[Path]:
    """扫描文件夹下所有支持的音频文件，按文件名排序。
    目录不存在或无权访问时返回空列表，不抛异常。"""
    try:
        ensure_folder(folder)
    except Exception:
        return []
    return sorted(
        [f for f in folder.iterdir()
         if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS],
        key=lambda x: x.name.lower(),
    )


def add_files(src_paths: Iterable[str | Path], dst: Path) -> tuple[int, int]:
    """把若干源文件拷贝到 dst 目录。
    返回 (ok, skipped) —— 后缀不支持 / 已存在 / 异常都计入 skipped。
    需要 dst 目录已存在。"""
    ok, skipped = 0, 0
    for src_str in src_paths:
        src = Path(src_str)
        if src.suffix.lower() not in SUPPORTED_EXTS:
            skipped += 1
            continue
        target = dst / src.name
        if target.exists():
            skipped += 1
            continue
        try:
            shutil.copy2(src, target)
            ok += 1
        except Exception:
            skipped += 1
    return ok, skipped


def delete_file(path: Path) -> None:
    """删除单个音乐文件。失败抛异常。"""
    path.unlink()


def parse_track_meta(path: Path) -> tuple[str, str]:
    """从文件名解析 (title, sub)。
    约定：'Artist - Title.ext' → ('Title', 'Artist')；否则 ('stem', 后缀大写)。"""
    stem = path.stem
    if " - " in stem:
        artist, _, title = stem.partition(" - ")
        return title.strip(), artist.strip()
    return stem, path.suffix.upper().lstrip(".")
