## Context

- 现状:危险命令黑名单(FR-8.1)在 `BashTool._invoke` 内硬拒绝(字符串正则 + shlex 语义级),已闭环带审计;文件工具全部经 `resolve_to_cwd` 解析路径(lexical normalize,刻意不解析符号链接),绝对路径直通无边界;工具无状态同步,循环在 `asyncio.to_thread` 执行 `invoke`;`AgentPorts(model, tools)` 是 core 认识外部世界的唯一窗口,组合根是唯一跨层点;事件契约 10 类冻结(增量可加);`steer` 注入队列是现成的"运行中注入"机制。
- 约束:core 不 import tools/session(config 同理);工具保持无状态(确认不能做进工具内——同步线程无法 await 交互);离线可测是最高原则(分类器/边界判定必须是纯函数);平台无关断言。
- 动机见 proposal.md;行为契约见 specs(core / sessions / tools / tui 四个 delta)。

## Goals / Non-Goals

**Goals:**
- bash 敏感命令与越界文件写/编辑在执行前经用户确认,未确认不得执行(NFR-S3/S4);黑名单 deny 优先级不变。
- 确认交互 TUI 可操作(headless 默认拒绝不挂起);拒绝原因对模型可见(模型可调整行为)。
- 全部新增逻辑离线可测(注入 FakeClient / 桩确认响应器 / 内存 FsOps)。

**Non-Goals:**
- 确认记录落盘 JSONL(留给 T-42 /undo;本次仅事件流 + 结果文本)。
- 批量确认、确认超时、可配置敏感规则文件(规则表代码内可注入,MVP 不读配置文件)。
- 远程文件系统 / 多用户审批流(v0.3 及远期)。

## Decisions

1. **确认环在循环层,端口化(核心决策)**:`core/ports.py` 增 `ApprovalPolicy` 协议(`decide(tool_name, args) -> PolicyDecision`)与 `PolicyDecision(action: "allow"|"ask"|"deny", reason: str)` 数据类。`run_turn` 在**每个工具调用执行前**调用 policy;`ask` → emit `CONFIRMATION_REQUESTED` + `await` 确认队列 → 批准执行 / 拒绝回填 error tool_result。实现与装配分离:实现是 tools 层的纯分类器(见决策 4),装配在组合根(见决策 6)。
   - 备选否决:确认做进工具 `invoke`(同步线程无法 await 交互,破坏无状态);wrapper 工具(与循环职责重叠,事件语义绕路)。
2. **确认队列与会话响应**:`session/session.py` 持有一个 `asyncio.Queue[tuple[str, bool]]`(请求 id + 批准与否),经 `run_turn` 新参数 `confirm_queue` 传入;公开 `respond_approval(request_id, approved)` 方法写入队列。**逐个排队**:循环按调用顺序逐个等待(同一队列天然串行);abort 时等待点抛 `CancelledError`,走既有回滚 + `RUN_CANCELLED` 路径——不新增取消分支。
   - 事件负载:`confirmation_requested` 的 payload = `{"request_id", "tool", "summary", "reason"}`,request_id 由循环生成(uuid 短串),响应按 id 匹配(防御队列残留)。
3. **分类器(纯函数,tools/security.py 新模块)**:
   - `classify_bash(command: str, *, allowlist, ask_rules) -> PolicyDecision`:先过黑名单(复用 `_dangerous_hit` / `_dangerous_intent` → deny),再按**最后逻辑段首 token + 标志组合**(复用 `_last_segment_first_token` 的经验,含 `&&`/`;`/`|` 分段)匹配:只读白名单 → allow;敏感规则表 → ask;其余默认 allow(不打扰正常开发流程——确认环是"敏感闸门"而非"全量闸门")。
   - 敏感规则表(中等集合,可注入):`rm -r`(无 -f 的递归删除)、`git push` / `git reset --hard` / `git clean -f`、`sudo`、`chmod -R` / `chown -R`、`curl|sh` / `wget|sh` / `curl|bash`(管道末段为 sh/bash 且前段为下载)、`kill` / `pkill` / `killall`、`mv` 覆盖(目标已存在)。
   - `within_workspace(path: Path, workspace: Path) -> "inside" | "outside" | "unresolvable"`:realpath 级判定(防符号链接逃逸);目标存在时 `os.path.samefile` 兜底(macOS 大小写不敏感文件系统,normcase 是 no-op);Windows 前置 `os.path.normcase`;不存在目标按 realpath 的父目录链比较;解析失败(权限/断链)保守视为越界。
   - `classify_file(tool_name, path, workspace) -> PolicyDecision`:**读**(read)越界 → allow + warning 标记;**写/编辑**(write/edit)越界 → ask;边界内 → allow。warning 不阻断,结果文本附带 `[越界读取警告: path]`。
