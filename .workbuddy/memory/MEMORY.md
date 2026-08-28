# 项目长期记忆：codeAgent

## 项目概况
自研 AI 编码代理（codeagent），Python 3.12 + uv 管理依赖，测试用 `.venv/Scripts/python.exe`。
源码 `src/codeagent/`，约 20k 行；测试 `tests/`，约 15k 行。全量 pytest 约 4 分钟。

## 架构约束（AGENTS.md 明文规定，评审确认零违规）
- `core/` 不得 import `config` / `ai` / `tools` / `session`
- `session/` 不得 import `ai` / `tools` / `config`
- 组合根在 `app/container.py` 与 `app/main.py`；跨层装配放 `app/composition/`
- 凭据只存 `~/.codeagent/.env`，**刻意不读仓库本地 `.env`**（`warn_cwd_env()` 只告警不读取）
- 本地开发与测试用 `fake` provider，不依赖真实凭据

## 已知高风险区（2026-08-28 评审）
详见 `docs/code-review-2026-08-28.md`。改动以下位置需格外谨慎：
- `tools/security/classifier.py` + `bash_rules.py`：DENY 实际靠字面量正则，绕过面较大
- `tools/security/filesystem.py`：`_SECRET_PATH_RE` 只覆盖 `.env`/`.codeagent`，读越界一律 allow
- `session/persistence/locking.py`：仅进程内 RLock，无跨进程保护
- `session/persistence/jsonl_store.py` `commit_turn`：整文件回滚，非原子且会擦除并发写入
- `session/session.py` `compact()`：未挡 `cut >= len(history)`
- 任何新增 `asyncio.create_task()`：必须登记以便 shutdown 时回收（当前 9 处泄漏）

## 本机环境坑
- `resolve_bash()` 会选中 `C:\Users\Administrator\.workbuddy\binaries\PortableGit\...\bash.exe`，
  该实例 `/etc/msystem` 缺失，每次调用向 stderr 输出噪声且冷启动约 6.5s。
  因此 `tests/tools/test_execution.py` 的两条 5s 超时断言在本机**必然失败**（环境问题，非代码 bug）。
- Git Bash 下 `/tmp` 不映射到 Python 可见路径，临时脚本应直接写到项目目录。
