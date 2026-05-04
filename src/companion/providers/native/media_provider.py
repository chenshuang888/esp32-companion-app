"""media_provider —— 本地音乐文件夹（just_playback）+ SMTC 兼容 + 歌单 + 远程点歌。

核心逻辑：
  - 启动时扫 music_folder（默认 ~/Music/Watch）→ 本地歌单 list[{path, title, artist}]
  - 推歌单到手表（流式 BEGIN → ITEM × N → END）
  - just_playback 加载当前曲目；维护 current_index 自己实现 prev/next
  - 1Hz 轮询播放状态，状态变化时 pack_media 推回 NOWPLAYING；
    曲目结束自动 next（loop）
  - 监听 NOTIFY 8a5c000d：
      首字节 0x01 = BUTTON      → prev / play_pause / next
      首字节 0x02 = PLAY_TRACK  → play_index(idx)
      （本地无歌单时 BUTTON 回落到模拟系统媒体键，保留 SMTC 兜底）

依赖：just_playback（纯 pip，零外部软件依赖；底层 miniaudio）
"""

from __future__ import annotations

import asyncio
import logging
import os
import struct
import sys
from pathlib import Path
from typing import Optional

from ...constants import (
    MEDIA_BTN_STRUCT, MEDIA_BUTTON_CHAR_UUID, MEDIA_CHAR_UUID,
    MEDIA_NOTIFY_BUTTON, MEDIA_NOTIFY_PLAY_TRACK,
    MEDIA_PERIODIC_RESYNC_S, MEDIA_PLAYLIST_MAX_ITEMS,
    MEDIA_PLAYLIST_PUSH_GAP_S, MEDIA_PLAY_TRACK_STRUCT,
)
from ...platform.packers import (
    EMPTY_MEDIA_PAYLOAD, pack_media,
    pack_playlist_begin, pack_playlist_item, pack_playlist_end,
)
from ...platform.smtc import MediaState, SmtcMonitor, send_media_key
from ..base import Provider, ProviderContext

logger = logging.getLogger(__name__)

MEDIA_BTN_NAMES = {0: "prev", 1: "playpause", 2: "next"}
SUPPORTED_EXTS = {".mp3", ".flac", ".wav", ".ogg", ".m4a"}


def _scan_folder(folder: Path) -> list[dict]:
    """扫描音乐文件夹，返回 [{path, title, artist}]，按文件名排序。

    title/artist 解析规则：
      文件名形如 "Artist - Title.mp3" → artist + title 分开
      否则     "Title.mp3"            → title = stem, artist = ""
    （读 ID3 tag 太重，依赖 mutagen，这里偷懒用文件名约定）
    """
    if not folder.exists() or not folder.is_dir():
        return []
    items: list[dict] = []
    for p in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED_EXTS:
            continue
        stem = p.stem
        if " - " in stem:
            artist, _, title = stem.partition(" - ")
            artist, title = artist.strip(), title.strip()
        else:
            artist, title = "", stem.strip()
        items.append({"path": str(p), "title": title or p.name, "artist": artist})
        if len(items) >= MEDIA_PLAYLIST_MAX_ITEMS:
            break
    return items


