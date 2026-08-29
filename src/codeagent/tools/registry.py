"""工具注册表:make_tools(cfg) 工厂,装配原子工具集(自研版,2026-08-14)。

组合根调用 make_tools 取得具体原子工具,再由 `app/composition/tools/adapter.py`
转换为可交给自研循环的 AgentTool 列表。工厂即注入点:
cwd 注入全部工具(design D2;对应 spec「装配时注入工作目录」),技能注册表
(名 → 渲染块)注入 ``skill`` 工具(design skills-system D3,组合根预渲染)。
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
    SkillTool,
    WriteTool,
)
from codeagent.tools.base import AtomicTool
from codeagent.tools.shared import ToolResourceLimits

__all__ = ["make_tools"]


def make_tools(
    cfg: Any = None,
    skills: dict[str, str] | None = None,
    resource_limits: ToolResourceLimits | None = None,
) -> list[AtomicTool]:
    """按配置装配工具集,返回自研原子工具列表。

    - ``cfg`` 预留配置;若提供 ``cwd`` 字段则作为全部工具的工作目录,
      否则回退进程启动目录(P2-8);
    - ``skills`` 为技能名 → 渲染块 注册表(组合根预渲染;None = skill 工具
      返回"未注入"提示);
    - 默认包含 read / write / edit / bash / grep / find / ls / skill 八个工具;
    - 无网络、无密钥副作用。
    """
    cwd = getattr(cfg, "cwd", None) if cfg is not None else None
    limits = resource_limits or ToolResourceLimits.from_config(cfg)
    return [
        ReadTool(cwd=cwd, resource_limits=limits),
        WriteTool(cwd=cwd, resource_limits=limits),
        EditTool(cwd=cwd, resource_limits=limits),
        BashTool(cwd=cwd, resource_limits=limits),
        GrepTool(cwd=cwd, resource_limits=limits),
        FindTool(cwd=cwd, resource_limits=limits),
        LsTool(cwd=cwd, resource_limits=limits),
        SkillTool(cwd=cwd, skills=skills, resource_limits=limits),
    ]
