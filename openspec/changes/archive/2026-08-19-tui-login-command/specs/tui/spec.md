# tui Delta Specification

## ADDED Requirements

### Requirement: 密钥配置命令

TUI SHALL 提供 `/login` 斜杠命令配置 provider 的 API key:无参提交 SHALL 弹出 provider 选择器(与 `/provider` 同款候选与筛选);带参 `/login <provider>` SHALL 直通该 provider;选择或直通后 SHALL 进入密钥输入流程;无需密钥的 provider(fake)SHALL 明确提示、不进入输入流程;保存成功后 SHALL 切换到该 provider(等价 `/provider` 热切换,状态栏与反馈更新);保存失败 SHALL 就地提示且不切换。

#### Scenario: 无参命令弹选择器

- **WHEN** 用户提交 `/login`
- **THEN** 弹出 provider 选择器,候选列表与筛选行为与 `/provider` 一致

#### Scenario: 带参直通

- **WHEN** 用户提交 `/login deepseek`
- **THEN** 直接进入 deepseek 的密钥输入流程,不弹选择器

#### Scenario: 无需密钥的 provider

- **WHEN** 用户对 fake 执行 `/login`
- **THEN** 提示该 provider 无需密钥,不进入密钥输入流程

#### Scenario: 保存并切换

- **WHEN** 用户提交有效密钥
- **THEN** 密钥写入配置,立即切换到该 provider,反馈保存结果

#### Scenario: 保存失败

- **WHEN** 配置不可写或保存出错
- **THEN** 就地提示错误,不切换 provider

#### Scenario: 已配置状态标记

- **WHEN** 登录选择器展示 provider 候选
- **THEN** 已配置密钥的 provider 带可见的已配置标记(如 `✓`)

### Requirement: 密钥掩码输入

密钥输入期间 TUI SHALL 隐藏明文显示(逐字符掩码,内部保留原文供提交);输入框 SHALL 显示可操作提示(目标键名、Enter 保存 / Esc 取消);输入期间建议浮层 SHALL 不弹出;空密钥提交 SHALL 提示并要求重新输入;Esc SHALL 取消输入回到空闲,不发起任何写入;提交或取消后输入框 SHALL 恢复普通输入形态(掩码解除、提示清除)。密钥 SHALL 不进入聊天区、会话历史与日志。

#### Scenario: 掩码显示

- **WHEN** 用户键入密钥
- **THEN** 输入框以掩码字符显示,不显示明文

#### Scenario: 操作提示

- **WHEN** 进入密钥输入
- **THEN** 输入框显示目标键名与 Enter 保存 / Esc 取消的键位提示

#### Scenario: 空值拒绝

- **WHEN** 用户空提交密钥
- **THEN** 提示密钥不能为空,保持在输入态

#### Scenario: 取消输入

- **WHEN** 用户按 Esc
- **THEN** 退出输入态回到空闲,不写入任何内容

#### Scenario: 明文不外泄

- **WHEN** 密钥输入或提交
- **THEN** 聊天区、会话历史与日志均不出现密钥明文

#### Scenario: 恢复普通输入

- **WHEN** 密钥提交或取消
- **THEN** 输入框恢复普通输入形态(掩码解除、提示清除)

### Requirement: 认证失败引导

会话层认证失败提示 SHALL 在 API Key 无效或未配置时给出可操作引导(指向 `/login` 命令),不只有错误本身。

#### Scenario: 401 引导文案

- **WHEN** 模型调用返回认证失败(如 HTTP 401)
- **THEN** 错误提示说明 API Key 无效或未配置,并引导使用 `/login` 命令配置密钥