class _PlaybackController:
    """just_playback 包装：单文件播放 + 自维护 current_index + prev/next。

    从 asyncio 线程调用；just_playback 内部用线程，对外 API 是同步阻塞。
    """

    def __init__(self) -> None:
        self._pb = None
        self._tracks: list[dict] = []
        self._idx: int = -1
        self._available = False

    def is_available(self) -> bool:
        return self._available and self._pb is not None

    def load_tracks(self, tracks: list[dict]) -> bool:
        try:
            from just_playback import Playback  # type: ignore
        except ImportError:
            logger.warning("just_playback not installed; pip install just_playback")
            return False
        try:
            if self._pb is None:
                self._pb = Playback()
            self._tracks = list(tracks)
            self._idx = -1
            self._available = True
            return True
        except Exception:
            logger.exception("load_tracks failed")
            return False

    def current_index(self) -> int:
        return self._idx

    def current_track(self) -> Optional[dict]:
        if 0 <= self._idx < len(self._tracks):
            return self._tracks[self._idx]
        return None

    def play_index(self, index: int) -> bool:
        if not self.is_available(): return False
        if index < 0 or index >= len(self._tracks): return False
        try:
            self._pb.load_file(self._tracks[index]["path"])
            self._pb.play()
            self._idx = index
            return True
        except Exception:
            logger.exception("play_index failed")
            return False

    def toggle_play_pause(self) -> None:
        if not self.is_available(): return
        try:
            if self._idx < 0:
                self.play_index(0)
                return
            if self._pb.playing:
                self._pb.pause()
            else:
                self._pb.resume()
        except Exception:
            logger.exception("toggle_play_pause failed")

    def next(self) -> None:
        if not self.is_available() or not self._tracks: return
        nxt = (self._idx + 1) % len(self._tracks) if self._idx >= 0 else 0
        self.play_index(nxt)

    def prev(self) -> None:
        if not self.is_available() or not self._tracks: return
        prv = (self._idx - 1) % len(self._tracks) if self._idx > 0 else len(self._tracks) - 1
        self.play_index(prv)

    def query_state(self) -> Optional[MediaState]:
        """返回当前播放状态；ended=True 时调用方自行 next()"""
        if not self.is_available(): return None
        track = self.current_track()
        title  = track["title"]  if track else ""
        artist = track["artist"] if track else ""
        try:
            playing  = bool(self._pb.playing)
            position = int(self._pb.curr_pos) if track else -1
            duration = int(self._pb.duration) if track else -1
            if duration <= 0: duration = -1
            if position < 0: position = -1
            return MediaState(playing=playing, title=title, artist=artist,
                                position_sec=position, duration_sec=duration)
        except Exception:
            return None

    def is_track_ended(self) -> bool:
        """just_playback 没有显式 end 事件 —— 用 active 反向判断。
        条件：曾经播过（idx >= 0）+ 当前 active=False + 不是用户暂停。"""
        if not self.is_available() or self._idx < 0: return False
        try:
            return (not self._pb.active) and (not self._pb.paused)
        except Exception:
            return False


