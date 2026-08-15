## Context

- 现状:`AssistantBlock` 纯文本累积渲染;`Transcript` 已实现 follow/scroll/scroll_to_bottom(组件层滚动语义完整,spec 场景差输入来源);`TuiBackend` 端口无滚动回调;textual `_InputArea` 现有 Enter/Shift+Enter binding;样式为受控标签词表(theme.py,测试断言标签序列)。
- 约束:NFR-P5 流式渲染 ≥30fps;组件纯函数(给定事件序列 → 渲染行);样式标签受控(不引入 ANSI);`TuiBackend` 是引擎缝。
- 动机见 proposal.md;行为契约见 specs(tui delta)。

## Goals / Non-Goals

**Goals:**
- Agent 正文 Markdown 结构(加粗/行内代码/列表/标题/代码块)以受控样式渲染,流式期间即时呈现。
- 滚动输入闭环:滚轮 + PageUp/PageDown → follow 翻转语义,spec「alt 屏渲染与滚动」全场景可离线断言。

**Non-Goals:**
- 完整 CommonMark 合规(仅 5 类结构,表格/图片/链接/嵌套列表不覆盖)。
- 自研终端引擎(textual 保持唯一实现;端口不变即未来可换)。
- 会话树 UI / 分支渲染(v0.3)。

## Decisions

1. **流式全量重解析(方案 A)**:Markdown 渲染为无状态纯函数 `md_renderer(text, width) -> list[RichLine]`,经 `AssistantBlock.__init__(md_renderer=...)` 注入(仿 clock 注入模式,离线测试注入桩/直接断言输出)。每帧对当前累积 body 全量重解析——body 通常 ≤ 几 KB,单次解析 < 1ms,远低于 30fps 预算。
   - 备选 B(增量解析/终态一次解析):增量解析状态复杂、闭合边界多;终态解析违背 spec「文本增量累积」的流式精神。均否决。
2. **宽容解析策略**:未闭合结构按已识别部分渲染(如 `**bold` 未闭合 → 按纯文本),绝不抛错、不渲染错误背景;终态自然完整。代码块以"完整块才上背景"为界,流式中间帧显示文本即可。
3. **超长退化阈值**:body 超过 ~20k 字符退化为纯文本渲染(绕过解析),保护 NFR-P5;阈值常量可注入。
4. **`on_scroll` 端口**:`ScrollHandler = Callable[[int], None]`(行增量,正数上滚);`view._on_scroll(delta)` → `transcript.scroll(delta)`(scroll 内已处理 follow 翻转,`render` 内已处理滚到底恢复)。textual 实现:`_Transcript` 绑定滚轮事件转发;PageUp/PageDown 走应用层绑定,按焦点分派——输入框聚焦时归属编辑区,否则滚动视口。
5. **样式标签扩展**:新增 `CODE_BG`(行内代码/代码块背景)、`HEADING`、`LIST_BULLET`、`BLOCK_MARK` 等词表项,theme.py 与 textual 映射同步;测试延续"断言标签序列"模式,词表保持受控(新标签必须进 theme.py + PALETTE,不得硬编码色值)。

## Risks / Trade-offs

- [每帧全量解析拖慢帧率] → 超长退化阈值 + 单次解析复杂度为线性(单遍扫描),可加基准测试锁定 <1ms。
- [PageUp/PageDown 被 TextArea 吞掉] → 显式按键归属:应用层绑定 + 焦点判断;与 tui-interaction 的补全键位共用一个"按键分派表"设计思路,键位不重叠。
- [样式标签扩散失控] → 词表受控不变式(测试断言 PALETTE 覆盖所有标签)+ 新标签进 __all__。

## Migration Plan

纯增量,无部署;实现顺序:T-47 滚动(端口 → 引擎 → view → 测试)→ T-46 Markdown(解析器 → AssistantBlock 接入 → 词表 → 测试),互不阻塞可并行。

## Open Questions

无(流式重解析性能、按键归属均已在本设计定案;剩余为纯实现细节)。
