"""platform/ —— 平台能力适配层。

定位：providers/ 只管 BLE，gui/ 只管页面渲染，业务逻辑（providers/native, plugins）
需要"对接外部能力"时调本目录。每个文件 = 一种平台能力，而不是"被多方共用"才放进来。

当前能力：
  geoip_weather  HTTP 抓 IP 定位 + 天气 API
  smtc           Windows 媒体接口（SMTC）
  archive_org    HTTP 抓 archive.org 音乐资源
  toast          Win10 toast 通知
  packers        BLE 协议二进制打包
"""
