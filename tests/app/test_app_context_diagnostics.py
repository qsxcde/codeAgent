from codeagent.app.context_diagnostics import format_context_diagnostics
from codeagent.core.context.budget import ContextBudgetSnapshot
from codeagent.core.context.diagnostics import ContextDiagnostics
from codeagent.core.context.preflight import ContextPreflightConfig, evaluate_context_preflight


def _diagnostics() -> ContextDiagnostics:
    snapshot = ContextBudgetSnapshot(
        context_window=20_000,
        output_reserve=1_000,
        reserve_tokens=500,
        input_budget=18_500,
        system_prompt_tokens=100,
        tool_definitions_tokens=200,
        conversation_tokens=2_000,
        tool_result_tokens=300,
        input_tokens=2_600,
        headroom=15_900,
        status="estimate",
        window_source="catalog",
    )
    return ContextDiagnostics.from_budget(snapshot, model_id="demo").with_preflight(
        evaluate_context_preflight(
            snapshot,
            ContextPreflightConfig(warning_headroom_tokens=1_000),
        )
    )


def test_context_diagnostics_formatter_groups_budget_and_preflight() -> None:
    text = "\n".join(format_context_diagnostics(_diagnostics()))

    assert "上下文诊断:" in text
    assert "模型: demo" in text
    assert "窗口: 20,000 · 来源 catalog · 精确" in text
    assert "预算: 输入 2,600 / 18,500 · 余量 15,900" in text
    assert "system_prompt: 100" in text
    assert "Preflight: safe" in text
    assert "最近压缩: (未发生)" in text


def test_context_diagnostics_formatter_marks_unknown_values() -> None:
    text = "\n".join(format_context_diagnostics(ContextDiagnostics.empty()))

    assert "窗口: 未知" in text
    assert "预算: 未知" in text
    assert "Preflight: (未发生)" in text
    assert "最近压缩: (未发生)" in text


def test_main_context_flag_prints_diagnostics_without_running_model(monkeypatch, capsys):
    from codeagent.app import main as main_module

    class Session:
        context_diagnostics = ContextDiagnostics.empty()
        closed = False

        def close_sync(self):
            self.closed = True

    session = Session()
    calls = []
    monkeypatch.setattr(
        main_module.container,
        "create_agent_session",
        lambda **kwargs: calls.append(kwargs) or session,
    )

    assert main_module.main(["--context"]) == 0

    assert calls == [{"approval_mode": "deny"}]
    assert "上下文诊断:" in capsys.readouterr().out
    assert session.closed is True
