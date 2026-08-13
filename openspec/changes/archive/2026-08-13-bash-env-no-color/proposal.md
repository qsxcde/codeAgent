## Why

`bash` 工具以 `bash -lc` 启动登录 shell,会执行用户 `~/.bash_profile` 里的 conda init 并在 `.condarc` `auto_activate: True` 下自动激活 base。每次登录初始化派生多个 conda python 子进程;这些进程在 import `conda_libmamba_solver.mamba_utils` 时执行模块级 `palettes_and_formats()`,其中 `sys.stdout.isatty()`(mamba_utils.py:174)在无有效控制台句柄的分离进程(Windows `CREATE_NO_WINDOW`)里因 stdio 为 None 而崩溃,被 `conda/plugins/manager.py:236` 捕获并打印警告——于是**每条 bash 工具调用的 stderr 都被 3-4 行 `Error while loading conda entry point: conda-libmamba-solver ('NoneType' object has no attribute 'isatty')` 污染**,且噪音无法通过命令本身消除(它在 bash 启动期就已产生)。

这不是本项目代码缺陷,而是继承的 conda 环境缺陷;但工具层有义务给 Agent 返回干净、可读的输出。设置 `NO_COLOR` 环境变量可让 libmamba-solver 在 `mamba_utils.py:169` 直接短路、完全不执行 `isatty()`,从而在**不改 conda** 的前提下彻底消除噪音。这是 no-color.org 社区约定,对无 tty 的子进程是合理且无害的显式声明。

## What Changes

- `BashTool._bash_env()`(`tools/atomic/bash.py`)在子进程环境里设置 `NO_COLOR=1`,与现有 `LANG=en_US.UTF-8` 并列。
- 效果:每次 bash 调用不再在 stderr 输出 conda libmamba-solver 的加载噪音;`NO_COLOR` 同时让任何尊重该约定的命令默认不带 ANSI 颜色输出。
- 不影响:工具签名、输入参数 schema、退出码语义、黑名单、超时、截断等既有契约全部不变。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `tools`:bash 需求新增一条子进程环境契约——bash 工具 SHALL 在子进程环境注入 `NO_COLOR`,使继承自登录 shell 的 conda 初始化噪音不再污染工具输出;且该注入 SHALL 不影响命令执行结果与退出码。

## Impact

- **代码**:仅 `src/codeagent/tools/atomic/bash.py` 的 `_bash_env()` 一处改动(约 1 行)。
- **测试**:`tests/tools/test_tools.py` 需新增/调整断言,验证子进程环境含 `NO_COLOR`(离线可测,不依赖真实 conda)。
- **API / 依赖**:无新增依赖、无对外接口变化。`_bash_env` 是私有方法,仅被 `BashTool._invoke` 消费。
- **环境**:不触碰用户 `~/.bash_profile`、`.condarc`、conda 安装——纯工具侧缓解。同根的 `SSL_CERT_FILE` 指向不存在路径问题(导致 `test_client_reuses_connection_and_aclosable` 在 login-shell 场景失败)属环境层,不在本变更范围,见 design.md「范围外」。
