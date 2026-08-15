## 1. TUI 迁到 SessionManager(前置改造)

- [x] 1.1 `container.create_tui_app` 改用 SessionManager 装配(create_session_manager),view 经 `manager.current` 发起运行、经 `manager.subscribe` 订阅
- [x] 1.2 适配 `view.py` 的 `_submit` / `_interrupt` / `_exit` 路径为 manager 感知;`test_view` 系列同步更新并通过
- [x] 1.3 迁移步骤基线:全量离线测试全绿(此步独立提交)

## 2. 命令注册表与解析(纯函数)

- [x] 2.1 `app/tui/commands.py`:命令注册表(名称/参数/available 标志)+ `parse` 纯函数(`Literal | Command | UnknownCommand`)
- [x] 2.2 `//` 转义语义;未知命令与未接线命令(`/undo`)的可操作提示(NFR-U7)
- [x] 2.3 离线测试:parse 各分支、注册表校验、转义、未可用提示

## 3. 命令落地(无依赖命令)

- [x] 3.1 `/help` `/status` `/tools` 只读命令的 view 分派与渲染
- [x] 3.2 `/clear` 清空聊天区(transcript 状态重置)
- [x] 3.3 `/sessions` 参数形式:`/sessions` 列表、`/sessions new`、`/sessions <id>` 切换(复用 manager;浮层归任务 5)
- [x] 3.4 `/undo` 注册槽位(`available=False`,提示未可用);命令行为测试覆盖

## 4. replace_ports 与配置切换命令

- [x] 4.1 `SessionManager.replace_ports`:重建模型端口与 header 配置,保留会话壳与历史(逐壳转发 `AgentSession.replace_ports`)
- [x] 4.2 store `model_change` entry(追加式、读侧后写覆盖、旧文件回退 header model/effort)
- [x] 4.3 `/provider` `/model` `/effort` 命令接线(view → 组合根注入回调 → `manager.replace_ports`);model:effort 解析唯一引用 `split_model_pattern`
- [x] 4.4 离线测试:热切换后新配置生效、`model_change` 持久化、重启后按最新配置恢复

## 5. 模糊补全与选择器

- [x] 5.1 `fuzzy_match` 纯函数(精确 > 前缀 > 子串 > 子序列 > 编辑距离;≤50 项单次 <10ms)
- [x] 5.2 输入 `/` 建议浮层:view 层浮层状态 + backend 渲染通道(`set_suggestions` / `set_input_text` / `on_input_changed`)
- [x] 5.3 `_InputArea` 补全激活键位拦截(↑/↓/Tab/Enter),取消后恢复原生键位;Esc 先收起浮层
- [x] 5.4 provider/model/effort 选择器:候选数据经组合根注入(`_resolve_candidates`),筛选 + 直接输入,确认后触发 `replace_ports`
- [x] 5.5 离线测试:fuzzy_match 排序与性能、浮层交互、选择器确认→热切换链路

## 6. 收尾

- [x] 6.1 全量离线测试全绿(378/378);`openspec validate --change tui-interaction` 通过
- [x] 6.2 文档同步:v0.2.md 阶段 5 任务状态(T-44/T-45 ✅、E10 变更记录、验收表、测试基线)与 CLAUDE.md 测试数(333→378)
