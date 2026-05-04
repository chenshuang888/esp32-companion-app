"""Windows SMTC 监听 + 媒体键模拟。

合并自 desktop_companion.py / media_publisher.py / providers/media_provider.py。
对外提供：
  SmtcMonitor    异步监听当前媒体会话变化
  send_media_key 触发 Windows 媒体键
"""

from __future__ import annotations

import asyncio
import ctypes
import logging
import sys
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 媒体键
# ---------------------------------------------------------------------------

VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP     = 0x0002

MEDIA_KEYS = {
    "prev":      VK_MEDIA_PREV_TRACK,
    "next":      VK_MEDIA_NEXT_TRACK,
    "playpause": VK_MEDIA_PLAY_PAUSE,
}


def send_media_key(name: str) -> None:
    if sys.platform != "win32":
        logger.warning("send_media_key skip: not windows")
        return
    vk = MEDIA_KEYS.get(name)
    if vk is None:
        logger.warning("send_media_key unknown: %s", name)
        return
    user32 = ctypes.windll.user32
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, 0)


# ---------------------------------------------------------------------------
# SMTC 监听
# ---------------------------------------------------------------------------

@dataclass
class MediaState:
    playing: bool = False
    title: str = ""
    artist: str = ""
    position_sec: int = -1
    duration_sec: int = -1


class SmtcMonitor:
    """订阅 GlobalSystemMediaTransportControlsSession，状态变化回调 on_change(state)。"""

    def __init__(self,
                  on_change: Callable[[MediaState], Awaitable[None]],
                  loop: asyncio.AbstractEventLoop) -> None:
        self._on_change = on_change
        self._loop = loop
        self._mgr = None
        self._session = None
        self._mgr_token: int | None = None
        self._session_tokens: list[tuple[object, str, int]] = []
        self._available = sys.platform == "win32"

    async def start(self) -> None:
        if not self._available:
            logger.warning("smtc unavailable: not windows")
            return
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as SessionManager,
            )
        except ImportError:
            logger.warning("winsdk import failed; smtc disabled")
            self._available = False
            return
        self._mgr = await SessionManager.request_async()
        self._mgr_token = self._mgr.add_current_session_changed(
            self._on_session_changed)
        await self._rebind_session()

    async def stop(self) -> None:
        self._unbind_session_events()
        if self._mgr is not None and self._mgr_token is not None:
            try:
                self._mgr.remove_current_session_changed(self._mgr_token)
            except Exception:
                pass
        self._mgr = None
        self._mgr_token = None

    async def fetch_state(self) -> MediaState:
        return await self._build_state(self._session)

    # internal

    def _unbind_session_events(self) -> None:
        for obj, event, token in self._session_tokens:
            try:
                getattr(obj, f"remove_{event}")(token)
            except Exception:
                pass
        self._session_tokens.clear()

    async def _rebind_session(self) -> None:
        self._unbind_session_events()
        self._session = self._mgr.get_current_session() if self._mgr else None
        if self._session is not None:
            for ev in ("media_properties_changed",
                       "playback_info_changed",
                       "timeline_properties_changed"):
                try:
                    add_fn = getattr(self._session, f"add_{ev}")
                    token = add_fn(self._on_any_changed)
                    self._session_tokens.append((self._session, ev, token))
                except Exception as e:
                    logger.warning("smtc subscribe %s failed: %s", ev, e)
        await self._emit_change()

    def _on_session_changed(self, *_):
        # COM 线程 → asyncio loop
        try:
            asyncio.run_coroutine_threadsafe(self._rebind_session(), self._loop)
        except Exception:
            pass

    def _on_any_changed(self, *_):
        try:
            asyncio.run_coroutine_threadsafe(self._emit_change(), self._loop)
        except Exception:
            pass

    async def _emit_change(self) -> None:
        try:
            state = await self._build_state(self._session)
            await self._on_change(state)
        except Exception:
            logger.exception("smtc on_change crashed")

    async def _build_state(self, session) -> MediaState:
        if session is None:
            return MediaState()
        try:
            from winsdk.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionPlaybackStatus as PS,
            )
        except ImportError:
            return MediaState()
        try:
            props = await session.try_get_media_properties_async()
        except Exception:
            return MediaState()
        info = session.get_playback_info()
        tl   = session.get_timeline_properties()
        playing = (info.playback_status == PS.PLAYING)
        position = self._td_seconds(getattr(tl, "position", None))
        duration = self._td_seconds(getattr(tl, "end_time", None))
        if duration == 0:
            duration = -1
        return MediaState(
            playing=playing,
            title=getattr(props, "title", "") or "",
            artist=getattr(props, "artist", "") or "",
            position_sec=position,
            duration_sec=duration,
        )

    @staticmethod
    def _td_seconds(td) -> int:
        if td is None:
            return -1
        try:
            s = int(td.total_seconds())
        except Exception:
            return -1
        return s if s >= 0 else -1
