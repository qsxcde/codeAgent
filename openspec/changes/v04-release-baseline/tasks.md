## 1. 发布目标与文档边界

- [x] 1.1 校验 `b981534` 是最后一个纯 v0.4 提交，确认其中的包版本、CHANGELOG 和 release check 状态均为 `0.4.0`，并记录它不能包含 V5-01。
- [x] 1.2 更新 `docs/iteration/v0.4.md`、`README.md`、`docs/design/architecture.md` 和 `docs/design/requirements-analysis.md` 的当前发布状态，保留带日期的历史测试快照。
- [x] 1.3 更新 `docs/iteration/v0.5.md` 的 V5-00 状态和起点说明，区分 `v0.4.0` 标签基线与包含 V5-01 的当前工作树。

## 2. 发布验证与标签

- [x] 2.1 运行 `uv run pytest -q`、`uv run ruff check src tests scripts`、`openspec validate --specs --strict`、`git diff --check` 和 `uv build`，确认文档变更没有破坏现有质量门禁。
- [x] 2.2 运行 `uv run python scripts/release_check.py --dist-dir artifacts/v04-release-dist --output artifacts/v04-release-check.json`，确认 wheel/sdist、资源、干净安装和 fake provider CLI 检查通过。
- [x] 2.3 创建 annotated `v0.4.0` 标签指向 `b981534`，验证 `git rev-list -n 1 v0.4.0` 与目标提交一致；若标签已存在或目标不一致则停止，不覆盖。
- [x] 2.4 提交本变更并将文档提交与 `v0.4.0` 标签推送到 `origin`，记录提交 ID、标签目标和验证结果。
