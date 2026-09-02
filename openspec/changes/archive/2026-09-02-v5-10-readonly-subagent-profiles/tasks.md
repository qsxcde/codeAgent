## 1. Profile 契约与 registry

- [x] 1.1 扩展应用层 `SubagentProfile` 定义，集中描述正式名称、角色指令、只读工具白名单和有限输出指导，并提供稳定的 profile 名称枚举与严格查找入口。
- [x] 1.2 将 `explore` 和 `review` 注册为唯一可用的本变更 profile；保持两者只允许 `read`、`grep`、`find`、`ls`、`skill`，明确排除 `write`、`edit`、`bash`、MCP 和 `delegate`。
- [x] 1.3 将 provider-neutral `SubagentRequest` 的默认 profile 字符串从 `read_only` 同步为 `explore`，但不把 profile registry、工具名称或权限判断引入 core。
- [x] 1.4 增加 registry 自校验，确保每个公开 profile 都有非空角色指令和有效工具集合，且禁止出现已移除的 `read_only` 入口。

## 2. Delegate 与子 Session 装配

- [x] 2.1 让 `delegate` schema 的 profile 枚举和默认值从 registry 获取；请求解析、直接 runner 校验和 schema 对外展示必须使用同一组正式名称。
- [x] 2.2 更新 `delegate` 参数边界，使新的 `read_only` 请求在创建子 Session、占用子任务配额或调用模型前被拒绝，并返回明确的迁移提示。
- [x] 2.3 统一普通组合根和 TUI 组合根的 profile 装配路径，从同一 profile 定义取得工具白名单和角色指令，消除重复的 profile 策略读取。
- [x] 2.4 固定 explore/review 子 Session 的实际工具集合、`enable_subagents=False`、临时存储和最大深度行为，确认 task/context 文本不能扩大权限。
- [x] 2.5 补充 review 角色指令，使其只报告实际从 task、显式 context 或只读工具中获得的范围；证据不足时明确报告范围不足，不声称检查隐藏父历史或未读取的 diff。

## 3. 回归测试

- [x] 3.1 增加 profile registry、delegate schema 和 runner 校验的一致性测试，覆盖公开 profile 均可运行且未注册 profile 在子 Session 创建前失败。
- [x] 3.2 更新新的 delegate 请求和 FakeClient fixture 使用 `explore`，同时保留历史 JSONL 使用 `read_only` 文本的读取/展示兼容测试。
- [x] 3.3 增加 explore 子 Agent 集成测试，验证其绑定工具严格为只读白名单，不包含写入、编辑、Shell、MCP 或 delegate。
- [x] 3.4 增加 review 子 Agent 集成测试，验证显式 context 传递、父历史隔离、审查角色指令和范围不足时的诚实结果。
- [x] 3.5 增加 prompt 注入负向测试，覆盖 task/context 要求写文件、执行命令、调用 MCP 或递归委派时仍维持原 profile 权限。
- [x] 3.6 运行既有 Subagent 生命周期、事件、运行记录、TUI 和 headless 回归，确认 profile 重命名不改变状态、结果、持久化格式和展示边界。

## 4. 文档与迁移

- [x] 4.1 更新 v0.5 迭代文档，记录 V5-10 的范围、`explore`/`review` 职责和 `tester` 后续变更边界。
- [x] 4.2 更新架构或 Subagent 使用文档，说明 profile 是应用组合层策略、Reviewer 依赖显式范围，以及 `read_only` 不再是新的 delegate 入口。
- [x] 4.3 核对仓库内所有新入口、示例和测试引用，确保没有把 `read_only` 作为可用 profile 宣传，同时不改写历史会话记录。

## 5. 质量门禁

- [x] 5.1 运行 Subagent 相关 unit、contract、integration 和 TUI 窄测试，修复 profile 迁移回归。
- [x] 5.2 运行 `uv run ruff check src tests scripts`、`git diff --check` 和 `openspec validate v5-10-readonly-subagent-profiles --type change --strict`。
- [x] 5.3 运行完整离线测试和 `uv build`，确认既有单 Agent、Session、工具确认、上下文治理和 TUI 行为无回归。
