## 1. 基线与结构契约

- [x] 1.1 记录当前 `git status`、相关 diff 和 core 现有导出，确认不覆盖前一变更的未提交修改
- [x] 1.2 盘点仓内全部 `codeagent.core.<old_module>` 导入，并建立旧路径到目标路径的迁移清单
- [x] 1.3 新增 core 包结构测试，验证六个职责子包、根级 `agent.py` 和预期模块存在
- [x] 1.4 新增负向结构测试，验证旧平铺模块在迁移完成后不存在且旧内部路径不再作为兼容入口

## 2. 契约与上下文模块迁移

- [x] 2.1 创建 `contracts`、`context`、`model`、`execution`、`orchestration` 和 `support` 的最小 `__init__.py`
- [x] 2.2 将 errors、events、messages 和外部端口迁移到 `contracts`，并保持类型定义与 `__all__` 语义不变
- [x] 2.3 从原 `ports.py` 提取上下文契约到 `context/contracts.py`，包括上下文准备类型、工具元数据和预算端口
- [x] 2.4 将 context、context budget 和 context preflight 迁移到 `context`，更新其消息和契约导入
- [x] 2.5 将 `awaiting.py` 迁移到 `support/awaiting.py`，确保同步/异步回调归一化行为不变
- [x] 2.6 将 `AgentLoopConfig` 及其编排回调类型提取到 `orchestration/config.py`，消除 `contracts` 对 `context` 的反向依赖

## 3. 模型、执行与编排模块迁移

- [x] 3.1 将模型请求实现迁移到 `model/request.py`，改用新的 context、contracts 和 support 路径
- [x] 3.2 将 execution runtime、state、cleanup 和 result 迁移到 `execution`，按新契约路径更新相互引用
- [x] 3.3 将 loop、turn、tool batch、tool result 和 loop errors 迁移到 `orchestration`，分别落到 loop、turn、batch、tool_call 和 errors
- [x] 3.4 按依赖方向修正 orchestration 对 model、context、execution 和 contracts 的导入，禁止子包通过 `codeagent.core` 根 façade 回导
- [x] 3.5 删除旧的平铺 core 实现文件，确认 `agent.py` 仅保留运行时外壳而不重新承载已迁移逻辑

## 4. 公共导出与仓内调用方

- [x] 4.1 更新 `core/__init__.py`，从新模块显式 re-export 现有公共名称并保持 `__all__` 和对象身份
- [x] 4.2 更新 app、session、tools、测试和文档中的内部导入，统一使用新职责路径或稳定的 `codeagent.core` 公共 façade
- [x] 4.3 新增导出契约测试，验证公共根导出与新模块对象相同，并验证常用导入顺序不会触发循环依赖
- [x] 4.4 新增 core 分层边界测试，拒绝对 config、ai、tools、session 的生产依赖以及子包对根 façade 的反向依赖

## 5. 验证与变更收口

- [x] 5.1 运行 core、contracts、context、model、execution 和 orchestration 相关窄测试并修复路径迁移回归
- [x] 5.2 运行 app、session、tools 相关 contract/integration 测试，确认执行、预算、事件和取消语义未改变
- [x] 5.3 运行 `uv run ruff check src tests scripts`、`git diff --check` 和 core 规模/导入检查
- [x] 5.4 运行完整离线测试与 `uv build`，检查资源、版本和发行产物未受影响
- [x] 5.5 运行 `openspec validate --changes`，核对任务勾选、proposal、design 和工作区 diff，记录剩余限制
