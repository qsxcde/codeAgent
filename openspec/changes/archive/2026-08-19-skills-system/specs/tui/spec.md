# tui Delta Specification

## ADDED Requirements

### Requirement: 技能命令

TUI SHALL 提供 `/skills` 斜杠命令:无参提交 SHALL 在聊天区列出已加载技能(名称/描述/来源路径,按名称排序);带参 `/skills <name>` SHALL 手动加载该技能——技能正文经注入消息进入会话并立即触发一轮回复;输入框内容为 `/skills ` 时 SHALL 弹出技能名模糊补全候选;加载不存在的技能 SHALL 反馈明确错误并列出可用技能名。

#### Scenario: 无参列出技能

- **WHEN** 用户提交 `/skills`
- **THEN** 聊天区列出已加载技能(名称/描述/来源路径),按名称排序;无技能时明确说明

#### Scenario: 带参手动加载

- **WHEN** 用户提交 `/skills <name>` 且技能已注册
- **THEN** 技能正文以标注技能名与来源的注入消息进入会话,并立即触发一轮回复

#### Scenario: 技能名补全候选

- **WHEN** 输入框内容为 `/skills `(命令后尾随空格)
- **THEN** 弹出技能名模糊补全候选,确认填入后提交即加载

#### Scenario: 加载不存在的技能

- **WHEN** 用户提交 `/skills <name>` 且技能未注册
- **THEN** 反馈明确错误并列出可用技能名,不注入任何内容

## MODIFIED Requirements

### Requirement: 斜杠命令体系

TUI SHALL 支持以 `/` 起始的斜杠命令;命令 SHALL 经注册表校验与解析,命中注册表 SHALL 执行命令而非发起对话;未知命令 SHALL 给出可操作错误提示而不误执行;以 `//` 起始的输入 SHALL 转义为字面量文本发送,不触发命令解析;已注册但尚未接线的命令 SHALL 明确提示"未可用",不静默忽略。建议浮层激活期间,提交键(Enter)的确认动作 SHALL 不阻塞后续提交:确认填入后再次按 Enter SHALL 提交输入内容执行命令。

#### Scenario: 发送斜杠命令

- **WHEN** 用户提交以 `/` 起始且命中注册表的文本
- **THEN** 执行对应命令,不发起对话;`/help` 显示命令帮助、`/clear` 清空聊天区、`/status` 显示会话状态、`/sessions` 列出并可切换会话、`/tools` 列出可用工具、`/provider` `/model` `/effort` 切换模型配置、`/fork` 从指定消息分叉会话、`/compact` 压缩当前会话上下文、`/skills` 列出或手动加载技能

#### Scenario: 压缩会话命令

- **WHEN** 用户提交 `/compact`
- **THEN** 当前会话执行上下文压缩,反馈压缩结果(摘要轮次数等);无会话时给出提示

#### Scenario: 分叉会话命令

- **WHEN** 用户提交 `/fork <message-id>`(缺省为最近一条 user 消息)
- **THEN** 当前会话从该消息之前分叉出新会话并切换;反馈分叉结果(新会话 id / 分叉点 / 原会话保留提示);分叉点非法时给出明确错误

#### Scenario: 状态含指令来源

- **WHEN** 用户提交 `/status`
- **THEN** 除会话状态外,显示本次会话加载的分层上下文文件来源列表(AGENTS.md 等)与已加载技能列表及诊断;无加载时明确说明

#### Scenario: 未知命令

- **WHEN** 用户提交未注册的斜杠命令
- **THEN** 显示可操作错误提示,输入内容不发送、不执行

#### Scenario: 字面量转义

- **WHEN** 用户输入以 `//` 起始
- **THEN** 按字面量文本发送(转义前缀不进入对话内容),不触发命令解析

#### Scenario: 未实现命令

- **WHEN** 用户提交已注册但尚未接线的命令
- **THEN** 显示"未可用"提示,不静默忽略、不执行

#### Scenario: 确认后提交

- **WHEN** 建议浮层激活,用户以确认键(Enter/Tab)填入建议后再次按 Enter
- **THEN** 输入内容被提交执行(不因浮层仍在而被再次消费为确认动作)
