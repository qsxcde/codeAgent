# Design: tui-login-command

## Context

动机与范围见 `proposal.md - Why`;行为契约见 `specs/tui/spec.md`。

现状约束(决定本设计的关键事实):

- key 读取链:`~/.codeagent/.env`(`CONFIG_ENV_FILE`,H10 固定目录)→ 各 provider `Config`(pydantic-settings,`env_prefix` + `env_file`)→ `make_llm` 非空校验。**没有写回机制**,模板注释要求"填入后重启生效"。
- **pydantic-settings 每次实例化 Config 都会重读 `.env`(无进程级缓存)**;`make_llm` 每次 `cfg = cfg or DeepSeekConfig()` 新建实例 → 写文件后重新走装配链即可拿到新 key,无需任何缓存失效代码(已验证 `ai/factory.py` / `ai/providers/deepseek.py` 调用链)。
- TUI 分层:`app/tui/view.py` 不读配置、不跨层(design 决策);跨层动作(热切换)经组合根注入回调 `rebuild_ports`。输入区为 textual `TextArea`(`_InputArea`,多行),**无内置 password 掩码**。
- 命令体系:`commands.py` 纯函数注册表(parse/help),`/provider /model /effort` 已有 picker 浮层 + 模糊补全基础设施(选择器命令填 `/kind ` 弹候选、值确认即生效)。
- 参照:pi-agent `/login`(选择器 → 对话框输入 → 保存 → 自动切换,`auth-guidance` 文案引导);opencode 凭据文件 0600。

## Goals / Non-Goals

**Goals**

- `/login` 闭环:选 provider → 掩码输入 key → 写 `.env` → 热切换(等价 `/provider`)+ 反馈;view 层零跨层。
- 掩码输入为可复用输入框能力(端口级 `set_input_mask`,未来其它敏感输入可复用)。
- 登录选择器已配置 `✓` 标记;401 文案带 `/login` 引导。

**Non-Goals**

- OAuth / device-code / 浏览器登录(当前 7 个 provider 均为 API key 形态;架构留扩展面即可)。
- key 加密存储(沿用 `.env` 明文 + 0600,与现状一致;加密属于独立课题)。
- key 有效性网络验证(opencode/pi 均不验证;失败由 401 引导闭环兜底)。
- 独立 credentials 文件(见决策 1)。

## Decisions

### 1. 存储:写回 `~/.codeagent/.env`(行级替换),不做独立 credentials 文件

- 写入函数 `write_env_key(provider, key)` 放 `app/config.py`(该层本就管理 `.env` 与 H10 安全模型):
  - 按 `<PREFIX>_API_KEY` 行级替换;不存在则追加;保留注释与其它的行;
  - 值含 `#` / `=` / 空白时用双引号包裹(对齐 dotenv 解析);
  - 写入用临时文件 + `os.replace` 原子替换(防崩溃半写);
  - 写后 `chmod 0600`(Windows 跳过,依赖用户目录 ACL)。
- 备选:独立 credentials 文件(auth.json 风格)+ provider Config 读取链合并——需改全部 provider 的 key 来源,破坏"provider 改动只动 `ai/providers/`"的简单性。**否**。

### 2. 热生效:写 `.env` → 复用 `rebuild_ports`,组合根注入 `save_key` 回调

- 组合根(`app/container.py`)注入 `save_key(provider, key) -> (model, effort)`:内部 = `write_env_key` + `rebuild_ports(provider=provider)`;返回新 model/effort 供状态栏与反馈。
- 生效原理:重建端口时 `make_llm` 新建 Config 实例重读 `.env`(决策依据见 Context),新 key 自然生效。
- view 层调用一个注入回调完成"保存 + 切换 + 反馈",**零跨层**;错误(ValueError / OSError)就地提示、不切换。
- 备选:显式构造 `Config(api_key=SecretStr(key))` 传 `make_llm`——更直白但不必要,且要为 `create_llm` 增加注入面、改动 ai 层签名;**否**(留作 pydantic-settings 缓存假设被打破时的逃生口)。

### 3. 掩码:端口新增 `set_input_mask` / `set_input_placeholder`,登录态切换为 `Input(password=True)`

- `TuiBackend` 端口 + `set_input_mask(masked: bool)` 与 `set_input_placeholder(text: str)`;`TextualBackend` 转发给 composer。
- **Spike 结论(2026-08-15)**:TextArea 渲染链路 `render_line → _line_cache → wrapped_document → get_line` 中,行缓存 key 不含掩码态(切态后残留明文缓存)、`wrapped_document` 基于原文(掩码字符宽度差异会导致 wrap 行不一致)、选区/光标需自绘——显示层替换方案不干净。**改选方案 D**:登录态把输入组件切换为 textual `Input(password=True)`(原生掩码、原生 placeholder、单行正合 API key),退出换回 `_InputArea`。组件常驻 compose、`display` 互斥切换(零异步 mount),`_KeyInput(Input)` 子类覆写 `action_submit` 复用现有 `InputSubmitted` 消息与提交路径;Esc 不绑定,冒泡到应用层由视图在登录态优先取消。
- 代价(已接受):登录态失去多行输入与 Shift+Enter 换行——key 为单行,无影响;普通输入行为完全不变。

### 4. 视图状态机:`_login_pending` + 三态分支

- `_login_pending: str | None`(待输入 key 的 provider;None = 非登录态)。
- 登录态下:`_submit` 走保存分支(空值提示停留);`_interrupt` 的 Esc 先取消登录态;`_suggestion_context` 返回 None(建议浮层禁用);`_on_input_changed` 不弹浮层。
- 入口:`/login` 无参 → 复用 `_open_inline_picker("provider")` 的填 `/login ` 弹候选;`/login <name>` 带参直通;值确认(浮层 Enter)→ 进入登录态。fake 等无需密钥 provider 直通提示、不进入登录态。
- `✓` 标记:组合根注入 `configured_providers: set[str]`(读 `.env` 判断 `<PREFIX>_API_KEY` 非空),`_render_suggestions` 的 value 语境为 `/login` 显示已配置标记。

### 5. 401 引导:仅文案,不动逻辑

- `session/session.py` 认证失败分支追加「可用 /login 配置密钥」;行为不变,一行文案(对齐 pi `auth-guidance`)。

## Risks / Trade-offs

- [Input 与 TextArea 组件切换的布局/焦点抖动] → display 互斥切换 + 显式 focus;掩码态固定 1 行;spike 已确认 run_test 环境可驱动。
- [登录态失去多行/换行能力] → API key 单行,无实际影响;退出即恢复。
- [`.env` 写入崩溃半写 / 并发] → 临时文件 + `os.replace` 原子替换;写入前读、替换后不重写其它行。
- [key 含 `#` / `=` / 空格破坏 dotenv 解析] → 写入引号转义;测试覆盖特殊字符。
- [`.env` 明文权限] → chmod 0600 对齐 opencode auth.json;Windows 跳过(主目录 ACL)。
- [pydantic-settings"每次实例化重读 .env"假设失效] → 逃生口:显式构造 Config 注入 key(决策 2 备选);风险低(文档行为 + 现有测试依赖)。

## Migration Plan

- 无数据迁移:`.env` 兼容追加;旧版本无 `/login` 不影响既有 `.env` 手改工作流。
- 回滚:撤掉命令注册与状态机分支即可,无残留数据(写入即用户主动行为)。

## Open Questions

- 掩码字符选 `●`(与确认条风格一致);不影响 spec/方案,实现时定。
