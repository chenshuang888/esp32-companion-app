"""dynapp_uploader 协议常量。

跟固件 services/dynapp_upload_service.c + services/manager/dynapp_upload_manager.h
严格对齐。改这里时必须同步改固件。
"""

# ---- GATT ----
SVC_UUID    = "a3a40001-0000-4aef-b87e-4fa1e0c7e0f6"
RX_UUID     = "a3a40002-0000-4aef-b87e-4fa1e0c7e0f6"   # PC → ESP, WRITE
STATUS_UUID = "a3a40003-0000-4aef-b87e-4fa1e0c7e0f6"   # ESP → PC, READ + NOTIFY

# ---- 帧格式 ----
HEADER_LEN = 4          # [op][seq][len_lo][len_hi]
MAX_FRAME  = 200        # 与固件 MAX_PAYLOAD 一致
MAX_CHUNK  = MAX_FRAME - HEADER_LEN - 4   # 减去 header + chunk 内的 offset(4B)
NAME_LEN   = 15         # app_id 长度上限（DELETE 用）
PATH_LEN   = 31         # "<app_id>/<filename>" 长度上限（START 用）
FNAME_LEN  = 31         # filename 长度上限

MAX_SCRIPT_BYTES = 64 * 1024    # DYNAPP_SCRIPT_STORE_MAX_BYTES

# ---- op codes ----
OP_START   = 0x01
OP_CHUNK   = 0x02
OP_END     = 0x03
OP_DELETE  = 0x10
OP_LIST    = 0x11

OP_NAMES = {
    OP_START:  "START",
    OP_CHUNK:  "CHUNK",
    OP_END:    "END",
    OP_DELETE: "DELETE",
    OP_LIST:   "LIST",
}

# ---- result codes（固件 upload_result_t）----
RESULT_OK            = 0
RESULT_BAD_FRAME     = 1
RESULT_NO_SESSION    = 2
RESULT_TOO_LARGE     = 3
RESULT_CRC_MISMATCH  = 4
RESULT_FS_ERROR      = 5
RESULT_BUSY          = 6

RESULT_NAMES = {
    RESULT_OK:           "OK",
    RESULT_BAD_FRAME:    "BAD_FRAME",
    RESULT_NO_SESSION:   "NO_SESSION",
    RESULT_TOO_LARGE:    "TOO_LARGE",
    RESULT_CRC_MISMATCH: "CRC_MISMATCH",
    RESULT_FS_ERROR:     "FS_ERROR",
    RESULT_BUSY:         "BUSY",
}

# ---- 默认设备名片段 ----
DEFAULT_DEVICE_NAME_HINT = "ESP32"

# 注：固件 registry 已改为单源（仅 FS）。除了 prelude.js（runtime 标准库）外
# 没有任何"内嵌 app"。如果旧版 PC 工具还引用 BUILTIN_APP_NAMES，应改为只看
# UPL_OP_LIST 的返回结果。
