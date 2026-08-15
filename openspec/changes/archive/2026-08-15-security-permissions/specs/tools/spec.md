## ADDED Requirements

### Requirement: 文件访问边界

read / write / edit 工具 SHALL 默认限定在注入的工作区边界内访问:边界内访问直接执行;越出边界的**读**访问 SHALL 放行并附带越界提示(警告),越出边界的**写与编辑**访问 SHALL 需用户确认,未确认不得执行;边界判定 SHALL 防符号链接逃逸(工作区内符号链接指向边界外文件不得穿透边界);判定 SHALL 平台无关(Windows / macOS / Linux 行为一致)。

#### Scenario: 边界内访问

- **WHEN** 目标路径解析后位于工作区内
- **THEN** 访问直接执行,无需确认

#### Scenario: 越界读警告放行

- **WHEN** 读目标解析后位于工作区外
- **THEN** 读取放行,结果携带越界提示,模型可见

#### Scenario: 越界写需确认

- **WHEN** 写/编辑目标解析后位于工作区外
- **THEN** 访问需用户确认;未确认不执行;确认后正常执行

#### Scenario: 符号链接逃逸拦截

- **WHEN** 工作区内路径经符号链接解析后指向工作区外
- **THEN** 按越界处理(读警告 / 写需确认),不静默穿透边界

## MODIFIED Requirements

### Requirement: bash 命令执行

`bash` 工具 SHALL 在注入的工作目录执行 shell 命令并返回输出与退出码;默认超时 120 秒、上限 600 秒;超时或中断时 SHALL 终止整个命令进程树;输出按字节与行双上限截断并保留末尾;危险命令 SHALL 被拒绝并返回拒绝原因;敏感命令 SHALL 需用户确认,未确认不得执行;只读白名单命令 SHALL 免确认执行;grep 无匹配(退出码 1)SHALL 不视为失败;Windows 下无可用 bash 时 SHALL 返回可操作安装指引。

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
- **THEN** 命令进程被终止并返回超时提示;派生进程树被尽力终止——Unix 经进程组全树击杀(含后台子进程),Windows 经 `taskkill /T` 击杀命令进程与直接子进程(MSYS 派生的后台孙进程受 taskkill 局限,尽力而为)

#### Scenario: grep 无匹配豁免

- **WHEN** 执行以 grep 结尾的管道且 grep 无匹配
- **THEN** 退出码 1 不被视为失败,输出照常返回

#### Scenario: 输出保留末尾

- **WHEN** 命令输出超过截断上限
- **THEN** 返回末尾部分并标记截断,错误信息(通常在末尾)可见

#### Scenario: Windows 无 bash

- **WHEN** 在未安装 bash 的 Windows 环境执行命令
- **THEN** 返回带安装指引的可操作错误
