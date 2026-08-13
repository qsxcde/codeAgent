## ADDED Requirements

### Requirement: bash 子进程环境注入
`bash` 工具 SHALL 在派生子进程时向子进程环境注入 `NO_COLOR=1`(与现有 `LANG` 注入并列)。目的:使登录 shell 初始化(如 conda 的 libmamba-solver 颜色探测)在无 tty 的分离进程中不再因调用 `isatty()` 而产生 stderr 噪音;该注入 SHALL 不改变命令的执行语义、输出内容与退出码判定。

#### Scenario: 子进程环境含 NO_COLOR
- **WHEN** `bash` 工具派生子进程执行一条命令
- **THEN** 子进程环境变量中包含 `NO_COLOR=1`,命令可从环境中读到该值

#### Scenario: 注入不影响命令结果
- **WHEN** 命令在注入 `NO_COLOR` 的子进程环境下执行
- **THEN** 命令的输出与退出码与未注入时一致(仅无 tty 的颜色类行为可能不同),失败/成功判定不变
