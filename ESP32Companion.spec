# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格文件 —— 打包成单 .exe（GUI 无控制台）。

构建：  pyinstaller ESP32Companion.spec --noconfirm
产物：  dist/ESP32Companion.exe
"""
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# customtkinter 需要带它的 themes/json/icon 资源
ctk_datas = collect_data_files("customtkinter")

# winsdk 子模块运行时动态 import，需要预收集
hidden = []
hidden += collect_submodules("winsdk")
hidden += collect_submodules("companion")
hidden += [
    "just_playback",
    "PIL._tkinter_finder",
]

a = Analysis(
    ["launcher.py"],
    pathex=["src"],
    binaries=[],
    datas=ctk_datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "test", "unittest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="ESP32Companion",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico" if __import__("os").path.exists("assets/icon.ico") else None,
)
