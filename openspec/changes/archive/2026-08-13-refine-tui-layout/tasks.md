## 1. 组件层样式重构(components.py)

- [x] 1.1 `UserBlock` 改为命令记录行:`❯`(ACCENT)+ 文本(TEXT),去掉全宽 `USER_BG` 补齐(spec「对话输入与回复渲染」用户消息场景;design D2)
- [x] 1.2 `AssistantBlock` 思维链弱化:元信息标题(思考耗时/工具数,DIM)+ 每行 `│` 前缀 + THINKING 灰缩进;`TuiModel` 注入 `clock` 记录 thinking 起止、TOOL_CALL 计数(spec「思考过程独立展示」;design D3)
- [x] 1.3 `ToolCallBlock` header 重构:折叠符 `▶`/`▼`(DIM)+ 状态图标 + 工具名 + 参数摘要;构造改为收结构化 `args: dict`;新增 `_summarize_args` / `_summarize_result` 纯函数(bash `exit N · Xs`、write `N B`、edit `N 处`,解析失败回退首行)(spec「工具调用过程可见」;design D4)
- [x] 1.4 新增 `FooterLine` 组件:左端 `● ready · Esc 退出`、右端 `model · effort`(右对齐,截断右侧优先);`TuiModel` 持 `footer` 数据(spec「双端底部状态条」;design D5)

## 2. 后端布局与契约(textual_backend.py / backend.py / view.py)

- [x] 2.1 `_TextualApp` Dock 布局:compose 改为 `transcript → TopSeparator → composer → BottomSeparator → footer`;composer 为固定 `height:1` 的 Horizontal(`❯` + Input),移除 round border 与自由高度(design D1)
- [x] 2.2 `TuiBackend` 契约升级:`set_status(line: RichLine)`、新增 `set_footer(line: RichLine)`;`view._flush_render` 直接传 `status.render(width)[0]` 与 `footer.render(width)[0]`(修复富样式当 str 传的 bug);`TextualBackend` 用 `_line_to_text` 渲染(spec「双端底部状态条」;design D5)
- [x] 2.3 footer 双端渲染:`Label` 改为 `Horizontal` 双端(左状态/快捷键,右 model · effort),focus/blur 不触发整行变色(design D1/D5)

## 3. 装配(container.py / tui/main.py)

- [x] 3.1 组合根新增 `create_tui_app()` 工厂:`Settings()` + `split_model_pattern` 解析 `(model, effort)`,构造 `TuiApp(session, backend, footer=FooterInfo(model, effort))`;`tui/main.py` 只调组合根(design D5,跨层集中在组合根)
- [x] 3.2 `TuiApp` 构造签名加 `footer` 参数(带默认值,不破坏现有测试构造)(design D5)

## 4. 测试与验证

- [x] 4.1 更新 `tests/tui/test_components.py`:用户命令记录行断言、思维链弱化断言、工具折叠符/参数摘要/结果摘要断言、`FooterLine` 双端与右对齐断言(含假时钟注入测耗时显示)
- [x] 4.2 更新 `tests/tui/test_view.py`:`StubBackend.set_status/set_footer` 签名改 `RichLine`;`_flush_render` 传值断言;新增 footer 富样式传递断言
- [x] 4.3 `uv run pytest` 全量通过,不引入新失败(保持 204 项全绿)
