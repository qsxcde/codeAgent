## Context

动机见 proposal.md「Why」:`bash -lc` 继承的 conda 初始化在无控制台句柄的分离进程中崩溃并污染 stderr。现状约束:

- `BashTool._exec` 用 `[shell, "-lc", command]` + `CREATE_NO_WINDOW` 启动子进程(`tools/atomic/bash.py:323-357`),stdout/stderr 均落临时文件(永远不是 tty)。
- `_bash_env()`(`bash.py:317-321`)是构造子进程环境的唯一入口,已注入 `LANG`,是注入点的天然归属。
- 根因是**继承环境**(conda)而非工具自身缺陷,工具侧只做缓解,不改用户机器配置。

## Goals / Non-Goals

**Goals:**
- 在 `_bash_env()` 注入 `NO_COLOR=1`,使 conda libmamba-solver 的 `palettes_and_formats()`(mamba_utils.py:169)短路,彻底不执行 `sys.stdout.isatty()`,stderr 噪音消失。
- 保持既有契约不变:退出码语义、黑名单、超时、截断、输出格式。
- 变更离线可测:不依赖真实 conda,单测即可验证环境注入。

**Non-Goals:**
- 修复 conda 的 `SSL_CERT_FILE` 指向不存在路径(同根的另一症状,导致 `test_client_reuses_connection_and_aclosable` 在 login-shell 场景失败)——属环境层(方向 C),明确排除。
- 把 `bash -lc` 改为 `bash -c`:会丢掉登录环境(PATH 等),得不偿失。
- 修改 `~/.bash_profile` / `.condarc` / conda 安装:不碰用户机器配置。
- 在工具层过滤/清洗 stderr 文本:错误分层,正则匹配噪音脆弱,且可能误伤真实错误信息。

## Decisions

**D1: 注入点选 `_bash_env()` 而非 `_exec` 的 Popen 层**
`_bash_env` 已是环境构造的唯一入口,与 `LANG` 注入并列最内聚。在 `_exec` 里硬编码会绕开环境构造逻辑,后续新增环境变量也无处安放。
*备选*:在 `app/container.py` 或 session 层做全局 env 清洗——影响面过大,且 tools 层无依赖其它层。

**D2: 值用 `NO_COLOR=1`,而非 `FORCE_COLOR` 或删除式清环境**
`mamba_utils.py:169-174` 三分支:`NO_COLOR` 设值 → `use_color=False` 短路;`FORCE_COLOR` 设值 → `use_color=True` 同样跳过 `isatty()`。两者都能消除崩溃,但 `NO_COLOR` 符合 no-color.org 社区约定、语义是"显式关闭颜色",比强制开色更克制、对其它命令影响更小。
*备选*:给子进程环境批量删除 conda 相关变量(`CONDA_PREFIX` 等)——治标不治本(噪音来自 login 脚本拉起的 conda 进程,不依赖传入的 conda 变量),且删除式维护成本高。

**D3: 无条件注入,不做平台/场景特判**
stdout/stderr 无论 Windows/Linux/macOS 都落文件、非 tty,`NO_COLOR` 的语义在所有平台一致;设置它只是把"本就没有颜色"的既成事实显式化。做条件特判反而增加不可测试的分支。

**D4: `_bash_env` 的返回值仍是 `os.environ.copy()` 的浅拷贝,注入对其无副作用**
子进程环境是独立 dict,不污染 codeagent 进程自身的 `os.environ`,符合"依赖显式传入、不隐式改全局"的规范。

## Risks / Trade-offs

- **[尊重 `NO_COLOR` 的命令会关掉颜色输出]** → 本就无 tty、输出落文件,颜色是 ANSI 垃圾而非信息;显式关色反而让捕获输出更干净。影响趋近于零。
- **[部分工具不认 `NO_COLOR`]** → 目标对象(conda libmamba-solver)经 `mamba_utils.py:169` 确认认;其它不认的工具本来就输出颜色,与现状无差异。
- **[命令主动探测 `NO_COLOR` 做分支]** → 属本变更预期内行为(显式声明无颜色环境);在本工具的非 tty 上下文中是合理语义。
- **[只缓解不根治]** → 治本属环境层(修 conda `ssl/`、关 auto_activate),已在 Non-Goals 声明;本变更解决工具输出被污染的表层问题,不掩盖其它真实 stderr 错误。

## Migration Plan

纯增量:在 `_bash_env()` 加一行。无数据迁移。回滚=删行。上线后通过既有 bash 工具用例 + 新增环境注入断言验证。
