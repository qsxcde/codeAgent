## MODIFIED Requirements

### Requirement: bash 命令执行

`bash` 工具 SHALL 在注入的工作目录执行 shell 命令并返回输出与退出码;默认超时 120 秒、上限 600 秒;超时或中断时 SHALL 终止整个命令进程树;输出按字节与行双上限截断并保留末尾;危险命令 SHALL 被拒绝并返回拒绝原因;敏感命令 SHALL 需用户确认,未确认不得执行;只读白名单命令 SHALL 免确认执行;grep 无匹配(退出码 1)SHALL 不视为失败;Windows 下无可用 bash 时 SHALL 返回可操作安装指引。工具 SHALL 能接收来自 Agent 执行器的取消请求;外层超时不得仅停止等待而让 bash 继续无状态运行。Windows 下无法确认终止 MSYS 派生后台孙进程时,结果 SHALL 明确标记清理不确定性。

#### Scenario: 正常执行

- **WHEN** 执行一条成功的 shell 命令
- **THEN** 返回输出、退出码 0 与耗时

#### Scenario: 命令失败返回退出码

- **WHEN** 执行一条退出码非零的命令
- **THEN** 返回非零退出码与输出,失败信息对调用方可见

#### Scenario: 危险命令被拒绝

- **WHEN** 命令命中危险模式(如 `rm -rf /`)
- **THEN** 命令不被执行,返回拒绝原因

#### Scenario: 敏感命令需确认

- **WHEN** 命令命中敏感类别(如递归删除、推送、提权、网络下载执行、进程终止、递归权限修改)
- **THEN** 命令不被执行,等待用户确认;未确认不执行;确认后正常执行

#### Scenario: 只读白名单免确认

- **WHEN** 命令为只读白名单命令(如 ls / cat / grep / pwd / git status / git diff)
- **THEN** 命令直接执行,无需确认

#### Scenario: 超时终止进程树

- **WHEN** 命令超过指定超时(含其派生的后台子进程)
- **THEN** 命令进程被终止并返回超时提示;派生进程树被尽力终止——Unix 经进程组全树击杀(含后台子进程),Windows 经 `taskkill /T` 击杀命令进程与直接子进程(MSYS 派生的后台孙进程受 taskkill 局限,尽力而为),清理不确定时结果明确标注

#### Scenario: 外层取消

- **WHEN** Agent 执行器在 bash 运行期间发出取消
- **THEN** bash 进入同一进程树清理路径,不会只取消等待方而继续执行;若平台无法确认全部后代进程已结束,结果标记清理不确定

#### Scenario: grep 无匹配豁免

- **WHEN** 执行以 grep 结尾的管道且 grep 无匹配
- **THEN** 退出码 1 不被视为失败,输出照常返回

#### Scenario: 输出保留末尾

- **WHEN** 命令输出超过截断上限
- **THEN** 返回末尾部分并标记截断,错误信息(通常在末尾)可见

#### Scenario: Windows 无 bash

- **WHEN** 在未安装 bash 的 Windows 环境执行命令
- **THEN** 返回带安装指引的可操作错误

## ADDED Requirements

### Requirement: 工具执行资源状态

工具实现 SHALL 向执行器提供可观察的执行状态,至少包含 running、completed、failed、timed_out、cancelled 和 cleanup_uncertain。状态不得依赖解析人类可读输出文本,并 SHALL 可用于事件 metadata 和测试断言。

#### Scenario: 正常完成状态

- **WHEN** bash 命令正常退出且进程树已收尾
- **THEN** 执行结果状态为 completed

#### Scenario: 清理不确定状态

- **WHEN** 命令超时或取消后平台无法确认所有派生进程已结束
- **THEN** 执行结果状态为 cleanup_uncertain,调用方得到明确诊断而不是普通成功结果
