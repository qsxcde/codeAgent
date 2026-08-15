## Context

- 现状:TUI MVP 单 `AgentSession` 装配(`container.create_tui_app`);`SessionManager` 已落地(单活 current、switch 重建壳 + 订阅跟随、dispose 保留文件),`manager.py` docstring 明确 `replace_ports` 属 T-44;store 已有 `meta` entry(后写覆盖语义)可类比 `model_change`。
- 约束:TUI 层不读配置、不跨层(model/effort 组合根注入);命令解析须为纯函数可离线测;分层规则 session 不 import ai/tools/config;`TuiBackend` 端口是视图与引擎唯一缝。
- 动机见 proposal.md;行为契约见 specs(tui / sessions delta)。

## Goals / Non-Goals

**Goals:**
- TUI 会话可管理(/sessions 列出与切换),命令体系整体可离线测试。
- provider/model/effort 热切换经 `SessionManager.replace_ports`,切换记录持久化为 `model_change` entry。
- 保持 10 类 AgentEvent 契约与组合根唯一跨层点不变。

**Non-Goals:**
- `/undo` 的真实回滚实现(T-42,本 change 只注册命令槽位并提示未可用)。
- 并行会话事件转发(manager 已列为未来演进)、分支 fork / 会话树 UI(v0.3)。

## Decisions

1. **TUI 装配迁 SessionManager(前置改造,单独一步)**。`create_tui_app` 改用 `create_session_manager` 装配;`view.py` 通过 `manager.current` 发起运行、经 `manager.subscribe` 订阅(切换会话订阅自动跟随,视图零改动);`_submit` / `_interrupt` 路径改为 manager 感知。
   - 备选:view 内嵌多会话管理——重复实现单活/订阅跟随,违背"薄 Manager"设计,否决。
2. **命令注册表 + 解析为纯函数**(新模块 `app/tui/commands.py`,或并入 components 同层):`parse(input) → Literal | Command(name, args) | Unknown`;注册表声明命令名/参数/是否已接线(`/undo` 注册但 `available=False`);view 层只做分派。命令动作分两类:纯 TUI 状态(`/clear` `/status`)与跨层动作(`/sessions` `/provider` `/model` `/effort` 经 manager)。
3. **`SessionManager.replace_ports` 语义**:ports 无状态共享,热切换只重建模型端口与 header 配置;`model_change` entry 追加到 store(读侧后写覆盖,与 `meta` entry 同语义;旧文件仅有 header model/effort 时回退 header)。模型/effort 解析仍唯一引用 `split_model_pattern`。
4. **`/sessions` 命令形态**:先支持参数形式(`/sessions` 列表展示、`/sessions new`、`/sessions <id>` 切换),浮层选择器归 T-45 复用;命令解析自包含,不依赖 TUI 浮层。
5. **键盘归属与 T-45 共用设计**:补全浮层激活时 `_InputArea` 以 priority binding 拦截 ↑/↓/Tab/Enter,取消时恢复原生语义;与 tui-rendering 的 PageUp/PageDown 分派同属"按键分派表"问题,两 change 各管各的键位,不互相依赖。
6. **命令依赖注入**:注册表不 import 具体模块,动作闭包由组合根装配(view 构造时注入 manager 引用),保持 app/tui 不跨层。

## Risks / Trade-offs

- [TUI 迁移改动面大(create_tui_app + view + test_view 系列)] → 分两步落地:先 manager 化(测试全绿),再叠加命令;manager 化本身有 test_session_manager 兜底。
- [replace_ports 后旧会话文件无 model_change 记录] → 读侧兼容:header model/effort 为初始值,model_change 后写覆盖,旧文件不回退。
- [/sessions 与 T-45 选择器边界] → 命令参数形态先行,浮层交互归 T-45,命令注册表接口预留"带选择器"扩展位。
- [补全激活时误吞正常输入键] → 仅在输入以 `/` 起始且建议非空时激活拦截,其余时刻键位原生。

## Migration Plan

无部署/迁移(本地 CLI 应用);实现按"manager 化 → 命令骨架 → replace_ports → 补全/选择器"顺序,每步测试全绿后继续。

## Open Questions

- `/sessions` 切换时未提交输入与活动运行的处理(切换前 halt 由 manager 保证,输入框清空策略属实现细节,不影响契约)。
