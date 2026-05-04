"""上传协议的帧打包/拆包。

纯函数，不依赖 bleak / asyncio，可单元测试。

帧格式（小端）：
    rx (PC → ESP):
        [1B op][1B seq][2B payload_len][payload...]

        op 0x01 START   payload = path(31B,NUL pad) + total_len(4B) + crc32(4B) = 39B
                        path = "<app_id>/<filename>" 例 "alarm/main.js"
        op 0x02 CHUNK   payload = offset(4B) + data(...)
        op 0x03 END     payload = (空)
        op 0x10 DELETE  payload = app_id(15B,NUL pad) = 15B   （删整个 app 目录）
        op 0x11 LIST    payload = (空)

    status notify (ESP → PC):
        [1B op_echo][1B result][1B seq_echo][1B reserved][payload...]
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Optional

from .constants import (
    HEADER_LEN, MAX_CHUNK, NAME_LEN, PATH_LEN,
    OP_START, OP_CHUNK, OP_END, OP_DELETE, OP_LIST,
)


# =============================================================================
# helpers
# =============================================================================

def _pack_fixed(s: str, width: int, label: str) -> bytes:
    """编码字符串为 NUL-padded ASCII（width 字节）。"""
    if not s:
        raise ValueError(f"{label} must be non-empty")
    raw = s.encode("ascii")
    if len(raw) > width:
        raise ValueError(f"{label} too long: {len(raw)} > {width}")
    return raw + b"\x00" * (width - len(raw))


def _pack_app_id(name: str) -> bytes:
    return _pack_fixed(name, NAME_LEN, "app_id")


def _pack_path(path: str) -> bytes:
    """编码 "<app_id>/<filename>" 为 31B NUL-padded ASCII。"""
    if "/" not in path:
        raise ValueError(f"path must be '<app_id>/<filename>', got {path!r}")
    return _pack_fixed(path, PATH_LEN, "path")


def _build_frame(op: int, seq: int, payload: bytes) -> bytes:
    if not 0 <= seq <= 0xFF:
        raise ValueError(f"seq out of range: {seq}")
    if len(payload) > 0xFFFF:
        raise ValueError("payload too large")
    return struct.pack("<BBH", op, seq, len(payload)) + payload


# =============================================================================
# pack
# =============================================================================

def pack_start(path: str, total_len: int, crc32: int, seq: int) -> bytes:
    """path 形如 "alarm/main.js"。"""
    payload = _pack_path(path) + struct.pack("<II", total_len, crc32 & 0xFFFFFFFF)
    return _build_frame(OP_START, seq, payload)


def pack_chunk(offset: int, data: bytes, seq: int) -> bytes:
    if len(data) == 0:
        raise ValueError("chunk data must be non-empty")
    if len(data) > MAX_CHUNK:
        raise ValueError(f"chunk too large: {len(data)} > {MAX_CHUNK}")
    payload = struct.pack("<I", offset) + data
    return _build_frame(OP_CHUNK, seq, payload)


def pack_end(seq: int) -> bytes:
    return _build_frame(OP_END, seq, b"")


def pack_delete(app_id: str, seq: int) -> bytes:
    """删除整个 app 目录。"""
    return _build_frame(OP_DELETE, seq, _pack_app_id(app_id))


def pack_list(seq: int) -> bytes:
    return _build_frame(OP_LIST, seq, b"")


# =============================================================================
# parse
# =============================================================================

@dataclass
class StatusFrame:
    """ESP → PC 的 status 通知帧。

    Attributes:
        op:     op_echo（对应触发本次状态的请求）
        result: result code（见 constants.RESULT_*）
        seq:    seq_echo（用来匹配请求-响应）
        payload: 剩余字节，根据 op 解读
                  - CHUNK OK: 4B next_expected_offset (LE u32)
                  - LIST OK:  NUL 分隔的 app 名列表
                  - 其它:     空
    """
    op: int
    result: int
    seq: int
    payload: bytes

    @property
    def next_offset(self) -> Optional[int]:
        if len(self.payload) >= 4:
            return struct.unpack_from("<I", self.payload, 0)[0]
        return None

    @property
    def names(self) -> list[str]:
        """LIST 帧专用：拆 NUL 分隔列表。"""
        if not self.payload:
            return []
        # 末尾可能是 NUL，也可能不是；split 后过滤空串
        parts = self.payload.split(b"\x00")
        return [p.decode("ascii", errors="replace") for p in parts if p]


def parse_status(buf: bytes) -> StatusFrame:
    if len(buf) < 4:
        raise ValueError(f"status frame too short: {len(buf)}")
    op, result, seq, _reserved = struct.unpack_from("<BBBB", buf, 0)
    return StatusFrame(op=op, result=result, seq=seq, payload=bytes(buf[4:]))


# =============================================================================
# 文件切片辅助
# =============================================================================

def crc32_of(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def chunk_iter(data: bytes, chunk_size: int = MAX_CHUNK):
    """按 chunk_size 切块，yield (offset, slice)。"""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    off = 0
    n = len(data)
    while off < n:
        end = min(off + chunk_size, n)
        yield off, data[off:end]
        off = end
