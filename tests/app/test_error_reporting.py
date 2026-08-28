from __future__ import annotations

import logging


def test_unexpected_error_report_hides_exception_from_user_and_logs_context(caplog) -> None:
    """意外异常必须可诊断，但不能将敏感异常文本投影到应用界面。"""
    try:
        from codeagent.app.error_reporting import report_unexpected_error
    except ImportError:
        report_unexpected_error = None

    assert report_unexpected_error is not None, "应用层必须提供统一的意外错误报告器"

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
