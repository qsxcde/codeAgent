## Why

工具已经分别实现并发、超时、输出截断和取消清理，但默认值散落在 core、Bash 和进程执行器中，调用方无法为一次运行统一调整资源边界。长输出、慢工具或并发工具批次因此缺少一致的内存与清理时限保障。

## What Changes

- 增加统一的工具资源限制对象，覆盖并发数、工具超时、最大输出字节/行数、输出读取内存上限和取消清理等待时限。
- 由组合根将限制同时注入工具执行 runtime、原子工具和进程执行器；未配置时保留当前默认行为。
- 进程输出读取按有效内存上限物化，超时/取消后的清理等待使用有限时限并保留不确定诊断。
- 增加配置校验、运行时边界和取消清理回归测试；不改变工具结果治理字段和既有安全策略。

## Capabilities

### New Capabilities

### Modified Capabilities

- `tools`: 增加统一可配置资源保护和有限清理语义。

## Impact

- 影响 `tools/shared`、`tools/atomic`、`tools/execution` 以及 app composition 的装配 API。
- 可能新增 provider 无关的 Settings 配置项，但不新增第三方依赖、不改变会话持久化格式。
- core 仍只接收已配置的工具 runtime，不导入工具层具体类型。