class MediaProvider(Provider):
    name = "media"

    def __init__(self, music_folder: Optional[str] = None) -> None:
        self._music_folder = Path(music_folder).expanduser() if music_folder else None
        self._unsubs: list = []
        self._smtc: SmtcMonitor | None = None
        self._last_payload: bytes | None = None
        self._last_btn_seq: int | None = None
        self._last_play_seq: int | None = None
        self._resync_task: asyncio.Task | None = None
        self._poll_task: asyncio.Task | None = None
        self._push_lock = asyncio.Lock()

        self._vlc = _PlaybackController()
        self._tracks: list[dict] = []
        self._playlist_version = 0

    def subscriptions(self) -> list[str]:
        return [MEDIA_BUTTON_CHAR_UUID]

    # -------- 启动 / 停止 -------------------------------------------------

    async def on_start(self, ctx: ProviderContext) -> None:
        # NOTIFY 监听
        def _on_notify(payload: object) -> None:
            data = payload if isinstance(payload, (bytes, bytearray)) else b""
            self._handle_notify(ctx, bytes(data))
        self._unsubs.append(
            ctx.bus.on(f"notify:{MEDIA_BUTTON_CHAR_UUID.lower()}", _on_notify))

        # GUI 触发的事件
        loop = asyncio.get_running_loop()
        def _on_rescan(payload: object) -> None:
            asyncio.run_coroutine_threadsafe(
                self._rescan_and_push(ctx, payload), loop)
        self._unsubs.append(ctx.bus.on("media:rescan", _on_rescan))

        def _on_set_folder(payload: object) -> None:
            if isinstance(payload, str) and payload:
                self._music_folder = Path(payload).expanduser()
                ctx.bus.emit("log", ("info", self.name,
                    f"music_folder set to {self._music_folder}"))
        self._unsubs.append(ctx.bus.on("media:set_folder", _on_set_folder))

        # 1) 加载本地歌单
        await self._load_local_playlist(ctx)

        # 2) SMTC（无本地歌单时仍跑，作为 NOWPLAYING 兜底）
        if sys.platform == "win32" and not self._tracks:
            async def _on_change(state: MediaState) -> None:
                await self._push_nowplaying(ctx, state)
            self._smtc = SmtcMonitor(_on_change, loop)
            try: await self._smtc.start()
            except Exception as e:
                ctx.bus.emit("log", ("warn", self.name, f"smtc start: {e}"))

        # 3) 兜底：把空 NOWPLAYING 推一次让屏幕至少能显示状态
        if not self._tracks and not self._smtc:
            try: await ctx.write(MEDIA_CHAR_UUID, EMPTY_MEDIA_PAYLOAD, response=True)
            except Exception: pass

        self._resync_task = asyncio.create_task(self._resync_loop(ctx))
        if self._tracks:
            self._poll_task = asyncio.create_task(self._vlc_poll_loop(ctx))

    async def on_stop(self, ctx: ProviderContext) -> None:
        for u in self._unsubs:
            try: u()
            except Exception: pass
        self._unsubs.clear()
        for t in (self._resync_task, self._poll_task):
            if t:
                t.cancel()
                try: await t
                except (asyncio.CancelledError, Exception): pass
        self._resync_task = self._poll_task = None
        if self._smtc:
            try: await self._smtc.stop()
            except Exception: pass
            self._smtc = None

    # -------- 本地歌单 ----------------------------------------------------

    async def _load_local_playlist(self, ctx: ProviderContext) -> None:
        if self._music_folder is None:
            ctx.bus.emit("log", ("info", self.name, "music_folder not configured"))
            return
        tracks = _scan_folder(self._music_folder)
        if not tracks:
            ctx.bus.emit("log", ("info", self.name,
                f"music folder empty or missing: {self._music_folder}"))
            return
        ok = self._vlc.load_tracks(tracks)
        if not ok:
            ctx.bus.emit("log", ("warn", self.name,
                "just_playback unavailable; pip install just_playback"))
            return
        self._tracks = tracks
        self._playlist_version = (self._playlist_version + 1) & 0xFFFF
        ctx.bus.emit("log", ("info", self.name,
            f"loaded {len(tracks)} tracks from {self._music_folder}"))
        await self._push_playlist(ctx)

    async def _rescan_and_push(self, ctx: ProviderContext, payload: object) -> None:
        """GUI 触发：重新扫描 music_folder 并推歌单。
        payload 可选包含 future（concurrent.futures.Future），完成时通过 set_result/exception 回报。
        """
        fut = None
        if isinstance(payload, dict):
            fut = payload.get("future")
        try:
            await self._load_local_playlist(ctx)
            # 启动 vlc poll loop（首次扫到歌时）
            if self._tracks and self._poll_task is None:
                self._poll_task = asyncio.create_task(self._vlc_poll_loop(ctx))
            # 给 GUI 一份当前歌单快照
            ctx.bus.emit("media:tracks", list(self._tracks))
            if fut is not None and not fut.done():
                fut.set_result(len(self._tracks))
        except Exception as e:
            ctx.bus.emit("log", ("warn", self.name, f"rescan: {e}"))
            if fut is not None and not fut.done():
                fut.set_exception(e)

    def get_music_folder(self) -> Optional[Path]:
        return self._music_folder

    def get_tracks_snapshot(self) -> list[dict]:
        return list(self._tracks)

    async def _push_playlist(self, ctx: ProviderContext) -> None:
        """流式推送 BEGIN → ITEM × N → END。"""
        if not self._tracks: return
        async with self._push_lock:
            try:
                await ctx.write(MEDIA_CHAR_UUID,
                                pack_playlist_begin(len(self._tracks),
                                                     self._playlist_version),
                                response=True)
                for i, t in enumerate(self._tracks):
                    await ctx.write(MEDIA_CHAR_UUID,
                                    pack_playlist_item(i, t["title"], t["artist"]),
                                    response=True)
                    await asyncio.sleep(MEDIA_PLAYLIST_PUSH_GAP_S)
                await ctx.write(MEDIA_CHAR_UUID, pack_playlist_end(), response=True)
                ctx.bus.emit("log", ("info", self.name,
                    f"playlist pushed: {len(self._tracks)} items v{self._playlist_version}"))
            except Exception as e:
                ctx.bus.emit("log", ("warn", self.name, f"playlist push: {e}"))

    # -------- 播放状态轮询 → 推 NOWPLAYING + 自动 next ---------------------

    async def _vlc_poll_loop(self, ctx: ProviderContext) -> None:
        while True:
            try:
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                return
            if ctx.quiesce_during_upload(): continue
            # 曲目结束 → 自动下一首（loop）
            if self._vlc.is_track_ended():
                ctx.bus.emit("log", ("info", self.name, "track ended, auto next"))
                self._vlc.next()
            state = self._vlc.query_state()
            if state is None: continue
            await self._push_nowplaying(ctx, state)

    # -------- 通用 NOWPLAYING 推送 ----------------------------------------

    async def _push_nowplaying(self, ctx: ProviderContext, state: MediaState) -> None:
        if ctx.quiesce_during_upload(): return
        async with self._push_lock:
            data = pack_media(state.playing, state.position_sec, state.duration_sec,
                                state.title, state.artist)
            if data == self._last_payload: return
            try:
                await ctx.write(MEDIA_CHAR_UUID, data, response=True)
                self._last_payload = data
                ctx.bus.emit("log", ("info", self.name,
                    f"{'PLAY' if state.playing else 'PAUSE'} \"{state.title}\""))
            except Exception as e:
                ctx.bus.emit("log", ("warn", self.name, f"nowplaying: {e}"))

    async def _resync_loop(self, ctx: ProviderContext) -> None:
        while True:
            try: await asyncio.sleep(MEDIA_PERIODIC_RESYNC_S)
            except asyncio.CancelledError: return
            if ctx.quiesce_during_upload(): continue
            # SMTC 兜底重发
            if self._smtc and not self._tracks:
                try:
                    state = await self._smtc.fetch_state()
                    await self._push_nowplaying(ctx, state)
                except Exception as e:
                    ctx.bus.emit("log", ("warn", self.name, f"resync: {e}"))

    # -------- NOTIFY 收包 --------------------------------------------------

    def _handle_notify(self, ctx: ProviderContext, data: bytes) -> None:
        if len(data) < 1: return
        type_tag = data[0]
        body = data[1:]
        if type_tag == MEDIA_NOTIFY_BUTTON:
            self._handle_button(ctx, body)
        elif type_tag == MEDIA_NOTIFY_PLAY_TRACK:
            self._handle_play_track(ctx, body)
        else:
            ctx.bus.emit("log", ("warn", self.name,
                f"unknown notify type=0x{type_tag:02x}"))

    def _handle_button(self, ctx: ProviderContext, body: bytes) -> None:
        if len(body) != struct.calcsize(MEDIA_BTN_STRUCT): return
        btn_id, action, seq = struct.unpack(MEDIA_BTN_STRUCT, body)
        if action != 0: return
        if seq == self._last_btn_seq: return
        self._last_btn_seq = seq
        name = MEDIA_BTN_NAMES.get(btn_id)
        if name is None: return
        ctx.bus.emit("log", ("info", self.name, f"btn {name} seq={seq}"))
        # 优先操作本地 vlc，没有歌单则回落到模拟系统媒体键
        if self._vlc.is_available() and self._tracks:
            if   name == "prev":      self._vlc.prev()
            elif name == "next":      self._vlc.next()
            elif name == "playpause": self._vlc.toggle_play_pause()
        else:
            try: send_media_key(name)
            except Exception as e:
                ctx.bus.emit("log", ("warn", self.name, f"key: {e}"))

    def _handle_play_track(self, ctx: ProviderContext, body: bytes) -> None:
        if len(body) != struct.calcsize(MEDIA_PLAY_TRACK_STRUCT): return
        idx, seq = struct.unpack(MEDIA_PLAY_TRACK_STRUCT, body)
        if seq == self._last_play_seq: return
        self._last_play_seq = seq
        ctx.bus.emit("log", ("info", self.name, f"play_track idx={idx} seq={seq}"))
        if not self._vlc.play_index(idx):
            ctx.bus.emit("log", ("warn", self.name,
                f"play_track idx={idx} ignored (no vlc / out of range)"))
