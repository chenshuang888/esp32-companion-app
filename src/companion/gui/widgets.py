"""gui/widgets.py —— 通用小部件。"""

from __future__ import annotations

import customtkinter as ctk

from .theme import COLOR_OFF, COLOR_OK, COLOR_PANEL, COLOR_TEXT


class StatusDot(ctk.CTkLabel):
    """一个 ● 灯 + 文字。"""

    def __init__(self, master, text: str = "", color: str = COLOR_OFF, **kw):
        super().__init__(master, text=f"●  {text}", text_color=color,
                          anchor="w", **kw)
        self._text = text

    def set(self, text: str | None = None, color: str | None = None) -> None:
        if text is not None:
            self._text = text
        if color is None:
            color = COLOR_OK
        self.configure(text=f"●  {self._text}", text_color=color)


class Card(ctk.CTkFrame):
    def __init__(self, master, **kw):
        super().__init__(master, fg_color=COLOR_PANEL, corner_radius=12, **kw)


class KV(ctk.CTkFrame):
    def __init__(self, master, key: str, value: str = "", **kw):
        super().__init__(master, fg_color="transparent", **kw)
        self.grid_columnconfigure(1, weight=1)
        self._k = ctk.CTkLabel(self, text=key, text_color="#9B94B5",
                                anchor="w")
        self._k.grid(row=0, column=0, sticky="w", padx=(8, 4), pady=2)
        self._v = ctk.CTkLabel(self, text=value, text_color=COLOR_TEXT,
                                anchor="w")
        self._v.grid(row=0, column=1, sticky="ew", padx=(4, 8), pady=2)

    def set_value(self, v: str) -> None:
        self._v.configure(text=v)
