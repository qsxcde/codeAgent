## 1. 依赖与入口

- [x] 1.1 `pyproject.toml` 加 `textual` 主依赖(运行时入口需要);`uv sync` 后确认可 import
- [x] 1.2 `app/main.py` 加 `--tui` 入口 flag:headless 保持默认路径,`--tui` 转交 TUI 启动(见 §5)

## 2. 组件树 `app/tui/components.py`(纯 render,引擎无关)

- [x] 2.1 定义组件基类 `Component`:`render(width: int) -> list[str]`;模块 docstring 注明「不碰终端/textual,纯函数可离线测」(design D2)
- [x] 2.2 实现 `Transcript`(有序子块 + 滚动状态)+ `UserBlock` / `AssistantBlock`(thinking 折叠区 + body)/ `ToolCallBlock`(name/args/status: pending→done/error + 截断 result)/ `ErrorBlock` / `CancelledBlock`(对应 spec「流式回复渲染」「工具调用过程可见」)
- [x] 2.3 实现 `StatusLine`(status/model/usage,对应 spec「状态栏实时反馈」)与 MVP `Editor`(文本 + 提交;预留 `set_completion_provider` / `set_command_handler` 扩展缝,design D6)
- [x] 2.4 实现事件 → 组件状态映射的纯逻辑(`TuiModel`:维护块列表,暴露 `apply(event)` 变更状态;事件回调只调它,不碰渲染,design D3)

## 3. TuiBackend 端口 + textual 后端

- [x] 3.1 `app/tui/backend.py`:`TuiBackend` Protocol(run / render(lines) / set_status / on_submit / on_interrupt / on_resize / exit_document),docstring 注明引擎可换(design D1)
- [x] 3.2 `app/tui/textual_backend.py`:textual 实现——alt 屏 + 「显示行」widget(呈现组件渲染的 ANSI 行)+ `Input` 编辑器 + 键事件转发(Esc 中断/退出,不走终端信号,design D5/D7)
- [x] 3.3 后端 `render` 实现差分更新 + 合并请求(每帧最多一次,design D4)

## 4. TuiApp 逻辑 `app/tui/view.py`

- [x] 4.1 `TuiApp`:装配 `AgentSession` 订阅 + `TuiModel` 状态 + `request_render` 合并(事件回调只 apply + 排渲染,≥30fps,design D4)
- [x] 4.2 打断/退出语义:`on_interrupt` 按运行态分派——运行中 `session.abort()`、空闲退出;`RUN_CANCELLED` 事件回状态栏 IDLE(design D5;spec「运行中打断」)
- [x] 4.3 提交语义:`on_submit` → 在事件循环上 `create_task(session.run(text))`;`exit_document` 以视口宽度打印完整 transcript(design D5;spec「退出完整文档」)

## 5. 入口接线

- [x] 5.1 `app/tui/main.py`:装配 `AgentSession`(复用 `app/container.create_agent_session`)+ `TuiApp` + `textual_backend`,启动;`app/main.py --tui` 转交此处

## 6. 测试 `tests/tui/`

- [x] 6.1 夹具:脚本化事件序列→ `TuiModel` → 渲染行(离线零终端;不 import textual——测试直接构造 AgentEvent,与 FakeClient.steps 等价的事件注入)
- [x] 6.2 组件渲染测试:各块(含 thinking 折叠、ToolCall 状态流转)与事件→渲染映射(对应 spec 各场景)
- [x] 6.3 打断/退出语义测试:运行中 abort → CancelledBlock + 状态栏 IDLE;空闲退出 → 完整文档(注入 stub 后端)
- [x] 6.4 渲染合并测试:N 个增量事件 → 恰 1 次渲染调用(design D4;spec「帧率达标」)
- [x] 6.5 全量 `uv run pytest` 通过(现 240 项 = 224 + 16 新增,零失败)

## 7. 收尾

- [x] 7.1 更新需求分析 FR-1.11 / v0.1 迭代文档:MVP TUI 落地说明(斜杠命令等仍登记下一迭代)
- [x] 7.2 归档本 change 至 `openspec/changes/archive/`,specs 同步回主 `openspec/specs/tui/spec.md`(归档于 `openspec/changes/archive/2026-08-13-restore-tui/`,主 spec 已同步至 `openspec/specs/tui/spec.md`)
