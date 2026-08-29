"""AtomicTool 基类:无状态原子工具的抽象(自研版,2026-08-14)。

设计要点(design D1/D2):
- 无状态:工具本身不持有会话/文件缓存状态,天然可离线测试;
- 依赖注入:构造函数注入 ``cwd``(相对路径解析基准)与 ``ops``(文件系统抽象,
  缺省 ``LocalFsOps``),工具逻辑不直接触碰文件系统 → 可测试、可远程化;
- 工具实现保留自己的 Pydantic ``Args`` / ``invoke`` 细节,由应用组合根的
  ``AgentToolAdapter`` 统一挂载到 core,不让 core 依赖这些实现形态;
- ``args_schema`` 属性供模型端口生成 OpenAI function schema;
- 分层约束:本模块不 import langchain,不触碰 core/session。
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel

from codeagent.tools.shared import FsOps, LocalFsOps, ToolResourceLimits

__all__ = ["AtomicTool"]


class AtomicTool:
    """无状态原子工具的基类(由组合根适配后进入 Agent Runtime)。

    子类需要:
    - 定义 ``name`` / ``description`` 类属性;
    - 定义 ``Args``:``pydantic.BaseModel`` 子类作为输入 schema;
    - 实现 ``_invoke(args) -> str``:纯函数式执行,返回要回填给模型的结果文本;
    - ``_invoke`` 内经 ``self._cwd`` / ``self._ops`` 访问注入的依赖。
    """

    #: 工具名(供模型调用的唯一标识)
    name: ClassVar[str] = ""
    #: 工具描述(注入模型提示词,保持精简)
    description: ClassVar[str] = ""
    #: 输入参数 schema(pydantic 模型,转换为 JSON Schema 给模型)
    Args: ClassVar[type[BaseModel]] = BaseModel

    def __init__(
        self,
        cwd: str | Path | None = None,
        ops: FsOps | None = None,
        resource_limits: ToolResourceLimits | None = None,
    ) -> None:
        """装配时注入工作目录与文件操作实现(design D2)。

        - ``cwd``:相对路径解析基准;缺省回退进程启动目录;
        - ``ops``:文件系统抽象;缺省用 ``LocalFsOps``(本地文件系统)。
        """
        self._cwd = cwd
        self._ops: FsOps = ops if ops is not None else LocalFsOps()
        self._resource_limits = resource_limits or ToolResourceLimits()

    @property
    def resource_limits(self) -> ToolResourceLimits:
        """工具实例共享的不可变资源限制。"""
        return self._resource_limits

    @property
    def output_max_bytes(self) -> int:
        """返回同时受输出和预览内存约束的字节上限。"""
        return self._resource_limits.effective_output_bytes

    @property
    def output_max_lines(self) -> int:
        """返回统一的输出行上限。"""
        return self._resource_limits.max_output_lines

    @property
    def args_schema(self) -> type[BaseModel]:
        """输入参数 schema(模型端口据此生成 function schema)。"""
        return self.Args

    def invoke(self, args: BaseModel) -> str:
        """校验后的执行入口;子类应实现 ``_invoke``。"""
        return self._invoke(args)

    def _invoke(self, args: BaseModel) -> str:  # pragma: no cover - 抽象方法
        raise NotImplementedError(f"{type(self).__name__} 未实现 _invoke")
