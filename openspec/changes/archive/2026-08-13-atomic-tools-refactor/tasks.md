## 1. 共享层 `tools/shared/`

- [x] 1.1 新建 `src/codeagent/tools/shared/fsops.py`:定义 `FsOps` Protocol(read_bytes / write_bytes / exists / is_file / is_dir / mkdir / readdir / walk)+ `LocalFsOps` 默认实现(基于 pathlib/os);模块 docstring 注明分层约束与职责(design D1)
- [x] 1.2 新建 `src/codeagent/tools/shared/paths.py`:`resolve_to_cwd(path, cwd)`、`normalize_path`(`~` 展开、`@` 前缀剥离)、`format_posix`(统一正斜杠);所有工具统一经此解析相对路径(对应 spec「路径解析」)
- [x] 1.3 新建 `src/codeagent/tools/shared/textfile.py`:`strip_bom` / `detect_line_ending` / `normalize_to_lf` / `restore_line_endings`(design D5;对应 spec「edit 保留原始换行约定」)
- [x] 1.4 新建 `src/codeagent/tools/shared/truncate.py`:`truncate_head(text, max_lines, max_bytes)` 与 `truncate_tail(text, ...)`,返回 (text, TruncationResult);统一字节+行双上限(对应 spec「输出截断」)
- [x] 1.5 新建 `src/codeagent/tools/shared/mutation_queue.py`:`with_path_lock(path)` 上下文管理器,内部 `dict[path, threading.Lock]`;线程安全(对应 spec「并行写串行化」)
- [x] 1.6 `src/codeagent/tools/shared/__init__.py` 显式导出 5 个模块的公共符号

## 2. 基类与装配改造

- [x] 2.1 改造 `src/codeagent/tools/base.py`:`AtomicTool.__init__(cwd=None, ops=None)`,内部存 `self._cwd` / `self._ops`(默认 `LocalFsOps()`);`name/description/Args/_invoke/to_langchain` 契约不变(design D2)
- [x] 2.2 改造 `src/codeagent/tools/registry.py`:`make_tools(cfg)` 把 `cfg.cwd` 注入全部 7 个工具构造;更新 docstring(design D2;对应 spec「装配时注入工作目录」)

## 3. 既有四工具重构

- [x] 3.1 重构 `read`:`ops.read_bytes` + `resolve_to_cwd` + `textfile` 读入;字节+行双上限截断(经 truncate_head),分页与二进制前缀行为保留(对应 spec「read」)
- [x] 3.2 重构 `write`:`ops.mkdir(parents)` + `ops.write_bytes(content.encode("utf-8"))` 恒写 LF;套 `with_path_lock`;返回字节数(design D5;对应 spec「write」)
- [x] 3.3 重构 `edit`:`ops` 读入 → `strip_bom` + `normalize_to_lf` → 匹配(唯一性/非空校验保留)→ `restore_line_endings` + 补 BOM 写回;套 `with_path_lock`;保留「替换结果与原文相同则 no-change」判据(design D5/D7;对应 spec「edit」)
- [x] 3.4 重构 `bash`:改用 `subprocess.Popen` + 手动超时;Unix `start_new_session` + `os.killpg`,Windows `CREATE_NEW_PROCESS_GROUP` + `taskkill /F /T /PID` 树级击杀;输出改 `truncate_tail` 保留尾部;`_resolve_bash` 补 `PROGRAMFILES(X86)` 兜底;黑名单/grep 豁免/UTF-8 双端编码保留(design D6;对应 spec「bash」)

## 4. 新增三工具

