"""plugin_sdk.platform —— 平台能力 SDK 门面。

插件作者通过本模块访问"对接外部能力"的 helper（HTTP / 平台 API / 二进制打包等），
不要直接 from companion.platform.* —— 那是主程序内部路径，可能在重构时变动。

本模块的稳定性等同于 plugin_sdk.Plugin 基类：除非确实必要，签名和导出名不变。
**仅暴露当前确实有插件需要**的能力；原生 provider 私有依赖的能力（如 smtc / toast /
packers）不在此处出现，等真有插件需要再加。

使用例::

    from companion.plugin_sdk.platform import geoip_weather
    info = geoip_weather.get_weather()
"""

from __future__ import annotations

# 重新导出（业务可见的稳定 API）
from ..platform import geoip_weather

__all__ = ["geoip_weather"]
