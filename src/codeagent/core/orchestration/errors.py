"""Public errors shared by the core loop and its turn helpers."""


class RecursionLimitError(RuntimeError):
    """循环超限(替代 GraphRecursionError):session 壳捕获后回滚并友好提示。"""

    friendly = (
        "模型连续调用工具次数过多,已自动停止本轮并清理中间状态。"
        "请重试,或换一个更明确的指令。"
    )

    def __str__(self) -> str:
        return self.friendly


__all__ = ["RecursionLimitError"]
