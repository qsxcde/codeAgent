## Why

v0.4 的包版本、发布说明和构建检查已经完成，但正式标签和当前文档仍停留在“发布准备”状态，导致 v0.5 无法引用一个明确、可复现的发布基线。现在需要把最后一个纯发布收尾动作固定下来，并让所有面向维护者的状态描述与 Git 历史一致。

## What Changes

- 将纯 v0.4 最终提交 `b981534` 固定为 `v0.4.0` Git 标签，不把后续 V5-01 实现纳入 v0.4 标签。
- 将 v0.4 迭代文档、README、架构文档和需求分析中的发布状态从“待创建标签”更新为已固定的 `v0.4.0` 基线。
- 保留带日期的测试与 CI 历史快照，并明确它们与当前 v0.5 开发工作树的关系。
- 重新执行发布检查、测试、静态检查、OpenSpec 校验和构建，记录可复现的验收证据。

## Capabilities

### New Capabilities

无。本变更只涉及发布基线、文档事实和 Git 标签，不新增运行时行为。

### Modified Capabilities

无。没有改变任何 OpenSpec 行为契约，因此使用 `skip_specs: true`。

## Impact

- 影响 `docs/iteration/v0.4.md`、`docs/iteration/v0.5.md`、`docs/design/architecture.md`、`docs/design/requirements-analysis.md`、`README.md` 和可能的发布说明链接。
- 新增一个 Git annotated tag `v0.4.0`，目标提交固定为 `b981534`；需要将标签推送到 GitHub。
- 不修改 Python 运行时代码、公共 API、依赖、会话格式或测试行为。
