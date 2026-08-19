# Tasks: tui-login-command

## 1. 配置层:`.env` 写回

- [x] 1.1 `app/config.py` 新增 `write_env_key(provider, key)`:按 `<PREFIX>_API_KEY` 行级替换/追加,保留注释与其它行;值含 `#`/`=`/空白时双引号包裹;临时文件 + `os.replace` 原子替换;写后 chmod 0600(Windows 跳过)
- [x] 1.2 测试 `tests/test_config.py`:`write_env_key` 隔离配置目录覆盖——已存在键替换、键不存在追加、注释保留、特殊字符值引号、权限 0600、不可写目录报错

## 2. 后端端口:掩码输入

- [x] 2.1 `backend.py` 端口新增 `set_input_mask(masked: bool)`(placeholder 复用现有输入区能力或一并加 `set_input_placeholder`)
- [x] 2.2 spike:textual `_InputArea` 掩码渲染可行性(显示层替换 vs shadow-buffer),按 design 决策 3 选定实现路径
- [x] 2.3 `textual_backend.py` 实现掩码渲染:掩码态显示 `●`、内部保留原文、提交取原文;placeholder 随登录态切换
- [x] 2.4 测试:stub/真实后端断言掩码开关调用与提交原文(掩码态提交返回真实 key,非掩码态行为不变)

## 3. 视图状态机:`/login` 命令

- [x] 3.1 `commands.py` 注册 `login`(args=(provider,), picker=True)+ `/help` 文案
- [x] 3.2 `view.py` 状态机:`_login_pending`;无参 → 复用 provider picker;带参直通;值确认进入登录态;fake 等无需密钥 provider 提示不进入
- [x] 3.3 登录态分支:`_submit` 保存(空值提示停留)、Esc 取消、建议浮层禁用(`_suggestion_context` 返回 None)
- [x] 3.4 登录态反馈:进入时设置 placeholder + 掩码;保存成功/失败反馈并恢复普通输入;`configured_providers` 注入后登录选择器显示 `✓` 标记
- [x] 3.5 测试(view 状态机,stub 后端):无参进选择器、带参直通、空值拒绝、Esc 取消(不调用保存)、保存成功/失败反馈、fake 直通提示、✓ 标记、掩码开关调用顺序

## 4. 组合根装配

- [x] 4.1 `container.py` 注入 `save_key(provider, key) -> (model, effort)`:内部 = `write_env_key` + `rebuild_ports(provider=...)`,错误就地抛 ValueError/OSError;`configured_providers` 从 `.env` 解析非空 key 的 provider 集
- [x] 4.2 测试(隔离配置目录 + FakeClient 注入):`save_key` 写文件 + 端口重建生效;`configured_providers` 正确;TuiApp 装配携带新回调

## 5. 认证失败引导

- [x] 5.1 `session/session.py` 401 分支文案追加「可用 /login 配置密钥」,逻辑不变
- [x] 5.2 测试:认证失败文案断言含 /login 引导

## 6. 收尾

- [x] 6.1 全量测试绿(`.venv/bin/python -m pytest`,基线 532 不回归)
- [x] 6.2 `docs/iteration/v0.2.md` 追加 E-record(变更摘要 + 测试数)
