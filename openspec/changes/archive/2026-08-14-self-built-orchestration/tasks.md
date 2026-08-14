## 1. 消息归约 Spike(gate)

- [x] 1.1 实现最小自研 ReAct 循环原型(~50-100 行):调模型 → 若有 tool_calls 执行工具并归并结果 → 继续/结束;10 类 AgentEvent 直接 emit
- [x] 1.2 实现消息归约 R2(~15 行):按 tool_call_id 归属(写入顺序保证)+ 按 id 删除等价物;消息 id 分配(uuid4 临时)
- [x] 1.3 双跑 diff:同一 FakeClient steps 驱动 langgraph 版(现状)与自研循环版,5 场景(单工具 / 并行双工具成败归属 / 三轮循环 / 失败回滚 / 空响应兜底)逐事件对比事件序列与消息列表
- [x] 1.4 判定与产出:事件类型序列逐项相等(仅允许非语义字段差异);产出循环原型 + 归约实现 + diff 基线;文档勘误项登记(`core/state.py`、CLAUDE.md 的 add_messages 描述)

## 2. 自研消息模型与循环落地

- [x] 2.1 实现 uuid7(时间前缀 + 随机后缀,~15 行,不引三方依赖);单测锁定单调性与格式
- [x] 2.2 定义自研 Message 数据模型(role/content/tool_calls/tool_call_id/id/parentId),替换 langchain 消息类型
- [x] 2.3 重写 `core/loop.py`:for 循环(模型→工具→继续/结束),recursion_limit / abort / 工具超时均为普通代码;thinking/usage 事件原生化
- [x] 2.4 实现归约模块(按 id 删除、同 id 替换、消息 id 稳定),失败/取消回滚语义与 v0.1 一致
- [x] 2.5 工具执行逻辑上移为循环内代码:并行 `gather` + 单 call 错误归属 + 错误标记(additional_kwargs.error 等价)

## 3. JSONL 树形会话存储

- [x] 3.1 定义 SessionStore 协议(hexagonal 缝)与 JsonFileStore / MemoryStore 实现;写串行化复用 `with_path_lock`
- [x] 3.2 JSONL 格式 v1:session header(version/parentSession)/ message(id/parentId)/ compaction(预留 summary + details.readFiles/modifiedFiles);append-only 写入
- [x] 3.3 会话恢复:从 JSONL 重建消息历史;格式版本解析(不兼容版本明确报错)
- [x] 3.4 存储测试:追加不重写历史、父级链回放、版本解析、并发写串行化

## 4. 事件壳与运行干预

- [x] 4.1 重写 `session/session.py`:直接驱动自研循环,10 类事件经 EventBus 分发;run_sync / abort 语义保留
- [x] 4.2 运行干预:中断(abort)、追问轮(followup)、运行中注入消息(steer,下一轮循环前消费)
- [x] 4.3 事件壳测试:事件序列与 v0.1 契约一致;失败/取消回滚;run_sync 双形态

## 5. 工具层与组合根适配

- [x] 5.1 `tools/base.py` 删除 `to_langchain()`;`registry.make_tools` 返回自研工具列表(不再 BaseTool)
- [x] 5.2 重写 `app/container.py`:注入 ChatClient / 工具列表 / JsonFileStore 到自研循环与事件壳;删除 ToolNode / InMemorySaver
- [x] 5.3 适配 `core/ports.py`(AgentPorts 结构)、`test_factory.py`、tools 相关测试的类型断言

## 6. 桥接层删除与测试重写

- [x] 6.1 删除 `ai/bridge/langchain.py` 与 `tests/ai/test_bridge.py`(互相锁定)
- [x] 6.2 重写 `tests/core/test_loop.py` 与 `tests/session/test_session.py`:断言从"图输出"改为"事件序列"(以 spike diff 基线为基准数据)
- [x] 6.3 重写 `tests/test_container.py` 装配断言;FakeClient 直接对接自研循环
- [x] 6.4 pyproject 移除 langchain-core / langgraph;全量 `uv run pytest` 跑绿(离线、零网络零密钥)

## 7. 文档与收尾

- [x] 7.1 勘误 `core/state.py` docstring 与 CLAUDE.md 的 add_messages 归约描述
- [x] 7.2 更新 v0.2 任务书阶段 1 状态(T-30~T-34)与演进蓝图第二步落地记录
- [x] 7.3 全量验收:按 v0.2 DoD 第 1/2/3 条核对(自研落地 / 事件契约 / JSONL 持久化);`openspec validate` 通过
