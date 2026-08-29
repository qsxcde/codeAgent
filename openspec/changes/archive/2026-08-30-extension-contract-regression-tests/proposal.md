## Why

v0.4 已完成生命周期 Hook、上下文扩展和统一组合根装配，但相关回归分散在多个测试文件。V4-32 需要把扩展端口的关键行为固化为可重复的契约测试，避免后续重构破坏顺序、取消、异常、上下文临时视图或工具结果治理。

## What Changes

- 增加一组聚焦 core 扩展契约的离线回归测试，覆盖多个 Hook 顺序和返回值语义。
- 覆盖同步/异步上下文修改、工具结果修改、扩展异常和取消路径，验证模型调用、错误事件、回滚和清理边界。
- 复用现有 FakeClient、内存工具和 pytest asyncio 夹具，不新增依赖，不改变生产行为或持久化格式。
- 同步测试文档与 v0.4 完成状态，并将变更作为测试型 OpenSpec 归档。

## Capabilities

### New Capabilities

无。本变更只补齐既有扩展契约的回归覆盖。

### Modified Capabilities

无。运行时行为保持既有 `core`、`session` 和 `lifecycle-hooks` 规格。

## Impact

- 影响 `tests/core/`、必要的 `tests/session/behavior/` 和测试文档。
- 不修改运行时实现，除非契约测试暴露既有实现与已声明规格不一致的问题。
- 不新增第三方依赖，不改变 API、事件格式或 JSONL 数据。
