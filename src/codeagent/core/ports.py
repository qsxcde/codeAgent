"""编排层端口:core 认识外部世界的唯一窗口。

`core/` 是纯编排层,不 import config / ai / tools / session。
外部世界(模型、工具、持久化)统一收敛到 `AgentPorts` 三个字段,
由组合根(container.py)负责组装。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from langchain_core.runnables import Runnable


@dataclass(frozen=True)
class AgentPorts:
    """编排层的外部端口集合。

    - ``bound_model``:已 ``bind_tools`` 的模型(由组合根负责 bind,core 零感知工具);
    - ``tool_executor``:工具执行器,对 loop 是黑盒(通常是 ToolNode);
    - ``checkpointer``:持久化对象,None 表示不启用(由组合根决定)。
    """

    bound_model: BaseChatModel
    tool_executor: Runnable
    checkpointer: Any | None = None
