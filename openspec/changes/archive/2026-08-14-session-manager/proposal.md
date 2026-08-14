## Why

阶段 1(self-built-orchestration)已落地 JSONL 树形存储与 `AgentSession`(会话恢复、steer/followup 已随阶段 1 完成),但会话生命周期仍缺管理层:每次启动只能新建/恢复单个会话,无法在多个会话间 create / switch / dispose,也无会话元数据与列表入口——v0.2 DoD 4(SessionManager)与 F-12 / F-17 未闭合。

## What Changes

- **会话元数据**:`SessionRef` 扩展;会话头(header entry)增加 `model` / `effort`(创建时即知);新增 `meta` entry 类型承载**可变**元数据(对齐 Pi `session_info`:append-only 下后写覆盖先写,读侧取最新,格式 v1 兼容);标题派生规则:显式命名优先,否则取首条用户消息截断(对齐 Pi `/name` + 首消息回退)。
- **SessionManager**(`session/manager.py`):`create / switch / dispose / list / current / continue_recent`;**薄管理器**——默认单活(仅 current 可运行),switch 时重建会话壳并把订阅转移到新会话(订阅方无感,10 类事件契约零改动);不做全局事件转发总线(并行会话事件转发列为未来演进)。
- **CLI 会话入口**:`--session <id>` 恢复既有会话继续对话、`-c` 继续最近会话(对齐 Pi `pi -c`)、`--list-sessions` 打印会话列表;TUI 斜杠命令 `/sessions` 由 T-44 接管(本 change 不做命令解析器)。
- **清理**:`AgentPorts.store` 死字段移除——core 循环从不落盘,`SessionStore` 只经 session 层注入,消除"core 认识 store"的假象。
- **不含**(登记后置):compaction(T-37,独立 change;details 结构已定 Pi 式 `{readFiles, modifiedFiles}` 纯路径数组 + 累积)、`replace_ports` 端口替换(FR-5.9 回归,待 T-44 `/provider` `/model` 用到再补——持久化侧届时追加 `model_change` entry)、T-42 `/undo` 跨压缩点决策。

## Capabilities

### New Capabilities

- (无新 capability)

### Modified Capabilities

- `sessions`:会话恢复需求扩展(元数据 / 标题 / 列表),新增 SessionManager 生命周期管理需求与事件转发契约。

## Impact

- `src/codeagent/session/store.py`:header 字段扩展 + `meta` entry + `SessionRef` 扩展(title / model / effort);
- `src/codeagent/session/manager.py`(新):SessionManager,经 `session/__init__.py` 导出;
- `src/codeagent/core/ports.py`:`AgentPorts` 移除 `store` 字段;
- `src/codeagent/app/container.py`:`create_agent_ports` 不再传 store;新增 `create_session_manager` 装配(ports 工厂 + store 注入);
- `src/codeagent/app/main.py`:`--session <id>` / `--list-sessions` 参数;
- 测试:`tests/session/test_store.py`(meta/元数据)、`tests/session/test_session_manager.py`(新)、`tests/test_container.py`、`tests/test_cli.py`;分层断言保持绿(session 不 import ai / tools / config)。
- 依赖:无新增(python 标准库 + 既有依赖)。