- [x] 4.1 新建 `src/codeagent/tools/atomic/ls.py`:Args(`path` 可选 / `limit` 可选);`ops.readdir` + `ops.is_dir`(目录加 `/`)+ 大小写不敏感排序 + limit + 截断;路径不存在/非目录报错;默认不显示隐藏条目(对应 spec「ls」)
- [x] 4.2 新建 `src/codeagent/tools/atomic/find.py`:Args(`pattern` 必填 / `path` 可选 / `limit` 可选);模块级纯函数 `find_files(ops, cwd, pattern, path, limit)`(升级缝,design D3)——`ops.walk`(os.walk 风格)遍历 + 调用方剪枝 `dirs[:]` + limit 早停;glob→regex 匹配(自写,** 递归;fnmatch 的 `*` 跨分隔符故不直接用);输出正斜杠路径 + 截断;`_invoke` 只做解析/格式化(对应 spec「find」)
- [x] 4.3 新建 `src/codeagent/tools/atomic/grep.py`:Args(`pattern` 必填 / `path` 可选 / `glob` 可选 / `ignore_case` / `literal` / `context` / `limit`);模块级纯函数 `grep_files(ops, cwd, pattern, ...)`(升级缝,design D3)——`ops.walk` 枚举候选(剪枝)+ 逐文件 `ops.read_bytes` 后**字节级整块匹配**:编译 `bytes` 正则 + 整块 buffer `finditer`(C 速度)+ 换行偏移数组 `bisect` 映射行号;二进制探测查前缀 `\x00`;字面量 `re.escape(term.encode())`;非 ASCII 模式回退 str 逐行;输出 `relative_path:行号: 内容`、context 行用 `-` 区分;limit 早停;`_invoke` 只做解析/格式化(对应 spec「grep」)

## 5. 导出与噪声目录常量

- [x] 5.1 更新 `src/codeagent/tools/atomic/__init__.py` 与 `src/codeagent/tools/__init__.py`:`GrepTool / FindTool / LsTool` 加入导出
- [x] 5.2 在 `tools/shared/`(或 `tools/`)定义 `NOISE_DIRS` 常量(`.git / node_modules / __pycache__ / .venv / dist / build`),find/grep 共用(design D4;对应 spec「跳过噪声目录」)(实现于 `shared/ignore.py`)`

## 6. 测试

- [x] 6.1 `tests/conftest.py` 新增夹具:`tmp_fsops`(基于 `tmp_path` 的 `LocalFsOps`)与内存版 FsOps(供注入测试);确认 autouse `_isolate_config_dir` 不受影响
- [x] 6.2 重写 `tests/tools/test_tools.py` 既有用例:4 个工具改为注入 `tmp_fsops` + 显式 cwd,去掉 `monkeypatch.chdir` 依赖;行为断言对齐新语义(注册表 4→7;bash chdir("/") 改显式 cwd)
- [x] 6.3 新增 read 用例:字节+行双上限截断、分页、二进制前缀、路径不存在报错(对应 spec「read」场景)
- [x] 6.4 新增 write 用例:覆盖写、父目录自动创建、恒写 LF(断言落盘字节含 `\n` 无 `\r\n`)(对应 spec「write」场景)
- [x] 6.5 新增 edit 用例:CRLF 文件编辑后仍 CRLF、BOM 保留、替换结果相同报 no-change(对应 spec「edit」场景)
- [x] 6.6 新增 bash 用例:超时终止命令进程(`echo $$` 记录 + `kill -0` 验证,跨平台可靠;MSYS 后台孙进程局限已记录)、截断保留尾部、Windows 无 bash 报错路径(平台无关断言)(对应 spec「bash」场景)
- [x] 6.7 新增 ls/find/grep 用例:正常/无匹配/噪声目录跳过/context 行/字面量/limit(对应 spec 三场景);断言平台无关(posix 路径、无特定 shell 输出)
- [x] 6.8 新增并行写用例:多线程对同文件并发 edit,断言结果与串行一致(`aaa bbb`);锁定读-改-写整周期(对应 spec「并行写串行化」)
- [x] 6.9 全量 `uv run pytest` 通过(现 224 项 = 204 + 20 新增,零失败)

## 7. 收尾

- [x] 7.1 更新 `docs/iteration/v0.1.md` 或需求分析 FR-3 状态:标记 grep/find/ls 落地(FR-3.7 闭合)、工具层 hexagonal 改造说明
- [x] 7.2 归档本 change 至 `openspec/changes/archive/`,specs 同步回主 `openspec/specs/tools/spec.md`(归档于 `openspec/changes/archive/2026-08-13-atomic-tools-refactor/`,主 spec 已同步至 `openspec/specs/tools/spec.md`)
