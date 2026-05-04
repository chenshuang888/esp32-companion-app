"""struct.pack helpers + UTF-8 安全截断。

把散落在 desktop_companion/ble_time_sync/dynapp_companion 的 struct 打包统一到这里。
"""

from __future__ import annotations

import struct
import time as _time
from datetime import datetime
from typing import Tuple

from ..constants import (
    CTS_STRUCT,
    MEDIA_ARTIST_MAX_BYTES, MEDIA_PAYLOAD_STRUCT, MEDIA_TITLE_MAX_BYTES,
    MEDIA_MSG_NOWPLAYING, MEDIA_MSG_PLAYLIST_BEGIN, MEDIA_MSG_PLAYLIST_ITEM,
    MEDIA_MSG_PLAYLIST_END,
    MEDIA_PLAYLIST_BEGIN_STRUCT, MEDIA_PLAYLIST_ITEM_STRUCT,
    MEDIA_PLAYLIST_TITLE_BYTES, MEDIA_PLAYLIST_ARTIST_BYTES,
    NOTIFY_BODY_MAX, NOTIFY_PRIO_NORMAL, NOTIFY_STRUCT, NOTIFY_TITLE_MAX,
    SYSTEM_STRUCT,
    WC_CLEAR, WC_CLOUDY, WC_FOG, WC_OVERCAST, WC_RAIN, WC_SNOW, WC_THUNDER,
    WC_UNKNOWN, WEATHER_STRUCT,
)


# ---------------------------------------------------------------------------
# UTF-8 安全截断
# ---------------------------------------------------------------------------

def utf8_fixed(s: str, max_body: int, total: int) -> bytes:
    """UTF-8 编码；超长时回退到最近的合法字符边界，避免截半个多字节字符。
    然后右侧填 \0 到 total 字节。"""
    b = (s or "").encode("utf-8", errors="replace")
    if len(b) > max_body:
        b = b[:max_body]
        while b:
            try:
                b.decode("utf-8")
                break
            except UnicodeDecodeError:
                b = b[:-1]
    return b.ljust(total, b"\0")


# ---------------------------------------------------------------------------
# CTS Time
# ---------------------------------------------------------------------------

def pack_cts(now: datetime | None = None) -> bytes:
    if now is None:
        now = datetime.now()
    return struct.pack(
        CTS_STRUCT,
        now.year, now.month, now.day,
        now.hour, now.minute, now.second,
        now.isoweekday(),
        0, 0,
    )


# ---------------------------------------------------------------------------
# Weather (68 B)
# ---------------------------------------------------------------------------

WMO_TO_CODE = {
    0: WC_CLEAR,
    1: WC_CLOUDY, 2: WC_CLOUDY,
    3: WC_OVERCAST,
    45: WC_FOG, 48: WC_FOG,
    51: WC_RAIN, 53: WC_RAIN, 55: WC_RAIN, 56: WC_RAIN, 57: WC_RAIN,
    61: WC_RAIN, 63: WC_RAIN, 65: WC_RAIN, 66: WC_RAIN, 67: WC_RAIN,
    80: WC_RAIN, 81: WC_RAIN, 82: WC_RAIN,
    71: WC_SNOW, 73: WC_SNOW, 75: WC_SNOW, 77: WC_SNOW,
    85: WC_SNOW, 86: WC_SNOW,
    95: WC_THUNDER, 96: WC_THUNDER, 99: WC_THUNDER,
}

WMO_DESC = {
    0: "Clear",
    1: "Mainly Clear", 2: "Partly Cloudy", 3: "Overcast",
    45: "Fog", 48: "Fog",
    51: "Light Drizzle", 53: "Drizzle", 55: "Heavy Drizzle",
    56: "Freezing Drizzle", 57: "Freezing Drizzle",
    61: "Light Rain", 63: "Rain", 65: "Heavy Rain",
    66: "Freezing Rain", 67: "Freezing Rain",
    71: "Light Snow", 73: "Snow", 75: "Heavy Snow",
    77: "Snow Grains",
    80: "Light Showers", 81: "Showers", 82: "Heavy Showers",
    85: "Snow Showers", 86: "Heavy Snow Showers",
    95: "Thunderstorm", 96: "Thunder w/ Hail", 99: "Thunder w/ Hail",
}


def wmo_to_code(wmo: int) -> int:
    return WMO_TO_CODE.get(int(wmo), WC_UNKNOWN)


