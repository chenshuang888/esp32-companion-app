"""项目统一深紫青绿配色 + DPI awareness。"""

from __future__ import annotations

import sys

CTK_APPEARANCE = "dark"
CTK_THEME      = "dark-blue"

# 来自 ble_time_sync / dynapp_push_gui 配色（深紫主调）
COLOR_BG       = "#14101F"
COLOR_PANEL    = "#231C3A"
COLOR_PANEL_HI = "#2F2752"
COLOR_SIDEBAR  = "#100C1A"
COLOR_ACCENT   = "#06B6D4"   # 青绿
COLOR_ACCENT2  = "#9333EA"   # 紫
COLOR_TEXT     = "#F1ECFF"
COLOR_MUTED    = "#9B94B5"
COLOR_OK       = "#10B981"
COLOR_ERR      = "#EF4444"
COLOR_WARN     = "#F59E0B"
COLOR_OFF      = "#4A4368"

WINDOW_W = 880
WINDOW_H = 560
SIDEBAR_W = 200


def enable_windows_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    import ctypes
    for fn in (
        lambda: ctypes.windll.shcore.SetProcessDpiAwareness(2),
        lambda: ctypes.windll.shcore.SetProcessDpiAwareness(1),
        lambda: ctypes.windll.user32.SetProcessDPIAware(),
    ):
        try:
            fn(); return
        except Exception:
            continue
