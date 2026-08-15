## 1. 滚动交互(T-47)

- [ ] 1.1 `backend.py` 增 `on_scroll` 端口与 `ScrollHandler` 类型(行增量,正数上滚)
- [ ] 1.2 textual 实现:`_Transcript` 滚轮事件转发;App 层 PageUp/PageDown 绑定并按焦点分派(输入框聚焦归编辑区,否则滚动视口)
- [ ] 1.3 `view._on_scroll` 分派 → `Transcript.scroll` / `scroll_to_bottom`;stub 后端注入滚动事件的离线测试
- [ ] 1.4 spec「alt 屏渲染与滚动」全场景闭环测试:滚轮上滚解除跟随、滚回底部恢复跟随、键盘翻页

## 2. Markdown 渲染(T-46)

- [ ] 2.1 `md_renderer` 无状态纯函数(加粗/行内代码/列表/标题/代码块 → `list[RichLine]`,单遍线性扫描)
- [ ] 2.2 宽容策略:未闭合结构按已识别部分渲染、不抛错;body 超长(阈值可注入)退化为纯文本
- [ ] 2.3 `theme.py` 词表扩展(`CODE_BG` / `HEADING` 等)+ textual 映射同步;词表受控不变式测试
- [ ] 2.4 `AssistantBlock` 注入 `md_renderer`(默认实现),流式期间每帧对累积正文重解析
- [ ] 2.5 测试:结构标签序列断言、未闭合宽容、超长退化、流式中间帧渲染

## 3. 收尾

- [ ] 3.1 全量离线测试全绿;`openspec validate --change tui-rendering` 通过
- [ ] 3.2 文档同步:v0.2.md 阶段 5 任务状态与变更记录(E 记录)
