"""ls 原子工具:列举目录条目,目录加 / 后缀,大小写不敏感排序,默认不显示隐藏条目。

纯 Python 实现(design D3;对应 spec「ls」):走 ``ops.readdir`` + ``ops.is_dir``,
无任何 shell 依赖,天然跨平台。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from codeagent.tools.base import AtomicTool
from codeagent.tools.shared import (
    GovernedText,
    resolve_to_cwd,
    truncate_head,
)

__all__ = ["LsTool", "DEFAULT_LIMIT"]

#: 默认单次最多返回的条目数。
DEFAULT_LIMIT = 500


class LsArgs(BaseModel):
    path: str | None = Field(None, description="要列举的目录,缺省当前目录")
    limit: int | None = Field(None, description="最多返回的条目数,缺省 500")


class LsTool(AtomicTool):
    name = "ls"
    description = "列出目录内容;目录条目带 / 后缀,大小写不敏感排序,默认不显示隐藏条目。"
    Args = LsArgs

    def _invoke(self, args: LsArgs) -> str:
        dir_path = resolve_to_cwd(args.path or ".", self._cwd)
        if not self._ops.exists(dir_path):
            raise ValueError(f"路径不存在: {dir_path}")
        if not self._ops.is_dir(dir_path):
            raise ValueError(f"不是目录: {dir_path}")

        try:
            entries = self._ops.readdir(dir_path)
        except OSError as exc:
            raise ValueError(f"无法读取目录 {dir_path}: {exc}")

        # 默认不显示隐藏条目,大小写不敏感排序。
        entries = [e for e in entries if not e.startswith(".")]
        entries.sort(key=str.lower)

        requested_limit = args.limit if args.limit is not None else DEFAULT_LIMIT
        limit = min(requested_limit, self.output_max_lines)
        count = len(entries)
        shown = entries[:limit]

        lines = []
        for name in shown:
            suffix = "/" if self._ops.is_dir(dir_path / name) else ""
            lines.append(name + suffix)
        body = "\n".join(lines) if lines else "(空目录)"
        body, trunc = truncate_head(
            body, max_lines=limit, max_bytes=self.output_max_bytes
        )

        parts = [body]
        if count > limit:
            parts.append(f"[条目超限,仅显示前 {limit} 条(共 {count} 条),可用 limit 调大]")
        if trunc.truncated:
            parts.append("[输出已截断]")
        content = "\n".join(parts)
        return GovernedText(
            content,
            {
                "completeness": "truncated" if count > limit or trunc.truncated else "complete",
                "total_bytes": len("\n".join(entries).encode("utf-8")),
                "total_lines": count,
                "shown_bytes": len("\n".join(shown).encode("utf-8")),
                "shown_lines": len(shown),
                "truncated_by": "tool_limit" if count > limit else ("tool_bytes" if trunc.truncated else None),
                "path": str(dir_path),
                "continuation": f"limit={limit}" if count > limit else None,
                "source": "tool",
            },
        )
