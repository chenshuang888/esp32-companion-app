"""ip-api 定位 + open-meteo 天气拉取 + 进程级缓存。

合并自 desktop_companion.py / ble_time_sync.py / providers/weather_provider.py
三处实现，去重为唯一来源。
"""

from __future__ import annotations

import asyncio
import logging
import time as _time
from dataclasses import dataclass
from typing import Optional, Tuple

import requests

from ..constants import WEATHER_CACHE_TTL_S
from .packers import WMO_DESC

logger = logging.getLogger(__name__)


@dataclass
class WeatherSnapshot:
    temp_c: float
    temp_min: float
    temp_max: float
    humidity: int
    wmo: int
    city: str

    def desc(self) -> str:
        return WMO_DESC.get(self.wmo, "Unknown")


# 模块级缓存：避免反复进出天气页时打爆 open-meteo / ip-api 免费 API
_cache: Optional[Tuple[float, WeatherSnapshot]] = None
_location: Optional[Tuple[float, float, str]] = None


def _locate_by_ip_sync() -> Tuple[float, float, str]:
    r = requests.get("http://ip-api.com/json/", timeout=10)
    r.raise_for_status()
    j = r.json()
    if j.get("status") != "success":
        raise RuntimeError(f"ip-api: {j}")
    return float(j["lat"]), float(j["lon"]), j.get("city", "Unknown")


def _fetch_sync(lat: float, lon: float, city: str) -> WeatherSnapshot:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}"
        "&current=temperature_2m,relative_humidity_2m,weather_code"
        "&daily=temperature_2m_max,temperature_2m_min"
        "&timezone=auto&forecast_days=1"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    j = r.json()
    cur, daily = j["current"], j["daily"]
    return WeatherSnapshot(
        temp_c=float(cur["temperature_2m"]),
        temp_min=float(daily["temperature_2m_min"][0]),
        temp_max=float(daily["temperature_2m_max"][0]),
        humidity=int(cur["relative_humidity_2m"]),
        wmo=int(cur["weather_code"]),
        city=city,
    )


async def get_weather(force: bool = False) -> WeatherSnapshot:
    """带 10 分钟缓存的拉取。force=True 跳过缓存。requests 是阻塞的，
    用 asyncio.to_thread 避免阻塞事件循环。"""
    global _cache, _location
    now_ts = _time.time()
    if (not force) and _cache is not None and (now_ts - _cache[0]) < WEATHER_CACHE_TTL_S:
        return _cache[1]

    if _location is None:
        _location = await asyncio.to_thread(_locate_by_ip_sync)
        lat, lon, city = _location
        logger.info("weather: located %s (%.2f, %.2f)", city, lat, lon)
    lat, lon, city = _location
    snap = await asyncio.to_thread(_fetch_sync, lat, lon, city)
    _cache = (now_ts, snap)
    return snap
