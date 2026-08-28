## Why

当前 CI 已执行测试、版本检查、补丁格式检查和 OpenSpec 校验，但仍只有 Linux 单平台，缺少覆盖率、静态检查、构建安装冒烟和真实 CLI 入口验证。项目因此能够证明单元行为大致可用，却不能持续证明跨平台兼容性和可发布性。

## What Changes

- 将测试按快速门禁、完整 PR 门禁和发布/夜间门禁分层执行。
- 在 CI 中增加 Windows、Linux、macOS 平台矩阵。
- 增加测试超时、覆盖率报告和逐步收紧的覆盖率门槛。
- 增加 Ruff 等基础静态检查，并保持检查结果可在本地复现。
- 增加 wheel 构建、临时虚拟环境安装和 `codeagent --prompt` smoke 测试。
- 将 MCP、跨平台 bash、性能基线和端到端测试纳入合适的 CI 阶段。
- 对性能测试采用基线与告警机制，避免不稳定的绝对耗时阈值直接阻塞普通 PR。

## Capabilities

### New Capabilities

无。本变更只增加工程质量门禁，不新增运行时产品能力。

### Modified Capabilities

无。`.openspec.yaml` 使用 `skip_specs: true` 声明这是纯测试与 CI 工程变更。

## Impact

- 影响 `.github/workflows/ci.yml`、`pyproject.toml`、开发依赖和测试执行命令。
- 可能增加 CI 执行时间和平台维护成本，需要通过分层门禁控制反馈速度。
- 依赖 `test-foundation-stability` 的稳定测试基础，并建议在 `test-structure-coverage` 完成后接入完整测试分层。
