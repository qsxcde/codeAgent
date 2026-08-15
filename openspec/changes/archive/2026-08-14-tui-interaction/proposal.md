## Why

TUI MVP(restore-tui)已恢复对话/流式渲染/打断,但斜杠命令、模糊补全与选择器缺失(FR-1.3~1.6 拆入 v0.2)——对标 Claude Code / Codex 的行业公约(命令体系、`/undo`、输入容错),TUI 仍是"只读形态",无法切换 provider/model/effort、管理会话或查询状态。

## What Changes

- **TUI 迁到 SessionManager(前置改造)**:`create_tui_app` 装配从单 `AgentSession` 改为 `SessionManager`;`view.py` 通过 `manager.current` 发起运行;订阅跟随机制使切换会话对视图无感。
- **斜杠命令体系**:命令注册表 + 校验 + 解析(纯函数可离线测),首批落地 `/help /clear /status /sessions /tools`;`/provider /model /effort` 随 `replace_ports` 一起落地;`/undo` **注册槽位但依赖 T-42(会话回滚)延迟接线**,未实现时给出"未可用"提示(NFR-U7 容错);`//` 转义发送字面量。
- **命令选择器与模糊补全**:`fuzzy_match` 纯函数(精确 > 前缀 > 子串 > 子序列 > 编辑距离,≤50 命令 <10ms 满足 NFR-P6);provider/model/effort 选择器支持筛选与直接输入。
- **`SessionManager.replace_ports`**:热切换 provider/model/effort 时重建端口并保留会话上下文(manager docstring 已预留 T-44 归属;Pi 式 `model_change` entry 写入会话文件)。
- 无 **BREAKING** 对外接口变更;`TuiBackend` 端口仅增补命令相关回调。

## Capabilities

### New Capabilities

无(命令/补全/选择器均属既有 `tui` 能力的扩展,不新建 capability 文件)。

### Modified Capabilities

- `tui`:新增「斜杠命令体系」与「模糊补全与选择器」两条 requirement(FR-1.3~1.6 行为契约)。
- `sessions`:新增「运行时可切换模型配置」requirement(`SessionManager.replace_ports` + `model_change` entry 的持久化语义)。

## Impact

- `src/codeagent/app/container.py`:`create_tui_app` 改用 SessionManager 装配;`create_session_manager` 增 `replace_ports` 接线。
- `src/codeagent/app/tui/view.py`:提交/打断路径适配 `manager.current`;命令分派入口。
- `src/codeagent/app/tui/components.py`、`textual_backend.py`:命令输入拦截(补全激活时 ↑/↓/Tab/Enter 归属)、浮层渲染。
- `src/codeagent/session/manager.py`:`replace_ports`;`session/store.py`:`model_change` entry 类型。
- `tests/tui/*`、`tests/session/test_session_manager.py`:命令解析/模糊匹配/选择器/热切换全量离线测试。
