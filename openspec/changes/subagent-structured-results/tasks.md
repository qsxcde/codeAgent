## 1. Core 结构化结果契约

- [x] 1.1 在 core 契约测试中覆盖 finding、evidence、usage、artifact 的构造、JSON-safe 序列化、默认值和非法输入拒绝。
- [x] 1.2 在 core 契约测试中覆盖结果数量/字符/token 边界、evidence id 唯一性及 finding 引用完整性。
- [x] 1.3 新增四类 frozen provider-neutral 结果值对象和固定边界常量，提供 `to_dict()` 并使用 `invalid_result` 归一错误。
- [x] 1.4 扩展 `SubagentResult` 的结构化字段、归一化逻辑和 `to_dict()`，更新 `core.contracts` 与 `codeagent.core` 公共导出。

## 2. 子运行事实提取

- [x] 2.1 先补充 runner 结果提取测试：从 assistant tool call 与 tool message 元数据生成有界 evidence，提取 locator、完整性、摘录和首次 artifact 引用。
- [x] 2.2 增加公开的子 Session 最近一次运行用量视图，并覆盖多轮累计 usage 与旧测试 double 的兼容回退。
- [x] 2.3 实现组合层结果提取器，按历史顺序配对工具调用，只读取 `ToolOutputMetadata`，限制证据数量和摘录大小，不解析自然语言 findings。
- [x] 2.4 在 `_result_from_child` 接入 findings/evidence/usage/artifact，保证失败、预算、取消和超时路径不泄漏 transcript 且保留已有诊断。

## 3. 父级 ToolResult 映射

- [x] 3.1 补充 `delegate` ToolResult 映射测试，验证结构化字段出现在 details 顶层且值为 detached JSON-safe 数据。
- [x] 3.2 更新 `delegate_result`，在保留摘要 content、状态、错误和 cleanup 语义的同时映射结构化结果；缺失字段使用空列表或空值。
- [x] 3.3 增加真实 FakeClient 子 Session 集成回归，验证父级可读取摘要、证据、用量和 artifact，且不包含完整子历史或无界工具输出。

## 4. 文档与质量门禁

- [x] 4.1 运行变更相关 unit/contract、app 集成和完整离线测试，修复回归并保持单 Agent 行为不变。
- [x] 4.2 更新 `docs/iteration/v0.5.md` 的 V5-05 实现记录和验证证据。
- [x] 4.3 运行 Ruff、规模扫描、`git diff --check`、OpenSpec strict validation 和 `uv build`，确认所有新增生产文件符合规模约束。
