## Context

`rg`/`fd` 是可选环境能力，不应成为 `grep`/`find` 的运行时前提。现有纯 Python 实现已经定义了 glob、上下文、二进制跳过、噪声目录剪枝、路径格式和结果上限语义，外部检索器只能作为可替换的遍历加速层。

## Goals / Non-Goals

**Goals:**

- 优先使用当前 PATH 中可执行的 `rg`/`fd`，将成功结果转换为现有工具输出格式。
- 缺失、非零错误、超时、输出不可解析或平台不支持时不向用户暴露新的硬故障，回退纯 Python。
- 外部调用不使用 shell，用户 pattern/path/glob 只作为独立 argv 参数传入。
- 对外部输出采用临时文件和有界预览读取，沿用 `ToolResourceLimits` 的时间与输出边界。

**Non-Goals:**

- 不替换现有搜索语义，不引入完整 `.gitignore` 解释器。
- 不把 `rg`/`fd` 变成强依赖，不自动安装外部程序。
- 不改变工具结果的状态、metadata 或 session JSONL 格式。

## Decisions

1. **外部命令边界独立于搜索语义。** `tools/execution/search.py` 只负责可选 executable 查找、非 shell 启动、超时/退出状态和有界输出；glob、上下文和路径归一化仍由 `grep`/`find` 负责。
2. **失败结果统一返回不可用信号。** 缺失 executable、`OSError`、超时、非 0/1 退出码或无法解析的输出均返回 `None`，调用方立即使用纯 Python 实现；`rg` 的 1 表示无匹配，允许作为成功的空结果。
3. **rg 使用 JSON 行协议。** 通过 `--json` 区分 match/context，避免按内容中的冒号猜路径；解析后重新生成现有 `path:line:` 和 `path-line-` 格式，并对重复上下文去重。
4. **fd 只加速枚举。** `fd` 输出所有候选文件路径（启用 hidden/no-ignore，排除既有噪声目录），结果在 Python 侧重新应用当前 glob、相对路径和 limit 规则，避免外部工具版本造成语义漂移。
5. **有界输出不影响 fallback。** 外部结果超过资源预览上限时只保留可解析的完整行；如果命令本身不能提供可靠结果，则回退纯 Python，而不是返回半解析数据。

## Risks / Trade-offs

- 外部工具版本的参数差异可能导致启动失败 → 失败即 fallback，并由回归测试覆盖。
- `rg` JSON 解析增加少量 CPU → 只在外部加速路径使用，安全性和路径语义优先。
- `fd` 仍可能在临时文件中写入较多候选路径 → 复用既有磁盘临时文件模型，内存读取保持有界；完整磁盘配额不在本变更范围。

## Migration Plan

先加入可选命令边界和失败测试，再接入 `grep`/`find`；默认行为在缺失或失败时与现有纯 Python 路径一致。回滚只需禁用外部 backend，不涉及数据迁移。
