"""PyInstaller 入口：以包方式调用 companion，避免相对导入失败。"""
import sys
from companion.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
