# tools Specification

## Purpose

定义编程 Agent 的原子工具集能力:read / write / edit / bash / grep / find / ls / skill 八工具的对外行为契约,以及工具层共享的路径解析、输出截断、并行写串行化、跨平台语义。
## Requirements
### Requirement: 工具注册与装配

系统 SHALL 通过 `make_tools` 工厂装配八个原子工具,名称固定为 `read`、`write`、`edit`、`bash`、`grep`、`find`、`ls`、`skill`。每个工具 SHALL 对外暴露稳定的名称、描述与输入参数 schema,供编排层绑定;`skill` 工具 SHALL 在装配时注入技能注册表(组合根提供),不读取配置、不跨层;工具 SHALL 同时提供只读的运行环境能力快照供诊断和后续能力选择使用;MCP 工具 SHALL 经组合根加载后追加到工具列表(内建工具恒保留),命名含 `mcp__<server>__<tool>` 前缀。

#### Scenario: 工厂产出全部工具

- **WHEN** 调用 `make_tools` 装配工具集
- **THEN** 返回的工具列表中包含全部八个名称:read、write、edit、bash、grep、find、ls、skill

#### Scenario: 装配时注入工作目录

- **WHEN** `make_tools` 收到的配置含 `cwd`
- **THEN** 全部八个工具都以该 `cwd` 为相对路径解析基准

#### Scenario: 技能工具注入注册表

- **WHEN** 装配 `skill` 工具
- **THEN** 技能注册表由组合根注入,工具按名称查找技能;未注入注册表时工具返回不可用提示

#### Scenario: MCP 工具追加

- **WHEN** 用户级 MCP 配置存在且 server 加载成功
- **THEN** 工具列表在八个内建工具之后追加 MCP 工具(`mcp__<server>__<tool>` 命名),内建工具不受影响

#### Scenario: 能力快照可用于诊断

- **WHEN** 工具工厂或运行时请求当前环境能力
- **THEN** 系统返回稳定的只读能力快照,至少列出 shell、平台、外部检索器和权限策略,每项包含可用性及缺失原因,且不执行工具调用或修改会话状态

### Requirement: 工具环境能力探测

工具层 SHALL 提供平台无关的只读能力探测。探测结果 SHALL 至少覆盖真实 shell、操作系统平台、可选外部检索器(`rg`、`fd`)和文件/命令权限策略;每项 SHALL 包含稳定名称、`available` 状态以及面向用户的诊断代码和消息。探测 SHALL 使用当前注入的环境和工作目录,不可用依赖 SHALL 被明确标记而不是抛出未处理异常或静默降级为可用。探测 SHALL 不执行任意用户命令、不读取工具结果、不写入文件,且同一环境下结果可重复。

#### Scenario: 完整能力探测

- **WHEN** 当前环境提供 shell、平台信息、`rg`/`fd` 中的一项或多项以及安全策略
- **THEN** 返回所有能力项及其可用状态、解析路径或策略说明,而不是只返回成功项

#### Scenario: 缺少 shell

- **WHEN** 当前平台没有可解析的真实 shell
- **THEN** shell 能力为不可用,诊断包含稳定的缺失代码和安装或配置指引,其它能力仍正常返回

#### Scenario: 可选检索器缺失

- **WHEN** `rg` 或 `fd` 不在 PATH 或不可执行
- **THEN** 对应能力标记为不可用并说明将使用纯 Python 路径,不把缺失可选依赖报告为工具故障

#### Scenario: 平台能力可识别

- **WHEN** 在 Windows、macOS 或 Linux 环境执行探测
- **THEN** 平台项使用稳定的标准标识,并说明 shell 解析和进程清理等平台相关能力是否可用

#### Scenario: 权限策略可识别

- **WHEN** 工具安全分类器已装配
- **THEN** 权限策略能力标记为可用并说明读写边界、确认和拒绝策略;未装配时标记为不可用并给出诊断,不执行越权探测

#### Scenario: 探测无副作用

