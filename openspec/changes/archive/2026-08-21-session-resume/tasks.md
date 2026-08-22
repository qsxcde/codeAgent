## 1. 命令注册与参数解析

- [x] 1.1 `commands.py`:`sessions` 注册为 `picker=True`(值候选 = 会话列表)
- [x] 1.2 `_cmd_sessions` 分派增加 `recent` 分支(`continue_recent`,反馈会话 id)

## 2. 交互式选择器

- [x] 2.1 视图 `_picker_candidates("sessions")`:候选 = `manager.list()` 会话展示串(标题 + id 后缀;标记当前会话)
- [x] 2.2 值确认分派:`_on_suggestion_confirm` 对 sessions 走 `manager.switch(id)`(订阅跟随既有)并反馈
- [x] 2.3 无会话空态:候选为空时无参 `/sessions` 显示「暂无历史会话」提示

## 3. 测试

- [x] 3.1 命令分派测试:`recent` 恢复最近(有会话)/新建(无会话);`list`/`new`/`<id>` 回归
- [x] 3.2 选择器测试:候选列表(标题+id、当前标记)、无参弹浮层、↑↓ 选择后确认切换、无会话空态
- [x] 3.3 全量 `uv run pytest` 全绿(零网络零密钥);`openspec validate` 通过
