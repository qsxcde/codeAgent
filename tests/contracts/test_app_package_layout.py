"""应用层规范包路径和具体引擎边界契约。"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[2] / "src" / "codeagent" / "app"

LEGACY_FLAT_MODULES = frozenset(
    {
        "agents.py",
        "error_reporting.py",
        "package_manager.py",
        "package_registry.py",
        "skill_discovery.py",
        "skill_models.py",
        "skill_packages.py",
        "skill_runtime.py",
        "task_lifecycle.py",
        "task_modes.py",
        "task_results.py",
        "task_supervisor.py",
        "task_verification.py",
        "verification_models.py",
        "verification_runner.py",
        "verification_workspace.py",
        "composition/model_budget.py",
        "composition/model_factory.py",
        "composition/model_port.py",
        "composition/model_selection.py",
        "composition/policy_factory.py",
        "composition/prompt_builder.py",
        "composition/runtime_factory.py",
        "composition/session_factory.py",
        "composition/tool_definitions.py",
        "composition/tool_factory.py",
        "composition/tui_config.py",
        "composition/tui_factory.py",
        "tui/backend.py",
        "tui/blocks.py",
        "tui/command_coordinator.py",
        "tui/command_dispatch.py",
        "tui/command_skills.py",
        "tui/command_status.py",
        "tui/components.py",
        "tui/conversation_coordinator.py",
        "tui/fuzzy.py",
        "tui/interaction.py",
        "tui/md_renderer.py",
        "tui/model.py",
        "tui/model_events.py",
        "tui/model_history.py",
        "tui/output.py",
        "tui/performance.py",
        "tui/primitives.py",
        "tui/render_coordinator.py",
        "tui/runtime.py",
        "tui/runtime_state.py",
        "tui/runtime_transitions.py",
        "tui/session_action_runner.py",
        "tui/session_actions.py",
        "tui/session_commands.py",
        "tui/session_coordinator.py",
        "tui/session_restore.py",
        "tui/status.py",
        "tui/textual_app.py",
        "tui/textual_backend.py",
        "tui/textual_rich.py",
        "tui/textual_widgets.py",
        "tui/theme.py",
        "tui/transcript.py",
        "tui/transcript_layout.py",
        "tui/view.py",
    }
)


@pytest.mark.contract
def test_canonical_app_packages_expose_migrated_symbols() -> None:
    expected = {
        "codeagent.app.context.agents": ("load_agents_files", "build_system_prompt"),
        "codeagent.app.errors.reporting": ("report_unexpected_error",),
        "codeagent.app.skills.discovery": ("discover_skills_in",),
        "codeagent.app.skills.packages.registry": ("PackageRegistry",),
        "codeagent.app.tasks.modes": ("TaskMode", "parse_mode_input"),
        "codeagent.app.tasks.verification.runner": ("VerificationRunner",),
        "codeagent.app.composition.model.factory": ("LlmSummarizer",),
        "codeagent.app.composition.runtime.factory": ("create_agent_config",),
        "codeagent.app.composition.tools.factory": ("create_tools",),
        "codeagent.app.composition.tui.factory": ("create_tui_app",),
        "codeagent.app.tui.ports.backend": ("TuiBackend",),
        "codeagent.app.tui.state.model": ("TuiModel",),
        "codeagent.app.tui.presentation.blocks": ("ErrorBlock",),
        "codeagent.app.tui.commands.parser": ("parse",),
        "codeagent.app.tui.session.coordinator": ("TuiSessionCoordinator",),
        "codeagent.app.tui.rendering.coordinator": ("TuiRenderCoordinator",),
        "codeagent.app.tui.benchmark.benchmark": ("run_benchmark",),
    }

    for module_name, symbols in expected.items():
        module = importlib.import_module(module_name)
        for symbol in symbols:
            assert hasattr(module, symbol), f"{module_name} 缺少规范符号 {symbol}"


@pytest.mark.contract
def test_legacy_flat_modules_are_removed() -> None:
    present = sorted(
        relative_path
        for relative_path in LEGACY_FLAT_MODULES
        if (APP_ROOT / relative_path).exists()
    )
    assert present == []


@pytest.mark.contract
def test_textual_imports_are_confined_to_adapter_package() -> None:
    violations: list[str] = []
    allowed_root = APP_ROOT / "tui" / "adapters" / "textual"
    for path in (APP_ROOT / "tui").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if path.is_relative_to(allowed_root):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(alias.name == "textual" or alias.name.startswith("textual.") for alias in node.names):
                violations.append(str(path))
            if isinstance(node, ast.ImportFrom) and node.module and (node.module == "textual" or node.module.startswith("textual.")):
                violations.append(str(path))
    assert violations == []
