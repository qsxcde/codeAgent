## 1. 建立测试执行基础

- [x] 1.1 记录当前测试收集数量、重点测试命令和现有全量基线
- [x] 1.2 在 pytest 配置中定义 unit、contract、integration、e2e、platform、security、performance、slow markers
- [x] 1.3 增加本地可复现的快速测试、集成测试和全量测试命令说明
- [x] 1.4 明确声明 pytest 异步测试插件和测试辅助依赖

## 2. 统一异步与资源生命周期

- [x] 2.1 选取代表性的 core、session、tools 和 TUI 异步测试迁移到统一 async 测试风格
- [x] 2.2 批量迁移剩余可迁移的 `asyncio.run()` 测试并保留原有行为断言（同步 `run_sync()` 回归测试保留 `asyncio.run`）
- [x] 2.3 为后台任务、MCP 客户端、模型客户端和 subprocess 增加统一清理 fixture
- [x] 2.4 为可能挂起的异步和进程测试增加可诊断的超时保护

## 3. 消除时间与调度脆弱性

- [x] 3.1 移除会话最近排序测试中的固定 `sleep`，改用确定性时间或受控 clock
- [x] 3.2 检查所有基于短时间窗口的 TUI、MCP 和进程测试并改为事件驱动等待
- [x] 3.3 将 subprocess 超时测试调整为跨平台且可重复的测试场景
- [x] 3.4 增加任务取消、超时和资源回收后的状态断言

## 4. 抽取共享测试资源

- [x] 4.1 将 FakeClient、fake model 和模型事件构造器整理到 tests/fixtures
- [x] 4.2 将 FakeBackend、TUI 输入和渲染辅助器整理到 tests/fixtures
- [x] 4.3 将 session、store、工具和隔离配置构造器整理到 tests/fixtures
- [x] 4.4 为共享 fixture 增加最小权限和 teardown 检查，避免污染全局状态

## 5. 阶段验收

- [x] 5.1 分别执行快速、集成和标记测试，确认 marker 分类无遗漏
- [x] 5.2 重复执行时间敏感和 subprocess 测试，确认不再依赖偶然调度
- [x] 5.3 更新测试开发文档，记录异步、超时、fixture 和清理约定
