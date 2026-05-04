"""dynapp_uploader —— ESP32 dynamic app 上传/运维 SDK。

GUI 入口：python -m companion（在 GUI 的 Upload 页操作）

也可以独立用：

    import asyncio
    from dynapp_uploader import UploaderClient

    async def main():
        async with UploaderClient(device_name="ESP32") as c:
            # 推荐：传整个 app 包目录（含 main.js + 可选 manifest/icon/assets）
            await c.upload_app_pack("echo", "scripts/echo_pkg",
                                    display_name="回声示范")
            print(await c.list_apps())
            await c.delete_app("echo")

    asyncio.run(main())
"""

from .client import UploaderClient, UploadError
from .constants import (
    DEFAULT_DEVICE_NAME_HINT,
    MAX_CHUNK,
    MAX_SCRIPT_BYTES,
    NAME_LEN,
    PATH_LEN,
    RESULT_NAMES,
)

__all__ = [
    "UploaderClient",
    "UploadError",
    "DEFAULT_DEVICE_NAME_HINT",
    "MAX_CHUNK",
    "MAX_SCRIPT_BYTES",
    "NAME_LEN",
    "PATH_LEN",
    "RESULT_NAMES",
]
