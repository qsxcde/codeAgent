## Why

provider API key 目前只能手动编辑 `~/.codeagent/.env` 并重启生效;TUI 内 `/provider` 切到未配置 key 的 provider 会直接报错,没有任何引导闭环。参照 pi-agent(LoginDialogComponent + auth-guidance)与 opencode(`opencode auth login` / TUI `/login`)的做法,在 TUI 内完成「选 provider → 输 key → 保存 + 热切换」一次到位,消除手动改文件与重启。

## What Changes

- 新增 `/login` 斜杠命令(注册表 + 分派 + `/help` 文案 + 补全候选):
  - 无参 → provider 选择器(复用现有 picker 浮层 / 模糊补全);带参 `/login <provider>` 直通;
  - fake provider 提示"无需密钥",不进入输入态。
- 掩码输入态:provider 确认后,输入框清空并进入掩码模式(输入显示为 `●`,内部保留原文,提交取原文),placeholder 提示「输入 `XXX_API_KEY`,Enter 保存 / Esc 取消」;输入态期间禁用建议浮层;Esc 取消回空闲;空 key 提交提示并停留。
- 保存:写回 `~/.codeagent/.env`(行级替换 `<PROVIDER>_API_KEY` 一行,保留注释与其它键;写入后收紧权限 0600,Windows 跳过);不覆盖用户已有配置。
- 热生效:保存成功后重建 LLM 端口并切换到该 provider(复用 `/provider` 热切换路径),状态栏与反馈更新;保存失败就地提示、不切换。
- 引导闭环(对齐 pi 的 auth-guidance):会话 401「API Key 无效或未配置」错误文案追加「可用 /login 配置密钥」;登录选择器中已配置 key 的 provider 打 `✓` 标记。
- 密钥安全:掩码显示,key 不进 transcript / 会话历史 / 日志。

## Capabilities

### New Capabilities

(无)

### Modified Capabilities

- `tui`:斜杠命令体系新增 `/login` 命令(配置 provider 密钥);输入框新增掩码输入态(隐藏显示、Enter 提交 / Esc 取消、禁用建议浮层);登录选择器展示已配置状态。

## Impact

- `app/tui/commands.py`:`/login` 注册项(纯声明)。
- `app/tui/view.py`:登录状态机(provider 选择 → 掩码输入态)、分派、反馈;仍不跨层,保存经组合根注入回调。
- `app/tui/backend.py` / `textual_backend.py`:`set_input_mask(bool)` 端口方法 + `_InputArea` 掩码渲染(显示层替换,内部文本不变)。
- `app/config.py`:`write_env_key(provider, key)`(行级替换 + 0600;config 层本就管理 `.env`)。
- `app/container.py`:`save_key` 回调注入(写 `.env` + 热切换,唯一跨层点)。
- `session/session.py`:401 错误文案追加 `/login` 引导。
- 测试:命令解析注册、视图状态机(stub 后端)、`.env` 读写(隔离配置目录)、装配、401 文案。
- 无新增依赖;不触碰 `core/`、`session/` 编排逻辑(除一行文案)。
