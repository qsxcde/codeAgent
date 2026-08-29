"""工具运行环境能力探测契约。"""

from dataclasses import FrozenInstanceError

import pytest


def test_capability_snapshot_is_frozen_and_has_stable_serialization() -> None:
    from codeagent.tools.capabilities import ToolCapabilities, ToolCapability

    item = ToolCapability(
        key="rg",
        available=True,
        code="rg_available",
        message="rg 可用",
        detail="/usr/bin/rg",
    )
    snapshot = ToolCapabilities(platform="linux", items=(item,))

    assert snapshot.get("rg") is item
    assert snapshot.as_dict() == {
        "platform": "linux",
        "items": {
            "rg": {
                "available": True,
                "code": "rg_available",
                "message": "rg 可用",
                "detail": "/usr/bin/rg",
            }
        },
    }
    with pytest.raises(FrozenInstanceError):
        item.available = False


def test_probe_reports_all_capabilities_without_running_external_commands() -> None:
    from codeagent.tools.capabilities import detect_tool_capabilities

    calls: list[str] = []

    def which(name: str) -> str | None:
        calls.append(name)
        return {"rg": "/tools/rg"}.get(name)

    snapshot = detect_tool_capabilities(
        os_name="posix",
        sys_platform="linux",
        which=which,
        shell_resolver=lambda: "/bin/bash",
        security_policy=True,
    )

    assert [item.key for item in snapshot.items] == [
        "platform",
        "shell",
        "process_tree_cleanup",
        "rg",
        "fd",
        "permissions",
    ]
    assert snapshot.get("platform").available is True
    assert snapshot.get("shell").detail == "/bin/bash"
    assert snapshot.get("rg").available is True
    assert snapshot.get("fd").available is False
    assert "纯 Python" in snapshot.get("fd").message
    assert snapshot.get("permissions").available is True
    assert calls == ["rg", "fd"]


def test_probe_reports_actionable_missing_shell_and_optional_dependencies() -> None:
    from codeagent.tools.capabilities import detect_tool_capabilities

    def missing_shell() -> str:
        raise ValueError("no bash")

    snapshot = detect_tool_capabilities(
        os_name="nt",
        sys_platform="win32",
        which=lambda _name: None,
        shell_resolver=missing_shell,
        security_policy=False,
    )

    assert snapshot.platform == "windows"
    assert snapshot.get("shell").code == "shell_missing"
    assert "Git for Windows" in snapshot.get("shell").message
    assert snapshot.get("process_tree_cleanup").available is False
    assert snapshot.get("process_tree_cleanup").code == "cleanup_best_effort"
    assert snapshot.get("rg").code == "external_tool_missing"
    assert snapshot.get("fd").code == "external_tool_missing"
    assert snapshot.get("permissions").code == "security_policy_missing"


def test_probe_keeps_unknown_security_policy_explicit() -> None:
    from codeagent.tools.capabilities import detect_tool_capabilities

    snapshot = detect_tool_capabilities(
        os_name="posix",
        sys_platform="freebsd13",
        which=lambda _name: None,
        shell_resolver=lambda: "/bin/sh",
        security_policy=None,
    )

    assert snapshot.platform == "freebsd"
    permissions = snapshot.get("permissions")
    assert permissions.available is False
    assert permissions.code == "security_policy_unknown"
    assert "未知" in permissions.message
