## Why

视觉测试(pilot 驱动真实 Textual 应用逐帧截图 + 最小复现)发现斜杠命令补全/提交链路四个缺陷,最严重的是**建议浮层激活时 Enter 永远无法提交命令**:Enter 被确认逻辑消费后,`set_input_text` 触发的异步 Changed 事件立即重算建议使浮层复活,形成"确认→重弹→再确认"循环——所有已注册命令必须先按 Esc 收起浮层才能提交,`/` 命令体系实际处于半瘫痪状态。其余缺陷:单独输入 `/` 不弹全量建议(违反 spec 场景)、浮层显示时 composer 高度不增长裁剪输入行(用户看不到正在输入的内容)、`/model ` 空参数不展示选择器候选。

## What Changes

- 修复 Enter 提交竞态(P0):建议确认填入后浮层 SHALL 收起且不被异步文本变更事件重弹,下一次 Enter 正常提交
- 单独输入 `/` SHALL 弹出全量命令建议列表(P1)
- composer 高度 SHALL 计入建议条高度,浮层显示时输入行不被裁剪(P1)
- `/provider ` `/model ` `/effort ` 空参数(带尾随空格)SHALL 展示选择器全量候选(P2)

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `tui`: 「斜杠命令体系」补充确认后提交语义;「模糊补全与选择器」修订弹出条件(裸 `/`)、确认循环修复、选择器空参候选、建议条不裁剪输入行的渲染要求

## Impact

- `src/codeagent/app/tui/view.py`:建议上下文判定(裸 `/`、选择器空参)、确认后抑制重弹、确认/提交语义
- `src/codeagent/app/tui/textual_backend.py`:`_Composer` 高度计算计入建议条
- `tests/tui/test_view.py`、`tests/tui/test_commands.py` 等离线测试同步补回归用例
- 不涉及 session/ai/tools/core 层;无破坏性变更
