## Context

实测(pty 驱动 + pyte 屏幕捕获)确认三处缺陷的根因,详见 proposal.md。现状约束:

- Textual 8.2.8 的 `ANSIToTruecolor` 过滤器把 Rich 默认背景(`bgcolor.is_default`)映射为主题实色 rgb(12,12,12),这是全屏不透明 `#121212` 的直接来源;过滤链 `App._filters` 在初始化时构建,可插入自定义 `LineFilter`。
- `action_page_up/down` 当前在输入框聚焦时把按键分派给 TextArea 光标翻页;而应用内焦点永远停留在输入区(无其它可聚焦控件、点击 transcript 会触发折叠),键盘翻页因此不可达。
- `_InputArea` 的 `y`/`n` 绑定为 priority:无论确认条是否激活都会先于 TextArea 消费按键,再经 `insert()` 回填;突发输入下回填与原生输入竞争,产生丢失/重排(`banana` → `nnbaaa`)。

## Goals / Non-Goals

**Goals:**
- 顶层屏幕与聊天区背景与终端融合;显式背景块(用户消息块、composer)保持深灰区分。
- PageUp/PageDown 在任何焦点状态下都能整页滚动聊天区视口,保留 follow 翻转与回底恢复语义。
- 确认未激活时 y/n 零干预输入(含粘贴/突发);激活时键位归属确认条的行为不变。

**Non-Goals:**
- 不改滚轮滚动、点击折叠、Esc 打断/退出键位(实测正常)。
- 不改安全分类器与确认请求的会话侧链路。
- 不引入失焦/焦点切换交互(被 D2 方案取代)。

## Decisions

### D1:透明背景 = `ansi_default` 背景 + 自定义 LineFilter 剥离 default 背景

在 `on_mount` 将 App/Screen/transcript/输入区的 `styles.background` 设为 `ansi_default`,并向 `self._filters` 头部插入自定义过滤器:对每个 segment,若其样式背景为 Rich default(`is_default`),以去背景方式重建 `Style`(Rich Style 不可变,无 setter,需全字段构造),`bgcolor=None`。显式色值背景(#2b2b2b 等)不命中该分支,原样透传。

被否路径(上一轮已实证):`transparent` 关键字渲染为 `48;2;0;0;0` 黑色;`ansi_color=True` 会激活 CSS 的 `&:ansi` 变体(占位符变成 `2;30;47`)。

### D2:PageUp/PageDown 恒定滚动视口

删除 `action_page_up/down` 的焦点分派分支,统一调用 `_notify_scroll(±page_delta)`(`page_delta = transcript 高度 - 1`)。备选:提供失焦途径(点击状态栏失焦/Tab 循环)——被否,理由是无其它可聚焦控件、点击 transcript 与折叠切换冲突,且多一步操作违背滚动直觉。代价是失去 TextArea 原生整页光标移动;composer 仅 1~4 行,无实际损失。

### D3:确认键改为状态感知的按键拦截

移除 `_InputArea` 上 `y`/`n` 的 Binding,改在 `_InputArea.on_key`(或等价键事件钩子)中拦截:仅当 `backend.confirmation_active` 为真且按键为小写 `y`/`n` 时,`stop()` 事件并回调确认响应;否则完全不触碰,按键走 TextArea 原生路径(单键、粘贴、突发输入一致)。备选:保留绑定但在未激活时不消费——Textual 绑定命中即消费,「不做事」会吞字符,无法透传,故不可行。

### D4:stderr 为空不渲染标签行

工具块展开渲染时,stderr 为空字符串则不输出 `stderr:` 行(仅消视觉噪声,不改数据)。

## Risks / Trade-offs

- [自定义 LineFilter 依赖 Textual 内部过滤链结构,升级可能失效] → 依赖版本已锁定;补单测验证过滤器行为,pty 冒烟断言屏幕流中 default 背景不透明色码为 0。
- [on_key 拦截需精确匹配键名,大写/输入法场景] → 仅匹配小写 `y`/`n`(与原绑定语义一致);确认条激活时提示文案引导用户按小写键。
- [PgUp/PgDn 恒滚视口后,多行编辑中的光标翻页习惯改变] → composer 上限 4 行,方向键/鼠标足够;规范已同步该语义。
- [显式背景块与非透明终端的观感差异] → 属既有设计(深灰块为消息区分手段),不在本变更内调整。
