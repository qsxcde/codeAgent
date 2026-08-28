"""TUI 组合根：会话管理、Package、登录和模型热切换。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import model_selection
from .model_factory import _resolve_context_window, _resolve_model_effort
from .prompt_builder import _workspace, agents_sources, skills_view
from .runtime_factory import (
    _LazyConfig,
    _LazySummarizer,
    close_runtime_for_config,
    close_runtime_for_config_async,
    create_agent_config,
    policy_for_config,
)
from .session_factory import create_session_manager


def _configured_providers() -> set[str]:
    """返回已配置非空 key 的 provider 集。"""
    from codeagent.app import config as app_config

    return app_config.configured_providers(app_config.CONFIG_ENV_FILE)


def _resolve_candidates(cfg: Any = None, registry: Any = None) -> dict[str, Any]:
    """解析 provider、model、effort 选择器候选。"""
    from codeagent.ai.catalog.registry import ModelRegistry
    from codeagent.ai.catalog.store import ModelStore
    from codeagent.app import config as app_config
    from codeagent.ai.providers import PROVIDERS

    reg = (
        registry
        if registry is not None
        else ModelRegistry(ModelStore(app_config.CONFIG_MODELS_FILE))
    )
    providers = sorted(PROVIDERS)
    models = {provider: sorted(reg.available(provider)) for provider in providers if reg.available(provider)}
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
) -> Any:
    """解析底部状态栏所需的 model、effort、provider 和 cwd。"""
    from codeagent.app.config import Settings
    from codeagent.app.tui.status import FooterInfo

    model_id, effort = _resolve_model_effort(cfg, provider, model, reasoning_effort)
    resolved_provider = (
        provider or getattr(cfg, "llm_provider", None) or Settings().llm_provider
    )
    cwd = getattr(cfg, "cwd", None) if cfg is not None else None
    cwd = str(Path(cwd or Path.cwd()).expanduser().resolve())
    return FooterInfo(model=model_id, effort=effort, provider=resolved_provider, cwd=cwd)


class TuiAssembler:
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
    ) -> None:
        from codeagent.ai.catalog.registry import ModelRegistry
        from codeagent.ai.catalog.store import ModelStore
        from codeagent.app import config as app_config
        from codeagent.app.config import CONFIG_DIR
        from codeagent.app.skill_packages import PackageManager

        self.cfg = cfg
        self.backend = backend
        self.registry = (
            registry
            if registry is not None
            else ModelRegistry(ModelStore(app_config.CONFIG_MODELS_FILE))
        )
        self.store = store
        self.reasoning_effort = reasoning_effort
        self.provider = provider
        self.model = model
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
        if action == "install":
            if len(values) != 1:
                raise ValueError("用法: /skills install <git-url|目录> [--project]")
            record = self.package_manager.install(values[0], scope=scope)
            return f"已安装 Package {record.package_id}@{record.version or 'unversioned'} ({scope})"
        if action == "update":
            if len(values) != 1:
                raise ValueError("用法: /skills update <package-id> [--project]")
            record = self.package_manager.update(values[0], scope=scope)
            return f"已更新 Package {record.package_id}@{record.version or 'unversioned'} ({scope})"
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
            if not records:
                lines = ["Package: (无)"]
                if diagnostics:
                    lines.append("诊断:")
                    lines.extend(
                        f"  {item.code}: {item.message}" for item in diagnostics
                    )
                return "\n".join(lines)
            lines = ["Package:"]
            for record in records:
                skill_count = sum(
                    1
                    for path in record.skills_dir.rglob("SKILL.md")
                    if path.is_file()
                )
                revision = record.revision or record.version or "unversioned"
                lines.append(
                    f"  {record.package_id}@{revision} · {record.scope} · "
                    f"{skill_count} skills · {record.status}"
                )
            if diagnostics:
                lines.append("诊断:")
                lines.extend(f"  {item.code}: {item.message}" for item in diagnostics)
            return "\n".join(lines)
        raise ValueError(f"未知 Package 操作: {action}")

    def _build_summarizer(self) -> Any:
        from .model_factory import LlmSummarizer

        return LlmSummarizer(
            model_selection.create_llm(
                cfg=self.cfg,
                registry=self.registry,
                reasoning_effort=self.reasoning_effort,
                provider=self.provider,
                model=self.model,
            )
        )

    def _build_config(self) -> Any:
        return create_agent_config(
            self.cfg,
            registry=self.registry,
            reasoning_effort=self.reasoning_effort,
            provider=self.provider,
            model=self.model,
            approval_mode="interactive",
            mcp_diagnostics=self.mcp_diagnostics,
        )

    def _build_manager(self) -> Any:
        self.manager = create_session_manager(
            self.cfg,
            registry=self.registry,
            store=self.store,
            reasoning_effort=self.reasoning_effort,
            provider=self.provider,
            model=self.model,
            approval_mode="interactive",
            summarizer=_LazySummarizer(self._build_summarizer),
            config=_LazyConfig(self._build_config),
            context_window=_resolve_context_window(
                self.registry, self.cfg, self.provider, self.model
            ),
            mcp_diagnostics=self.mcp_diagnostics,
        )
        return self.manager

    def rebuild_config(
        self,
        new_provider: str | None = None,
        new_model: str | None = None,
        new_effort: str | None = None,
    ) -> tuple[str, str]:
        """重建模型/工具配置并更新 SessionManager。"""
        if self.manager is None:
            raise RuntimeError("TUI 尚未完成 SessionManager 装配")
        target_provider = new_provider
        if new_model and target_provider is None and self.registry is not None:
            base = model_selection.split_model_pattern(new_model)[0]
            owners = [
                provider
                for provider in self.registry.catalog_providers()
                if base in self.registry.available(provider)
            ]
            if len(owners) == 1:
                target_provider = owners[0]
        old_config = self.manager._config
        self.manager._halt_current()
        new_config = create_agent_config(
            self.cfg,
            registry=self.registry,
            reasoning_effort=new_effort or self.reasoning_effort,
            provider=target_provider or None,
            model=new_model or None,
            approval_mode="interactive",
        )
        close_runtime_for_config(old_config)
        model_id, effort = _resolve_model_effort(
            self.cfg,
            target_provider,
            new_model,
            new_effort or self.reasoning_effort,
        )
        self.manager.replace_config(
            new_config,
            model=model_id,
            effort=effort,
            policy=policy_for_config(new_config),
            context_window=_resolve_context_window(
                self.registry, self.cfg, target_provider, new_model or model_id
            ),
        )
        self.refresh_skills()
        return model_id, effort

    async def rebuild_config_async(
        self,
        new_provider: str | None = None,
        new_model: str | None = None,
        new_effort: str | None = None,
    ) -> tuple[str, str]:
        """Rebuild ports after awaiting the old run and resource owner."""
        if self.manager is None:
            raise RuntimeError("TUI 尚未完成 SessionManager 装配")
        target_provider = new_provider
        if new_model and target_provider is None and self.registry is not None:
            base = model_selection.split_model_pattern(new_model)[0]
            owners = [
                provider
                for provider in self.registry.catalog_providers()
                if base in self.registry.available(provider)
            ]
            if len(owners) == 1:
                target_provider = owners[0]
        old_config = self.manager._config
        await self.manager._halt_current_and_wait()
        new_config = create_agent_config(
            self.cfg,
            registry=self.registry,
            reasoning_effort=new_effort or self.reasoning_effort,
            provider=target_provider or None,
            model=new_model or None,
            approval_mode="interactive",
        )
        await close_runtime_for_config_async(old_config)
        model_id, effort = _resolve_model_effort(
            self.cfg,
            target_provider,
            new_model,
            new_effort or self.reasoning_effort,
        )
        await self.manager.replace_config_async(
            new_config,
            model=model_id,
            effort=effort,
            policy=policy_for_config(new_config),
            context_window=_resolve_context_window(
                self.registry, self.cfg, target_provider, new_model or model_id
            ),
        )
        self.refresh_skills()
        return model_id, effort

    def save_key(self, provider: str, key: str) -> tuple[str, str]:
        """写入 provider key 并通过统一热切换链路生效。"""
        from codeagent.app import config as app_config

        app_config.write_env_key(provider, key, app_config.CONFIG_ENV_FILE)
        return self.rebuild_config(new_provider=provider)

    def build(self) -> Any:
        """创建 TuiApp，并保持启动即进入首个会话。"""
        from codeagent.app.tui.view import TuiApp

        manager = self._build_manager()
        manager.create()
        if self.backend is None:
            from codeagent.app.tui.textual_backend import TextualBackend

            self.backend = TextualBackend()
        candidates = _resolve_candidates(self.cfg, self.registry)
        footer = _resolve_footer_info(
            self.cfg, self.provider, self.model, self.reasoning_effort
        )
        return TuiApp(
            manager,
            self.backend,
            footer=footer,
            rebuild_ports=self.rebuild_config,
            rebuild_ports_async=self.rebuild_config_async,
            candidates=candidates,
            agents_sources=agents_sources(self.cfg),
            skills=self.refresh_skills(),
            refresh_skills=self.refresh_skills,
            package_action=self.package_action,
            mcp_diagnostics=self.mcp_diagnostics,
            save_key=self.save_key,
            configured_providers=_configured_providers(),
            close_runtime=lambda: close_runtime_for_config(manager._config),
        )


def create_tui_app(
    cfg: Any = None,
    *,
    backend: Any = None,
    registry: Any = None,
    store: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
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
    ).build()
