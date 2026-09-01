## 1. 核心值对象与错误契约

- [x] 1.1 在 `src/codeagent/core/contracts/subagents.py` 中定义 provider-neutral 的 `SubagentStatus`、稳定 reason code、`SubagentBudget` 和最小上下文事实类型。
- [x] 1.2 定义不可变的 `SubagentRequest`、`SubagentFailure` 和 `SubagentResult`，校验必需标识、深度、预算、终态约束以及请求与结果的归属一致性。
- [x] 1.3 在 `src/codeagent/core/contracts/errors.py` 中增加请求校验错误和非法状态转换错误，保留稳定错误 code，不携带具体 provider 或 Session 类型。

## 2. 委派状态机与运行器端口

- [x] 2.1 实现独立的 `SubagentState`，覆盖 created、queued、starting、running、waiting_confirmation、cancelling 和全部终态的合法转换。
- [x] 2.2 实现终态提交保护：同一 `delegation_id` 只允许一个终态，重复相同结果幂等，冲突终态和终态后的过程转换被拒绝。
- [x] 2.3 固定预算耗尽、超时、父级取消、确认中止、权限拒绝和执行失败的状态与 reason code 映射，并保留 `cleanup_uncertain` 诊断。
- [x] 2.4 在 `src/codeagent/core/contracts/subagents.py` 中定义 `SubagentRunner` 异步端口和事件回调类型，只暴露请求、结构化终态结果和按 `delegation_id` 的取消能力。

## 3. 父子事件与公共边界

- [x] 3.1 为 `src/codeagent/core/contracts/events.py` 的 `AgentEvent` 增加可选的 delegation、父子 run、attempt、depth、Subagent 状态和子阶段关联字段，并保持旧 metadata-only 事件可消费。
- [x] 3.2 固定事件关联规则：父级委派事件保留父 `run_id`，子 Agent 原生事件保留子 `run_id`，关联字段不得覆盖事件所属运行标识。
- [x] 3.3 从 `src/codeagent/core/contracts/__init__.py` 和 `src/codeagent/core/__init__.py` 导出新增公共契约，确保不引入 `ai`、`tools`、`session` 或 `config` 依赖。
- [x] 3.4 更新 core 包结构和公共对象身份测试，确认新增模块位于 contracts 职责目录且没有兼容平铺入口。

## 4. 回归测试

- [x] 4.1 在 `tests/core/` 增加请求、预算、失败结果和终态结果不变量的单元测试。
- [x] 4.2 使用 FakeRunner 覆盖正常路径、排队取消、确认等待、启动失败、预算耗尽、超时、父级取消和清理不确定场景。
- [x] 4.3 覆盖非法状态转换、重复终态、迟到结果、完成/取消竞态和不同 `attempt_id` 的重试隔离。
- [x] 4.4 增加事件关联字段、typed 字段与 metadata 兼容读取、父子 `run_id` 归属和旧事件消费者兼容测试。
- [x] 4.5 扩展 core import-boundary、模块规模和公共门面测试，确认阶段 1 没有改变现有单 Agent ReAct 行为。

## 5. 验证与文档同步

- [x] 5.1 运行相关 core 单元/契约测试、Ruff、`git diff --check` 和 `openspec validate --specs`，修复发现的问题。
- [x] 5.2 运行完整离线测试，确认现有 Session、工具和 Agent 生命周期回归通过。
- [x] 5.3 在 `docs/iteration/v0.5.md` 中仅在实现和验证完成后更新 V5-01 状态及验证证据，明确真实运行器仍属于后续变更。
