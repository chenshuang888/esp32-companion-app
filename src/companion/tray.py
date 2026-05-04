"""pystray 系统托盘。无 pystray 时降级为不显示托盘（关窗 = 直接退）。"""

from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False


def _make_icon():
    img = Image.new("RGB", (64, 64), (20, 16, 31))
    d = ImageDraw.Draw(img)
    d.ellipse([16, 16, 48, 48], fill=(6, 182, 212))
    return img


class Tray:
    """托盘菜单：[Show] [Quit]"""

    def __init__(self, on_show: Callable[[], None],
                  on_quit: Callable[[], None]) -> None:
        self._on_show = on_show
        self._on_quit = on_quit
        self._icon = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        if not HAS_TRAY:
            logger.info("pystray missing; tray disabled")
            return False
        try:
            menu = pystray.Menu(
                pystray.MenuItem("Show",  lambda *_: self._on_show()),
                pystray.MenuItem("Quit",  lambda *_: self._do_quit()),
            )
            self._icon = pystray.Icon("companion", _make_icon(),
                                       "ESP32 Companion", menu)
            self._thread = threading.Thread(target=self._icon.run, daemon=True)
            self._thread.start()
            return True
        except Exception as e:
            logger.warning("tray start failed: %s", e)
            return False

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass

    def _do_quit(self) -> None:
        try:
            self._on_quit()
        finally:
            self.stop()
