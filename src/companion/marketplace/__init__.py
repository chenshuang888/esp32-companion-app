"""marketplace 集成模块 —— 把 esp32-marketplace 的包一键装到设备 + 装 PC 插件。"""
from .client import MarketplaceClient, MarketplaceError, PackageCard
from .installer import (
    InstallerError, ParsedMpkg, parse_mpkg,
    make_temp_pack_dir, install_plugin_locally, uninstall_plugin_locally,
    request_upload_via_bus, request_delete_via_bus, request_list_via_bus,
)
from . import config, registry

__all__ = [
    "MarketplaceClient", "MarketplaceError", "PackageCard",
    "InstallerError", "ParsedMpkg", "parse_mpkg",
    "make_temp_pack_dir", "install_plugin_locally", "uninstall_plugin_locally",
    "request_upload_via_bus", "request_delete_via_bus", "request_list_via_bus",
    "config", "registry",
]
