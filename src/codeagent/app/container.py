"""组合根:跨层 import 只发生在这里(自研编排版,2026-08-14)。

装配链:``create_llm``(ai 层 ChatClient)→ ``ChatModelPort`` 适配为 core
模型端口 → 与 ``make_tools`` 工具列表、可选的 ``SessionStore`` 组装成
``AgentPorts`` → ``AgentSession`` 事件壳。langgraph 桥接层已删除,
适配(Message 互转 / usage 归一)全部收敛在本文件。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, AsyncIterator, Callable

from codeagent.ai.protocol.messages import ChatMessage, ToolCall as AiToolCall
from codeagent.core.messages import Message, ToolCall
from codeagent.core.ports import AgentPorts, ModelResponse, PolicyDecision, StreamEvent


def create_tools(cfg: Any = None, skills: dict[str, str] | None = None) -> list[Any]:
    """工具层接线:产出自研原子工具列表。

    ``skills`` 为技能名 → 渲染块 注册表(组合根预渲染,注入 skill 工具)。
    """
    from codeagent.tools.registry import make_tools

    return make_tools(cfg, skills=skills)


# -- 系统提示词(agents-md-hierarchy + skills)---------------------------------


def _workspace(cfg: Any = None) -> str:
    """解析装配工作目录(配置 cwd,缺省进程启动目录)——多装配点同源。"""
    workspace = getattr(cfg, "cwd", None) if cfg is not None else None
    return str(Path(workspace or Path.cwd()).expanduser().resolve())


def _load_skills(cfg: Any = None) -> tuple[list[Any], list[Any]]:
    """加载技能注册表与诊断(组合根装配点共用;热切换重读,同 cwd 幂等)。"""
    from codeagent.app.config import CONFIG_DIR
    from codeagent.app.skills import load_skills

    return load_skills(_workspace(cfg), CONFIG_DIR)


def _build_system_prompt(cfg: Any = None, skills: list[Any] | None = None) -> str:
    """组装 system prompt:基础提示词 + 分层 AGENTS.md + 技能描述段。

    - cwd 与 policy/工具同源(配置 cwd,缺省进程启动目录);
    - config_dir 取 ``app.config.CONFIG_DIR``(全局上下文文件所在地);
    - ``skills`` 缺省自行加载(既有调用兼容);技能段位于分层上下文之后,
      仅名称/描述/来源(渐进式披露,正文不预载);
    - 热切换(rebuild_ports)再次调用本函数,同 cwd 幂等。
    """
    from codeagent.app import agents
    from codeagent.app.config import CONFIG_DIR

    base = agents.build_system_prompt(
        agents.read_base_prompt(), agents.load_agents_files(_workspace(cfg), CONFIG_DIR)
    )
    if skills is None:
        skills, _ = _load_skills(cfg)
    from codeagent.app.skills import build_skills_prompt

    return build_skills_prompt(base, skills)


def agents_sources(cfg: Any = None) -> list[str]:
    """本次装配加载的上下文文件来源列表(供 TUI /status 展示,可见可断言)。"""
    from codeagent.app.agents import load_agents_files
    from codeagent.app.config import CONFIG_DIR

    return [path for path, _ in load_agents_files(_workspace(cfg), CONFIG_DIR)]


def skills_view(cfg: Any = None) -> tuple[list[Any], list[str]]:
    """技能加载结果视图(技能列表 + 诊断消息;供 TUI /status 与 /skills 展示)。

    诊断消息为一行文本(遮蔽/解析失败等),加载结果可见可断言(T-52)。
    """
    skills, diagnostics = _load_skills(cfg)
    return skills, [f"{d.code}: {d.message}" for d in diagnostics]


class LlmSummarizer:
    """真实摘要实现(session-compaction):同一 LLM 通道生成结构化摘要。

    - 提示词要求保留精确文件路径/函数名/错误消息(压缩语义不丢失);
    - 二次压缩时传入既有摘要,提示词要求保留既有信息并合并新窗口
      (对齐 Pi UPDATE_SUMMARIZATION_PROMPT 语义,MVP 不强约束输出格式);
    - 离线测试注入桩实现(不经本类)。
    """

    _SYSTEM_PROMPT = (
        "你是对话摘要器,为继续工作生成结构化上下文检查点摘要。"
        "必须保留精确的文件路径、函数名与错误消息。"
    )
    _PROMPT = (
        "以下是需要压缩的会话消息(完整轮次):\n\n{history}\n\n"
        "既有摘要(必须保留其全部信息,只合并新增内容,不得丢弃):\n{prev}"
    )

    def __init__(self, client: Any) -> None:
        self._client = client

    async def summarize(
        self, messages: list[Any], prev_summary: str | None
    ) -> str:
        history = "\n".join(
            f"{m.role}: {m.content}" for m in messages if getattr(m, "content", "")
        )
        prompt = self._PROMPT.format(
            history=history, prev=prev_summary or "(无)"
        )
        from codeagent.ai.protocol.messages import ChatMessage

        resp = await self._client.generate(
            [
                ChatMessage(role="system", content=self._SYSTEM_PROMPT),
                ChatMessage(role="user", content=prompt),
            ],
            tools=None,
        )
        return str(resp.content or "")


# -- 执行前安全策略(security-permissions)------------------------------------


def _create_policy(cfg: Any = None, approval_mode: str = "deny") -> Any:
    """按形态装配执行前安全策略(design 决策 6;approval_mode: interactive|deny|allow)。

    - interactive(TUI):分类器原样——ask 由用户经会话确认队列响应;
    - deny(headless 缺省):ask 降级 deny(fail closed,未确认不得执行 NFR-S3);
    - allow(--yes):ask 放行(显式承担风险)。

    workspace 取配置 cwd(缺省进程启动目录),与工具注入同源;分类器是
    tools 层纯函数,此处适配为 core ``ApprovalPolicy`` 端口。
    """
    from codeagent.tools.security import classify_tool

    workspace = getattr(cfg, "cwd", None) if cfg is not None else None
    workspace = str(Path(workspace or Path.cwd()).expanduser().resolve())

    def _target_exists(target: str) -> bool:
        """mv 覆盖判定:目标相对 bash 执行目录(workspace)解析。"""
        p = Path(target)
        if not p.is_absolute():
            p = Path(workspace) / p
        return p.exists()

    class _Policy:
        def decide(self, tool_name: str, args: dict) -> PolicyDecision:
            decision = classify_tool(
                tool_name, args, workspace=workspace, cwd=workspace, exists=_target_exists
            )
            if decision.action == "ask" and approval_mode == "deny":
                return PolicyDecision("deny", f"未确认不得执行(headless): {decision.reason}")
            if decision.action == "ask" and approval_mode == "allow":
                return PolicyDecision("allow", decision.reason)
            return PolicyDecision(decision.action, decision.reason, decision.warning)

    return _Policy()


# -- 模型端口适配 ---------------------------------------------------------


def _to_chat_message(m: Message) -> ChatMessage:
    """core Message → ai 层 ChatMessage(OpenAI 形状,经组合根适配)。"""
    if m.role == "tool":
        return ChatMessage(role="tool", content=m.content, tool_call_id=m.tool_call_id)
    if m.role == "assistant":
        return ChatMessage(
            role="assistant",
            content=m.content,
            tool_calls=[
                AiToolCall(
                    id=tc.id,
                    name=tc.name,
                    arguments=json.dumps(tc.args, ensure_ascii=False),
                )
                for tc in m.tool_calls
            ],
        )
    return ChatMessage(role="user", content=m.content)


def _usage_of(usage: dict[str, Any] | None) -> dict[str, int] | None:
    """usage 归一为 core 形状;兼容 OpenAI 口径(prompt/completion_tokens)。"""
    if not usage:
        return None
    input_tokens = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
    output_tokens = usage.get("output_tokens") or usage.get("completion_tokens") or 0
    details = usage.get("output_token_details") or {}
    reasoning = details.get("reasoning") or usage.get("reasoning_tokens") or 0
    return {
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "reasoning_tokens": int(reasoning),
    }


class ChatModelPort:
    """把 ai 层 ``ChatClient`` 适配为 core ``ModelPort``(组合根唯一适配处)。

    流式事件逐项透传(thinking / content / tool_call_arg / usage / finish);
    工具参数为 JSON 字符串分片,由 core 循环累积组装;
    ``system_prompt`` 为分层上下文合并结果(agents-md-hierarchy):消息列表
    首条非 system 时前置插入,保证模型收到基础指令 + AGENTS.md。
    """

    def __init__(self, client: Any, system_prompt: str | None = None) -> None:
        self._client = client
        self._system_prompt = system_prompt

    @property
    def model_id(self) -> str:
        return self._client.model_id

    def _prepend_system(self, chat: list[ChatMessage]) -> list[ChatMessage]:
        """首条非 system 时前置插入 system 消息(仅一次,不重复)。"""
        if self._system_prompt and (not chat or chat[0].role != "system"):
            return [ChatMessage(role="system", content=self._system_prompt), *chat]
        return chat

    def stream(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        return self._stream(messages, tools)

    async def _stream(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        chat = self._prepend_system([_to_chat_message(m) for m in messages])
        async for ev in self._client.stream(chat, tools):
            yield StreamEvent(
                type=ev.type,
                text=ev.text,
                tool_index=ev.tool_index,
                arg_delta=ev.arg_delta,
                tool_name=ev.tool_name,
                tool_id=ev.tool_id,
                finish_reason=ev.finish_reason,
                usage=_usage_of(ev.usage),
            )

    async def generate(
        self,
        messages: list[Message],
        tools: list[Any] | None = None,
    ) -> ModelResponse:
        chat = self._prepend_system([_to_chat_message(m) for m in messages])
        resp = await self._client.generate(chat, tools)
        calls: list[ToolCall] = []
        for tc in resp.tool_calls:
            try:
                args = json.loads(tc.arguments) if tc.arguments else {}
                if not isinstance(args, dict):
                    args = {}
            except json.JSONDecodeError:
                args = {}
            calls.append(ToolCall(id=tc.id, name=tc.name, args=args))
        return ModelResponse(
            content=resp.content,
            tool_calls=calls,
            usage=_usage_of(resp.usage),
            finish_reason=resp.finish_reason,
            model=resp.model,
        )


# -- 装配 -----------------------------------------------------------------


def create_agent_ports(
    cfg: Any = None,
    *,
    registry: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    approval_mode: str = "deny",
) -> AgentPorts:
    """组合根:装配自研编排端口(模型端口 + 工具 + 安全策略)。

    ``store`` 不进端口(core 循环不落盘);会话存储经 ``AgentSession`` /
    ``SessionManager`` 注入(session-manager change,design D6);
    ``approval_mode`` 见 ``_create_policy``(缺省 deny = headless 安全优先)。
    """
    from codeagent.ai.factory import create_llm
    from codeagent.app.skills import format_skill_invocation

    client = create_llm(
        cfg=cfg,
        registry=registry,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
    )
    # 技能一次加载两处消费:system prompt 描述段 + skill 工具渲染块注册表。
    skills, _diagnostics = _load_skills(cfg)
    rendered_skills = {s.name: format_skill_invocation(s) for s in skills}
    return AgentPorts(
        model=ChatModelPort(client, system_prompt=_build_system_prompt(cfg, skills)),
        tools=create_tools(cfg, skills=rendered_skills),
        policy=_create_policy(cfg, approval_mode),
    )


def create_agent_session(
    cfg: Any = None,
    *,
    registry: Any = None,
    store: Any = None,
    session_id: str | None = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    recursion_limit: int | None = None,
    tool_timeout: float | None = None,
    approval_mode: str = "deny",
    summarizer: Any = None,
) -> Any:
    """组合根:创建有状态会话壳(CLI / TUI 入口)。

    - ``store`` 缺省 None(一次性 headless 不持久化);注入 SessionStore
      后会话可恢复、可继续(v0.2 会话层);
    - ``session_id`` 缺省自动分配;注入既有 id 恢复既有会话;
    - ``recursion_limit`` / ``tool_timeout`` 可单会话覆盖;
    - ``approval_mode`` 见 ``_create_policy``(headless 缺省 deny);
    - ``summarizer`` 为上下文压缩摘要端口(session-compaction;缺省 None
      = 压缩不可用,保持既有调用兼容)。
    """
    from codeagent.session import AgentSession, EventBus

    ports = create_agent_ports(
        cfg,
        registry=registry,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
        approval_mode=approval_mode,
    )
    return AgentSession(
        ports,
        EventBus(),
        store=store,
        session_id=session_id,
        recursion_limit=recursion_limit or 50,
        tool_timeout=tool_timeout,
        summarizer=summarizer,
    )


class _LazyPorts:
    """端口延迟装配:首次属性访问才构造(模型客户端 + 工具 + 策略)。

    TUI 首启可能尚无 API key,急切构造抛 ValueError 会让整个 TUI 无法
    启动、/login 首启流不可达(审计 M-7);延迟到首次对话——经 /login 写回
    .env 后 create_llm 每次重读配置,新 key 自然生效。
    """

    def __init__(self, factory: Callable[[], AgentPorts]) -> None:
        self._factory = factory
        self._real: AgentPorts | None = None

    def __getattr__(self, name: str) -> Any:
        if self._real is None:
            self._real = self._factory()
        return getattr(self._real, name)


class _LazySummarizer:
    """摘要器延迟构造:首次 /compact 才创建 LLM 客户端(同 _LazyPorts 动机)。"""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._real: Any = None

    async def summarize(
        self, messages: list[Any], prev_summary: str | None
    ) -> str:
        if self._real is None:
            self._real = self._factory()
        return await self._real.summarize(messages, prev_summary)


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
    """组合根:TUI 装配——SessionManager + backend + footer 的 model/effort(design D5/D6)。

    - TUI 经 ``SessionManager`` 装配(T-44 前置改造):会话可切换、订阅跟随,
      ``/sessions`` 等命令无需重建视图;启动即创建首个会话;
    - footer 信息在装配时解析固化:``model:effort`` 内联后缀 > ``reasoning_effort``
      > provider 配置默认;model:effort 解析唯一引用 ``split_model_pattern``;
    - backend 缺省构造 TextualBackend(textual 延迟到此处 import,保持启动路径轻量);
    - TUI 层不读配置/不跨层:model/effort 作为显式依赖注入 ``TuiApp``。
    """
    from codeagent.app.tui.components import FooterInfo
    from codeagent.app.tui.view import TuiApp

    from codeagent.ai.catalog.registry import ModelRegistry
    from codeagent.ai.factory import create_llm

    registry = registry if registry is not None else ModelRegistry()

    def _build_summarizer() -> Any:
        return LlmSummarizer(
            create_llm(
                cfg=cfg,
                registry=registry,
                reasoning_effort=reasoning_effort,
                provider=provider,
                model=model,
            )
        )

    def _build_ports() -> AgentPorts:
        return create_agent_ports(
            cfg,
            registry=registry,
            reasoning_effort=reasoning_effort,
            provider=provider,
            model=model,
            approval_mode="interactive",  # TUI:敏感操作经确认条交互(security-permissions)
        )

    manager = create_session_manager(
        cfg,
        registry=registry,
        store=store,
        reasoning_effort=reasoning_effort,
        provider=provider,
        model=model,
        approval_mode="interactive",  # TUI:敏感操作经确认条交互(security-permissions)
        summarizer=_LazySummarizer(_build_summarizer),  # 首启缺 key:首次 /compact 才建(审计 M-7)
        ports=_LazyPorts(_build_ports),  # 首启缺 key:首次对话才装配(审计 M-7)
    )
    manager.create()  # 启动即进入首个会话(命令 /sessions new 可再建)
    if backend is None:
        from codeagent.app.tui.textual_backend import TextualBackend

        backend = TextualBackend()

    candidates = _resolve_candidates(cfg, registry)

    def rebuild_ports(
        new_provider: str | None = None,
        new_model: str | None = None,
        new_effort: str | None = None,
    ) -> tuple[str, str]:
        """配置热切换回调(/provider /model /effort):重建端口并更新 manager。

        唯一跨层点:构造新 LLM 端口必须经组合根;解析出的 (model, effort)
        返回给视图更新状态栏。未知 provider 抛 ValueError 由视图提示。

        picker 候选为跨 provider 合并,故仅切模型时按目录推断归属 provider
        (id 唯一归属才推断;歧义时保持原解析链,错误提示照常)。
        """
        target_provider = new_provider
        if new_model and target_provider is None and registry is not None:
            from codeagent.ai.model_pattern import split_model_pattern

            base = split_model_pattern(new_model)[0]
            owners = [
                p for p in registry.catalog_providers() if base in registry.available(p)
            ]
            if len(owners) == 1:
                target_provider = owners[0]
        new_ports = create_agent_ports(
            cfg,
            registry=registry,
            reasoning_effort=new_effort or reasoning_effort,
            provider=target_provider or None,
            model=new_model or None,
            approval_mode="interactive",  # 热切换保留确认环(security-permissions)
        )
        model_id, effort = _resolve_model_effort(
            cfg, target_provider, new_model, new_effort or reasoning_effort
        )
        manager.replace_ports(new_ports, model=model_id, effort=effort)
        return model_id, effort

    def save_key(provider: str, key: str) -> tuple[str, str]:
        """/login 密钥保存回调(唯一跨层点):写 .env + 热切换。

        - 写回固定配置目录 .env(行级替换 ``<PREFIX>_API_KEY``,config 层实现);
        - 随后走 ``rebuild_ports``:provider Config 每次实例化重读 .env,新 key
          自然生效,无需任何缓存失效;
        - 返回 (model, effort) 供视图更新状态栏;未知 provider / 写失败抛
          ValueError / OSError 由视图就地提示、不切换。
        """
        from codeagent.app import config as app_config

        app_config.write_env_key(provider, key, app_config.CONFIG_ENV_FILE)
        return rebuild_ports(new_provider=provider)

    return TuiApp(
        manager,
        backend,
        footer=_resolve_footer_info(cfg, provider, model, reasoning_effort),
        rebuild_ports=rebuild_ports,
        candidates=candidates,
        agents_sources=agents_sources(cfg),  # 上下文文件来源(/status 展示)
        skills=skills_view(cfg),  # 技能列表 + 诊断(/skills /status 展示)
        save_key=save_key,  # /login 密钥保存 + 热切换(tui-login-command)
        configured_providers=_configured_providers(),  # 登录选择器 ✓ 标记
    )


def _configured_providers() -> set[str]:
    """已配置非空 key 的 provider 集(登录选择器 ✓ 标记,tui-login-command)。

    从固定配置目录 .env 解析;动态访问 ``CONFIG_ENV_FILE`` 以支持测试注入。
    """
    from codeagent.app import config as app_config

    return app_config.configured_providers(app_config.CONFIG_ENV_FILE)


def _resolve_candidates(cfg: Any = None, registry: Any = None) -> dict[str, Any]:
    """选择器候选(design T-45):provider / model / effort 各一份,组合根注入。

    provider 取注册表工厂;model 按 provider 分表(视图按当前 provider 过滤,
    保证 /model 只列当前提供商的模型);effort 为约定强度档位。TUI 层不读配置。
    """
    from codeagent.ai.catalog.registry import ModelRegistry
    from codeagent.ai.providers import PROVIDERS

    reg = registry if registry is not None else ModelRegistry()
    providers = sorted(PROVIDERS)
    models = {p: sorted(reg.available(p)) for p in providers if reg.available(p)}
    return {
        "provider": providers,
        "login": providers,  # /login 选择器候选 = 全部 provider(tui-login-command)
        "model": models,
        "effort": ["low", "medium", "high"],
    }


def create_session_manager(
    cfg: Any = None,
    *,
    registry: Any = None,
    store: Any = None,
    reasoning_effort: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    recursion_limit: int | None = None,
    tool_timeout: float | None = None,
    approval_mode: str = "deny",
    summarizer: Any = None,
    ports: Any = None,
) -> Any:
    """组合根:创建会话管理器(薄 Manager,design D1/D4)。

    - ports 装配一次共享(模型端口 / 工具无状态,跨会话复用);``ports``
      可注入预装配端口(TUI 延迟装配场景,审计 M-7),缺省按 cfg 装配,
      注入时 approval_mode 语义由调用方保证;
    - store 注入后会话可持久化;header 的 model/effort 在创建时固化
      (_resolve_model_effort 与 footer 同源解析,唯一引用 split_model_pattern);
    - replace_ports 属 T-44(/provider /model 命令时按 Pi 式 model_change
      entry 演进,design D4);
    - approval_mode 见 ``_create_policy``(TUI 传 interactive,headless 会话
      入口传 deny/allow);
    - summarizer 为上下文压缩摘要端口(session-compaction;缺省 None)。
    """
    from codeagent.session import SessionManager

    if ports is None:
        ports = create_agent_ports(
            cfg,
            registry=registry,
            reasoning_effort=reasoning_effort,
            provider=provider,
            model=model,
            approval_mode=approval_mode,
        )
    model_id, effort = _resolve_model_effort(cfg, provider, model, reasoning_effort)
    return SessionManager(
        ports,
        store=store,
        model=model_id,
        effort=effort,
        recursion_limit=recursion_limit or 50,
        tool_timeout=tool_timeout,
        summarizer=summarizer,
    )


def _resolve_model_effort(
    cfg: Any,
    provider: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> tuple[str, str]:
    """解析 model / effort(design D4):``model:effort`` 内联 > ``reasoning_effort``
    > provider 配置默认(与 footer 状态栏同源,组合根专用)。"""
    import importlib

    from codeagent.ai.model_pattern import split_model_pattern
    from codeagent.ai.providers import PROVIDERS
    from codeagent.app.config import Settings

    provider = provider or getattr(cfg, "llm_provider", None) or Settings().llm_provider
    base, inline = split_model_pattern(model) if model else (None, None)
    effort = inline or reasoning_effort
    model_id = base
    factory = PROVIDERS.get(provider)
    if factory is not None:
        module = importlib.import_module(factory.__module__)
        config_cls = next(
            (v for n, v in vars(module).items() if n.endswith("Config") and isinstance(v, type)),
            None,
        )
        if config_cls is not None:
            defaults = config_cls()
            if model_id is None:
                model_id = defaults.model
            if effort is None:
                effort = defaults.reasoning_effort
    return model_id or "", effort or ""


def _resolve_footer_info(
    cfg: Any,
    provider: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> Any:
    """解析底部状态栏装配数据:``(model, effort, cwd)``(组合根专用,design D5)。

    与 ``create_llm`` 同优先级:``model:effort`` 内联后缀 > ``reasoning_effort``
    > provider 配置默认(model/effort 解析委托 ``_resolve_model_effort``);
    ``cwd`` 取配置或当前工作目录。
    """
    from pathlib import Path

    from codeagent.app.config import Settings
    from codeagent.app.tui.components import FooterInfo

    model_id, effort = _resolve_model_effort(cfg, provider, model, reasoning_effort)
    resolved_provider = (
        provider or getattr(cfg, "llm_provider", None) or Settings().llm_provider
    )
    cwd = getattr(cfg, "cwd", None) if cfg is not None else None
    cwd = str(Path(cwd or Path.cwd()).expanduser().resolve())
    return FooterInfo(model=model_id, effort=effort, provider=resolved_provider, cwd=cwd)
