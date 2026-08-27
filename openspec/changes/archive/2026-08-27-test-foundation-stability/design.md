## Context

当前测试按源码模块分包，但大量异步测试通过 `asyncio.run()` 驱动，少数测试使用 `pytest.mark.anyio`；会话管理测试还依赖固定的毫秒级 `sleep`，工具和 MCP 测试包含 subprocess 生命周期。测试配置目前只有 `testpaths`，没有统一的 marker、超时和执行层级。

## Goals / Non-Goals

**Goals:**

- 让测试执行方式、异步生命周期、时间和资源清理具有统一约定。
- 提供可复用且相互隔离的 fake、fixture 和构造器。
- 为后续测试拆分和 CI 分层提供稳定基础。

**Non-Goals:**

- 不在本变更中重写业务测试断言。
- 不改变生产运行时行为或公共 API。
- 不在本阶段引入真实模型、真实凭据或网络测试。

## Decisions

### 1. 使用 asyncio 专用测试模式

项目核心运行时基于 asyncio，因此统一采用 `pytest-asyncio` 的自动模式，异步测试直接使用 `async def`。现有 anyio 测试迁移为同一风格，避免同时维护两套事件循环入口。

备选方案是继续使用 anyio，但当前项目没有使用 trio 的需求，保留抽象层会增加 fixture 和插件配置复杂度。

### 2. 以确定性事件替代固定睡眠

测试中的时间排序使用注入或 monkeypatch 的 clock、显式时间值和完成事件；不使用“睡眠若干毫秒来等待排序稳定”。异步完成使用 `Event`、任务状态或受控 fake，而不是依赖调度器刚好运行。

### 3. 在测试边界统一超时与清理

为异步测试、subprocess 和 MCP 测试设置统一的 runner timeout，并在 fixture 的 teardown 中关闭客户端、任务、后台线程和临时资源。测试应能区分业务超时、清理不确定和测试本身超时。

### 4. 保留一个共享 fixture 层

将 fake model、TUI backend、session builder、内存文件系统和隔离配置集中到 `tests/conftest.py` 或 `tests/fixtures/`。fixture 只提供测试所需的最小能力，避免把组合根真实装配逻辑复制到每个测试文件。

### 5. 先加 marker，不立即移动所有文件

第一步通过 marker 和执行命令建立测试层级，目录拆分留给 `test-structure-coverage`。这样可以先验证测试分类和稳定性，再进行大规模文件迁移。

## Risks / Trade-offs

- [异步框架迁移引入行为差异] → 先迁移少量代表性测试，保留原测试结果作为基线，再批量迁移。
- [更严格的超时暴露现有慢测试] → 先报告并分类，不立即用过低阈值阻塞全部测试。
- [fixture 过度抽象导致测试可读性下降] → fixture 只封装重复的环境构造，不隐藏关键业务输入和断言。
- [消除 sleep 需要生产代码可测试化] → 优先使用现有模块级时间函数的 monkeypatch；若必须改生产接口，另行拆出产品变更。

## Migration Plan

1. 记录当前测试收集基线和重点测试结果。
2. 增加 marker、异步测试配置和超时配置。
3. 抽取共享 fixture，并迁移异步与时间敏感测试。
4. 按模块运行快速测试和集成测试，确认行为基线不变。
5. 将稳定后的约定交给后续结构拆分和 CI 变更使用。

回滚方式是恢复 pytest 配置、开发依赖和测试入口；不涉及生产数据或运行时迁移。
