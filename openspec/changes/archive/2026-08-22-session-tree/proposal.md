## Why

会话 fork 后,TUI 无法看清分支结构:数据层 `parentSession` 链已完备(v0.2 fork 落盘),但 `/sessions list` 是平铺列表,无父子关系展示、无 `/tree` 导航命令。用户分叉多个会话后难以理解"哪个会话从哪个分叉而来、当前在哪条分支"——这是 F-23 会话树 UI 的剩余部分。

## What Changes

- **会话树数据视图(T-60)**:新增 `build_tree(refs)` 纯函数——把 `SessionStore.list()` 返回的平铺会话列表组织为树(父会话 → 子会话分支),孤儿会话(父不存在)作为独立根;纯函数零 I/O,可离线测。
- **TUI `/tree` 命令(T-61)**:展示当前会话的 fork 链树(缩进 + 分支字符,含标题与 id),并可切换到指定节点(复用 `manager.switch`,订阅跟随既有);无参展示全树,`/tree <id>` 切换。
- **`/sessions list` 父子展示增强(T-61)**:列表从平铺改为带缩进的树形展示(复用 `build_tree`),父会话下缩进展示其分支子会话。
- **BREAKING(轻微)**:`/sessions list` 输出格式变化(平铺 → 树形缩进),既有断言该格式的测试需同步更新。

## Capabilities

### New Capabilities

- `session-tree`:会话树数据视图与导航能力——`build_tree` 纯函数组织 fork 链、TUI `/tree` 命令展示与切换、`/sessions list` 父子缩进展示。

### Modified Capabilities

- `sessions`:会话管理契约补充——fork 链可组织为树视图(孤儿作为独立根),会话列表可呈现父子关系。
- `tui`:`/sessions` 命令需求扩展(父子缩进展示);新增 `/tree` 命令(展示 fork 链 + 切换节点)。

## Impact

- `src/codeagent/session/`:`build_tree` 纯函数(新模块或 store 扩展,建议独立纯函数模块,零跨层)。
- `src/codeagent/app/tui/view.py`:`/tree` 命令注册与 handler、`/sessions list` 树形渲染(复用 `build_tree`)、切换节点分派。
- `src/codeagent/app/tui/commands.py`:`tree` 命令注册(带可选 `session-id` 参数)。
- 测试:`build_tree` 纯函数(含孤儿/循环/排序边界)、`/tree` 展示与切换、`/sessions list` 缩进断言(更新既有平铺断言)。