- **WHEN** 用户查看能力快照或 TUI `/status` 读取能力
- **THEN** 不启动 shell/检索命令、不触发确认、不修改文件或会话 JSONL,重复读取返回等价结果

#### Scenario: 状态输出暴露诊断

- **WHEN** 用户查看 TUI `/status`
- **THEN** 状态输出包含能力分组及每项的可用/不可用状态和必要诊断,并保留现有运行、上下文和用量信息

### Requirement: read 文件读取

`read` 工具 SHALL 读取文本文件内容并返回,支持 `offset`/`limit` 分页;大文件按字节与行双重上限截断并明确标记;二进制或非 UTF-8 文件 SHALL 返回可读前缀并说明截断。

#### Scenario: 读取文本文件

- **WHEN** 读取一个存在的文本文件
- **THEN** 返回其文本内容,并在输出中标明总行数

#### Scenario: 分页读取

- **WHEN** 以 `offset`/`limit` 读取一个长文件
- **THEN** 只返回指定行范围,并标记「已截断,可通过 offset 继续」及剩余行数

#### Scenario: 读取二进制文件

- **WHEN** 读取一个非 UTF-8 的二进制文件
- **THEN** 返回可读前缀(限字节数)并明确说明文件为二进制

#### Scenario: 读取不存在的文件

- **WHEN** `read` 的目标路径不存在
- **THEN** 返回明确错误,不抛未捕获异常

### Requirement: write 文件写入

`write` 工具 SHALL 创建新文件或完整覆盖已有文件;父目录不存在时 SHALL 自动创建;写入的文本 SHALL 使用 LF 换行;成功返回写入字节数。

#### Scenario: 覆盖写文件

- **WHEN** 向已存在文件写入新内容
- **THEN** 文件内容被完整替换,返回写入字节数

#### Scenario: 自动创建父目录

- **WHEN** 写入路径的父目录不存在
- **THEN** 父目录被递归创建,写入成功

#### Scenario: 写入使用 LF 换行

- **WHEN** 新建文件写入含换行的内容
- **THEN** 落盘字节使用 LF 换行,不随平台换行约定改变

### Requirement: edit 精确编辑

`edit` 工具 SHALL 按 `old_string`→`new_string` 精确替换;`old_string` 在文件中出现多处且未指定 `replace_all` 时 SHALL 报错;找不到或 `old_string` 为空时 SHALL 报错;写回 SHALL 保留文件原有换行约定与 BOM。

#### Scenario: 精确替换

- **WHEN** 目标文件中 `old_string` 恰好出现一次
- **THEN** 该处被替换为 `new_string`,其余内容不变

#### Scenario: 匹配不唯一

- **WHEN** `old_string` 出现多次且未设置 `replace_all`
- **THEN** 返回「文本不唯一」错误,文件不变

#### Scenario: 找不到匹配

- **WHEN** 文件中不存在 `old_string`
- **THEN** 返回「未找到匹配文本」错误,文件不变

#### Scenario: 保留原始换行约定

- **WHEN** 编辑一个使用 CRLF 换行或带 BOM 的文件
- **THEN** 编辑后文件仍使用 CRLF 换行并保留 BOM,不改变未触碰区域

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

### Requirement: 工具执行资源状态

工具实现 SHALL 向执行器提供不依赖人类可读输出文本的结构化状态。执行状态至少 SHALL 区分 `running`、`completed`、`failed`、`rejected`、`timed_out` 和 `cancelled`；资源清理状态 SHALL 独立使用 `not_required`、`pending`、`confirmed`、`failed`、`uncertain` 或 `unsupported` 表示。结果输出的完整性 SHALL 独立提供 `complete`、`truncated`、`incomplete` 或 `unknown` 等结构化事实，并可同时携带总量、展示量、截断原因和继续读取/导出信息。新事件和新结果 SHALL 将正常成功规范化为 `completed`；现有持久化数据或订阅方中的 `ok` 与聚合 `cleanup_uncertain` 值 SHALL 可被兼容读取，但不得阻止调用方获得原始执行状态和独立清理状态。状态、清理和输出完整性字段 SHALL 可直接用于事件 metadata、TUI 展示和测试断言。

