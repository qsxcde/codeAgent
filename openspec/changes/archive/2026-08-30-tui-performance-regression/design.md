## Context

当前 `src/codeagent/app/tui/benchmark/` 已有离线纯组件 fixture、帧耗时和部分内存计数，`TuiRenderCoordinator` 也维护 generation、丢帧和超帧状态。但 benchmark 没有覆盖提交准备态和首个文本增量，`dropped_frames` 在基准结果中被固定为 0，比较脚本只比较少量 p50/p95 与峰值内存；跨平台运行时会直接落入不可比较但缺少完整指标的报告。V4-20/V4-21 已经提供可观测状态和按需渲染能力，本变更只在其上增加测量和验收闭环。

## Goals / Non-Goals

**Goals:**

- 建立不依赖真实 provider、网络、用户会话或随机 sleep 的确定性性能 fixture。
- 以统一 JSON 记录提交首帧、首 token、渲染分布、控制延迟、内存、丢帧和超帧，并保存足够的环境信息进行复现。
- 让基线比较能明确区分通过、回归、不可比较和数据不完整，CI 即使非阻塞也能留下可操作报告。

**Non-Goals:**

- 不把单台开发机结果解释为跨平台绝对 SLO，不在本变更中强制所有 CI 平台使用同一数值阈值。
- 不修改模型协议、会话 JSONL、TUI 用户交互语义或生产运行时的持久化数据。
- 不为追求更低 benchmark 数值继续改写布局算法；算法优化应另立变更并使用本基准验收。

## Decisions

### 1. 使用两层 fixture：纯组件指标为主，真实 Textual 交互为回归补充

继续以 `TuiModel`、`TuiRenderCoordinator` 和 fake backend 构建离线 benchmark，保证数据稳定、无需终端和网络；增加轻量事件时钟，模拟提交、准备态、首个文本增量和结构事件。现有 Textual `run_test()` 测试继续覆盖输入、滚动、取消和点击映射，但不把其调度抖动混入跨提交基线。

备选方案是只在真实终端上测量，用户感知更接近真实，但会受到 runner、终端驱动和系统调度影响，难以作为稳定回归比较；因此真实 Textual 测试用于行为证明，纯 fixture 用于指标比较。

### 2. 采用事件边界测量延迟，而不是固定等待时间

提交延迟从 `submit` 事件开始，到包含用户消息与运行状态的 backend 首帧提交结束；首 token 延迟从同一提交事件开始，到首个非空 `TEXT_DELTA` 被模型归约并提交到 backend。所有阶段使用同一个可注入 monotonic clock，测试可用确定性 tick 验证，不使用 `sleep` 猜测调度。

备选方案是从日志时间戳推断首 token，无法保证首帧与首 token 的因果边界，也容易将后台任务初始化误归入错误阶段。

### 3. 结果 schema 显式保留“没有发生”和“没有测到”

在 `BenchmarkResult` 中加入版本化的指标/计数契约；每个场景声明必需指标集合。场景不产生某一指标时使用明确的 `not_applicable` 记录或场景级说明，采集器缺少必需指标则比较器返回 `incomplete`，不使用 0 伪装。环境元数据只包含操作系统、Python 主次版本、视口、fixture 参数和提交版本，不包含内容。

备选方案是缺失值按 0 处理，兼容旧基线更容易，但会把未采集的首 token 或丢帧误报为最好结果，违反诊断要求。

### 4. 回归比较只在兼容维度相同的情况下进行

比较器继续检查 schema、场景、fixture 参数和平台，补充视口、必需指标与基线版本；`incomparable` 保留具体原因，`incomplete` 列出缺失字段。时间指标按配置的相对阈值比较，丢帧/超帧按计数单独展示，CI 使用可配置 `--fail-on-regression` 产生告警但性能 job 保持非阻塞。

备选方案是把 macOS、Linux 和不同 block 数直接归一化比较，这会把环境差异误判为代码回归，因此不采用。

## Risks / Trade-offs

- [Risk] 纯组件 benchmark 可能低估真实终端绘制成本 → 保留 Textual 交互回归，并在报告中明确测量层级。
- [Risk] `perf_counter` 样本受 runner 抖动影响 → 固定参数、多次迭代、使用 p50/p95 和环境元数据，不把单次极值作为唯一结论。
- [Risk] 新 schema 暂时无法与旧 Linux baseline 比较 → 比较器返回 `incomplete`/`incomparable` 并上传报告，先完成新 schema 的 CI 采集，再更新同环境 baseline。
- [Risk] 基准代码意外保存用户输入 → fixture 只使用常量占位文本，序列化前做安全字段断言，禁止写入 prompt、正文、工具参数和 session id。

## Migration Plan

1. 先增加 schema、fixture 和离线契约测试，保持旧 CLI 参数兼容。
2. 更新 CI 生成标准场景和长会话场景报告；首次运行允许生成明确的不可比较/不完整报告。
3. 在同平台、同参数的新报告稳定后更新版本化基线；回滚时只需恢复 benchmark/compare 脚本和 CI 步骤，不影响运行时。
