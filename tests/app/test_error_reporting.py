from __future__ import annotations

import logging

from codeagent.app.errors.reporting import report_unexpected_error


def test_unexpected_error_report_hides_exception_from_user_and_logs_context(caplog) -> None:
    """意外异常必须可诊断，但不能将敏感异常文本投影到应用界面。"""
    with caplog.at_level(logging.ERROR, logger="codeagent.app"):
        try:
            raise RuntimeError("token=secret-value")
        except RuntimeError as exc:
            message = report_unexpected_error("会话恢复", exc)

    assert message == "会话恢复失败，请查看日志。"
    assert "secret-value" not in message
    record = caplog.records[-1]
    assert record.name == "codeagent.app"
    assert record.getMessage() == "会话恢复失败"
    assert record.exc_info is not None
