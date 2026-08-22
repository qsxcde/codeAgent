## Context

见 proposal.md — Why。复用资产:
- `SessionRef.parent_session` 已存在(v0.2 fork 落盘)——树边数据现成;
- `SessionStore.list()` 返回全部会话(含父 id / 标题 / 时间)——树的输入现成;
- `manager.switch(id)` + 订阅跟随——切换导航现成(T-44 前置改造);
- TUI 命令注册/分派/`append_info` 渲染——`/tree` 与 `/sessions` 增强的载体现成。

## Goals / Non-Goals

**Goals:**
- `build_tree(refs)` 纯函数:平铺会话列表 → 树(孤儿独立根、同级时间序)。
- `/tree` 命令:展示 fork 链 + `/tree <id>` 切换。
- `/sessions list` 树形缩进展示。

**Non-Goals:**
- 不做 `/tree` 的交互式选择器(切换已由 `/sessions` 选择器覆盖,`/tree` 专注展示结构 + 直接 id 切换)。
- 不引入新的持久化字段(树完全由既有 `parentSession` 推导,纯视图层)。
- 不做超深树的折叠/虚拟滚动(会话数为小量级,直接全量渲染)。

## Decisions

### D1: `build_tree` 为独立纯函数模块(非 store 方法)

`build_tree(refs) -> list[TreeNode]`,其中 `TreeNode = (ref, children)`;零 I/O、零跨层,可离线测试。

- **理由**:树是视图派生,非存储契约——放 store 会误导(store 不关心父子展示);独立纯函数与 `app/agents.py` / `app/skills.py` 的"纯函数镜像"先例一致,`test_decoupling` 友好;
- 输出根列表(非单根):孤儿/多根场景天然覆盖;
- 循环防护:parentSession 理论无环(fork 只进不退),但防御性断言(检测到环时报诊断而非死循环)。

### D2: 树展示为文本缩进(append_info),不引入新组件

`/tree` 与 `/sessions list` 均以缩进 + 分支字符(`├─`/`└─`)输出到聊天区(复用 `model.append_info`),不新增浮层/树组件。

- **理由**:会话量小(几十),文本树已足够;与 `/sessions list` 既有"append_info 文本输出"风格一致;零新 UI 组件。
- `/tree <id>` 切换复用 `manager.switch`(订阅跟随既有,无需重建视图)。

### D3: `/sessions list` 格式变更(平铺 → 树形)为轻微 BREAKING

既有 `test_sessions_list_switch_and_new` 断言平铺格式,同步更新为树形断言。

- **理由**:F-23 明确要求"父子关系展示增强",格式变化是需求本身;变更记录在 proposal 标 BREAKING。

## Risks / Trade-offs

- [孤儿会话(父文件被删)挂错父] → build_tree 检测父不存在 → 独立根,不丢失不误导;
- [`/sessions list` 格式变更破坏既有输出断言] → 显式标 BREAKING,同步更新测试;
- [树渲染深度大导致输出长] → 会话数为小量级,全量渲染可接受(不做折叠,Non-Goal)。

## Migration Plan

无数据迁移:树完全由既有 `parentSession` 推导,无新字段、无格式变更。`/sessions list` 输出格式变化为展示层改动,不影响会话文件。

## Open Questions

无(探索阶段已收敛:纯函数建树 + `/tree` 展示/切换 + `/sessions` 缩进增强)。
