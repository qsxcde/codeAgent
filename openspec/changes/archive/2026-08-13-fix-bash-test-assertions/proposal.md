## Why

`uv run pytest` 实测 **204 项中 4 项失败**,全部位于 `tests/tools/test_tools.py` 的 bash 工具测试。失败不是工具实现 bug,而是测试断言把 Linux 路径语义与过期的命令写法写死在测试里:

- **3 项(cwd 相关)**:断言 `str(tmp_path) in out`。pytest 的 `tmp_path` 恒在 `%TEMP%` 下,Windows Git Bash 按 MSYS 挂载表将其输出为 `/tmp/...`,任何 Windows + Git Bash 环境必败——工具行为(命令确实在目标目录执行)是正确的,错的是断言方式;
- **1 项(PIPESTATUS)**:测试命令 `ps aux | grep ...; exit ${PIPESTATUS[1]}` 在 P2-13 把豁免语义收窄为"仅 grep 前缀豁免"之后没有同步更新——末段首 token 是 `exit` 而非 `grep`,豁免按当前语义正确地不生效,该测试在任何平台都会失败。

保持测试全绿是项目回归底线(v0.1 DoD),这 4 项失败使基线失真,必须修复。

## What Changes

- **不改任何产品代码**:bash 工具实现(`src/codeagent/tools/atomic/bash.py`)零改动,行为不变;
- **重写 3 个 cwd 断言**(A1):以"标记文件 + 行为验证"替代路径字符串断言——在目标目录放 marker 文件,命令 `test -f marker.txt && echo CWD_OK`,断言 `CWD_OK` 出现在输出中。断言与平台路径表示彻底解耦,Windows / Linux / macOS 全部通过;
- **精简 1 条 PIPESTATUS 测试命令**(B1):删除 `; exit ${PIPESTATUS[1]}` 后缀,使用裸管道 `ps aux | grep codeagent-zzz-nonexistent`(退出码天然来自末段 grep=1),并补充断言 `"退出码: 1"` 以确认验证的是"grep 的 1 被豁免"路径,而非命令成功;
- 测试语义验证强度不降反升:不再依赖环境差异,且与相邻 `test_semantically_ok_*` 单测语义对齐。

## Capabilities

### New Capabilities

无(纯测试修复,不引入新能力)

### Modified Capabilities

无(产品行为不变——bash 工具在配置 cwd 中执行、grep 非零退出码语义豁免,均为既有行为,本轮仅修正测试对它们的验证方式)

> 本变更不产生任何 spec 增量:`skip_specs: true` 已在 `.openspec.yaml` 声明。

## Impact

- **受影响文件**(仅测试):`tests/tools/test_tools.py`
  - `test_bash_cwd_param_uses_configured_directory`(:209)
  - `test_bash_cwd_defaults_to_startup_directory`(:216)
  - `test_make_tools_passes_cwd_to_bash`(:223)
  - `test_bash_pipeline_grep_exit_one_not_failure`(:321)
- **API / 依赖 / 系统**:无影响;无新依赖;
- **验收口径**:修复后 `uv run pytest` 全量通过(204/204)。
