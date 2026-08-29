# 测试指南

## 当前基线

截至 2026-08-30 应用层包布局变更复核后：

- `uv run pytest -q`：**1506 passed**（2026-08-30，macOS）。测试数量变化来自测试拆分、边界契约补充、工具生命周期状态与事件归约回归、TUI 性能指标/基线契约测试、会话标题重启/分叉回归、会话查询双后端/TUI 回归、归档删除安全回归、恢复诊断回归、会话列表索引失效隔离回归、生命周期 Hook 契约、异常隔离、ContextTransformer 契约、RuntimeExtensions 装配、扩展契约、工具能力探测、工具资源保护、外部检索器 fallback 和 Provider 错误分类回归。
- `test-foundation-stability` 与 `test-structure-coverage` 均已归档；当前测试结构和 `last_activity_at` 跨层契约已落地。
- 既有 CI artifact：`quality-fast` 为 846 passed；Ubuntu、Windows、macOS 矩阵各为 114 passed，均无 failure/error/skip；本地最新质量集为 1037 passed，硬下限为 77.9%。
- package smoke 已升级为可复跑的 release check：同时检查 wheel/sdist、版本、资源、敏感文件、干净环境安装和 fake provider CLI，并输出 `release-check.json` 及完整日志。
- TUI 性能五个标准场景均生成 JSON；仓库内 [`docs/benchmarks/tui-baseline.json`](benchmarks/tui-baseline.json) 仍是 schema v1 历史基线，不能直接与 v2 报告比较。Linux/Python 3.12 的 v2 候选基线由 CI artifact 和 `scripts/update_tui_baseline.py` 生成，历史观测详见 [`docs/benchmarks/tui-ci-2026-08-28.md`](benchmarks/tui-ci-2026-08-28.md)。

测试改造应保持行为基线不变。测试数量变化时，需要说明是新增覆盖、拆分迁移还是删除过期兼容测试。

## 应用层包布局

`src/codeagent/app/` 的规范实现按职责归并到 `context/`、`errors/`、`skills/`、`tasks/`、`composition/` 和 `tui/` 子包；`main.py`、`container.py`、`config.py` 保留为根入口。已迁移的根层和 TUI 平铺模块已删除，生产代码和测试必须直接使用具体规范模块。

工具生命周期回归按 `tool_call_id` 验证 queued → running → terminal 的单向归约，覆盖确认、拒绝、超时、取消无结果、清理不确定、迟到/重复结果和输出截断；`TOOL_FINISHED` 只确定执行状态，`TOOL_RESULT` 只补充输出事实。

会话标题回归覆盖自动派生、显式名称优先、单行归一化、长度限制、空标题拒绝、延迟落盘空会话命名，以及 JsonFileStore/MemoryStore 的重启、索引重建、压缩和分叉语义。`/name` 的失败路径必须在 TUI 内反馈，且不得发起模型请求或改写聊天历史。

会话查询回归覆盖 `SessionQuery` 的标题/id、模型、时间和状态匹配，JsonFileStore 的有效索引命中、损坏索引回源、坏文件隔离及只读文件保证，MemoryStore 的同序行为，SessionManager 的驻留运行态叠加与重启 idle，以及 TUI `/sessions search`、`/sessions filter` 的引号值、组合条件、错误/空态和模型请求隔离。

归档删除回归覆盖双后端可逆归档、默认/归档列表范围、旧索引重建、目标 JSONL 与索引清理、非法 id/符号链接保护、批量全量预检、当前/运行中会话保护、存储失败诊断和 TUI `confirm` 删除入口。

会话恢复诊断回归覆盖健康、坏 JSONL 行、无效消息、缺失/损坏/过期索引、缺失压缩切点、header 缺失、版本不兼容和非法会话 id；同时验证有效历史的局部降级、typed 恢复错误、当前会话保护、TUI `/sessions recovery` 和 CLI `--session` 的可操作提示，以及不会发起模型请求或覆盖原始 JSONL。

会话列表索引回归覆盖多个有效索引命中时列表/搜索/筛选不扫描 JSONL、单个索引缺失/损坏/过期时只重建对应目标、源文件回源失败时隔离损坏会话，以及 `continue_recent` 依据索引选择最近目标并只恢复最终会话。