#### Scenario: 正常完成状态

- **WHEN** bash 命令正常退出且进程树已收尾
- **THEN** 执行结果状态为 `completed`，清理状态为 `not_required` 或 `confirmed`，输出完整性单独反映结果是否完整

#### Scenario: 超时与清理已确认

- **WHEN** 命令超过超时且执行器确认受控进程资源已经停止
- **THEN** 执行状态为 `timed_out`，清理状态为 `confirmed`，调用方不会将其展示或统计为普通成功

#### Scenario: 清理不确定状态

- **WHEN** 命令超时或被取消且平台无法确认所有派生资源已经停止
- **THEN** 执行状态保留 `timed_out` 或 `cancelled`，清理状态为 `uncertain` 或 `unsupported`，调用方得到明确的清理诊断而不是普通成功结果

#### Scenario: 清理失败状态

- **WHEN** 工具提供清理接口但清理调用失败
- **THEN** 结果保留原始失败、超时或取消事实，并额外标记清理状态为 `failed` 或 `uncertain`，不能依据接口存在与否推断清理成功

#### Scenario: 同步工具不可抢占

- **WHEN** 同步工具在线程中执行且取消只能停止等待方
- **THEN** 工具结果明确保留未确认清理状态，执行器不得释放该状态对应的资源保证或允许安全自动重试

#### Scenario: 结果截断不改变执行结论

- **WHEN** 工具成功、失败、超时或取消，但返回内容超过输出限制或只能保留部分内容
- **THEN** 执行状态和清理状态保持原值，输出完整性独立标记为 `truncated` 或 `incomplete`，并提供可用的总量、预览范围和继续读取/导出诊断

#### Scenario: 状态不依赖文本

- **WHEN** 工具返回相同文本但结构化执行状态、清理状态或输出元数据不同
- **THEN** 调用方依据结构化字段区分这些结果，不通过匹配错误提示、图标或人类可读摘要推断状态

#### Scenario: 旧结果兼容读取

- **WHEN** session 恢复只包含旧版 `ok` 或 `cleanup_uncertain` 状态而缺少新字段
- **THEN** 系统将其安全映射为可展示的完成或清理不确定状态，并将缺失的清理/输出完整性标记为未知，不阻塞会话恢复

### Requirement: bash 子进程环境注入

`bash` 工具 SHALL 在派生子进程时向子进程环境注入 `NO_COLOR=1`(与现有 `LANG` 注入并列)。目的:使登录 shell 初始化(如 conda 的 libmamba-solver 颜色探测)在无 tty 的分离进程中不再因调用 `isatty()` 而产生 stderr 噪音;该注入 SHALL 不改变命令的执行语义、输出内容与退出码判定。

#### Scenario: 子进程环境含 NO_COLOR

- **WHEN** `bash` 工具派生子进程执行一条命令
- **THEN** 子进程环境变量中包含 `NO_COLOR=1`,命令可从环境中读到该值

#### Scenario: 注入不影响命令结果

- **WHEN** 命令在注入 `NO_COLOR` 的子进程环境下执行
- **THEN** 命令的输出与退出码与未注入时一致(仅无 tty 的颜色类行为可能不同),失败/成功判定不变

### Requirement: grep 内容搜索

`grep` 工具 SHALL 在指定目录或文件中按正则或字面量搜索文本;返回匹配行并带 `path:行号: 内容` 格式;支持忽略大小写、glob 过滤、context 上下文行与结果上限;SHALL 跳过噪声目录(如 `.git`、`node_modules`);无匹配时 SHALL 明确说明。

#### Scenario: 正则搜索

- **WHEN** 以正则模式搜索目录
- **THEN** 返回每条匹配的路径、行号与内容

#### Scenario: 字面量搜索

- **WHEN** 以 `literal` 模式搜索含正则元字符的字符串
- **THEN** 按字面量精确匹配,不做正则解析

#### Scenario: 上下文行

