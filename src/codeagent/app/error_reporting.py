"""应用层意外失败的安全呈现与诊断记录。"""

from __future__ import annotations

import logging

_LOGGER = logging.getLogger("codeagent.app")


def report_unexpected_error(operation: str, error: BaseException) -> str:
    """记录完整异常上下文，并返回不包含异常详情的用户提示。"""
    _LOGGER.error("%s失败", operation, exc_info=error)
    return f"{operation}失败，请查看日志。"
