"""bash 原子工具:执行 shell 命令,带超时 / 输出截断 / 退出码语义化 / 危险命令黑名单。"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool

__all__ = ["BashTool", "DEFAULT_TIMEOUT_S", "MAX_TIMEOUT_S", "MAX_OUTPUT_CHARS", "DANGEROUS_PATTERNS"]

#: 默认超时(秒);命令可在 timeout 参数内延长,上限见 MAX_TIMEOUT_S。
DEFAULT_TIMEOUT_S = 120
#: 单条命令超时上限。
MAX_TIMEOUT_S = 600
#: 输出截断阈值(字符),保留开头。
MAX_OUTPUT_CHARS = 30_000

#: 危险命令黑名单:命中即拒绝执行(v0.1 无确认环时的安全底线)。
#: 注:`rm -rf /` 中 "/" 后是字符串结尾,需用 (\s|$) 而非 /\b(否则漏拦)。
DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)+(/(\s|$))"),  # rm -rf /
    re.compile(r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)+\.\s*$"),  # rm -rf .(删除当前目录)
    re.compile(r":\s*\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:\s*"),  # fork bomb
    re.compile(r"\bmkfs\b"),  # 格式化
    re.compile(r"\bdd\s+if=\s*/dev/(?:zero|random|urandom)"),  # dd 覆写设备
    re.compile(r">\s*/dev/(?:sda|sdb|nvme)"),  # 直接写块设备
]

#: grep 等"非零但语义上非失败"的退出码场景(前缀匹配命令名)。
SEMANTIC_OK_PREFIXES = ("grep",)

#: 输出截断的省略标记。
TRUNCATION_MARKER = "\n...[输出已截断]..."


#: 已解析的 bash 解释器路径(模块级缓存);None 表示尚未解析或解析失败(失败不缓存,装好 bash 后重试可即时生效)。
_bash_executable: str | None = None


def _resolve_bash() -> str:
    """探测可用的 bash 解释器:PATH 优先,Git for Windows 常见安装路径兜底。

    顺序:① `shutil.which("bash")`(覆盖 macOS/Linux 及显式将 Git\\bin 加入 PATH 的用户);
    ② 基于 PROGRAMFILES 环境变量构造的 Git for Windows 路径(避免硬编码盘符)。
    全部失败时抛出带安装指引的 RuntimeError。
    """
    global _bash_executable
    if _bash_executable is not None:
        return _bash_executable

    candidates: list[str | None] = [shutil.which("bash")]
    program_files = os.environ.get("PROGRAMFILES")
    if program_files:
        candidates.extend(
            [
                os.path.join(program_files, "Git", "bin", "bash.exe"),
                os.path.join(program_files, "Git", "usr", "bin", "bash.exe"),
            ]
        )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            _bash_executable = candidate
            return candidate

    raise ValueError(
        "未找到 bash 解释器:请安装 Git for Windows 或启用 WSL,"
        "或将 Git\\bin 目录加入系统 PATH 后重试"
    )


class BashArgs(BaseModel):
    command: str = Field(description="要执行的 shell 命令")
    timeout: int | None = Field(None, description="超时秒数,缺省 120,上限 600")


def _dangerous_hit(command: str) -> str | None:
    """返回命中的黑名单模式描述,未命中返回 None。"""
    for pat in DANGEROUS_PATTERNS:
        if pat.search(command):
            return pat.pattern
    return None


#: 删除目标路径里被视为"不可解析的动态成分"的字符(变量/命令替换/通配符/引号等)。
_DYNAMIC_TARGET_CHARS = set("$`\\\"*?[]{}")


def _dangerous_intent(command: str) -> str | None:
    """分词语义级危险检测:识别 `rm` 递归+强制删除的等价写法。

    相比 `DANGEROUS_PATTERNS` 的字符串正则,本函数先经 `shlex.split` 还原
    命令的真实参数结构,因此能识别 `rm -r -f /`、`rm -rf "/"`、`rm -rf -- /`
    等正则漏掉的等价拼写。

    危险判定(仅当同时出现递归与强制标志时生效):
    - 目标解析后为文件系统根目录 → 拒绝;
    - 目标解析后为当前工作目录本身(`rm -rf .` / `./`) → 拒绝;
    - 目标解析后为用户主目录本身(`rm -rf ~`) → 拒绝;
    - 目标含变量/通配符等动态成分、无法可靠解析 → 保守拒绝。
    其它明确的具体路径(含 cwd 子目录、`/tmp/xxx` 等)正常放行。
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return f"命令无法分词,保守拒绝: {command}"
    if not tokens or tokens[0] != "rm":
        return None

    recursive = False
    force = False
    targets: list[str] = []
    opts_done = False
    for tok in tokens[1:]:
        if opts_done or not tok.startswith("-"):
            targets.append(tok)
            continue
        if tok == "--":
            opts_done = True
            continue
        if tok in ("-r", "-R", "--recursive"):
            recursive = True
        if tok in ("-f", "--force"):
            force = True
        if tok.startswith("-") and not tok.startswith("--"):
            body = tok[1:]
            if "r" in body or "R" in body:
                recursive = True
            if "f" in body:
                force = True

    if not (recursive and force):
        return None
    if not targets:
        return None

    cwd = Path.cwd().resolve()
    home = Path.home().resolve()
    for target in targets:
        if any(ch in target for ch in _DYNAMIC_TARGET_CHARS):
            return f"删除目标含动态成分(变量/通配符),保守拒绝: {target}"
        try:
            resolved = Path(target).expanduser().resolve()
        except OSError:
            return f"删除目标无法解析,保守拒绝: {target}"
        if resolved == Path("/") or (resolved.anchor and resolved == Path(resolved.anchor)):
            return f"删除目标为文件系统根目录: {target}"
        if resolved == cwd:
            return f"删除目标为当前工作目录: {target}"
        if resolved == home:
            return f"删除目标为用户主目录: {target}"
    return None


