## Context

动机与范围见 `proposal.md`。现状(`tools/` 层)要点:

- `AtomicTool` 基类:类属性 `name/description/Args`(pydantic)+ 实现 `_invoke(args)->str` + `to_langchain()` 转 `StructuredTool`;
- 4 个工具 `read/write/edit/bash` 直接触碰 `pathlib` / `subprocess`,无 I/O 抽象;`cwd` 仅 `BashTool` 有;
- `make_tools(cfg)` 是唯一装配点,组合根 `app/container.py` 消费;
- 工具在 `core/nodes/tools.py` 中经 `asyncio.gather` **并行**执行(同步 `_invoke` 跑在 langchain 线程池里);
- 分层约束:`tools/` 可 import `config`,禁止 import `core/session`;langchain 延迟导入。

设计参照:Pi-Agent(`earendil-works/pi`)工具层——Operations 抽象缝、cwd 全注入、共享 truncate/paths/文本归一/mutation-queue。

## Goals / Non-Goals

**Goals:**
- 工具层回归 hexagonal:所有文件 I/O 经注入的 `FsOps`,可替换、可离线测试;
- 修掉两个真实缺陷:并发写竞态、CRLF 被改写;
- 补齐 `grep / find / ls` 三个检索工具(纯 Python,零外部依赖);
- 统一跨平台语义:路径解析、换行、截断、bash 进程管理;
- 全部 7 个工具创建时注入 `cwd`。

**Non-Goals:**
- **异步工具 + AbortSignal**:`session.abort()` 打断运行中的 bash 仍是结构性限制,登记 v0.2;
- **图片读取**(pi 支持 image,本仓库不做);
- **rg/fd 子进程 + 自动下载**(已选纯 Python);
- **完整 .gitignore 语义**(用噪声目录黑名单);
- **工具确认环 / 文件访问白名单**(FR-8,v0.2);
- **`core/`、`session/`、`ai/`、`app/` 任何改动**(工具对它们是黑盒)。

## Decisions

### D1. FsOps:共享一份协议,而非 pi 的每工具一个接口

```python
class FsOps(Protocol):
    def read_bytes(self, path: Path) -> bytes: ...
    def write_bytes(self, path: Path, data: bytes) -> None: ...
    def exists(self, path: Path) -> bool: ...
    def is_file(self, path: Path) -> bool: ...
    def is_dir(self, path: Path) -> bool: ...
    def mkdir(self, path: Path, parents: bool = True) -> None: ...
    def readdir(self, path: Path) -> list[str]: ...          # ls
    def walk(self, path: Path) -> Iterator[tuple[Path, list[str], list[str]]]: ...  # os.walk 风格(root, dirs, files)
```

`LocalFsOps` 用 `pathlib`/`os` 实现,为默认实现;`walk` 直接包 `os.walk`——**调用方在遍历中剪枝**(`dirs[:] = [d for d in dirs if d not in NOISE]`),这既让「跳过噪声目录」策略留在工具层而非泄漏进 FsOps,又让测试能注入假目录树。

- **为什么共享一份**:7 个工具的操作交集高度重叠,一份协议足够表达;真到远程化(SSH)时再按工具拆分接口,不预付复杂度;
- **备选**:pi 的 `ReadOperations/WriteOperations/...` 每工具一个——粒度细,但 7 接口 + 7 套默认实现规模效益不明显;
- **配套收益**:测试注入内存/tmp `FsOps`,告别 `monkeypatch.chdir`;未来远程化工具零改动。

### D2. AtomicTool 加注入,保留「类 + _invoke + to_langchain」契约

```python
class AtomicTool:
    def __init__(self, cwd: str | Path | None = None, ops: FsOps | None = None):
        self._cwd = cwd
        self._ops = ops or LocalFsOps()
```

- **为什么保留类式**:本项目风格是「类 + pydantic Args + `_invoke`」,`to_langchain()` 适配已被组合根消费,契约稳定;构造函数注入已达 pi 工厂同样的解耦效果,不必照搬 `createXTool` 函数;
- **备选**:pi 的工厂函数风格——更函数式,但与现有代码、文档风格冲突,且要重写 `to_langchain` 接线;
- `make_tools(cfg)` 即工厂:`cwd = getattr(cfg, "cwd", None)`,注入全部 7 个工具(`ops` 不默认暴露给 cfg,测试直接构造)。

### D3. 搜索工具纯 Python 实现(含性能优化)

