# 测试结构与覆盖清单

## 当前基线

`test-foundation-stability` 完成后，测试按源码层级组织。经过拆分、契约集中和异步稳定性改造，2026-08-27 当前全量测试为 **944 passed**。大型文件的现状和本变更目标如下：

| 当前文件 | 当前职责 | 目标拆分 |
| --- | --- | --- |
| `tests/tui/test_view.py` | 生命周期、命令、会话、确认、状态、Skill/MCP、选择器 | `tests/tui/view/` 下按行为域拆分 |
| `tests/session/test_store.py` | JSONL、MemoryStore、索引、分叉、压缩、用量 | `tests/session/store/` 下按存储行为拆分 |
| `tests/session/test_session.py` | 运行、恢复、取消、确认、压缩、用量 | `tests/session/behavior/` 下按会话行为拆分 |
| `tests/test_container.py` | 装配、Provider、Session、TUI 和生命周期 | `tests/app/` 下按组合根行为拆分 |
| `tests/tools/test_tools.py` | 原子工具、bash、共享文件系统、注册表、安全边界 | `tests/tools/atomic/` 与既有 execution/security 测试 |

拆分的验收标准是：测试收集总数不减少；每个原测试名称只出现一次；共享 fixture 继续从 `tests/fixtures/` 加载；生产代码不因测试重组而修改。

## `last_activity_at` 状态

`SessionRef.last_activity_at` 已落地。新会话以创建时间初始化，成功追加消息时更新；JSONL 将初始值写入 header、消息写入时间写入 message entry，并由可重建索引聚合。旧 JSONL 缺少这些字段时回退到创建时间；MemoryStore 与 JSONL Store 的 `list()` 均按最近活动时间排序，`SessionManager.continue_recent()` 继续取列表末项。

## 目标目录

```text
tests/
├── contracts/              # 跨实现公共契约和分层边界
├── fixtures/               # fake model、session、TUI backend、资源 tracker
├── ai/                     # Provider、ChatClient、transport 行为
├── app/                    # 组合根和任务模式
├── core/                   # Agent、loop、消息和执行契约
├── mcp/                    # MCP 子进程集成
├── session/
│   ├── store/              # JSONL、MemoryStore、索引和记录
│   └── behavior/           # 运行、恢复、取消、确认、压缩和用量
├── tools/
│   ├── atomic/             # 原子文件工具和 bash
│   └── execution/          # subprocess 执行器和平台后端
└── tui/
    └── view/               # 生命周期、命令、会话、确认、状态、扩展
```

## 兼容测试生命周期

`tests/contracts/test_ai_import_boundaries.py`、`tests/contracts/test_runtime_boundaries.py` 和对应契约测试集中在 `tests/contracts/`。已删除入口的负向断言保留为公共契约，旧 facade/store 导出测试已迁移或删除；后续删除兼容入口时仍需同步复核契约测试。

## 分层验证

```bash
uv run pytest --collect-only -q --strict-markers
uv run pytest -m "unit or contract" -q
uv run pytest -m "integration or e2e or platform or compatibility" -q --strict-markers
uv run pytest -m compatibility -q
```
