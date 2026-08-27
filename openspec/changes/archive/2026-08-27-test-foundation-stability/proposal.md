## Why

当前测试已经达到 923 个，但异步测试风格、时间依赖、进程超时和测试隔离策略不完全统一。部分测试依赖固定的毫秒间隔或很短的超时时间，在不同负载和平台下容易出现偶发失败，降低了测试结果的可信度和反馈速度。

## What Changes

- 建立统一的 pytest 测试分层标记和执行入口。
- 统一异步测试运行方式，减少测试内部反复创建事件循环。
- 移除基于固定 `sleep` 的时序断言，改用可控时钟、事件或确定性数据。
- 为 subprocess、MCP 和异步任务增加统一的超时与资源清理约束。
- 抽取共享 fixture、fake model、backend 和 session 构造器，强化测试隔离。
- 明确测试依赖，避免依赖传递安装的 pytest 插件。

## Capabilities

### New Capabilities

无。本变更只调整测试基础设施和开发流程，不新增运行时产品能力。

### Modified Capabilities

无。`.openspec.yaml` 使用 `skip_specs: true` 声明这是纯测试工程变更。

## Impact

- 影响 `tests/conftest.py`、pytest 配置、测试依赖和异步测试文件。
- 影响现有测试的执行命令和 marker 组织，但不改变生产代码 API。
- 为后续测试结构拆分和 CI 门禁提供稳定基础。