生命周期 Hook 回归覆盖 Hook 快照脱离原始事件、多个 Hook 注册顺序和返回值忽略、turn/model/tool/session 的阶段映射、模型请求成功/失败/取消时边界事件 exactly-once、工具调用关联、同步/异步/快照失败诊断、取消任务清理以及 core 不导入具体 provider/tools/MCP/Skill/UI。组合根回归继续验证 `RuntimeExtensions` 的字段身份、生命周期 Hook 顺序，以及 session 恢复和 TUI 模型重建不丢失扩展。

工具能力回归覆盖能力快照冻结与稳定序列化、Bash/`rg`/`fd` 缺失诊断、Windows 进程树清理不确定性、未知安全策略、注入式平台/PATH 探测和 TUI `/status` 展示；探测只做只读 PATH/配置判断，不启动外部命令、不触发确认或写入会话。

工具资源保护回归覆盖 `ToolResourceLimits` 严格校验与有效输出上限、统一 runtime 并发排队、Bash/进程请求的输出与内存限制、输出截断原因、超时/取消后的有限清理等待和清理不确定状态；进程完整输出只保留在临时文件中，内存上限约束返回预览物化而非底层磁盘写入量。

外部检索器回归覆盖 `rg --json` 的匹配/上下文解析、`fd` 路径过滤、可选依赖缺失、非零失败、超时和输出有界读取；同时断言搜索参数以独立 argv 传递、不经过 shell，fallback 后的 glob、相对路径、上下文和 limit 语义保持不变。

Provider 错误回归覆盖 HTTP 状态分类、限流重试提示、认证和参数不支持判定、网络/超时可重试标记、响应详情脱敏，以及流式/非流式传输的统一错误字段和 `httpx.HTTPStatusError` 兼容性。

本次收口会使旧平铺导入路径失效；`tests/contracts/test_app_package_layout.py` 会同时检查旧模块不存在和规范模块可导入。

TUI 的具体 Textual 类型只能位于 `app/tui/adapters/textual/`；`ports/`、`state/`、`presentation/`、`commands/`、`session/` 和 `rendering/` 必须保持 Textual-free。`tests/contracts/test_app_package_layout.py`、`tests/test_decoupling.py` 和 `tests/contracts/test_tui_boundaries.py` 负责检查这些导入边界。

## 常用命令

```bash
# 安装开发依赖
uv sync --group dev

# 收集测试，不执行
uv run pytest --collect-only -q

# 快速单元和契约测试
uv run pytest -m "unit or contract" -q --strict-markers

# 集成、端到端和平台测试
uv run pytest -m "integration or e2e or platform or compatibility" -q --strict-markers

# 排除慢速测试的默认反馈集
uv run pytest -m "not slow" -q

# 完整离线测试
uv run pytest -q

# CI 同步的正确性静态检查（只阻断语法错误、未定义名称和未使用局部变量）
uv run ruff check src tests scripts

# 应用层生产文件/函数规模护栏
uv run python scripts/scale_scan.py

# 生成覆盖率报告（不设置高比例硬门槛）
uv run pytest -m "unit or contract" -q --strict-markers --cov=codeagent --cov-report=term-missing

# 发布检查：构建、检查产物、干净环境安装并运行 fake provider
uv run python scripts/release_check.py \
  --dist-dir artifacts/dist \
  --output artifacts/release-check.json

# OpenSpec 规格校验
openspec validate --specs
```

测试必须离线运行，不依赖真实 API key、真实 Provider 或用户的 `~/.codeagent` 数据。

## Marker 约定

- `unit`：单模块、无外部进程、无真实网络的行为测试。
- `contract`：跨实现或架构边界契约，例如 Store、Provider、Tool 和导入边界。
- `integration`：组合多个运行时模块、文件存储、MCP 或 subprocess 的测试。
- `e2e`：从 CLI/TUI 入口验证完整用户路径的测试。
- `platform`：依赖 Windows、Linux 或 macOS 差异的测试。
- `security`：安全分类、拒绝、确认和文件边界测试。
- `performance`：性能基线、内存和渲染指标测试。
- `slow`：不适合快速反馈但仍属于常规回归的测试。

一个测试可以拥有多个 marker。marker 描述测试的执行边界，不替代测试名称对行为的说明。

当前分类由 `tests/conftest.py::pytest_collection_modifyitems` 统一补齐：未特别识别的新增测试默认归入 `unit`，边界、组合根、MCP、CLI 和性能测试分别升级到对应主分类；工具进程测试追加 `platform`，安全测试追加 `security`。因此新增测试不会因漏写 marker 而从分层命令中消失。

