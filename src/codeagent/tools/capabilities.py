"""只读的工具运行环境能力探测。"""

from __future__ import annotations

import os
import re
import shutil
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from codeagent.tools.execution.shell import resolve_bash

__all__ = [
    "ToolCapabilities",
    "ToolCapability",
    "detect_tool_capabilities",
]


@dataclass(frozen=True, slots=True)
class ToolCapability:
    """一项工具环境能力及其可操作诊断。"""

    key: str
    available: bool
    code: str
    message: str
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """返回稳定字段，供诊断输出和契约测试使用。"""
        values = asdict(self)
        values.pop("key", None)
        return values


@dataclass(frozen=True, slots=True)
class ToolCapabilities:
    """一次工具装配得到的不可变能力快照。"""

    platform: str
    items: tuple[ToolCapability, ...]

    def get(self, key: str) -> ToolCapability:
        """按稳定 key 取得能力；未知 key 明确报错而不返回空值。"""
        for item in self.items:
            if item.key == key:
                return item
        raise KeyError(f"未知工具能力: {key}")

    def __iter__(self) -> Iterator[ToolCapability]:
        return iter(self.items)

    def as_dict(self) -> dict[str, Any]:
        """返回不含可变内部对象的诊断快照。"""
        return {
            "platform": self.platform,
            "items": {item.key: item.as_dict() for item in self.items},
        }


def detect_tool_capabilities(
    *,
    env: Mapping[str, str] | None = None,
    os_name: str | None = None,
    sys_platform: str | None = None,
    which: Callable[[str], str | None] | None = None,
    shell_resolver: Callable[[], str] | None = None,
    security_policy: bool | None = True,
) -> ToolCapabilities:
    """探测工具依赖，不启动外部进程，也不触碰会话或文件状态。

    ``which`` 与 ``shell_resolver`` 是显式注入点，允许测试在无真实 shell、无
    PATH 命令的环境中复现诊断；未注入时使用当前进程环境的只读 PATH 查询。
    """
    env_values = os.environ if env is None else env
    detected_os = os.name if os_name is None else os_name
    detected_platform = sys.platform if sys_platform is None else sys_platform
    platform = _platform_name(detected_os, detected_platform)
    path = env_values.get("PATH")
    path_lookup = which or (lambda name: shutil.which(name, path=path))

    items = [
        ToolCapability(
            "platform",
            True,
            "platform_detected",
            f"当前平台 {platform}",
            platform,
        ),
        _probe_shell(
            platform,
            env_values,
            path_lookup,
            shell_resolver,
        ),
        _probe_process_cleanup(platform),
        _probe_optional_executable("rg", path_lookup),
        _probe_optional_executable("fd", path_lookup),
        _probe_security_policy(security_policy),
    ]
    return ToolCapabilities(platform=platform, items=tuple(items))


def _platform_name(os_name: str, sys_platform: str) -> str:
    if os_name == "nt" or sys_platform.startswith("win"):
        return "windows"
    if sys_platform == "darwin":
        return "macos"
    if sys_platform.startswith("linux"):
        return "linux"
    if sys_platform.startswith("freebsd"):
        return "freebsd"
    return re.split(r"[-\d]", sys_platform, maxsplit=1)[0] or "unknown"


def _probe_shell(
    platform: str,
    env: Mapping[str, str],
    which: Callable[[str], str | None],
    resolver: Callable[[], str] | None,
) -> ToolCapability:
    try:
        if resolver is not None:
            path = resolver()
        elif env is os.environ:
            path = resolve_bash()
        else:
            path = which("bash")
        if not path:
            raise ValueError("未找到 bash")
    except (OSError, ValueError) as exc:
        message = "未找到可用 Bash"
        if platform == "windows":
            message += "；请安装 Git for Windows，或将 Git\\bin 加入 PATH"
        else:
            message += "；请安装 Bash 并将其加入 PATH"
        return ToolCapability("shell", False, "shell_missing", message, str(exc))
    return ToolCapability("shell", True, "shell_available", "Bash 可用", str(path))


def _probe_process_cleanup(platform: str) -> ToolCapability:
    if platform == "windows":
        return ToolCapability(
            "process_tree_cleanup",
            False,
            "cleanup_best_effort",
            "Windows 可尝试清理进程树，但无法确认所有 MSYS 派生孙进程",
            "taskkill /T; MSYS descendants may remain uncertain",
        )
    return ToolCapability(
        "process_tree_cleanup",
        True,
        "cleanup_process_group",
        "POSIX 进程组支持可确认的进程树清理",
        "process group",
    )


def _probe_optional_executable(
    name: str,
    which: Callable[[str], str | None],
) -> ToolCapability:
    try:
        path = which(name)
    except OSError as exc:
        return ToolCapability(
            name,
            False,
            "external_tool_probe_failed",
            f"无法探测 {name}；当前使用纯 Python 搜索路径",
            str(exc),
        )
    if path:
        return ToolCapability(name, True, "external_tool_available", f"{name} 可用", path)
    return ToolCapability(
        name,
        False,
        "external_tool_missing",
        f"未找到 {name}；当前使用纯 Python 搜索路径",
    )


def _probe_security_policy(available: bool | None) -> ToolCapability:
    if available is True:
        return ToolCapability(
            "permissions",
            True,
            "security_policy_available",
            "安全策略已装配：读写边界、确认和危险命令拒绝生效",
            "workspace boundary; confirmation; rejection",
        )
    if available is False:
        return ToolCapability(
            "permissions",
            False,
            "security_policy_missing",
            "安全策略未装配；无法确认工具权限边界",
        )
    return ToolCapability(
        "permissions",
        False,
        "security_policy_unknown",
        "安全策略状态未知；无法确认工具权限边界",
    )
