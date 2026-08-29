## 1. 目录结构与导入迁移

- [x] 1.1 新增目录结构契约测试，验证 `codeagent.session.manager` 和 `codeagent.session.persistence.jsonl` 的真实入口，并先锁定旧的平铺 JSONL 模块应被移除。
- [x] 1.2 将 `session/manager.py`、`manager_operations.py` 和 `manager_registry.py` 归并为 `session/manager/` 子包，设置 `manager/__init__.py` 的 `SessionManager` 导出，并迁移内部相对导入。
- [x] 1.3 将 `persistence/jsonl_store.py`、`jsonl_reading.py`、`jsonl_writing.py`、`jsonl_indexing.py` 和 `jsonl_forking.py` 归并为 `persistence/jsonl/` 子包，保持 mixin 顺序、模块级 `_now` 测试缝隙和锁/索引调用顺序。
- [x] 1.4 将生产代码、测试和文档中的直接模块导入迁移到 `codeagent.session.persistence` 或 `codeagent.session.persistence.jsonl`，同步更新 monkeypatch 路径和 `persistence/__init__.py` 导出。
- [x] 1.5 删除旧的 `persistence.jsonl_store`、`persistence.jsonl_reading`、`persistence.jsonl_writing`、`persistence.jsonl_indexing` 和 `persistence.jsonl_forking` 平铺模块，确认旧路径不可导入且包级公开入口仍可用。

## 2. 文档与质量约束

- [x] 2.1 更新 `docs/design/architecture.md` 和 `docs/design/session-layout.md`，记录 manager/jsonl 的新目录树、规范入口及直接模块路径变更。
- [x] 2.2 更新或补充 session 规模扫描与模块边界契约，确保 `session/manager/`、`persistence/jsonl/` 下文件不超过 300 行、函数不超过 80 行，且不产生循环导入。

## 3. 回归验证

- [x] 3.1 运行 manager、persistence、session、app container 和 contract 相关窄测试，确认会话创建、切换、分叉、恢复、压缩、用量和索引行为不变。
- [x] 3.2 运行 `uv run ruff check src tests scripts`、`git diff --check`、session 规模扫描和 `openspec validate --specs`，检查差异只包含本次目录重组。
- [x] 3.3 运行完整离线测试 `uv run pytest -q`，再执行 `openspec validate nest-session-responsibility-modules --type change --strict --no-interactive` 并汇总迁移限制。
