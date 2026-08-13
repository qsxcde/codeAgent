## Context

当前状态与约束(动机见 proposal.md):

- `tests/tools/test_tools.py` 4 项失败,均为**测试自身问题**,产品代码 `src/codeagent/tools/atomic/bash.py` 行为正确;
- **cwd 失败根因**:pytest `tmp_path` 恒在 `%TEMP%` 下;Windows Git Bash(MSYS2)按挂载表把 `C:\Users\...\Temp` 显示为 `/tmp/...`。实测同一 bash 存在路径表示不对称:
  - `D:\project\codeAgent` → `pwd` 输出 `D:/project/codeAgent`(Windows 形式);
  - `C:\...\AppData\Local\Temp` → `pwd` 输出 `/tmp`(POSIX 形式)。
  - 挂载表行为还依赖 `noumount`/`usertemp` 等逐机配置,字符串断言路径在 Windows 上本质脆弱;
- **PIPESTATUS 失败根因**:工具豁免逻辑(bash.py `_last_segment_first_token`)按**最后一个逻辑段的首 token** 判定;`ps aux | grep x; exit ${PIPESTATUS[1]}` 末段是 `exit` → 不在 `SEMANTIC_OK_PREFIXES`("grep")→ 判失败符合当前语义,测试本身过期(P2-13 语义收窄前遗留)。

## Goals / Non-Goals

**Goals:**

- 修复 4 项失败,`uv run pytest` 回到全绿;
- 断言与平台路径表示解耦,Windows / Linux / macOS 全部可跑;
- 保持既有语义验证强度(不弱化测试意图)。

**Non-Goals:**

- 不修改 bash 工具实现与行为;
- 不做产品侧输出路径翻译(职责越界,见决策 D1 备选 C);
- 不引入平台分支测试(`@pytest.mark.skipif` 之类),本方案无需平台特判;
- 不新增依赖。

## Decisions

### D1:cwd 断言 → 行为验证(标记文件法)

**方案**:在每个 `tmp_path` 内预写 marker 文件,让命令以"探测标记存在"代替打印路径:

```python
(tmp_path / "marker.txt").write_text("")          # 目标目录放标记
out = _invoke(BashTool(cwd=str(tmp_path)), command="test -f marker.txt && echo CWD_OK")
assert "CWD_OK" in out and "命令失败" not in out
```

三个 cwd 测试(`test_bash_cwd_param_uses_configured_directory` / `test_bash_cwd_defaults_to_startup_directory` / `test_make_tools_passes_cwd_to_bash`)统一改为:先写 marker,再断言 `CWD_OK`。

- 验证的是真实需求——"命令确实在配置的 cwd 中执行",与挂载表、路径形式、平台全部解耦;
- 三个测试各自保持原意图:cwd 参数生效 / 缺省回退启动目录(配合 `monkeypatch.chdir`) / `make_tools` 传递 cfg.cwd(该测试经 `create_tools` + `ainvoke` 走真实装配链路)。

**备选与取舍**:

| 备选 | 做法 | 弃用原因 |
|---|---|---|
| B | 输出归一化 | `cygpath -u` 还原后对比 | 依赖 Git Bash 存在;挂载表逐机不同,仍然脆弱 |
| C | 产品侧翻译 bash 输出路径为 Windows 形式 | 任意命令输出无法可靠翻译,且改动产品行为 | 职责越界,风险高 |
| D | 平台分支 skipif | 在 Windows 跳过测试 | 回避问题,测试失去验证价值 |

### D2:PIPESTATUS 测试 → 裸管道

**方案**:删除 `; exit ${PIPESTATUS[1]}` 后缀:

```python
out = _invoke(BashTool(), command="ps aux | grep codeagent-zzz-nonexistent")
assert "命令失败" not in out and "退出码: 1" in out
```

- 管道退出码天然来自末段 grep(=1),正好覆盖豁免路径,全平台一致;
- 追加 `"退出码: 1"` 断言,锁定"grep 的 1 被豁免"而非"命令成功"。

**备选与取舍**:

| 备选 | 做法 | 弃用原因 |
|---|---|---|
| B | 命令追加 `\|\| true` | 退出码归 0,不再验证"grep 1 豁免"路径,与相邻测试重复 |
| C | 产品逻辑忽略尾部 `exit` 内建 | `; exit ${PIPESTATUS[N]}` 是测试书写技巧,非模型真实命令模式,为它改语义不值 |

## Risks / Trade-offs

- **[低] marker 文件法对 `pwd` 功能本身不再直接断言** → 工具语义由 `test_bash_normal`(`echo hello` + `退出码: 0`)等其它用例覆盖,无缺口;
- **[低] 测试意图依赖 `test -f` 的存在性判断** → `test` 是 bash 内建,所有平台一致,无环境差异;
- **[无] 行为不变** → 无需回滚方案;若回归失败,原因只会在测试自身,与产品无关。
