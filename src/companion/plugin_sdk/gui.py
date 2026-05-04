"""plugin_sdk.gui —— GUI 资源 SDK 门面。

插件写 make_gui_page() 时通过本模块访问主题色 / 通用组件，不要直接
from companion.gui.theme / companion.gui.widgets —— 那是主程序内部路径。

使用例::

    from companion.plugin_sdk.gui import theme, widgets

    class MyPage(ctk.CTkFrame):
        def __init__(self, master, app):
            super().__init__(master, fg_color=theme.COLOR_BG)
            card = widgets.Card(self)
"""

from __future__ import annotations

from ..gui import theme, widgets

__all__ = ["theme", "widgets"]
