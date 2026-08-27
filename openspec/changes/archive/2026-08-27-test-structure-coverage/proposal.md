## Why

测试数量持续增长，但 `test_view.py`、`test_store.py`、`test_session.py`、`test_container.py` 和 `test_tools.py` 已同时承担多个职责。测试文件过大使失败定位、fixture 复用和行为覆盖检查变得困难；同时，部分关键流程仍缺少明确的契约、端到端和跨平台测试边界。

## What Changes

- 按行为和测试层级拆分大型测试文件，保留源代码镜像关系。
- 建立 Provider、Store、Tool、Session 和分层依赖的契约测试。
- 抽取可复用的 fake model、session、backend 和工具构造器。
- 补充 CLI 入口、会话活动时间戳、会话恢复、工具确认、MCP 生命周期和 TUI 关键流程测试，并同步落地缺失的活动时间产品契约。
- 将 MCP、Git、subprocess、CLI 和真实 Textual 后端测试明确标记为集成或端到端测试。
- 增加 Windows、Linux、macOS 差异行为的测试组织和平台专用用例。
- 识别并清理会阻止后续删除兼容入口的旧兼容测试。

## Capabilities

### New Capabilities

补充会话 `last_activity_at` 产品契约,其余内容主要重组测试并补充测试行为。

### Modified Capabilities

无。`.openspec.yaml` 使用 `skip_specs: true` 声明这是纯测试工程变更。

## Impact

- 影响 `tests/` 的目录结构、fixture 组织、测试命名和 marker。
- 可能新增测试专用依赖和平台专用测试辅助程序。
- 除 `last_activity_at` 这一已由本变更明确纳入的会话产品契约外，不修改其他生产代码行为；如发现新的缺失产品行为，应单独建立产品变更。
- 依赖 `test-foundation-stability` 提供稳定的异步、超时和隔离基础。
