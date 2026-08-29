# Proposal: 外部检索器可选加速与纯 Python 回退

## Why

工具能力探测已经能识别 `rg` 和 `fd`，但 `grep` 与 `find` 当前始终走纯 Python 遍历。对于大型工作区，这会浪费可用的外部检索器性能；如果直接依赖外部命令，又会在 Windows、精简环境、命令异常或参数不兼容时破坏基础搜索能力。

## What Changes

- `grep` 在 `rg` 可用且调用成功时使用安全的参数列表加速搜索；不可用、平台不支持、超时或返回执行错误时透明回退现有纯 Python 实现。
- `find` 在 `fd` 可用且调用成功时使用安全的参数列表加速文件枚举；其输出仍经过现有 glob、噪声目录和 limit 语义过滤，失败时回退现有纯 Python 实现。
- 外部命令不经过 shell，不拼接用户输入为 shell 字符串；外部输出受现有工具资源限制约束。
- 增加可注入的外部命令边界测试，验证加速、缺失、失败、超时和语义回退。

## Capabilities

### New Capabilities

- 可选外部检索器加速与纯 Python 回退。

### Modified Capabilities

- `tools`: `grep`/`find` 使用可选外部加速，但不改变对外搜索语义。

## Impact

- 影响 `tools/atomic/grep.py`、`tools/atomic/find.py` 及 `tools/execution` 的外部命令适配。
- 不新增依赖、不改变会话持久化格式和工具参数 schema。
