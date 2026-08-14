"""工具注册表:make_tools(cfg) 工厂,装配原子工具集(自研版,2026-08-14)。

组合根在 container.py 调用 make_tools,产出可直接交给自研循环的工具列表
(实现 ``name`` / ``description`` / ``args_schema`` / ``invoke``)。工厂即注入点:
cwd 注入全部七个工具(design D2;对应 spec「装配时注入工作目录」)。
"""

from __future__ import annotations

from typing import Any

from codeagent.tools.atomic import (
    BashTool,
    EditTool,
    FindTool,
    GrepTool,
    LsTool,
    ReadTool,
    WriteTool,
)
from codeagent.tools.base import AtomicTool

__all__ = ["make_tools"]


def make_tools(cfg: Any = None) -> list[AtomicTool]:
    """按配置装配工具集,返回自研原子工具列表。

    - ``cfg`` 预留配置;若提供 ``cwd`` 字段则作为全部工具的工作目录,
      否则回退进程启动目录(P2-8);
    - 默认包含 read / write / edit / bash / grep / find / ls 七个工具;
    - 无网络、无密钥副作用。
    """
    cwd = getattr(cfg, "cwd", None) if cfg is not None else None
    return [
        ReadTool(cwd=cwd),
        WriteTool(cwd=cwd),
        EditTool(cwd=cwd),
        BashTool(cwd=cwd),
        GrepTool(cwd=cwd),
        FindTool(cwd=cwd),
        LsTool(cwd=cwd),
    ]
