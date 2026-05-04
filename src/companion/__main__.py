"""ESP32 桌面助手（用户精简版）入口。

打包后双击 .exe 直接进 GUI，单进程托盘 + 主窗口。
"""

from __future__ import annotations

import logging
import logging.handlers
import sys

from . import app_paths, branding, config as cfg
from .bus import EventBus
from .core import Companion
from .plugin_manager import PluginManager
from .providers.dynapp.bridge_provider import BridgeProvider
from .providers.dynapp.upload_provider import UploadProvider
from .providers.native.media_provider  import MediaProvider
from .providers.native.notify_provider import NotifyProvider
from .providers.native.system_provider import SystemProvider
from .providers.native.time_provider   import TimeProvider
from .providers.native.weather_provider import WeatherProvider
from .runner import AsyncRunner


def _setup_logging() -> None:
    log_path = app_paths.log_file()
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)5s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    # 控制台（开发时跑源码模式还能看；exe 模式 console=False 时此 handler 输出会被丢）
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(sh)


def _build_companion(bus: EventBus, cfg_data: dict) -> tuple[Companion, PluginManager]:
    comp = Companion(
        device_name=cfg_data.get("device_name", branding.DEFAULT_DEVICE_NAME),
        bus=bus,
        device_address=cfg_data.get("device_address"),
    )

    def _tx(to_app: str, mtype: str, body) -> None:
        bus.emit("bridge:tx", (to_app, mtype, body))
    pm = PluginManager(bus, tx_func=_tx, is_connected=lambda: comp.is_connected)
    n = pm.discover_and_load()
    logging.getLogger("plugin_manager").info("loaded %d plugin(s)", n)

    bus.on("connect",    lambda addr: pm.dispatch_connect(addr))
    bus.on("disconnect", lambda _:    pm.dispatch_disconnect())

    enabled = cfg_data.get("providers", {})
    if enabled.get("time", True):    comp.register(TimeProvider())
    if enabled.get("weather", True): comp.register(WeatherProvider())
    if enabled.get("notify", True):  comp.register(NotifyProvider())
    if enabled.get("system", True):  comp.register(SystemProvider())
    if enabled.get("media", True):
        comp.register(MediaProvider(music_folder=cfg_data.get("music_folder")))
    if enabled.get("bridge", True):  comp.register(BridgeProvider(plugin_manager=pm))
    if enabled.get("upload", True):  comp.register(UploadProvider())
    return comp, pm


def _run_gui(bus: EventBus, runner: AsyncRunner, cfg_data: dict) -> int:
    try:
        from .gui.app import CompanionApp
    except ImportError as e:
        print(f"GUI 依赖缺失: {e}\n请重新安装本程序。", file=sys.stderr)
        return 2
    from .tray import Tray

    comp, pm = _build_companion(bus, cfg_data)
    fut = runner.submit(comp.run())

    quit_event = {"called": False}

    def _quit_all() -> None:
        if quit_event["called"]:
            return
        quit_event["called"] = True
        comp.stop()
        try:
            fut.result(timeout=8.0)
        except Exception:
            pass
        try:
            pm.unload_all()
        except Exception:
            pass
        try:
            app.quit_app()
        except Exception:
            pass
        runner.stop()

    def _on_quit_req(reason: str) -> None:
        if reason == "hide" and tray_started:
            return
        _quit_all()

    app = CompanionApp(bus=bus, runner=runner, cfg_data=cfg_data,
                        plugin_manager=pm,
                        on_quit_request=_on_quit_req)
    tray = Tray(on_show=lambda: app.root.after(0, app.show_window),
                 on_quit=lambda: app.root.after(0, _quit_all))
    tray_started = tray.start()

    try:
        app.mainloop()
    finally:
        if not quit_event["called"]:
            _quit_all()
        tray.stop()
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    cfg_data = cfg.load()

    bus = EventBus()
    runner = AsyncRunner()
    runner.start()
    bus.set_loop(runner.loop)

    try:
        return _run_gui(bus, runner, cfg_data)
    finally:
        cfg.save(cfg_data)


if __name__ == "__main__":
    sys.exit(main())
