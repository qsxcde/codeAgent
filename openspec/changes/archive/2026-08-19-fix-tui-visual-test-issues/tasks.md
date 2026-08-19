## 1. 终端背景融合(design D1)

- [x] 1.1 在 `textual_backend.py` 实现 `_strip_default_bg`(全字段重建 Style 去背景)与 `_NoDefaultBackground` LineFilter;`on_mount` 中将过滤器插入 `self._filters` 头部,并将 App/Screen/transcript/输入区 `styles.background` 设为 `ansi_default`
- [x] 1.2 单测:过滤器对 default 背景 segment 剥离背景、对显式色值背景与无样式 segment 原样透传;断言 `on_mount` 四处背景设置与过滤器插入位置
- [x] 1.3 pty 冒烟:启动 TUI 后屏幕字节流中不存在由 default 背景产生的不透明色码,而用户消息块/composer 的显式背景仍在

## 2. 键盘翻页恒定滚动视口(design D2)

- [x] 2.1 移除 `action_page_up/down` 的输入框聚焦分派分支,统一 `_notify_scroll(±page_delta)`(`page_delta = transcript 高度 - 1`,至少 1)
- [x] 2.2 更新 `tests/tui/test_textual_backend.py`:聚焦与非聚焦两种状态下 PgUp/PgDn 均触发视口滚动回调
- [x] 2.3 pty 冒烟:长工具输出展开态下 PgUp 上翻页、PgDn 回底并恢复跟随(新回复自动贴底)

## 3. 确认键状态感知拦截(design D3)

- [x] 3.1 移除 `_InputArea` 的 `y`/`n` Binding,改为键事件拦截:仅当 `backend.confirmation_active` 且按键为小写 `y`/`n` 时 `stop()` 并回调确认响应,其余情形不触碰事件
- [x] 3.2 单测:确认未激活时 y/n 按键不被拦截(等价于原生输入,含突发序列);激活时 y/n 分别触发批准/拒绝且事件不再进入输入文本
- [x] 3.3 pty 冒烟:突发输入含 n/y 的文本无丢失无重排;构造敏感工具触发确认条后 y/n 仍生效

## 4. stderr 空标签(design D4)

- [x] 4.1 `components.py` 工具块展开渲染:stderr 为空字符串时不输出 `stderr:` 行;补充/更新对应渲染测试

## 5. 收尾

- [x] 5.1 `uv run pytest` 全量通过(既有 flaky 项 `test_bash_pipeline_grep_exit_one_not_failure` 除外,如复现需注明)
- [x] 5.2 `openspec validate --change fix-tui-visual-test-issues` 与 `openspec validate --specs` 通过
