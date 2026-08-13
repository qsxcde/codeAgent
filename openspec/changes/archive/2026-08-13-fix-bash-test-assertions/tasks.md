## 1. 修复 cwd 相关测试断言(A1)

- [x] 1.1 `test_bash_cwd_param_uses_configured_directory`:改为标记文件法——在 tmp_path 写 `marker.txt`,命令 `test -f marker.txt && echo CWD_OK`,断言 `CWD_OK` 出现且无"命令失败"
- [x] 1.2 `test_bash_cwd_defaults_to_startup_directory`:同样改为标记文件法(配合 `monkeypatch.chdir(tmp_path)` 保持"缺省回退启动目录"意图)
- [x] 1.3 `test_make_tools_passes_cwd_to_bash`:同样改为标记文件法(经 `create_tools` + `ainvoke` 真实装配链路,验证 cfg.cwd 传递)

## 2. 修复 PIPESTATUS 测试命令(B1)

- [x] 2.1 `test_bash_pipeline_grep_exit_one_not_failure`:命令精简为 `ps aux | grep codeagent-zzz-nonexistent`,断言 `"命令失败" not in out and "退出码: 1" in out`

## 3. 验证

- [x] 3.1 全量跑测试:`uv run pytest -q` 204/204 全绿
- [x] 3.2 确认无产品代码改动:`git diff --stat` 仅含 `tests/tools/test_tools.py`
