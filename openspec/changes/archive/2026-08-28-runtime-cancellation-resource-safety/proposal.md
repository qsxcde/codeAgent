## Why

当前取消操作主要依赖 `Task.cancel()`，会话切换、释放和关闭也可能在后台工具、确认等待或 MCP/subprocess 清理完成前继续执行。工具清理结果还存在“具备取消接口但实际清理未确认”的误判，容易造成资源泄漏、迟到事件和副作用不确定时的错误重试。

## What Changes

- 区分取消请求、取消传播、工具清理和运行最终结束四个阶段。
- 为模型、异步工具、同步线程工具、subprocess 和 MCP 资源定义统一的清理结果语义。
- 增加等待运行真正空闲和异步关闭资源的生命周期入口，切换/释放/退出时等待清理完成。
- 将确认响应改为活动请求管理，处理过期响应、确认超时和取消，不保留悬挂等待。
- 固定 steer 只能在工具批次完成后注入，follow-up 只能在当前 turn 完成后启动。
- 当无法证明外部副作用已经停止时，明确标记 `cleanup_uncertain`，禁止自动重试。

## Capabilities

### New Capabilities

无。本变更强化已有运行干预、工具执行和确认能力。

### Modified Capabilities

- `core`: 修改“受控工具执行”和“运行干预”，明确取消、清理、steer 和 follow-up 的边界。
- `sessions`: 修改“确认响应”，增加活动请求、超时、取消和过期响应语义。
- `tools`: 修改“工具执行资源状态”，使清理状态反映实际可证明结果。

## Impact

- 影响 `src/codeagent/core/execution.py`、`src/codeagent/core/loop.py`、`src/codeagent/core/agent.py`、`src/codeagent/session/runtime/controller.py`、`src/codeagent/session/runtime/confirmation.py` 和 `src/codeagent/session/manager.py`。
- 影响 MCP、bash/subprocess 和模型客户端的关闭适配，但不改变各工具的业务功能。
- 可能新增异步生命周期 API；现有快速 `abort()` 保留为请求入口，调用方需要在切换或关闭时等待完成。
- 不引入自动重试；不把“取消请求已发出”展示为“资源已经清理完毕”。
