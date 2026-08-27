## Context

当前 `.github/workflows/ci.yml` 在 Ubuntu 上执行 pytest、版本一致性、补丁格式和 OpenSpec 校验；项目没有覆盖率、静态检查、构建安装冒烟或多平台矩阵。TUI 已有离线性能基准，但尚未形成稳定的 CI 性能观测流程。

## Goals / Non-Goals

**Goals:**

- 建立快速反馈、完整 PR 验证和发布/夜间验证三类门禁。
- 验证 Linux、Windows、macOS 下的关键行为。
- 验证包构建、安装和实际 CLI entry point。
- 逐步引入覆盖率与静态检查，并保持本地命令与 CI 一致。

**Non-Goals:**

- 不在普通 CI 中调用真实模型或需要 API key 的服务。
- 不让性能波动直接成为初期 PR 的硬失败条件。
- 不在本变更中修改应用运行时架构。

## Decisions

### 1. 使用三类 CI job

- `quality-fast`：静态检查、OpenSpec、快速单元/契约测试。
- `test-matrix`：Linux、Windows、macOS 上的完整离线测试和平台测试。
- `package-smoke`：构建 wheel、安装到临时环境、执行 `codeagent --prompt`。

性能基线单独运行或作为非阻塞告警 job，避免普通 PR 受共享 runner 波动影响。

### 2. 覆盖率先观察后强制

第一阶段生成覆盖率报告并记录基线，不立即设置过高失败阈值。基线稳定后再按包逐步提高阈值，重点关注 `core`、`session`、`tools/security` 和组合根，而不是追求无意义的行覆盖。

### 3. 平台矩阵只验证真实差异

Linux、Windows、macOS 共享大部分离线测试；bash、subprocess、路径、权限、MCP stdio 和 TUI 终端相关用例通过 marker 或平台选择器运行。平台专用断言必须说明差异原因，不能简单复制三份测试。

### 4. 构建安装使用隔离环境

package smoke job 在临时虚拟环境安装构建产物，验证 console script、内建 resources 和 fake provider。它不复用仓库开发环境，避免“源码可导入但发行包不可用”。

### 5. 性能使用基线与相对阈值

保存 TUI 渲染、恢复和内存指标的结构化结果；初期只对明显回归告警，待 runner 和样本稳定后再设置相对基线阈值。

## Risks / Trade-offs

- [多平台 CI 成本增加] → 快速 job 保持单平台，完整矩阵只执行稳定的离线测试。
- [覆盖率阈值阻碍重构] → 先报告、后分模块设阈值，并允许明确排除测试辅助代码。
- [构建 smoke 增加维护成本] → 使用 fake provider 和固定最小命令，避免网络依赖。
- [性能指标受 CI 机器噪声影响] → 使用多次样本、相对变化和非阻塞告警。

## Migration Plan

1. 依赖前两个变更建立稳定测试命令和 marker。
2. 将现有 CI 命令拆分为快速质量 job 和测试 job。
3. 增加覆盖率、静态检查和超时保护。
4. 增加 Windows/macOS 矩阵及平台测试选择。
5. 增加构建安装 smoke 和性能报告。
6. 根据至少一轮稳定 CI 数据决定是否启用硬性覆盖率/性能阈值。

回滚方式是关闭新增 job 或恢复旧 workflow；不影响应用代码和用户数据。