共享测试资源位于 `tests/fixtures/`：

- `ai.py`：离线 `FakeClient` 及构造器。
- `filesystem.py`：`InMemoryFsOps` 和 `memory_fsops`。
- `session.py`：默认离线工具集的 `session_factory`。
- `resources.py`：后台任务、同步资源和异步资源的 teardown tracker。

## 异步与资源清理约定

- 新增异步测试使用统一的 pytest asyncio 模式，直接声明 `async def`。
- 不使用固定 `sleep` 等待调度或排序稳定；使用显式事件、受控 clock 或确定性输入。
- 后台任务、MCP 客户端、模型客户端和 subprocess 必须在测试结束时关闭或确认已取消。
- 可能挂起的测试必须具备可诊断的超时保护。
- fixture 只封装环境构造，不隐藏被验证的业务输入和断言。
- `tests/conftest.py` 的 autouse fixture 会检查异步测试是否遗留 pending task；发现泄漏时先取消并等待，再以任务名报告失败。

## CI 分层与性能报告

`.github/workflows/ci.yml` 将门禁分为四类：

- `quality-fast`：Ruff、unit/contract、覆盖率报告、版本一致性、补丁格式和 OpenSpec 校验。
- `test-matrix`：Ubuntu、Windows、macOS 上执行 integration/e2e/platform/compatibility，统一使用 fake provider；失败时保留 JUnit 和跳过原因。
- `package-smoke`：运行 release check，构建并检查 wheel/sdist，在干净虚拟环境安装后检查 CLI 和内建 resources 可用。
- `performance`：运行离线 TUI 基准并上传 JSON；性能回归目前只告警，不阻断普通 PR。报告使用 schema v2，包含提交/首 token 延迟、帧 p50/p95、控制事件 p95、峰值 Python 分配和协调器帧计数。

性能结果可用以下命令进行相对比较。正式基线包含四个场景；环境或输入参数不一致时会明确标注 `incomparable`：

```bash
uv run python scripts/benchmark_tui.py --scenario stream --blocks 100 --stream-chars 10000 --tool-output-bytes 20000 --width 80 --height 24 --iterations 3 --output artifacts/tui-benchmark.json
uv run python scripts/compare_benchmark.py artifacts/tui-stream.json
uv run python scripts/compare_benchmark.py artifacts/tui-stream.json docs/benchmarks/tui-baseline.json --max-regression 0.20

# 在 Linux/Python 3.12 上将同一轮四场景报告组装为候选 v2 基线
uv run python scripts/update_tui_baseline.py \
  --output artifacts/tui-baseline-v2.json --baseline-id linux-py312-tui-v2 \
  artifacts/tui-history.json artifacts/tui-restore.json \
  artifacts/tui-stream.json artifacts/tui-tool-output.json

# 长会话扩展：固定 mixed-shape fixture，观察视口物化和索引扫描是否随历史线性增长
for blocks in 1000 5000 10000; do
  uv run python scripts/benchmark_tui.py --scenario history --blocks "$blocks" --iterations 1 \
    --output "artifacts/tui-history-${blocks}.json"
done
```

长会话结果中的 `blocks_inspected`、`blocks_materialized`、`index_updates`、`cache_entries`、
`cache_rows`、`rendered_frames`、`dropped_frames`、`over_budget_frames` 和
`peak_memory_bytes` 是无内容性能计数器；`metrics` 中的 `frame_total_ms`、
`model_render_ms` 和适用的 `control_event_latency_ms` 提供 p50/p95。stream 另外提供
`submit_latency_ms` 与 `first_token_latency_ms`。场景不适用的指标会出现在
`unavailable_metrics`，`not_measured` 则会使比较结果为 `incomplete`。1,000/5,000/10,000
block 扩展报告用于趋势观察，不与 100 block 的正式 Linux 基线直接比较，也不作为跨机器绝对 SLO。

当前 `quality-fast` 与平台矩阵之间有 25 个兼容性/平台边界测试重复执行；这不影响正确性，但需要后续决定保留边界保护还是调整 marker 分层。覆盖率硬下限当前为 77.9%；性能仍使用 20% 相对回归告警，不启用 `--fail-on-regression`。
