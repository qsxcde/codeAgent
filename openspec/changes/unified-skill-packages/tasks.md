## 1. Package 数据模型与配置路径

- [x] 1.1 定义用户级/项目级 Package 记录、锁定记录、来源类型、revision 和安装状态的数据模型
- [x] 1.2 在 `src/codeagent/app/config.py` 增加 Package Store、Registry 和 Lock 文件路径解析，保持现有 `CONFIG_DIR` 行为不变
- [x] 1.3 为注册记录实现稳定的读写、版本校验和损坏文件诊断，确保写入失败时保留旧记录

## 2. Package 安装与生命周期

- [x] 2.1 新增 Git URL 和本地目录 Package Source，实现临时目录下载/复制、Git revision 解析和安装根路径校验
- [x] 2.2 实现 Package install/update/remove/list/reload 服务，采用校验成功后原子替换，失败时不破坏已有 Package
- [x] 2.3 实现可选 `codeagent-package.json` 清单解析，支持 `skills` 根目录、Bootstrap Skill 和工具映射声明
- [x] 2.4 实现 Package 路径穿越、非法 id、重复 id 和缺失 Skill 根目录的安全诊断

## 3. Skill Registry 扩展

- [x] 3.1 扩展 `src/codeagent/app/skills.py`，递归发现 Package `skills/**/SKILL.md`，并保留直接目录的一层发现语义
- [x] 3.2 按个人直接目录 > 个人 Package > 项目直接目录 > 项目 Package > 内建的优先级合并来源、去重和同名遮蔽
- [x] 3.3 扩展 `Skill`/诊断及列表视图的来源元数据，显示 Package id、版本或 revision 和安装作用域
- [x] 3.4 为无清单但包含 `skills/using-superpowers/SKILL.md` 的 Package 实现 Bootstrap 约定推断，并提供可见诊断

## 4. CodeAgent Adapter 与 Bootstrap Runtime

- [x] 4.1 新增 CodeAgent Adapter，生成 `using-superpowers` Bootstrap、工具映射和能力声明
- [x] 4.2 将现有 `read`、`write`、`edit`、`bash`、`grep`、`find`、`ls`、`skill` 工具映射到抽象动作，并声明 subagent/todo/web 等缺失能力
- [x] 4.3 新增 Bootstrap Runtime 状态，记录 Bootstrap 标识、Adapter 版本和当前上下文已加载 Skill，支持去重
- [x] 4.4 修改组合根端口装配，使 Bootstrap、工具映射和普通 `available_skills` 按规定顺序生成，普通 Skill 正文仍按需加载

## 5. 会话生命周期接线

- [x] 5.1 在新会话和恢复会话的首轮上下文中注入 Bootstrap，验证同一会话普通轮次不重复注入
- [x] 5.2 在 provider/model/effort 端口重建和 TUI 会话切换时刷新 Adapter/Registry，并保持上下文去重
- [x] 5.3 在上下文压缩完成后重新注入 Bootstrap 和工具映射，允许模型按需重新加载当前任务 Skill
- [x] 5.4 将 Bootstrap 状态和 Package/Adapter 诊断接入 `/status`，不把普通 Skill 正文写入会话持久化记录

## 6. CLI 与 TUI 入口

- [x] 6.1 在 `src/codeagent/app/main.py` 增加 Skill Package 的 install/list/update/remove/reload CLI 入口和错误码
- [x] 6.2 扩展 `src/codeagent/app/tui/commands.py` 与 `src/codeagent/app/tui/view.py`，支持 `/skills` 的 Package 子命令并保持 `/skills <name>` 手动加载兼容
- [x] 6.3 在 TUI 技能列表、Package 列表和诊断中显示来源、作用域、版本/revision、Bootstrap 状态和未执行扩展提示

## 7. 测试与验收

- [x] 7.1 增加 Package 清单、Git/local source、锁定记录、原子失败和安全路径校验的单元测试
- [x] 7.2 增加 Package 递归发现、来源优先级、同名遮蔽、版本元数据和 `skill` 工具调用的测试
- [x] 7.3 增加 Bootstrap 新会话/普通轮次去重、会话恢复、端口重建和上下文压缩重新注入测试
- [x] 7.4 增加 TUI/CLI 生命周期命令、诊断和旧版直接目录兼容性测试
- [x] 7.5 增加 Superpowers 兼容验收：安装仓库后可发现 `brainstorming` 与 `using-superpowers`，新会话自动注入 Bootstrap，且不会执行 `.pi`/`.opencode` 等第三方扩展代码
- [x] 7.6 运行完整测试集和 `openspec validate --change unified-skill-packages --strict`，修复规划阶段发现的规格或任务问题
