## Why

v0.2 阶段 3 安全权限(FR-8.2 / FR-8.3 / NFR-S3 / NFR-S4):危险命令黑名单(FR-8.1)是硬拒绝,但「敏感但可救」的操作——bash 删除/推送/提权类命令、read/write/edit 越出工作区的访问——目前无用户确认环直接执行;文件工具对绝对路径(`/etc/passwd`、`~/secret`)直通无边界。对标 Claude Code 手动挡:敏感操作默认确认,未确认不得执行。

## What Changes

- **bash 确认环**:工具执行前经**循环层**策略判定(allow / ask / deny 三档)——黑名单 deny 不变(最高优先级);只读白名单命令(ls/cat/grep/pwd/git status 等)allow 免确认;敏感命令(rm -r、git push、git reset --hard、sudo、chmod -R、curl|sh、kill/pkill、mv 覆盖等,中等集合,规则表可注入扩展)ask 需用户确认;未确认不得执行(NFR-S3)。
- **确认等待与交互**:ask 档 emit 新事件 `CONFIRMATION_REQUESTED`(id/tool/summary/reason)并异步等待;多个待确认请求**逐个排队**呈现;无超时(手动挡),Esc 中止 = 拒绝并取消本轮(既有 CancelledError 回滚路径);拒绝结果回填 tool_result(带审计原因,模型可见);headless(CLI 无交互)→ 默认 deny(fail closed),`--yes` 逃生舱放行。
- **文件访问边界**:read/write/edit 注入工作区边界——越界**读**警告放行、越界**写/edit**必须确认;边界判定 realpath 级(防符号链接逃逸,`workspace/link → /etc/passwd` 必须拦住),目标存在时 `os.path.samefile` 兜底 macOS 大小写不敏感;判定平台无关。
- **审计**:确认/拒绝原因回填 tool_result 文本 + 事件流可订阅;JSONL 不新增 entry(approval 落盘留给 T-42 /undo 一并做)。
- 事件契约**增量**扩展(新增 1 类事件,订阅方忽略未知类型即可,非 BREAKING)。

## Capabilities

### New Capabilities

无(均为既有能力的扩展)。

### Modified Capabilities

- `core`:新增「工具执行确认」requirement(循环层 allow/ask/deny 决策与确认等待);「事件契约」requirement 扩展(新增 `CONFIRMATION_REQUESTED` 事件类型,契约只增不改)。
- `sessions`:新增「确认响应」requirement(会话持有确认队列、`respond_approval(id, approved)`、逐个排队、abort/Esc 取消语义)。
- `tools`:新增「文件访问边界」requirement(read/write/edit 工作区边界,读警告/写确认);「bash 命令执行」requirement 扩展(确认环三档语义,黑名单优先级不变)。
- `tui`:新增「确认交互」requirement(确认条 UI、y/n/Esc 键位归属、headless 形态由容器装配 deny 策略)。

## Impact

- `core/ports.py`:`ApprovalPolicy` 协议 + `PolicyDecision(allow/ask/deny, reason)` 数据类(core 只认识决策形态);
- `core/loop.py`:`run_turn` 增 policy 与确认队列参数;ask → emit 事件 + await;拒绝回填 error tool_result;
- `core/events.py`:新增 `CONFIRMATION_REQUESTED`(payload: id / tool / summary / reason);
- `session/session.py`:确认队列(与 steer 队列同机制)+ `respond_approval(id, bool)` 公开方法;abort 时待确认 await 随 CancelledError 自然取消;
- `tools/security.py`(新):纯分类器 `classify_bash(command)` + `within_workspace(path, workspace)`(tools 层知识,tools 层实现,离线可测);
- `tools/shared/paths.py`:新增边界判定函数(不动 `resolve_to_cwd` 既有语义);`tools/registry.py`:`make_tools` 注入 workspace;
- `app/container.py`:按形态装配 policy(TUI = ask + 交互队列;headless = deny + `--yes` 覆盖);`app/main.py`:`--yes` 参数;
- `app/tui/`:backend 增确认响应端口、view 确认条状态、键位分派(y/n/Esc,与补全浮层键位不重叠)、ToolCallBlock「待确认/已拒绝」状态;
- 依赖:无新增(纯标准库 + 既有事件总线);事件契约增量 10 → 11 类。

无 **BREAKING** 变更。
