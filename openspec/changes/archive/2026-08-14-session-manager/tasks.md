## 1. SessionStore 元数据与格式扩展

- [x] 1.1 header 扩展:`store.create` 增加 `model` / `effort` 参数,header entry 写入可选字段;`SessionRef` 增加 `model` / `effort`(JsonFileStore + MemoryStore 同步)
- [x] 1.2 meta entry:`set_meta(session_id, key, value)` / `get_meta(session_id, key)`(后写覆盖取最新;JsonFileStore 追加 `type=meta` entry,MemoryStore 同步;格式 v1 不 bump)
- [x] 1.3 标题派生:`SessionRef.title` 填充(meta name 优先,否则流式读至首条 user 消息截断 20 字符提前终止)
- [x] 1.4 测试:`tests/session/test_store.py` 补元数据 / meta 后写覆盖 / 标题派生 / 旧文件(缺 model/effort)向后兼容 / 未知 type 忽略

## 2. AgentPorts 死字段清理

- [x] 2.1 `core/ports.py` 移除 `AgentPorts.store` 字段;`app/container.py` `create_agent_ports` 去掉 `store` 参数
- [x] 2.2 更新受影响测试(`tests/test_container.py` 等),全量 `uv run pytest` 保持绿

## 3. SessionManager

- [x] 3.1 `session/manager.py`:create / switch / dispose / list / current / continue_recent(薄管理器:共享 ports + store,单活 current)
- [x] 3.2 订阅跟随:`subscribe(fn)` 注册到 current 的 bus,switch 时订阅自动转移到新会话(订阅方无感,10 类事件契约不变)
- [x] 3.3 `session/__init__.py` 导出 `SessionManager`;新增 `tests/session/test_session_manager.py`(事件序列断言、switch 订阅跟随、dispose 后文件保留可恢复、continue_recent、单活语义)

## 4. 组合根与 CLI 入口

- [x] 4.1 `app/container.py` 新增 `create_session_manager`(ports 工厂装配一次 + store 注入 + header model/effort 解析)
- [x] 4.2 `app/main.py`:`-c` / `--session <id>` / `--list-sessions`(store 目录 `~/.codeagent/sessions/`);默认行为不变(新建会话)
- [x] 4.3 测试:`tests/test_cli.py` 补三个入口的离线测试(注入 MemoryStore / 临时目录);分层断言(test_decoupling)保持绿

## 5. 文档与验收

- [x] 5.1 `docs/iteration/v0.2.md`:T-35 / T-36 / T-39 状态更新,E 编号变更记录补录;DoD 4 验收 ✅
- [x] 5.2 全量 `uv run pytest` 绿 + `openspec validate --changes session-manager` ✓
