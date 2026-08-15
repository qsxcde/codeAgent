# Design: fix-tui-command-completion

## Context

视觉测试(pilot 驱动 `run_test` + SVG 截图逐帧核对)定位到斜杠命令补全/提交链路四个缺陷:

1. **P0 确认循环**:输入 `/tools`(浮层激活)连按 Enter 永不提交。链路:`_InputArea.action_submit`(textual_backend.py:94)浮层激活时 Enter 走确认 → `view._on_suggestion_confirm` 调 `set_input_text` → TextArea 异步投递 Changed → `_on_input_changed` 重算建议(填入文本仍以 `/` 起始)→ 浮层复活 → 下次 Enter 再确认。同步清理输给异步事件。
2. **P1 裸 `/` 不弹列表**:`view._suggestion_context` 对空命令名返回 None(view.py:105),违反「以 / 起始即弹建议」。
3. **P1 输入行被裁剪**:`_Composer.styles.height` 仅按输入行数计算(lines+2,textual_backend.py:173),未计入建议条;建议条在 composer 内把输入行挤出固定高度,截图中输入 `/he` 时用户只看到建议行。
4. **P2 选择器空参**:`/model `(尾随空格)被 `if not rest` 归入命令名补全分支(view.py:104),选择器候选只有输入部分参数后才出现。

离线测试(378 全绿)未暴露 P0:测试同步调用 handler,无 textual 异步消息竞态。

## Goals / Non-Goals

**Goals**:四个缺陷全部修复,行为与 delta spec 一致;修复逻辑留在 view 层(引擎无关,离线可测);textual 层仅动 composer 高度。

**Non-Goals**:不改 `/sessions` store 注入与持久化(另立变更);不实现 Markdown 渲染与滚动(tui-rendering change 负责);不改 fuzzy 排序算法本身。

## Decisions

### D1:确认循环修复——视图层一次性抑制标志(P0)

`TuiApp` 增私有标志 `_suppress_next_suggestions: bool`:

- `_on_suggestion_confirm`:置位标志 → 调 `set_input_text(f"/{name}")`;
- `_on_input_changed`:若标志置位 → 清除标志、`set_suggestions([])`、直接返回(跳过本次建议计算)。该次通知正是 `set_input_text` 引发的异步 Changed;标志消费后用户继续编辑恢复正常计算。

标志只活在视图层,引擎无感;离线测试以「confirm 后补一次 `_on_input_changed` 调用」模拟异步时序。

**备选(否决)**:Enter 时若输入已完整命中命令则直接提交——改变「Enter 确认填入」语义(spec 选择填入场景),且不解决异步重弹。

**备选(否决)**:backend 层 `set_input_text` 静默置文本不触发 Changed——侵入 TextArea 内部事件模型,引擎耦合。

### D2:裸 `/` 全量建议(P1)

`_suggestion_context("/")` 返回 `("", list(_COMMANDS))`(空查询 + 全量候选)。`fuzzy_rank` 空查询语义需在 fuzzy.py 确认为「全量候选按原序返回」;若现实现不支持,在 `fuzzy_rank` 对空查询短路返回 `[(c, 0) for c in candidates]`(保持注册表序)。

### D3:composer 高度计入建议条(P1)

`_Composer` 抽私有 `_refresh_height()`:`height = clamp(输入行数, 1, MAX_HEIGHT) + 2 + 建议行数`,两处调用:

- `on_text_area_changed`(替换现有内联计算);
- `TextualBackend.set_suggestions`(更新建议条后同步调 `_refresh_height`)。

建议条隐藏(行数 0)时高度自然回落。

### D4:选择器空参候选(P2)

`_suggestion_context` 以分隔符存在性分流:`name, sep, rest = text[1:].partition(" ")`;

- `sep == ""`(无空格)→ 命令名补全(含 D2 的裸 `/`);
- `sep == " "` 且 name ∈ {provider, model, effort} → 返回 `(rest, 候选)`,`rest` 允许为空串(空查询 → 全量候选,与 D2 同源)。

## Risks / Trade-offs

- **抑制标志的时序边界**:若未来 backend 改为同步投递 Changed,标志会吃掉下一次真实编辑的建议——缓解:标志只在 `_on_input_changed` 消费一次,真实编辑必然先经该函数,最坏延迟一拍,可在回归测试固化「confirm→变更→再编辑」三步序列。
- **D3 高度抖动**:建议条弹出/收起改变 composer 高度,transcript 区高度随之变化——与主流 CLI(Cursor/Claude Code)行为一致,可接受。
- **textual 高度修复无法纯离线断言**:`_refresh_height` 计算可测(styles 值),像素级可见性靠 pilot 视觉回归(验收步骤保留复现脚本路径,不入库)。

## Open Questions

(无;四个缺陷修复路径已在复现脚本上验证可行方向)
