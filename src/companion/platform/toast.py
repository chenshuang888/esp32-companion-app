"""Windows Toast 通知中心轮询。

合并自 desktop_companion.ToastPublisher。对外提供：
  ToastWatcher  从 UserNotificationListener 获取增量 toast，按白名单过滤后回调
  TOAST_APP_WHITELIST  支持的 app 名 → (category, std_name)
"""

from __future__ import annotations

import asyncio
import collections
import logging
import sys
from typing import Awaitable, Callable

from ..constants import (
    NOTIFY_CAT_MESSAGE, NOTIFY_CAT_SOCIAL,
)

logger = logging.getLogger(__name__)


TOAST_APP_WHITELIST: dict[str, tuple[int, str]] = {
    "微信":            (NOTIFY_CAT_MESSAGE, "WeChat"),
    "WeChat":          (NOTIFY_CAT_MESSAGE, "WeChat"),
    "Weixin":          (NOTIFY_CAT_MESSAGE, "WeChat"),
    "QQ":              (NOTIFY_CAT_SOCIAL,  "QQ"),
    "腾讯QQ":          (NOTIFY_CAT_SOCIAL,  "QQ"),
    "Tencent QQ":      (NOTIFY_CAT_SOCIAL,  "QQ"),
    "TIM":             (NOTIFY_CAT_SOCIAL,  "TIM"),
    "Microsoft Teams": (NOTIFY_CAT_MESSAGE, "Teams"),
    "Teams":           (NOTIFY_CAT_MESSAGE, "Teams"),
}

TOAST_DEDUP_WINDOW    = 50
TOAST_POLL_INTERVAL_S = 2.0


def _extract_text(notif) -> tuple[str, str]:
    try:
        visual = notif.notification.visual
    except Exception:
        return "", ""
    if visual is None:
        return "", ""
    binding = None
    try:
        binding = visual.get_binding("ToastGeneric")
    except Exception:
        binding = None
    if binding is None:
        try:
            for b in visual.bindings:
                binding = b
                break
        except Exception:
            return "", ""
    if binding is None:
        return "", ""
    try:
        texts = list(binding.get_text_elements())
    except Exception:
        return "", ""
    lines: list[str] = []
    for t in texts:
        try:
            s = t.text or ""
        except Exception:
            s = ""
        if s:
            lines.append(s)
    if not lines:
        return "", ""
    return lines[0], "\n".join(lines[1:]) if len(lines) > 1 else ""


class ToastWatcher:
    """轮询 Windows 通知中心，按白名单回调 on_toast(std_name, category, title, body)。"""

    def __init__(self,
                  on_toast: Callable[[str, int, str, str], Awaitable[None]]) -> None:
        self._on_toast = on_toast
        self._listener = None
        self._seen_ids: collections.deque[int] = collections.deque(
            maxlen=TOAST_DEDUP_WINDOW)
        self._task: asyncio.Task | None = None
        self._first_scan = True
        self._enabled = False

    async def start(self) -> None:
        if sys.platform != "win32":
            logger.warning("toast unavailable: not windows")
            return
        try:
            from winsdk.windows.ui.notifications.management import (
                UserNotificationListener,
                UserNotificationListenerAccessStatus,
            )
        except ImportError:
            logger.warning("winsdk missing; toast disabled")
            return
        try:
            self._listener = UserNotificationListener.current
        except Exception as e:
            logger.warning("toast listener: %s", e)
            return
        try:
            status = await self._listener.request_access_async()
        except Exception as e:
            logger.warning("toast permission: %s", e)
            return
        if status != UserNotificationListenerAccessStatus.ALLOWED:
            logger.warning("toast permission denied (%s)", status)
            return
        self._enabled = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("toast watcher started, poll=%.1fs", TOAST_POLL_INTERVAL_S)

    async def stop(self) -> None:
        self._enabled = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        self._listener = None

    async def _poll_loop(self) -> None:
        while self._enabled:
            try:
                await self._scan_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("toast scan failed")
            try:
                await asyncio.sleep(TOAST_POLL_INTERVAL_S)
            except asyncio.CancelledError:
                raise

    async def _scan_once(self) -> None:
        if self._listener is None:
            return
        try:
            from winsdk.windows.ui.notifications import NotificationKinds
            toasts = await self._listener.get_notifications_async(
                NotificationKinds.TOAST)
        except Exception as e:
            logger.warning("get_notifications: %s", e)
            return

        new_entries: list[tuple[int, object]] = []
        for notif in toasts:
            try:
                nid = int(notif.id)
            except Exception:
                continue
            if nid in self._seen_ids:
                continue
            new_entries.append((nid, notif))

        if self._first_scan:
            for nid, _ in new_entries:
                self._seen_ids.append(nid)
            self._first_scan = False
            return

        for nid, notif in new_entries:
            self._seen_ids.append(nid)
            try:
                app_name = notif.app_info.display_info.display_name or ""
            except Exception:
                app_name = ""
            hit = TOAST_APP_WHITELIST.get(app_name)
            if hit is None:
                continue
            category, std_name = hit
            title, body = _extract_text(notif)
            if not title and not body:
                continue
            try:
                await self._on_toast(std_name, category, title, body)
            except Exception:
                logger.exception("toast callback crashed")
