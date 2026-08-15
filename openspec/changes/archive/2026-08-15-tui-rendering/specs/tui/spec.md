## ADDED Requirements

### Requirement: Markdown 正文渲染

Agent 正文 SHALL 以受控样式渲染 Markdown 结构:加粗、行内代码、列表、标题与代码块 SHALL 有可区分的样式标签;流式增量期间 SHALL 持续按最新累积内容渲染,不等待回合结束;未闭合的 Markdown 结构 SHALL 宽容渲染(不崩溃、不显示错误背景),终态 SHALL 渲染完整结构;正文超过阈值长度时 SHALL 退化为纯文本渲染以保持帧率。

#### Scenario: 流式 Markdown

- **WHEN** 正文增量包含 Markdown 结构
- **THEN** 聊天区按当前累积内容渲染对应样式,无需等待回合结束

#### Scenario: 结构样式区分

- **WHEN** 正文包含加粗、行内代码、列表、标题与代码块
- **THEN** 各结构以不同受控样式标签渲染,可离线断言标签序列

#### Scenario: 未闭合宽容

- **WHEN** 流式过程中 Markdown 结构尚未闭合
- **THEN** 按部分样式/纯文本渲染,不崩溃、不显示错误背景;回合结束后渲染完整结构

#### Scenario: 超长退化

- **WHEN** 正文长度超过阈值
- **THEN** 渲染退化为纯文本,不因 Markdown 解析拖慢帧率

## MODIFIED Requirements

### Requirement: alt 屏渲染与滚动

TUI SHALL 在 alt 屏渲染,应用自己管理滚动;流式输出 SHALL 自动跟随底部,用户上滚浏览历史后 SHALL 解除跟随,滚回底部 SHALL 恢复跟随;滚动输入 SHALL 支持滚轮与 PageUp/PageDown 键,输入框聚焦时按键归属 SHALL 显式分派。

#### Scenario: 流式跟底

- **WHEN** 流式输出使聊天区增长
- **THEN** 视口自动跟随底部,最新内容可见

#### Scenario: 上滚浏览历史

- **WHEN** 用户上滚查看历史
- **THEN** 视口停止跟随底部,新输出不强制跳回底部

#### Scenario: 回到底部恢复跟随

- **WHEN** 用户滚回底部
- **THEN** 视口恢复自动跟随

#### Scenario: 滚轮滚动

- **WHEN** 用户在聊天区滚动滚轮
- **THEN** 视口按滚动方向移动;上滚解除跟随,滚回底部恢复跟随

#### Scenario: 键盘滚动

- **WHEN** 输入框未聚焦且用户按 PageUp/PageDown
- **THEN** 视口按页滚动,按键不被输入区吞掉;输入框聚焦时按键归属输入区
