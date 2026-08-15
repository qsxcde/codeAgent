## 1. 分类器与边界判定(tools/security.py,纯函数,先行)

- [x] 1.1 `tools/security.py` 新模块:`PolicyDecision`(action: allow|ask|deny + reason)与 `classify_bash(command, *, allowlist, ask_rules) -> PolicyDecision` 纯函数——先过黑名单(复用 `_dangerous_hit` / `_dangerous_intent` → deny),再按最后逻辑段首 token + 标志组合匹配:只读白名单 → allow、敏感规则表 → ask、其余默认 allow;规则表可注入
- [x] 1.2 敏感规则表(中等集合):`rm -r`(无 -f)、`git push` / `git reset --hard` / `git clean -f`、`sudo`、`chmod -R` / `chown -R`、`curl|sh` / `wget|sh` / `curl|bash`、`kill` / `pkill` / `killall`、`mv` 覆盖(目标已存在);只读白名单:ls/cat/grep/pwd/cd/git status/git diff 等
- [x] 1.3 `within_workspace(path, workspace) -> inside|outside|unresolvable` 边界判定:realpath 级(防符号链接逃逸)、目标存在时 `os.path.samefile` 兜底(macOS 大小写)、Windows `normcase`、不存在目标按 realpath 父链比较、解析失败保守越界
- [x] 1.4 `classify_file(tool_name, path, workspace) -> PolicyDecision`:读越界 → allow + warning 标记;写/编辑越界 → ask;边界内 → allow
- [x] 1.5 测试(`tests/tools/test_security.py`):三档分类断言、黑名单优先级(deny > ask > allow)、分段命令(`cd /tmp && git push` 仍命中)、白名单免确认、越界读/写分类、符号链接逃逸(内存 FsOps 注入)、平台无关(Windows normcase 用例)

## 2. 循环层 policy 端口与确认等待(core)

- [x] 2.1 `core/ports.py`:增 `ApprovalPolicy` 协议(`decide(tool_name, args) -> PolicyDecision`)与 `PolicyDecision` 数据类;`AgentPorts` 增 `policy` 字段(可空 = 无确认环,保持既有测试兼容)
- [x] 2.2 `core/events.py`:增 `CONFIRMATION_REQUESTED = "confirmation_requested"`(事件契约 10 → 11 类,增量)
- [x] 2.3 `core/loop.py`:`run_turn` 增 `policy` 与 `confirm_queue` 参数——每个工具调用执行前 `policy.decide`;ask → emit `confirmation_requested`(request_id/tool/summary/reason)+ `await` 队列按 id 匹配 → 批准执行 / 拒绝回填 error tool_result(`用户拒绝执行: <reason>`);并行调用逐个等待(队列天然串行)
- [x] 2.4 测试(`tests/core/test_loop.py` 增量):allow 直通、ask 批准执行、ask 拒绝回填带原因、deny 拒绝、确认等待期间 abort 取消(确认队列随 CancelledError 清理)

## 3. 会话确认响应(session)

- [x] 3.1 `session/session.py`:确认队列(与 steer 队列同机制)经 `run_turn` 传入;公开 `respond_approval(request_id, approved)` 写入队列;构造时把队列桥接到 ports.policy 的交互实现
- [x] 3.2 测试(`tests/session/test_session.py` 增量):respond_approval 批准/拒绝驱动循环、未响应前不执行、abort 时无悬挂等待

## 4. 组合根装配与 headless 策略(app)

- [x] 4.1 `app/container.py`:`create_agent_ports` / `create_agent_session` 增 `approval_mode: interactive|deny|allow`(缺省 deny 安全优先);interactive = 分类器 + 会话队列桥接;deny = ask 降级 deny(fail closed);allow(`--yes`)= ask 放行
- [x] 4.2 `app/main.py`:解析 `--yes` 参数传入 approval_mode=allow;headless 缺省 deny(未确认不得执行)
- [x] 4.3 `tools/registry.py`:`make_tools` 注入 workspace(供 classify_file 判定);`BashTool` 等工具构造不变(无状态保持)
- [x] 4.4 测试(`tests/test_container.py` / `tests/test_cli.py` 增量):三种模式装配断言、headless 拒绝敏感命令不挂起、`--yes` 放行、CLI 对未知事件类型静默忽略

## 5. TUI 确认交互(app/tui)

- [x] 5.1 `backend.py`:增 `on_confirmation_response(handler)` 端口(批准/拒绝/拒绝并中止)
- [x] 5.2 `view.py`:`confirmation_requested` 事件 → 确认条状态(摘要/原因);y/n/Esc 分派(确认激活时优先于补全键位);响应经 `manager.current.respond_approval(id, bool)`;Esc = 拒绝 + `abort()`
- [x] 5.3 `textual_backend.py`:`_InputArea` 确认激活键位拦截(y/n/Esc);确认条渲染(composer 上方,仿 suggestions 浮层)
- [x] 5.4 `components.py`:ToolCallBlock 增「待确认/已拒绝」状态(拒绝 → error 图标 + 原因摘要);`TuiModel` 处理新事件
- [x] 5.5 测试(`tests/tui/test_view.py` / `test_components.py` / `test_textual_backend.py` 增量):确认条显示、y/n 响应、Esc 中止、拒绝状态渲染、多个请求逐个呈现、键位归属

## 6. 收尾

- [x] 6.1 全量离线测试全绿;`openspec validate --change security-permissions` 通过
- [x] 6.2 文档同步:v0.2.md 阶段 3 任务状态(T-40/T-41)与变更记录(E 记录);specs 主文件同步(core/sessions/tools/tui)或随归档执行
