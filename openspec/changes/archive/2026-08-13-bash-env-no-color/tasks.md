## 1. 实现

- [x] 1.1 在 `tools/atomic/bash.py` 的 `_bash_env()` 中注入 `NO_COLOR=1`,与现有 `LANG=en_US.UTF-8` 并列(design D1/D2)
- [x] 1.2 确认 `_bash_env()` 仍返回 `os.environ.copy()` 的浅拷贝、不污染进程级 `os.environ`(design D4)

## 2. 测试

- [x] 2.1 在 `tests/tools/test_tools.py` 新增单测:构造 `BashTool`,断言 `_bash_env()` 返回的环境包含 `NO_COLOR=1` 且保留 `LANG`
- [x] 2.2 新增集成用例:执行 `test -n "$NO_COLOR" && echo SET`(行为验证,平台无关),断言输出为 `SET`;并断言一条普通命令(`echo hi`)的输出与退出码不变
- [x] 2.3 运行 `uv run pytest -q` 确认全量通过、无新增失败(当前基线 239 passed / 1 failed 为 login-shell 环境问题,与本变更无关,见 design Non-Goals)

## 3. 端到端验证

- [x] 3.1 在 TUI/分离进程上下文复跑一次 bash 工具,确认 stderr 不再出现 `Error while loading conda entry point: conda-libmamba-solver`
