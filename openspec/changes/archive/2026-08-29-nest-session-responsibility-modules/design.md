## Context

上一变更已将 session 的运行时、持久化和导航职责拆开，但管理器的三个实现文件仍位于 `session/` 根目录，JSONL 的五个实现文件仍位于 `persistence/` 根目录。`codeagent.session` 和 `codeagent.session.persistence` 已经承担稳定包级导出，因此本次只调整内部模块路径，不改变对象行为或 JSONL 数据格式。

## Goals / Non-Goals

**Goals:**

- 将管理器相关实现集中到 `session/manager/`，让 `SessionManager` 的外观、操作和注册表边界在同一目录内可发现。
- 将 JSONL 相关实现集中到 `session/persistence/jsonl/`，区分 JSONL 文件实现与通用协议、模型、锁和提交协调。
- 保留 `from codeagent.session import AgentSession, EventBus, SessionManager`、`from codeagent.session.persistence import JsonFileStore, MemoryStore` 等包级入口。
- 迁移生产代码、测试和文档中的直接模块导入，并用规模扫描和入口契约测试锁定布局。

**Non-Goals:**

- 不改变会话运行、生命周期、压缩、分叉、用量、错误或取消语义。
- 不改变 JSONL 版本、记录格式、索引格式和已有用户数据。
- 不新增依赖，不把 `session` 根目录再次变成新的聚合实现文件。

## Decisions

### 1. 使用 `manager` 子包承载管理器实现

将当前 `manager.py`、`manager_operations.py` 和 `manager_registry.py` 移动为 `manager/manager.py`、`manager/operations.py` 和 `manager/registry.py`，由 `manager/__init__.py` 导出 `SessionManager`。这样 `codeagent.session.manager` 仍是可导入的包入口，`codeagent.session` 的稳定导出无需变化。

备选方案是保留三个文件在根目录，仅增加命名约定；该方案不能阻止同职责文件继续散落，因此不采用。

### 2. 使用 `persistence/jsonl` 子包承载 JSONL 实现

将 `jsonl_store.py`、`jsonl_reading.py`、`jsonl_writing.py`、`jsonl_indexing.py` 和 `jsonl_forking.py` 移动为 `persistence/jsonl/store.py`、`reading.py`、`writing.py`、`indexing.py` 和 `forking.py`，由 `jsonl/__init__.py` 导出 `JsonFileStore`。`persistence/__init__.py` 改从 `persistence.jsonl` 挂载该对象。

`codeagent.session.persistence.jsonl_store` 属于上一阶段的实现模块路径，不作为新的稳定 API 保留；仓库内所有引用统一切换到 `codeagent.session.persistence` 或 `codeagent.session.persistence.jsonl`。这样不会留下新的转发门面，且职责入口唯一。

### 3. 通过重命名保持内部依赖和测试缝隙

移动后只调整 import 路径、模块级 monkeypatch 路径和文档路径；JSONL 类的 mixin 继承顺序、`_now` 测试缝隙、索引锁和提交调用顺序保持不变。使用 `git diff --find-renames` 检查移动识别，避免把纯移动误报为删除重写。

### 4. 用结构契约防止回退

新增契约测试验证 `manager`、`persistence.jsonl` 的真实入口和包级导出，同时检查旧的平铺 JSONL 模块不可导入。规模测试扫描整个 `session/` 树，确保目录重组后仍满足文件不超过 300 行、函数不超过 80 行。

## Risks / Trade-offs

- [直接导入 `persistence.jsonl_store` 的外部调用方会受到影响] → 将其视为内部模块路径变更，在架构迁移文档中明确使用 `persistence` 或 `persistence.jsonl`；包级公开入口保持不变。
- [移动后 monkeypatch 仍指向旧模块] → 在仓库测试中统一改为 `persistence.jsonl.store` 的真实模块路径，并保留 `_now` 模块缝隙。
- [目录包与旧模块同名关系导致循环导入] → `jsonl/__init__.py` 只导出 `JsonFileStore`，实现模块只依赖通用 `persistence` 模块，不从 `session` 根包反向导入。

## Migration Plan

1. 先新增目录契约测试，使旧平铺路径在移动前呈现预期失败。
2. 移动 manager 和 JSONL 文件，更新所有生产代码、测试和文档导入。
3. 更新 `persistence` 与 `session` 包级导出，运行 manager、store、app 和 contract 测试。
4. 运行全量测试、Ruff、差异检查、规模扫描和 OpenSpec 校验。

回滚时只需恢复移动前的模块路径和导入；本变更不触碰用户会话文件，因此不需要数据回滚。