- **WHEN** 指定 `context` 参数
- **THEN** 每条匹配前后各带指定行数的上下文,上下文行与匹配行可区分

#### Scenario: 跳过噪声目录

- **WHEN** 搜索目录内含 `node_modules`、`.git` 等噪声目录
- **THEN** 噪声目录内的文件不被搜到

#### Scenario: 无匹配

- **WHEN** 搜索无任何结果
- **THEN** 返回「无匹配」的明确结果

### Requirement: find 文件查找

`find` 工具 SHALL 按 glob 模式查找文件(支持 `**` 递归);返回相对搜索根的路径列表;SHALL 跳过噪声目录;支持结果上限;返回路径 SHALL 使用统一的正斜杠表示。

#### Scenario: 递归查找

- **WHEN** 以 `**/*.py` 模式查找
- **THEN** 返回所有匹配文件的路径,格式统一

#### Scenario: 跳过噪声目录

- **WHEN** 查找目录内含 `node_modules`、`.venv` 等噪声目录
- **THEN** 噪声目录内的文件不出现

#### Scenario: 无匹配

- **WHEN** 查找无任何结果
- **THEN** 返回「无匹配文件」的明确结果

### Requirement: ls 目录列举

`ls` 工具 SHALL 列出指定目录条目;目录条目 SHALL 带 `/` 后缀;条目 SHALL 大小写不敏感排序;支持结果上限;路径不存在或不是目录时 SHALL 报错。

#### Scenario: 列举目录

- **WHEN** 列举一个存在的目录
- **THEN** 返回排序后的条目列表,目录条目带 `/` 后缀

#### Scenario: 路径不存在

- **WHEN** 列举一个不存在的路径
- **THEN** 返回明确错误

### Requirement: 路径解析

所有工具 SHALL 以注入的 `cwd` 为基准解析相对路径;支持 `~` 展开;解析失败 SHALL 返回明确错误而非静默歧义。

#### Scenario: 相对路径解析

- **WHEN** 工具收到一个相对路径
- **THEN** 该路径按注入的 cwd 解析,与进程当前目录无关

#### Scenario: 家目录展开

- **WHEN** 路径以 `~` 开头
- **THEN** 展开为当前用户主目录下的对应路径

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

### Requirement: 并行写串行化

对同一文件的并发写操作 SHALL 被串行化,不丢更新;对不同文件的写操作 SHALL 不受影响可并行。

#### Scenario: 同文件并发写不丢更新

- **WHEN** 多个线程/调用并发对同一文件执行写类操作(如 `write` + `edit`)
- **THEN** 操作按顺序逐个生效,最终文件内容与串行执行一致

#### Scenario: 异文件并发写互不阻塞

- **WHEN** 并发对不同文件写
- **THEN** 两操作互不等待,均完成

### Requirement: 输出截断

工具输出 SHALL 按字节与行双重上限截断,截断时 SHALL 明确标记,不让调用方误以为看到全量。

#### Scenario: 超限标记

- **WHEN** 输出超过任一上限
- **THEN** 输出被截断并带截断标记,说明被截断的事实

### Requirement: 离线可测与平台无关

工具 SHALL 通过注入的文件操作接口完成 I/O,不依赖真实文件系统即可离线测试;工具行为 SHALL 在 Windows / Linux / macOS 上一致(路径表示、换行、shell 行为)。

#### Scenario: 注入操作接口离线测试

- **WHEN** 测试注入一个替代的文件操作实现
- **THEN** 工具逻辑可在无真实文件系统、无网络下运行并被断言

#### Scenario: 跨平台输出一致

- **WHEN** 同一输入在三个平台运行同一工具
- **THEN** 返回结果不包含平台特有的路径表示或换行差异

### Requirement: 工具结果治理

工具层 SHALL 为每次工具调用生成统一的结果事实:执行状态、语义成功、输出完整性、原始总字节数、原始总行数、当前展示量、截断原因、路径、退出码、耗时和变更摘要。进入模型的文本 SHALL 是有界的治理结果,不得要求调用方解析人类可读文本来判断结果是否完整。

