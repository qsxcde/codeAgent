## 1. 存储模块边界和兼容入口

- [x] 1.1 建立 `store_models.py`、`store_codec.py`、`json_file_store.py`、`memory_store.py` 和 `store_index.py` 的内部模块边界
- [x] 1.2 记录现有 `codeagent.session.store`、`codeagent.session.session` 公共符号并建立导入兼容测试基线
- [x] 1.3 在新模块中保留 session 层只依赖 core 与同层模块的分层约束

## 2. 存储模型与编解码拆分

- [x] 2.1 将 `UsageStats`、`SessionRef`、`CompactionEntry`、`CompactionState` 和 `SessionStore` 移到 `store_models.py`
- [x] 2.2 将时间戳、标题派生、消息 JSONL 编解码和 header 校验移到 `store_codec.py`
- [x] 2.3 更新内部导入并保持 `store.py` 的 `__all__`、公共符号和错误语义不变

## 3. 存储后端拆分

- [x] 3.1 将 `MemoryStore` 移到 `memory_store.py`，保持压缩、usage、meta、model change 和 fork 语义
- [x] 3.2 将 `JsonFileStore` 移到 `json_file_store.py`，保持流式读取、权限、路径锁、追加写入和分叉语义
- [x] 3.3 保留 `store.py` 作为兼容重导出层，并验证 CLI、TUI、manager 和现有测试的旧导入路径
- [x] 3.4 为两个后端增加行为等价测试，覆盖空会话、损坏行、版本校验、压缩恢复、usage 和 fork

## 4. 索引逻辑抽取

- [x] 4.1 将索引构建、读取校验、源指纹、增量应用、原子写入和失效逻辑移到 `store_index.py`
- [x] 4.2 通过显式迭代器和文件操作回调连接 `JsonFileStore` 与索引模块，避免循环依赖
- [x] 4.3 保持 `_append` 的 JSONL 写入、权限设置、索引更新和失败失效顺序及路径锁范围
- [x] 4.4 增加索引命中、缺失、损坏、过期、重建、更新失败和并发追加回归测试

## 5. AgentSession 运行与持久化拆分

- [x] 5.1 定义 `SessionRuntime` 的显式输入输出，迁移 run_turn、运行任务、队列、run_id 和副作用诊断状态
- [x] 5.2 定义 `SessionPersistence` 的显式输入输出，迁移恢复、延迟创建、成功提交、usage 写入和回滚逻辑
- [x] 5.3 让 `AgentSession` 以门面方式协调 runtime 与 persistence，并保留现有公开方法和属性
- [x] 5.4 保持 compact、自动压缩、摘要父级链接、context token 和生命周期事件语义
- [x] 5.5 保持 abort、retry、steer、approval、取消、失败和 cleanup 不确定状态传播

## 6. 会话层验证与清理

- [x] 6.1 保持 `AgentSession`、`DEFAULT_CONTEXT_WINDOW`、压缩常量和错误转换入口的兼容导入
- [x] 6.2 增加 SessionRuntime 和 SessionPersistence 的离线单元测试，不依赖真实模型或终端
- [x] 6.3 运行 session、manager、container、CLI/TUI 会话相关回归测试
- [x] 6.4 运行分层依赖检查、公共导入烟测和完整 `uv run pytest -q`
- [x] 6.5 检查新增模块的文档、类型标注和未使用旧导入，确认旧 `store.py`/`session.py` 仅保留兼容门面与必要协调逻辑
