# Tasks: fix-tui-command-completion

## 1. Enter 提交竞态修复(P0)

- [x] 1.1 `view.py` 增 `_suppress_next_suggestions` 标志:`_on_suggestion_confirm` 置位后调 `set_input_text`;`_on_input_changed` 见标志即清标志、收起浮层并跳过本次计算
- [x] 1.2 回归测试:confirm → 补一次 `_on_input_changed`(模拟异步 Changed)→ 断言浮层收起、`_suggestions` 为空;再补一次真实编辑 → 断言建议恢复计算
- [x] 1.3 回归测试:confirm 后直接 submit → 断言命令被执行(transcript 出现命令输出),不出现"确认循环"

## 2. 裸 `/` 全量建议(P1)

- [x] 2.1 `_suggestion_context` 对空命令名返回 `("", 全量命令)`;确认 `fuzzy_rank` 空查询返回全量候选按原序,不支持则在 fuzzy.py 短路补齐
- [x] 2.2 回归测试:输入 `/` → 断言建议为全量命令(注册表序);fuzzy_rank 空查询单测

## 3. composer 高度计入建议条(P1)

- [x] 3.1 `textual_backend.py` `_Composer` 抽 `_refresh_height()`(输入行数 clamp + 2 + 建议行数);`on_text_area_changed` 与 `TextualBackend.set_suggestions` 两处调用
- [x] 3.2 离线断言:注入建议后 composer.styles.height 增长对应行数,清空后回落

## 4. 选择器空参候选(P2)

- [x] 4.1 `_suggestion_context` 按分隔符存在性分流:`/model ` 等空参形式返回 `(空查询, 候选)`;无空格仍走命令名补全
- [x] 4.2 回归测试:`/model ` → 全量 model 候选;`/provider ` `/effort ` 同;`/model`(无空格)仍是命令名补全

## 5. 收尾

- [x] 5.1 全量离线测试全绿(基线 378 起,新增用例全过;不引入新失败)
- [x] 5.2 pilot 视觉回归:确认填入后再次 Enter 即提交(无确认循环)、裸 `/` 弹全量、浮层显示时输入行可见、`/model ` 出候选
- [x] 5.3 `openspec validate --change fix-tui-command-completion` 通过
