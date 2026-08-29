## Why

工具目前分别在 Bash、进程执行、安全策略和搜索实现中判断环境条件，但没有统一的能力快照。用户只能在真正调用工具后才看到“没有 bash”或权限受限等问题，TUI 也无法在运行前解释当前环境缺少哪些可选能力。

## What Changes

- 增加平台无关的工具能力快照，覆盖 shell、运行平台、外部检索器和权限策略能力。
- 对每项能力记录可用性、稳定标识和可操作的诊断原因；探测失败不抛出未处理异常，也不伪造可用能力。
- 将能力快照接入工具装配和 TUI `/status`，让用户能在执行前查看环境限制。
- 保持现有工具行为和默认 fallback 不变；`rg`/`fd` 的实际加速与 fallback 由后续 V4-35 处理。

## Capabilities

### New Capabilities

### Modified Capabilities

- `tools`: 增加运行环境能力探测和用户可见诊断契约。

## Impact

- 影响 `src/codeagent/tools` 的能力检测与工具工厂，以及 TUI 状态诊断输出。
- 增加 provider-neutral 的只读数据模型和组合根注入，不新增第三方依赖，不改变 JSONL 会话格式。
- 测试覆盖 Unix/Windows 模拟环境、缺失 shell/检索器、权限能力和诊断文本稳定性。
