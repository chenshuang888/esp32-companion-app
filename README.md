# ESP32 桌面助手

通过蓝牙连接 ESP32-S3 设备，从市场一键安装 App、把本地音乐同步到手表的 Windows 桌面端。

> 配套固件请刷 `demo6` 系列（默认 BLE 设备名 `ESP32-S3-DEMO`）。

---

## 下载使用（普通用户）

直接到 [Releases](https://github.com/chenshuang888/esp32-companion-app/releases) 下载最新的 `ESP32Companion.exe`，双击运行即可。

首次启动会自动创建用户目录：

```
%APPDATA%\esp32-companion-user\
├── config.json     设备名、音乐文件夹等配置
├── plugins\        从市场装的桌面扩展
├── cache\          下载缓存
└── app.log         运行日志
```

要重置：删除整个 `%APPDATA%\esp32-companion-user\` 目录即可。

### 系统要求

- Windows 10 1803 及以上（winsdk / SMTC 依赖）
- 自带或外接的 BLE 蓝牙适配器
- ESP32-S3 端已刷配套 `demo6` 固件，BLE 设备名与 App 配置一致

---

## 功能

| 页面 | 说明 |
|---|---|
| 市场 | 浏览社区动态 App，一键装到设备；带「需要桌面扩展」标签的会自动把桌面端配套一并装好 |
| 音乐 | 选本地音乐文件夹，一键同步到手表；可在线搜索 archive.org 下载新曲 |

---

## 从源码运行（开发者）

```bat
git clone https://github.com/chenshuang888/esp32-companion-app.git
cd esp32-companion-app
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m companion
```

> Windows 环境只有 `python` 命令，无 `python3`。

### 自己打包 .exe

```bat
pip install pyinstaller
pyinstaller ESP32Companion.spec --noconfirm
```

或直接运行 `build.bat`。完成后产物在 `dist\ESP32Companion.exe`。

---

## 项目结构

```
src/companion/
├── __main__.py            程序入口
├── core.py / bus.py       核心调度 / 事件总线
├── runner.py              异步运行器
├── tray.py                系统托盘
├── app_paths.py           用户数据目录管理
├── config.py / branding.py
├── providers/             数据来源
│   ├── native/            本地：媒体/通知/系统/时间/天气
│   └── dynapp/            设备桥：bridge / upload
├── platform/              平台胶水：SMTC、toast、archive.org、geoip 天气、音乐库
├── marketplace/           市场：registry / client / installer
├── plugin_manager.py      插件加载器
├── plugin_sdk/            插件开发 SDK
├── dynapp_uploader/       设备端 App 上传协议
└── gui/                   界面：customtkinter + 页面
```

---

## 首次连接设备

1. ESP32-S3 设备先开机，确认 BLE 设备名为 `ESP32-S3-DEMO`（或在 `config.json` 改成你设备的名字）
2. 启动本程序，等几秒，侧边栏底部状态点变绿即已连接
3. 进入「市场」页选包安装

---

## 常见问题

- **状态点一直未连接**：检查蓝牙是否开启 + 设备是否在 `demo6` 固件 + BLE 设备名是否一致
- **装含「需要桌面扩展」的 App 后无效**：装完需重启本程序加载新扩展
- **音乐同步报缺 ffprobe**：装一下 `ffmpeg`（含 `ffprobe`），加进 PATH 后重启程序
- **多台同名设备**：在 `config.json` 里写死 `device_address`（MAC）锁定其中一台

---

## 插件机制

插件装在用户目录 `%APPDATA%\esp32-companion-user\plugins\`，**与电脑/用户绑定，不随 exe 分发**。每个用户首次运行只有空目录，需要自己去市场页装。

---

## 贡献

欢迎 Issue 和 PR。提交代码前请确保：

- 不引入新的强依赖（必要时再加进 `requirements.txt`）
- 遵循现有目录分层（`platform/` 放 OS 胶水，`providers/` 放数据源，`gui/` 只放界面）
- Windows 路径用 `pathlib` 或 `app_paths.py` 提供的辅助函数，别硬编码

---

## 许可证

[MIT](LICENSE) © 2026 ChenShuang