#### Scenario: 完整结果保留结构化事实

- **WHEN** 工具在限制内完成并返回结果
- **THEN** 结果标记为 complete,提供真实的字节/行统计和工具适用的路径、退出码、耗时或变更摘要,模型文本与展示事实保持一致

#### Scenario: 超过工具硬上限

- **WHEN** 工具输出超过配置的字节或行上限
- **THEN** 工具返回有界文本,标记 `truncated` 和具体限制来源,报告原始总量与当前展示量,不得将结果描述为完整

#### Scenario: 结果策略保留工具语义

- **WHEN** read、grep、find、ls、bash、write 或 edit 产生结果
- **THEN** 系统分别保留可继续读取的范围参数、匹配/条目数量、stderr 与退出码、目标路径或变更行数等关键语义,不能只保留无上下文的文本片段

#### Scenario: 非文本外部结果显式处理

- **WHEN** MCP 或其它外部工具返回图片、资源或无法转为文本的内容
- **THEN** 系统将可用内容转换为受控结果或标记为 unsupported/不可直接展示,并保留可定位的结构化引用,不得静默丢弃

#### Scenario: 超大输出不要求无界内存

- **WHEN** 外部进程或工具持续产生远超展示上限的输出
- **THEN** 采集和治理流程以有界内存生成结果统计与预览,继续消耗或终止输出的行为可诊断,不得因一次结果无界增长而阻塞其它会话

### Requirement: 验证所需的结构化执行元数据

工具层 SHALL 为可执行命令的结果提供机器可读的 `exit_code`、执行状态、耗时和输出截断信息，并通过会话事件 metadata 传播；调用方 MUST 能依据这些字段判定成功、失败、超时、取消和清理不确定，而无需解析人类可读输出。被豁免的退出码语义（如 grep 无匹配） SHALL 在结构化结果中明确标注。

#### Scenario: 非零退出码结构化返回

- **WHEN** bash 命令以退出码 2 结束
- **THEN** 工具结果包含 `exit_code=2` 和失败状态，事件 metadata 可直接读取该值

#### Scenario: 超时结构化返回

- **WHEN** bash 命令超时并进入进程清理
- **THEN** 工具结果包含超时状态、可用退出码或空值、耗时和清理确定性标记

#### Scenario: 输出截断可识别

- **WHEN** 命令输出超过工具限制
- **THEN** 结果包含截断标记和保留输出范围，调用方不需要猜测输出是否完整

### Requirement: AgentTool 显式适配

工具层或应用组合根 SHALL 为每个内建工具和已加载的 MCP 工具提供显式的 `AgentTool` 适配入口。适配后的工具 SHALL 暴露稳定的名称、描述和 provider-neutral 参数定义,并通过 `execute(tool_call_id, arguments, signal, on_update)` 处理调用,返回 core 可消费的统一工具结果。core 不得读取具体工具的输入 schema、执行方法或安全配置来推断适配方式。

#### Scenario: 内建工具完成适配

- **WHEN** 组合根装配内建 read、write、edit、bash、grep、find、ls、skill 工具
- **THEN** 每个工具都以 `AgentTool` 形态传入 Agent Runtime,名称、描述、参数定义和执行结果保持原有语义

#### Scenario: MCP 工具完成适配

- **WHEN** 组合根加载一个 MCP 工具
- **THEN** MCP 工具以 `AgentTool` 形态追加到运行时工具列表,名称仍遵守 `mcp__<server>__<tool>` 规则,core 无需知道 MCP 客户端类型

#### Scenario: 适配器传递取消与进度

- **WHEN** Agent Runtime 对适配后的工具发出取消或进度回调
- **THEN** 适配器将取消信号和进度回调传递给底层工具,并把真实清理状态转换为统一工具结果

#### Scenario: 旧工具不能绕过适配

- **WHEN** 一个只提供历史 `Args`/`invoke` 接口的工具未经过显式适配
- **THEN** 组合根不得将其直接挂载到 Agent Runtime,系统返回可诊断的装配错误而不是依赖 core 的隐式兼容
