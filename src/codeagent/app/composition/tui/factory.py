"""TUI 组合根：装配会话管理、Package、登录和模型热切换。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from codeagent.core.context.preflight import ContextPreflightConfig
from codeagent.tools.shared import ToolResourceLimits

from ..model import selection as model_selection
from ..prompts import _workspace, agents_sources, skills_view
from ..runtime.factory import close_runtime_for_config
from ..runtime.extensions import RuntimeExtensions
from .config import TuiConfigMixin


def _configured_providers() -> set[str]:
    """返回已配置非空 key 的 provider 集。"""
    from codeagent.app import config as app_config

    return app_config.configured_providers(app_config.CONFIG_ENV_FILE)


def _resolve_candidates(cfg: Any = None, registry: Any = None) -> dict[str, Any]:
    """解析 provider、model、effort 选择器候选。"""
    from codeagent.ai.catalog.registry import ModelRegistry
    from codeagent.ai.catalog.store import ModelStore
    from codeagent.ai.providers import PROVIDERS
    from codeagent.app import config as app_config

    reg = registry or ModelRegistry(ModelStore(app_config.CONFIG_MODELS_FILE))
    providers = sorted(PROVIDERS)
    models = {
        provider: sorted(reg.available(provider))
        for provider in providers
        if reg.available(provider)
    }
    return {
        "provider": providers,
        "login": providers,
        "model": models,
        "effort": ["low", "medium", "high"],
    }


def _resolve_footer_info(
    cfg: Any,
    provider: str | None,
    model: str | None,
    reasoning_effort: str | None,
    registry: Any = None,
) -> Any:
    """解析底部状态栏所需的 model、effort、provider 和 cwd。"""
    from codeagent.app.config import Settings
    from codeagent.app.tui.presentation.status import FooterInfo
    from codeagent.app.composition.model.factory import (
        _resolve_model_effort,
        resolve_model_capabilities,
    )

    model_id, effort = _resolve_model_effort(cfg, provider, model, reasoning_effort)
    resolved_provider = provider or getattr(cfg, "llm_provider", None) or Settings().llm_provider
    cwd = getattr(cfg, "cwd", None) if cfg is not None else None
    return FooterInfo(
        model=model_id,
        effort=effort,
        provider=resolved_provider,
        cwd=str(Path(cwd or Path.cwd()).expanduser().resolve()),
        capabilities=resolve_model_capabilities(registry, cfg, provider, model),
    )


class TuiAssembler(TuiConfigMixin):
    """持有 TUI 装配状态，并提供视图所需的组合根回调。"""

    def __init__(
        self,
        cfg: Any = None,
        *,
        backend: Any = None,
        registry: Any = None,
        store: Any = None,
        reasoning_effort: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        uncertain_budget_policy: str = "allow",
        context_preflight: ContextPreflightConfig | None = None,
        extensions: RuntimeExtensions | None = None,
        resource_limits: ToolResourceLimits | None = None,
    ) -> None:
        from codeagent.ai.catalog.registry import ModelRegistry
        from codeagent.ai.catalog.store import ModelStore
        from codeagent.app import config as app_config
        from codeagent.app.config import CONFIG_DIR
        from codeagent.app.skills.packages.manager import PackageManager

        self.cfg = cfg
        self.backend = backend
        self.registry = registry or ModelRegistry(ModelStore(app_config.CONFIG_MODELS_FILE))
        self.store = store
        self.reasoning_effort = reasoning_effort
        self.provider = provider
        self.model = model
        self.uncertain_budget_policy = uncertain_budget_policy
        self.context_preflight = context_preflight
        self.extensions = extensions
        self.resource_limits = resource_limits
        self.mcp_diagnostics: list[str] = []
        self.package_manager = PackageManager(CONFIG_DIR, _workspace(cfg))
        self.manager: Any = None

    def refresh_skills(self) -> tuple[list[Any], list[str]]:
        """重读 Skill Registry，供 TUI 生命周期刷新。"""
        return skills_view(self.cfg)

    def package_action(self, action: str, args: tuple[str, ...]) -> str:
        """处理 TUI `/skills` Package 子命令。"""
        scope = "project" if "--project" in args else "user"
        values = tuple(value for value in args if value != "--project")
        if action in {"install", "update"}:
            if len(values) != 1:
                noun = "git-url|目录" if action == "install" else "package-id"
                raise ValueError(f"用法: /skills {action} <{noun}> [--project]")
            method = getattr(self.package_manager, action)
            record = method(values[0], scope=scope)
            verb = "安装" if action == "install" else "更新"
            return f"已{verb} Package {record.package_id}@{record.version or 'unversioned'} ({scope})"
        if action == "remove":
            if len(values) != 1:
                raise ValueError("用法: /skills remove <package-id> [--project]")
            self.package_manager.remove(values[0], scope=scope)
            return f"已删除 Package {values[0]} ({scope})"
        if action == "reload":
            self.package_manager.reload()
            self.rebuild_config()
            return f"已重新加载 Package Registry 与 Adapter ({scope})"
        if action == "list":
            list_scope = scope if "--project" in args else None
            records = self.package_manager.list(scope=list_scope)
            diagnostics = self.package_manager.diagnostics(scope=list_scope)
            lines = ["Package:"] if records else ["Package: (无)"]
            for record in records:
                count = sum(1 for path in record.skills_dir.rglob("SKILL.md") if path.is_file())
                revision = record.revision or record.version or "unversioned"
                lines.append(
                    f"  {record.package_id}@{revision} · {record.scope} · "
                    f"{count} skills · {record.status}"
                )
            if diagnostics:
                lines.append("诊断:")
                lines.extend(f"  {item.code}: {item.message}" for item in diagnostics)
            return "\n".join(lines)
        raise ValueError(f"未知 Package 操作: {action}")

    def build(self) -> Any:
        """创建 TuiApp，并保持启动即进入首个会话。"""
        from codeagent.app.tui.application import TuiApp
        from codeagent.app.tui.adapters.textual.backend import TextualBackend

        manager = self._build_manager()
        manager.create()
        self.backend = self.backend or TextualBackend()
        footer = _resolve_footer_info(
            self.cfg, self.provider, self.model, self.reasoning_effort, self.registry
        )
        return TuiApp(
            manager,
            self.backend,
            footer=footer,
            rebuild_ports=self.rebuild_config,
            rebuild_ports_async=self.rebuild_config_async,
            candidates=_resolve_candidates(self.cfg, self.registry),
            agents_sources=agents_sources(self.cfg),
            skills=self.refresh_skills(),
            refresh_skills=self.refresh_skills,
            package_action=self.package_action,
            mcp_diagnostics=self.mcp_diagnostics,
            save_key=self.save_key,
            configured_providers=_configured_providers(),
            close_runtime=lambda: close_runtime_for_config(manager._config),
            resolve_model_capabilities=self.resolve_model_capabilities,
        )

    def resolve_model_capabilities(
        self, provider: str | None, model: str | None, effort: str | None
    ) -> Any:
        """Resolve the immutable capability view for a newly selected model."""
        del effort
        from ..model.factory import resolve_model_capabilities

        return resolve_model_capabilities(self.registry, self.cfg, provider, model)


def create_tui_app(
    cfg: Any = None,
    *,
    backend: Any = None,
    registry: Any = None,
    store: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    uncertain_budget_policy: str = "allow",
    context_preflight: ContextPreflightConfig | None = None,
    extensions: RuntimeExtensions | None = None,
    resource_limits: ToolResourceLimits | None = None,
) -> Any:
    """创建 TUI 应用，具体状态由 ``TuiAssembler`` 持有。"""
    return TuiAssembler(
        cfg,
        backend=backend,
        registry=registry,
        store=store,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
        uncertain_budget_policy=uncertain_budget_policy,
        context_preflight=context_preflight,
        extensions=extensions,
        resource_limits=resource_limits,
    ).build()