4. **`resolve_to_cwd` 不动**:边界判定是新增的独立函数(`within_workspace`),文件工具在 `_invoke` 内解析路径后调用——但**确认决策不在工具内做**(见决策 1),工具只负责"报告越界事实"给策略:`classify_file` 由循环层 policy 调用,工具 `_invoke` 保持纯执行。为让循环层拿到解析后路径,policy 端口签名用 `(tool_name, args)` + policy 实现内部自行解析(实现持有 workspace 与 cwd,组合根注入)。
5. **事件契约增量**:`core/events.py` 增 `CONFIRMATION_REQUESTED = "confirmation_requested"`(11 类)。订阅方忽略未知类型(CLI 聚合器不识别 → 不阻塞;headless 由策略 deny 从源头不产生 ask)。
6. **按形态装配(组合根)**:`create_agent_ports` 增 `approval_mode: "interactive" | "deny" | "allow"` 参数(缺省 deny 安全优先):
   - `interactive`(TUI):policy = 分类器 + 会话确认队列桥接;
   - `deny`(headless 缺省):ask 一律降级 deny(fail closed,NFR-S3 直接满足);
   - `allow`(`--yes` 逃生舱):ask 一律放行(显式承担风险)。
   `run_turn` 的 confirm_queue 由 `AgentSession` 持有并在构造时经 ports 传递(端口新增字段 `policy` 与 `confirm_queue` 均从组合根装配)。
7. **TUI 确认交互**:backend 增 `on_confirmation_response(handler)` 端口;view 维护 `_pending_confirmation` 状态,收到 `confirmation_requested` 事件 → 渲染确认条(composer 上方,仿 suggestions 浮层:⚠ 工具摘要 + 原因 + `[y] 允许 [n] 拒绝 [Esc] 拒绝并中止`);键位激活时 `_InputArea` 拦截 y/n/Esc(复用补全键位分派经验,键位不重叠);响应经 `manager.current.respond_approval(id, bool)` 反馈;ToolCallBlock 增「待确认/已拒绝」状态(拒绝 → error 图标 + 原因摘要);headless CLI 聚合器对未知事件类型静默忽略。
8. **审计**:拒绝/批准不新增持久化;审计信息 = tool_result 文本(`用户拒绝执行: <reason>` / `命令命中危险模式...`)+ 事件流。NFR-S8 既有拒绝审计保持。

## Risks / Trade-offs

- [确认环打断自动流程] → 只读白名单免确认 + 仅敏感/越界写 ask;对标 Claude Code 手动挡。
- [headless 挂起] → 缺省 deny 策略(fail closed);`--yes` 显式放行。
- [符号链接 TOCTOU(判定后链接被换)] → realpath 判定 + samefile;本地单用户 CLI 场景可接受,注释记录。
- [macOS 大小写不敏感] → samefile(inode 级)兜底;不存在目标的大小写歧义为已知缺口,注释记录。
- [并行工具调用的多个 ask] → 逐个排队(队列天然串行),一次一个确认条。
- [确认条与补全浮层键位冲突] → 确认激活时优先于补全,键位表统一维护(与 tui-interaction 同思路)。

## Migration Plan

纯增量,无部署;实现顺序(互不阻塞可并行):分类器与边界判定(tools/security.py + 测试)→ 循环层 policy 端口与队列(core)→ 会话响应(session)→ 组合根装配 + headless 策略 → TUI 确认交互。事件契约 10 → 11 类为增量,既有订阅方无需改动。

## Open Questions

无(超时/并行/读警告写确认/敏感集合/审计落盘五项已由用户在 propose 阶段定案;macOS 大小写与 TOCTOU 按本设计取舍记录)。
