"""tools/shared 共享工具模块:FsOps 抽象 / 路径 / 文本 / 截断 / 写串行化 / 忽略策略。

分层约束:本包可被 tools/ 内部使用,禁止 import core/session/ai;仅提供标准库
和文件系统抽象,不依赖外部编排框架。
"""

from codeagent.tools.shared.fsops import FsOps, LocalFsOps
from codeagent.tools.shared.ignore import NOISE_DIRS, prune_noise_dirs
from codeagent.tools.shared.mutation_queue import with_path_lock
from codeagent.tools.shared.paths import normalize_path, resolve_to_cwd
from codeagent.tools.shared.textfile import (
    detect_line_ending,
    normalize_to_lf,
    restore_line_endings,
    strip_bom,
)
from codeagent.tools.shared.truncate import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_LINES,
    TruncationResult,
    truncate_head,
    truncate_tail,
)
from codeagent.tools.shared.governance import (
    GovernedOutput,
    GovernedText,
    OutputPolicy,
    govern_text,
    redact_metadata_text,
)

__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_LINES",
    "FsOps",
    "GovernedOutput",
    "GovernedText",
    "LocalFsOps",
    "NOISE_DIRS",
    "OutputPolicy",
    "TruncationResult",
    "detect_line_ending",
    "normalize_path",
    "normalize_to_lf",
    "prune_noise_dirs",
    "resolve_to_cwd",
    "restore_line_endings",
    "strip_bom",
    "truncate_head",
    "truncate_tail",
    "govern_text",
    "redact_metadata_text",
    "with_path_lock",
]
