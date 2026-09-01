## Context

`pyproject.toml`、`src/codeagent/__init__.py`、`uv.lock` 和 `CHANGELOG.md` 已经将发布版本固定为 `0.4.0`，并且 `b981534` 是当前历史上最后一个只包含 v0.4 能力的提交。其后的 `c56f9b8` 已开始 v0.5 的 V5-01 实现，因此标签不能直接指向当前 HEAD。当前面向用户和维护者的文档仍使用“发布准备”或“标签待创建”的表述，需要在不改写历史测试快照的前提下完成收口。

## Goals / Non-Goals

**Goals:**

- 创建指向 `b981534` 的 annotated `v0.4.0` 标签，并推送到 `origin`。
- 统一当前状态文档对 v0.4 发布状态、标签目标和 v0.5 起点的描述。
- 通过现有 release check、测试、Ruff、OpenSpec 和构建命令固定发布证据。
- 让变更可回滚：文档修改可由提交回退，标签目标保持不可变。

**Non-Goals:**

- 不修改 Python 运行时、公共接口、依赖、会话格式或 v0.5 Subagent 行为。
- 不把 V5-01 或后续 v0.5 提交纳入 `v0.4.0` 标签。
- 不在本变更中创建 GitHub Release 页面或发布到 PyPI；这些是独立的发布操作。

## Decisions

### 1. 标签固定到历史 v0.4 提交

使用 `git tag -a v0.4.0 b981534 -m "发布 v0.4.0"` 创建 annotated tag，再使用 `git push origin v0.4.0` 推送。选择历史提交而不是 HEAD，是为了保证 v0.4 基线不包含 V5-01；annotated tag 保留发布说明和可审计的创建者/时间信息。若本地或远端已存在同名标签，任务应停止并报告，不覆盖已有标签。

### 2. 只更新当前状态段落

在 `README.md`、`docs/iteration/v0.4.md`、`docs/design/architecture.md` 和 `docs/design/requirements-analysis.md` 中只修改当前状态、发布状态和路线表等面向当前读者的段落；带日期的历史快照继续保留原文。`docs/iteration/v0.5.md` 增加 V5-00 的完成记录，明确 v0.4 标签提交与当前 v0.5 HEAD 的边界。

### 3. 使用现有质量门禁作为证据

沿用仓库既有的 `uv run pytest -q`、`uv run ruff check src tests scripts`、`openspec validate --specs --strict`、`git diff --check`、`uv build` 和 `scripts/release_check.py`。不新增依赖或新的发布脚本；如果构建生成报告或产物，只保留仓库已有的忽略规则覆盖的临时文件。

## Risks / Trade-offs

- [标签目标错误] → 在创建前校验 `git rev-parse b981534`，创建后校验 `git rev-list -n 1 v0.4.0` 与目标一致；若远端标签冲突则不强制覆盖。
- [文档历史快照被误改] → 只修改明确的当前状态段落，并用 `git diff` 检查替换范围。
- [发布证据与当前 HEAD 混淆] → 文档分别标注 v0.4 标签基线和 v0.5 当前工作树测试结果。
- [远端推送失败] → 保留本地 annotated tag 和提交，报告远端状态，不执行删除或强制推送。

## Migration Plan

1. 确认工作树无未提交的非本变更内容，并验证 `b981534` 的父子关系和版本元数据。
2. 更新当前状态文档与 v0.5 计划，执行 diff 检查。
3. 运行发布检查、测试、静态检查、OpenSpec 校验和构建。
4. 创建并校验本地 `v0.4.0` 标签，推送标签和文档提交到 GitHub。
5. 如需回滚，回退文档提交；标签不重写，发布纠正通过新的说明或后续版本处理。
