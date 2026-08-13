## Why

工具层是当前项目里唯一违背自身 hexagonal 哲学的模块:`AtomicTool` 子类直接触碰 `Path` / `subprocess`,没有 I/O 抽象,测试被迫 `monkeypatch.chdir`。同时存在两个真实缺陷与一个已预留的缺口:

- **并发写竞态**:`core/nodes/tools.py` 用 `asyncio.gather` 并行执行同一消息内的所有 tool_call,模型一条回复里对同一文件 `write` + `edit` 时读改写竞争,丢更新;
- **CRLF 被改写**:`EditTool` 直接 `content.count(old_string)` 匹配、`Path.write_text` 写回,Windows 下 `\n`→`\r\n` 翻译会静默改变文件的换行约定,`git diff` 看到整文件被改;
- **检索能力缺失**:`grep / find / ls` 是 FR-3.7 已登记的 P1 预留项,现无实现,模型只能靠 `bash` 拼凑搜索。

重构目标:让工具层对齐 Pi-Agent 的设计逻辑——schema 先行 + 依赖注入(cwd/ops)+ 共享横切模块 + 跨平台文本/路径/进程语义统一,并补齐三个检索工具。

## What Changes

- **新增共享层 `tools/shared/`**(新模块):`fsops.py`(`FsOps` 协议 + `LocalFsOps` 默认实现)、`paths.py`(路径解析/格式化)、`textfile.py`(BOM/换行 归一→还原)、`truncate.py`(字节+行双上限,头/尾截断)、`mutation_queue.py`(按路径串行化写);
- **改造 `AtomicTool` 基类**:构造签名增加 `cwd` 与 `ops` 注入(默认 `LocalFsOps()`),`name / description / Args / _invoke / to_langchain` 契约不变;
- **重构既有 4 工具**(read/write/edit/bash):全部改走 `FsOps` + `resolve_to_cwd`;`edit` 修复 CRLF/BOM 归一→匹配→还原写回;**全部写工具套 `mutation_queue`**;`bash` 增加进程树击杀(超时/中断连子进程一起杀)并改用保留尾部截断;
- **新增 3 工具**(纯 Python,零外部依赖):`grep`(正则/字面匹配 + 行号 + context 行 + 噪声目录黑名单)、`find`(glob 匹配 + 噪声目录黑名单)、`ls`(目录列举 + 目录后缀 + 大小写不敏感排序);
- **`make_tools` 注入 cwd 到全部工具**(现仅 `BashTool`);
- **测试改造**:`tests/tools/test_tools.py` 随重构重写——注入内存/tmp `FsOps`,告别 `monkeypatch.chdir`;新增 CRLF 保留、并发写串行、3 个新工具的测试;
- **行为变化**(工具名/参数不变,非破坏性 API 变更):`bash` 输出截断从保留开头改为保留结尾;`edit` 写回时保留文件原始换行约定;`write` 新建文件恒写 LF;全部工具对路径的解析统一经 `resolve_to_cwd`。

## Capabilities

### New Capabilities

- `tools`:原子工具集能力——`read / write / edit / bash / grep / find / ls` 七工具的统一契约(FsOps 抽象、cwd 注入、共享截断/文本/路径语义、并行写串行化)。本仓库 `openspec/specs/` 目前为空,`tools` 是首个能力;未来 config/ai/core/session 等能力按此组织扩展。

### Modified Capabilities

无(无既有 spec 需要修改)。

## Impact

- **受影响代码**:
  - `src/codeagent/tools/base.py` —— `AtomicTool` 加注入;
  - `src/codeagent/tools/atomic/{read,write,edit,bash}.py` —— 重构;新增 `grep.py / find.py / ls.py`;
  - `src/codeagent/tools/atomic/__init__.py`、`src/codeagent/tools/__init__.py`、`src/codeagent/tools/registry.py` —— 导出与工厂更新;
  - 新增 `src/codeagent/tools/shared/` 五个模块;
  - `tests/tools/test_tools.py`、`tests/conftest.py` —— 测试改造与新夹具;
- **不受影响**:`core/`、`session/`、`ai/`、`app/` 零改动——工具对它们是黑盒(`make_tools` 签名不变,组合根唯一交汇行不变);
- **依赖**:零新增(纯 Python 实现,不引入 rg/fd/第三方库);
- **验收口径**:全量 `uv run pytest` 保持绿色(现 204 项 + 新增用例);新增用例全部离线、平台无关。

> 设计决策来源:Pi-Agent(`earendil-works/pi`)的工具层设计逻辑——Operations 抽象缝、cwd 全注入、共享 truncate/paths/文本归一/mutation-queue。差异:本项目用共享一份 `FsOps` 而非每工具一个接口;grep/find 用纯 Python 而非 ripgrep/fd 子进程;忽略语义用噪声目录黑名单而非完整 .gitignore 解析。完整设计见 `design.md`。
