## Why

对当前 TUI 的视觉/交互实测(pty 驱动 + 屏幕捕获)暴露三类功能性问题:1) 此前已实现的「透明背景」机制在当前代码与规范中整体缺失,全屏渲染为不透明实色背景;2) PageUp/PageDown 键盘翻页在任何可达状态下都不生效——输入框永远持有焦点,按键被路由给输入区光标翻页,而没有任何途径使输入框失焦;3) 确认条的 y/n 优先绑定在突发/粘贴输入下与输入区原生处理竞争,导致字符丢失或重排(如 `banana` → `nnbaaa`,提示词中 `in/done` 丢 n)。三者均为用户可感知的功能缺陷,需一并修复。

## What Changes

- 重新实现终端背景融合:App/Screen/transcript/输入区背景改用终端默认背景语义,并以行级过滤器剥离 Rich default 背景,使 TUI 背景与终端自身背景一致(不再出现不透明色块)。
- 键盘翻页语义调整:PageUp/PageDown 无论输入框是否聚焦,均滚动聊天区视口(整页);不再分派给输入区光标翻页(多行输入框 1~4 行,无整页光标移动需求)。
- 确认条键位仅在确认激活时拦截:确认未激活时 y/n 按键(含粘贴、突发输入)完全归属输入区原生处理,杜绝字符丢失/重排;确认激活时 y/n 仍归属确认条。
- 工具结果展开区在 stderr 为空时不渲染「stderr:」空标签行(轻微视觉噪声)。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `tui`:
  - 「alt 屏渲染与滚动」:键盘滚动 Scenario 由「输入框未聚焦时翻页归视口、聚焦时归输入区」改为「PageUp/PageDown 始终滚动视口」。
  - 「确认交互」:键位归属补充约束——确认未激活时 y/n 不拦截,突发/粘贴输入不受影响。
  - 新增「终端背景融合」Requirement:组件背景 SHALL 与终端背景融合,不出现不透明实色底。

## Impact

- 代码:`src/codeagent/app/tui/textual_backend.py`(过滤器与背景设置、App 按键分派、_InputArea 键位拦截)、`src/codeagent/app/tui/components.py`(stderr 空标签)。
- 规范:`openspec/specs/tui/spec.md` 三个 Requirement 的增量同步。
- 测试:`tests/tui/` 相关单测(按键分派、确认键拦截条件、背景过滤器)。
- 无 API/依赖变更;不改变滚轮滚动、点击折叠、Esc 打断等已验证正常的行为。
