## Context

See proposal.md - Why. 当前 `AgentLoopConfig` 已能承载各类扩展，但 `app/composition/runtime/factory.py`、session 工厂和 TUI 配置分别接收参数；SessionManager 的模型配置恢复还依赖调用方重复传递 Hook。

## Goals / Non-Goals

**Goals:**

- 在 app/composition 建立唯一的扩展归一化和注入接缝。
- 在创建、恢复、模型切换和 TUI 重建中保留扩展对象、顺序和配置。
- 保持 core/session 不依赖具体应用实现，兼容现有散装参数。

**Non-Goals:**

- 不实现 memory、审计、遥测或新的第三方扩展。
- 不改变 AgentLoopConfig 的 core 端口语义，不删除现有直接构造入口。
- 不改变生命周期事件、上下文消息、JSONL 或工具结果格式。

## Decisions

1. **组合对象放在 app/composition。** 新增不可变 `RuntimeExtensions`，只作为应用侧装配载体，字段使用 core 已有协议类型；core 不反向导入该对象，避免架构循环。

2. **组合根优先、旧参数兼容。** 工厂新增可选 `extensions` 参数；当调用方仍传 `lifecycle_hooks` 时，将其转换为默认扩展集合。若两者同时存在，显式扩展集合作为主配置，旧 Hook 参数只在集合未提供时作为兼容补充。

3. **恢复链携带同一集合。** `create_agent_config`、`create_agent_session`、`create_session_manager` 和 TUI assembler 保存并透传 `RuntimeExtensions`；模型切换只替换 model/tool 资源，不重新生成空扩展集合。

4. **架构测试检查两类事实。** AST 测试继续锁定 core/session 的禁止导入；组合测试用可识别的回调对象验证创建、session 恢复和 TUI 重建后注入对象身份及顺序不变。

## Risks / Trade-offs

- [扩展集合增加工厂参数] → 保留现有散装参数，迁移可渐进完成。
- [恢复配置闭包捕获扩展集合] → 只捕获不可变的 `RuntimeExtensions`，避免每次恢复时重新发现或实例化扩展。
- [测试依赖资源工厂桩] → 复用现有 fake provider 和组合根夹具，不引入真实网络或凭据。

## Migration Plan

1. 增加 `RuntimeExtensions` 和组合根归一化辅助函数。
2. 将 runtime/session/TUI 工厂接入该对象，并补充恢复和重建回归。
3. 更新架构、v0.4 和测试文档，验证后归档；默认调用方无需迁移。
