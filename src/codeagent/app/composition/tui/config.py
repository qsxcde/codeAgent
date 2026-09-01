"""TUI 组合根的模型配置和 SessionManager 生命周期。"""

from __future__ import annotations

from typing import Any

from ..model import selection as model_selection
from ..model.factory import _resolve_context_window, _resolve_model_effort
from ..runtime.factory import (
    _LazyConfig,
    _LazySummarizer,
    close_runtime_for_config,
    close_runtime_for_config_async,
    create_agent_config,
    policy_for_config,
)
from ..runtime.extensions import RuntimeExtensions
from ..session.factory import create_agent_session, create_session_manager
from codeagent.tools.shared import ToolResourceLimits


class TuiConfigMixin:
    def _ensure_subagent_runner(self) -> Any:
        if getattr(self, "subagent_runner", None) is None:
            from ..subagent.factory import create_serial_subagent_runner

            self.subagent_runner = create_serial_subagent_runner(
                self._create_child_session
            )
        return self.subagent_runner

    def _create_child_session(self, request: Any) -> Any:
        from ..subagent.profiles import allowed_tool_names_for

        return create_agent_session(
            self.cfg,
            registry=self.registry,
            store=None,
            reasoning_effort=self.reasoning_effort,
            provider=self.provider,
            model=self.model,
            approval_mode="interactive",
            uncertain_budget_policy=self.uncertain_budget_policy,
            context_preflight=self.context_preflight,
            extensions=self.extensions,
            resource_limits=self.resource_limits,
            enable_subagents=False,
            allowed_tool_names=allowed_tool_names_for(request.profile),
        )

    def _build_summarizer(self) -> Any:
        from ..model.factory import LlmSummarizer

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
            uncertain_budget_policy=self.uncertain_budget_policy,
            context_preflight=self.context_preflight,
            extensions=self.extensions,
            resource_limits=self.resource_limits,
            subagent_runner=self._ensure_subagent_runner(),
        )

    def _restore_session_config(self, ref: Any) -> Any:
        """根据持久化会话头重建模型和工具端口。"""
        provider = self.provider
        base_model = model_selection.split_model_pattern(ref.model)[0]
        if self.registry is not None:
            owners = [
                candidate
                for candidate in self.registry.catalog_providers()
                if base_model in self.registry.available(candidate)
            ]
            if len(owners) == 1:
                provider = owners[0]
        return create_agent_config(
            self.cfg,
            registry=self.registry,
            reasoning_effort=ref.effort or self.reasoning_effort,
            provider=provider,
            model=ref.model,
            approval_mode="interactive",
            mcp_diagnostics=self.mcp_diagnostics,
            uncertain_budget_policy=self.uncertain_budget_policy,
            context_preflight=self.context_preflight,
            extensions=self.extensions,
            resource_limits=self.resource_limits,
            subagent_runner=self._ensure_subagent_runner(),
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
            session_config_factory=self._restore_session_config,
            uncertain_budget_policy=self.uncertain_budget_policy,
            context_preflight=self.context_preflight,
            extensions=self.extensions,
            resource_limits=self.resource_limits,
            subagent_runner=self._ensure_subagent_runner(),
        )
        return self.manager

    def _target_provider(self, new_model: str | None, new_provider: str | None) -> str | None:
        if new_provider or not new_model or self.registry is None:
            return new_provider
        base = model_selection.split_model_pattern(new_model)[0]
        owners = [
            provider
            for provider in self.registry.catalog_providers()
            if base in self.registry.available(provider)
        ]
        return owners[0] if len(owners) == 1 else None

    def _new_config(
        self, provider: str | None, model: str | None, effort: str | None
    ) -> Any:
        return create_agent_config(
            self.cfg,
            registry=self.registry,
            reasoning_effort=effort or self.reasoning_effort,
            provider=provider or None,
            model=model or None,
            approval_mode="interactive",
            uncertain_budget_policy=self.uncertain_budget_policy,
            context_preflight=self.context_preflight,
            extensions=self.extensions,
            resource_limits=self.resource_limits,
            subagent_runner=self._ensure_subagent_runner(),
        )

    def _resolved_selection(
        self, provider: str | None, model: str | None, effort: str | None
    ) -> tuple[str, str]:
        return _resolve_model_effort(self.cfg, provider, model, effort or self.reasoning_effort)

    def rebuild_config(
        self,
        new_provider: str | None = None,
        new_model: str | None = None,
        new_effort: str | None = None,
    ) -> tuple[str, str]:
        """重建模型/工具配置并更新 SessionManager。"""
        if self.manager is None:
            raise RuntimeError("TUI 尚未完成 SessionManager 装配")
        provider = self._target_provider(new_model, new_provider)
        old_config = self.manager._config
        self.manager._halt_current()
        config = self._new_config(provider, new_model, new_effort)
        close_runtime_for_config(old_config)
        model_id, effort = self._resolved_selection(provider, new_model, new_effort)
        self.manager.replace_config(
            config,
            model=model_id,
            effort=effort,
            policy=policy_for_config(config),
            context_window=_resolve_context_window(self.registry, self.cfg, provider, new_model or model_id),
        )
        self.refresh_skills()
        return model_id, effort

    async def rebuild_config_async(
        self,
        new_provider: str | None = None,
        new_model: str | None = None,
        new_effort: str | None = None,
    ) -> tuple[str, str]:
        """等待旧回合和资源所有者结束后重建端口。"""
        if self.manager is None:
            raise RuntimeError("TUI 尚未完成 SessionManager 装配")
        provider = self._target_provider(new_model, new_provider)
        old_config = self.manager._config
        await self.manager._halt_current_and_wait()
        config = self._new_config(provider, new_model, new_effort)
        await close_runtime_for_config_async(old_config)
        model_id, effort = self._resolved_selection(provider, new_model, new_effort)
        await self.manager.replace_config_async(
            config,
            model=model_id,
            effort=effort,
            policy=policy_for_config(config),
            context_window=_resolve_context_window(self.registry, self.cfg, provider, new_model or model_id),
        )
        self.refresh_skills()
        return model_id, effort

    def save_key(self, provider: str, key: str) -> tuple[str, str]:
        """写入 provider key 并通过统一热切换链路生效。"""
        from codeagent.app import config as app_config

        app_config.write_env_key(provider, key, app_config.CONFIG_ENV_FILE)
        return self.rebuild_config(new_provider=provider)
