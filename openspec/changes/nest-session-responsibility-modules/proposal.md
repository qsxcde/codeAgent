## Why

`session` 的职责已经完成拆分，但管理器辅助模块仍散落在根目录，JSONL 的读取、写入、索引和分叉模块也直接铺在 `persistence/` 下。继续按当前布局新增代码会让同一职责重新扩散，降低模块发现性和边界检查的有效性。

## What Changes

- 新增 `session/manager/` 子包，将管理器外观、会话操作和注册表实现归并到同一职责目录。
- 新增 `session/persistence/jsonl/` 子包，将 JSONL 存储外观、读取、写入、索引和分叉实现归并到同一职责目录。
- 更新所有生产代码、测试和文档导入，公共包级导出保持可用，持久化格式、运行行为和错误语义不变。
- 更新规模扫描和架构文档，防止新的管理器或 JSONL 细节重新散落到职责目录之外。
- 仅职责子包内部模块路径调整；`codeagent.session`、`codeagent.session.persistence` 和 `codeagent.session.runtime` 的公开导出保持不变。

## Capabilities

### New Capabilities

<!-- Pure package-layout refactor; no new runtime capability. -->

### Modified Capabilities

<!-- No requirement-level behavior changes. -->

## Impact

- 受影响代码：`src/codeagent/session/manager.py`、`src/codeagent/session/manager_operations.py`、`src/codeagent/session/manager_registry.py`、`src/codeagent/session/persistence/jsonl_*.py` 和相关导入。
- 受影响文档与测试：session 架构说明、模块边界契约、持久化和管理器测试。
- 不新增依赖，不改变 JSONL 文件格式、会话数据和外部运行行为。
- 由于本变更只调整职责目录，按仓库约定跳过行为规格增量，使用 `skip_specs: true`。