#: 逻辑段分隔符:管道 / 逻辑与 / 分号 / 逻辑或。退出码由最后一个逻辑段决定。
_SEGMENT_SEPARATORS = {"|", "&&", ";", "||"}


def _last_segment_first_token(command: str) -> str:
    """取命令最后一个逻辑段的首 token;无段分隔符时返回整条命令首 token。

    命令退出码由最后一个逻辑段决定(如 ``ps aux | grep x``、``cd /tmp && grep x``、
    ``cd /tmp; grep x``、``false || grep x`` 的退出码来源都是 ``grep``),
    豁免前缀判断应基于该 token 而非命令整体首 token(P2-13 回归修复)。
    用 ``shlex.shlex(punctuation_chars=True)`` 分词:引号内的 ``|``/``;`` 不分割
    (如 ``echo "a|b" | grep c``),紧贴分隔符也可识别(如 ``cd /tmp;grep x``)。
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = command.strip().split()
    if not tokens:
        return ""
    # 找到最后一个段分隔符之后的首 token
    last_seg: list[str] = []
    for tok in tokens:
        if tok in _SEGMENT_SEPARATORS:
            last_seg = []
        else:
            last_seg.append(tok)
    return last_seg[0] if last_seg else tokens[0]


def _semantically_ok(exit_code: int, command: str) -> bool:
    """退出码语义判断:grep 无匹配(退出码 1)等场景不视为错误。

    仅对 ``SEMANTIC_OK_PREFIXES`` 前缀的命令豁免非 0 退出码(如 grep 无匹配
    返回 1、grep 出错返回 2);豁免判断基于最后一个管道段首 token
    (``ps aux | grep x`` 退出码来源是 ``grep``);其它命令任何非 0 退出码
    一律视为失败。
    """
    if exit_code == 0:
        return True
    first = _last_segment_first_token(command)
    return first in SEMANTIC_OK_PREFIXES


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS] + TRUNCATION_MARKER, True


class BashTool(AtomicTool):
    name = "bash"
    description = (
        "执行 shell 命令并返回输出与退出码;默认超时 120s;"
        "grep 无匹配(退出码 1)不视为错误;危险命令会被拒绝。"
    )
    Args = BashArgs

    def __init__(self, cwd: str | None = None) -> None:
        """装配时指定的工作目录;未传则回退进程启动目录(P2-8)。"""
        self._cwd = cwd

    def _invoke(self, args: BashArgs) -> str:
        command = args.command.strip()
        if not command:
            raise ValueError("命令为空")

        hit = _dangerous_hit(command) or _dangerous_intent(command)
        if hit is not None:
            raise ValueError(f"命令命中危险模式,已拒绝执行: {hit}\n命令: {command}")

        timeout = args.timeout if args.timeout is not None else DEFAULT_TIMEOUT_S
        timeout = max(1, min(timeout, MAX_TIMEOUT_S))

        started = time.monotonic()
        try:
            # 编码双端修复:读侧显式 UTF-8 解码(防中文 Windows cp936 乱码/崩溃),
            # 写侧强制 LANG 让 bash 侧输出 UTF-8 字节,errors="replace" 兜底非法字节。
            proc_env = os.environ.copy()
            proc_env["LANG"] = "en_US.UTF-8"
            proc = subprocess.run(
                [_resolve_bash(), "-lc", command],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                cwd=self._cwd or str(Path.cwd()),
                env=proc_env,
            )
        except subprocess.TimeoutExpired:
            return f"[命令超时(>{timeout}s),已终止]\n命令: {command}"
        except OSError as exc:
            raise ValueError(f"命令执行失败: {exc}")

        elapsed = time.monotonic() - started
        stdout, out_truncated = _truncate(proc.stdout or "")
        stderr, err_truncated = _truncate(proc.stderr or "")

        if not _semantically_ok(proc.returncode, command):
            return (
                f"退出码: {proc.returncode}(命令失败,耗时 {elapsed:.1f}s)\n"
                f"stdout:\n{stdout}\n"
                f"stderr:\n{stderr}"
            )
        return (
            f"退出码: {proc.returncode}(耗时 {elapsed:.1f}s)"
            f"{' [stdout 已截断]' if out_truncated else ''}"
            f"{' [stderr 已截断]' if err_truncated else ''}\n"
            f"stdout:\n{stdout}\n"
            f"stderr:\n{stderr}"
        )
