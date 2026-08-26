"""Bash 解析、平台选择和受控子进程环境。"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["bash_env", "is_wsl_shim", "all_which", "resolve_bash"]

_BASH_ENV_ALLOWLIST: frozenset[str] = frozenset(
    {
        "PATH",
        "SystemRoot",
        "WINDIR",
        "SystemDrive",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "HOMEDRIVE",
        "HOMEPATH",
        "USER",
        "USERNAME",
        "SHELL",
        "TERM",
        "LANG",
        "LC_ALL",
        "LC_MESSAGES",
        "PWD",
        "OLDPWD",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
        "LOCALAPPDATA",
        "APPDATA",
        "PROCESSOR_ARCHITECTURE",
        "NUMBER_OF_PROCESSORS",
        "OS",
    }
)

_bash_executable: str | None = None


def is_wsl_shim(path: str) -> bool:
    """判断 Windows 自带 WSL 转发器，而不把它当作真实 Bash。"""
    if os.name != "nt":
        return False
    system_root = os.environ.get("SystemRoot") or r"C:\Windows"
    local_appdata = os.environ.get("LOCALAPPDATA") or str(
        Path.home() / "AppData" / "Local"
    )
    shims = {
        os.path.normcase(os.path.join(system_root, "System32", "bash.exe")),
        os.path.normcase(
            os.path.join(local_appdata, "Microsoft", "WindowsApps", "bash.exe")
        ),
    }
    return os.path.normcase(path) in shims


def all_which(name: str) -> list[str]:
    """返回 PATH 中全部候选，允许调用方跳过 WSL shim。"""
    exts = [""]
    if os.name == "nt":
        exts = [
            ext
            for ext in os.environ.get("PATHEXT", "").lower().split(os.pathsep)
            if ext
        ] or [".exe"]
    found: list[str] = []
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        if not directory:
            continue
        for ext in exts:
            candidate = os.path.join(directory, name + ext)
            if os.path.isfile(candidate):
                found.append(candidate)
                break
    return found


def resolve_bash() -> str:
    """解析真实 Bash；Windows 不隐式切换到 WSL。"""
    global _bash_executable
    if _bash_executable is not None:
        return _bash_executable

    candidates: list[str | None] = [
        path for path in all_which("bash") if not is_wsl_shim(path)
    ]
    for var in ("PROGRAMFILES", "PROGRAMFILES(X86)"):
        program_files = os.environ.get(var)
        if program_files:
            candidates.extend(
                [
                    os.path.join(program_files, "Git", "bin", "bash.exe"),
                    os.path.join(program_files, "Git", "usr", "bin", "bash.exe"),
                ]
            )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            _bash_executable = candidate
            return candidate
    raise ValueError(
        "未找到 bash 解释器:请安装 Git for Windows 或启用 WSL,"
        "或将 Git\\bin 目录加入系统 PATH 后重试"
    )


def bash_env() -> dict[str, str]:
    """构造不泄漏用户密钥的 Bash 子进程环境。"""
    env = {
        key: value
        for key, value in os.environ.items()
        if key in _BASH_ENV_ALLOWLIST
    }
    env["LANG"] = "en_US.UTF-8"
    env["NO_COLOR"] = "1"
    return env