- `ls`:`ops.readdir` + `ops.is_dir`(目录加 `/`)+ `toLowerCase` 大小写不敏感排序 + limit;
- `find`:`ops.walk`(os.walk 风格)遍历 + 调用方剪枝噪声目录(`dirs[:]`)+ limit 早停;模式语义沿用 pi:无 `/` 的 pattern 匹配 basename,含 `/` 的匹配完整路径,`**` 递归(用 `pathlib.PurePosixPath` + `fnmatch.translate` 组合实现);纯 I/O 遍历,如需再上 `ThreadPoolExecutor`(标注可选,实测瓶颈再启用);
- `grep`:经 `ops.walk` 枚举候选文件(同样剪枝),逐文件 `ops.read_bytes` 后**字节级整块匹配**——规避「每行一个 Python 解释循环」这一纯 Python 搜索慢的**主因**:编译 `bytes` 正则,在整块 buffer 上 `pattern.finditer(data)`(C 速度),用预计算的换行偏移数组 + `bisect` 把匹配偏移映射回行号,`context` 行也由偏移数组 O(1) 定位;二进制快速探测只查前缀 `data[:8192]` 是否含 `\x00`;字面量 `re.escape(term.encode())`;其余语义(IGNORECASE、limit、glob 过滤、`path:行号: 内容` 输出、context 行用 `-` 区分)不变;
- **性能期望**:字节级匹配 + 剪枝 + limit 早停把「典型项目(数百 MB、无 node_modules)」从数秒拉到亚秒;极限场景(整棵大仓库根)仍慢,但被剪枝 + limit 框住,且模型通常带 `path` 限定子树;
- **升级缝(搜索核心独立成纯函数)**:`grep.py` 的 `grep_files(ops, cwd, pattern, ...)` 与 `find.py` 的 `find_files(ops, cwd, pattern, ...)` 是模块级纯函数,`_invoke` 只做参数解析 + 输出格式化。将来换 rg/fd 子进程实现 = 重写这两个函数(组 args + 解析输出),工具 schema、导出、上层调用、既有测试全不动——这是真正的缝,而非 FsOps(见 Risks 修正);
- **为什么纯 Python**:零外部依赖、离线测试自然、`pathlib` 天然跨平台——**省掉 pi 在 Windows 上给 fd 做的 `[/\\]` 全路径特判**;rg/fd 虽快且 git 感知,但引入外部二进制 + 自动下载(有网络副作用),与「离线可测最高原则」冲突;
- **备选**:rg/fd 子进程 + `ensureTool` 自动下载(pi 原版)、rg/fd 优先 + 纯 Python 兜底(两套语义,测试双写,否决);
- **未来选项(不现在建,登记)**:运行时 `shutil.which("rg")` 探测,有则 rg 快路、无则 Python 兜底,噪声目录经 `--glob '!node_modules/**'` 传入保持一致;测试注入 Python 后端不探测 rg,离线性保持。等「大仓库检索成为实测瓶颈」再启用。

### D4. 噪声目录黑名单,而非完整 .gitignore

- 默认跳过:`{".git", "node_modules", "__pycache__", ".venv", "dist", "build"}`;
- **为什么**:完整 gitignore 解析(锚定、取反、逐级覆盖)是独立复杂体,本迭代不买单;黑名单覆盖真实噪声,模型可经 `path` 参数自行定位被跳过的目录;
- **备选**:完整解析(实现/测试量大)、不跳过(输出噪声大,否决)。

### D5. 文本处理:CRLF/BOM 归一→匹配→还原(移植 pi edit-diff.ts)

`shared/textfile.py`:

```python
def strip_bom(text) -> tuple[str, str]: ...            # 返回 (去BOM文本, BOM)
def detect_line_ending(text) -> str: ...               # "\n" | "\r\n" | "\r"
def normalize_to_lf(text) -> str: ...                  # \r\n|\r -> \n
def restore_line_endings(text, ending) -> str: ...     # 还原原始换行
```

- **edit**:读入 → `strip_bom` + `normalize_to_lf` → 匹配(唯一性/非空校验与现行为一致)→ 替换 → `restore_line_endings` + 重新加 BOM 写回。匹配在 LF 归一空间做,模型 `old_string` 不依赖文件换行;未触碰区域保留原始字节语义;
- **write**:新建文件**恒写 LF**(决策 ④),用 `ops.write_bytes(text.encode("utf-8"))` 绕过 Python 平台换行翻译——`Path.write_text` 在 Windows 会 `\n`→`\r\n`,这是当前潜在 bug;
- **read**:读入后不归一,原样返回(读取应忠实呈现文件);
- **为什么**:修掉 Windows 下编辑后整文件换行被改写、`git diff` 全红的真实缺陷;
- **备选**:逐行 I/O 保留 CRLF(实现繁琐,归一→还原更简单且测试直观)。