def pack_weather(temp_c: float, temp_min: float, temp_max: float,
                  humidity: int, wmo: int, city: str,
                  desc: str | None = None) -> bytes:
    if desc is None:
        desc = WMO_DESC.get(int(wmo), "Unknown")
    city_b = (city or "").encode("utf-8")[:23].ljust(24, b"\0")
    desc_b = desc.encode("utf-8")[:31].ljust(32, b"\0")
    return struct.pack(
        WEATHER_STRUCT,
        int(round(temp_c * 10)),
        int(round(temp_min * 10)),
        int(round(temp_max * 10)),
        max(0, min(100, int(humidity))),
        wmo_to_code(wmo),
        int(_time.time()),
        city_b, desc_b,
    )


# ---------------------------------------------------------------------------
# Notify (136 B)
# ---------------------------------------------------------------------------

def pack_notify(title: str, body: str,
                 category: int = 0, priority: int = NOTIFY_PRIO_NORMAL,
                 timestamp: int | None = None) -> bytes:
    if timestamp is None:
        timestamp = int(_time.time())
    title_b = utf8_fixed(title, NOTIFY_TITLE_MAX - 1, NOTIFY_TITLE_MAX)
    body_b  = utf8_fixed(body,  NOTIFY_BODY_MAX  - 1, NOTIFY_BODY_MAX)
    return struct.pack(NOTIFY_STRUCT,
                       int(timestamp), int(category), int(priority),
                       title_b, body_b)


# ---------------------------------------------------------------------------
# System (16 B)
# ---------------------------------------------------------------------------

def pack_system(cpu: int, mem: int, disk: int,
                 bat: int, charging: int, cpu_temp_x10: int,
                 uptime: int, down_kbps: int, up_kbps: int) -> bytes:
    return struct.pack(
        SYSTEM_STRUCT,
        max(0, min(100, int(cpu))),
        max(0, min(100, int(mem))),
        max(0, min(100, int(disk))),
        int(bat) & 0xFF, int(charging) & 0xFF, 0,
        int(cpu_temp_x10),
        max(0, min(0xFFFFFFFF, int(uptime))),
        max(0, min(0xFFFF, int(down_kbps))),
        max(0, min(0xFFFF, int(up_kbps))),
    )


# ---------------------------------------------------------------------------
# Media (92 B)
# ---------------------------------------------------------------------------

EMPTY_MEDIA_PAYLOAD = bytes([MEDIA_MSG_NOWPLAYING]) + struct.pack(
    MEDIA_PAYLOAD_STRUCT,
    0, 0, -1, -1, 0, 0,
    b"".ljust(48, b"\0"),
    b"".ljust(32, b"\0"),
)


def pack_media(playing: bool, position_sec: int, duration_sec: int,
                title: str, artist: str,
                sample_ts: int | None = None) -> bytes:
    if sample_ts is None:
        sample_ts = int(_time.time())
    title_b  = utf8_fixed(title  or "", MEDIA_TITLE_MAX_BYTES,  48)
    artist_b = utf8_fixed(artist or "", MEDIA_ARTIST_MAX_BYTES, 32)
    body = struct.pack(
        MEDIA_PAYLOAD_STRUCT,
        1 if playing else 0, 0,
        max(-1, min(int(position_sec), 32767)),
        max(-1, min(int(duration_sec), 32767)),
        0, int(sample_ts),
        title_b, artist_b,
    )
    return bytes([MEDIA_MSG_NOWPLAYING]) + body


def pack_playlist_begin(total_count: int, version: int) -> bytes:
    body = struct.pack(MEDIA_PLAYLIST_BEGIN_STRUCT,
                        total_count & 0xFFFF, version & 0xFFFF)
    return bytes([MEDIA_MSG_PLAYLIST_BEGIN]) + body


def pack_playlist_item(index: int, title: str, artist: str) -> bytes:
    title_b  = utf8_fixed(title  or "", MEDIA_PLAYLIST_TITLE_BYTES,  40)
    artist_b = utf8_fixed(artist or "", MEDIA_PLAYLIST_ARTIST_BYTES, 24)
    body = struct.pack(MEDIA_PLAYLIST_ITEM_STRUCT,
                        index & 0xFFFF, title_b, artist_b)
    return bytes([MEDIA_MSG_PLAYLIST_ITEM]) + body


def pack_playlist_end() -> bytes:
    return bytes([MEDIA_MSG_PLAYLIST_END])
