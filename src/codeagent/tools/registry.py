"""工具注册表:make_tools(cfg) 工厂,装配原子工具集为 langchain BaseTool 列表。

对齐 ai/registry 模式:组合根在 container.py 调用 make_tools,产出可直接
bind_tools / 交给 ToolNode 的工具列表。
"""

from __future__ import annotations

from typing import Any

from codeagent.tools.atomic import BashTool, EditTool, ReadTool, WriteTool

__all__ = ["make_tools"]


def make_tools(cfg: Any = None) -> list[Any]:
    """按配置装配工具集,返回 langchain ``BaseTool`` 列表。

    - ``cfg`` 预留配置(与 ai/registry.make_llm 签名对齐);若提供 ``cwd``
      字段则作为 bash 工具的工作目录,否则回退进程启动目录(P2-8);
    - 默认包含 read / write / edit / bash 四个工具;
    - 无网络、无密钥副作用(仅延迟 import langchain 做转换)。
    """
    # 延迟导入 langchain:只有真正装配图(container)时才加载。
    from langchain_core.tools import BaseTool

    # cfg 可能是 Settings 或任意配置对象;cwd 缺省回退 None(→ 启动目录)。
    cwd = getattr(cfg, "cwd", None) if cfg is not None else None

    tools: list[BaseTool] = [
        ReadTool().to_langchain(),
        WriteTool().to_langchain(),
        EditTool().to_langchain(),
        BashTool(cwd=cwd).to_langchain(),
    ]
    return tools