### D6. bash:进程树击杀 + 保留尾部截断

- 用 `subprocess.Popen` + 手动超时替代 `subprocess.run(timeout=)`(后者超时只杀 bash 本身,派生的后台进程仍存活);
- Unix:`start_new_session=True` + 超时后 `os.killpg(pgid, SIGKILL)`;
- Windows:`CREATE_NEW_PROCESS_GROUP` + `taskkill /F /T /PID <pid>`(树级击杀);
- 保留现有:危险命令黑名单(字符串正则 + `_dangerous_intent` shlex 语义级)、`SEMANTIC_OK_PREFIXES` grep 豁免、`LANG=en_US.UTF-8` + `errors="replace"` 双端编码修复;
- **截断保留尾部**:超时/报错信息通常在末尾,保留尾对调试更友好(决策 ②,行为变化——模型看到的格式变化,测试同步更新);
- bash 探测链保留 `_resolve_bash`(PATH 优先 + PROGRAMFILES),补 `PROGRAMFILES(X86)` 兜底。

### D7. mutation_queue:按路径串行化写

`shared/mutation_queue.py` 提供 `with_path_lock(path, fn)` 或上下文管理器,内部用 `dict[path, threading.Lock]`:

- **为什么线程锁**:工具经 langchain 在**线程池**中并行执行(`asyncio.gather` → 同步 `ainvoke`),并发是线程级,`threading.Lock` 即够;
- 只包**写类工具**(write/edit);read/bash 不锁,避免无谓串行;
- 锁表需防内存泄漏(路径数少,`threading.Lock` 小,暂不做 LRU/弱引用;若长会话路径膨胀再回收)。

### D8. 同步工具保持同步

- 不改 `_invoke` 为 async:langchain `StructuredTool` 同步适配已稳定,异步化波及 `to_langchain`、core 节点与全部测试;
- **代价**:bash 运行中无法被 `session.abort()` 中断(非目标,登记 v0.2)。

## Risks / Trade-offs

- **[纯 Python grep/find 大仓库慢]** → 已被 D3 性能优化收窄:字节级整块匹配 + `os.scandir` 剪枝 + limit 早停,典型项目降至亚秒;极限场景由 limit + 剪枝框住。若未来出现「整棵大仓库检索」实测瓶颈,走 D3 的「搜索核心独立函数」升级缝——重写 `grep_files`/`find_files` 为子进程实现(rg/fd 或探测快路),工具 schema、导出、上层、既有测试全不动。注意此缝是**函数级职责拆分**,不是 FsOps 抽象(修正早期表述:rg/fd 不经过 `FsOps.walk`,升级会绕过它);
- **[Windows 下 bash 树级击杀不覆盖 MSYS 后台孙进程]** → `taskkill /F /T` 可靠击杀命令进程本身与直接子进程,但 MSYS/Git Bash 派生的后台进程(``sleep 60 &``)可能被挂到 MSYS 运行时而非 bash 的 Windows 进程树下,taskkill 杀不到——Unix 经 `killpg` 进程组全树击杀,无此局限。测试断言「命令进程根被终止」这一跨平台可靠子集,局限已在 `bash._kill_tree` 注释与 spec 场景措辞中如实记录;
- **[bash 截断保尾是行为变化,模型可能不习惯]** → 只影响超长输出;返回格式带明确截断标记,测试补断言;
- **[FsOps 重构触及全部工具测试]** → 重写量集中在 `tests/tools/test_tools.py`;注入后测试更稳(免 chdir),净收益;
- **[mutation_queue 锁表内存增长]** → 路径规模有限;若验证膨胀再加弱引用回收;
- **[CRLF 还原与 no-change 检测交互]** → 若文件换行已混乱,归一后可能恰好匹配但还原后内容不变——edit 需保留「替换结果与原文相同则报 no-change」的判据(现状有类似逻辑,保持)。

## Migration Plan

- 单 change 一次性落地(工具层对 core/session 黑盒,无下游迁移面);
- 顺序:shared 层 → 基类注入 → 4 工具改造 → 3 新工具 → registry → 测试重写;
- 门槛:`uv run pytest` 全量绿(现 204 + 新增用例),新增用例全离线、平台无关;
- 回滚:`git revert` 即可,工具层无跨层耦合;
- 不引入新依赖,无需环境迁移。

## Open Questions

无(本设计覆盖的行为变化均已定;`grep` 二进制文件按「跳过并注明」处理、`ls` 默认不显示隐藏条目、`find` 匹配语义沿用 pi——以上均为记录性假设,不改变 spec 或任务拆解)。
