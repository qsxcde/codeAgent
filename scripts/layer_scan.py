"""扫描 src/codeagent 各层之间的 import 依赖，输出跨层矩阵与明细。

只做静态分析（ast），不执行任何项目代码。
"""

from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "codeagent"

LAYERS = ("app", "core", "session", "ai", "tools", "resources")


def layer_of(rel: Path) -> str:
    return rel.parts[0] if rel.parts[0] in LAYERS else "other"


def iter_py():
    for p in sorted(PKG.rglob("*.py")):
        yield p.relative_to(PKG), p


def extract_imports(path: Path) -> list[tuple[int, str, str | None]]:
    """返回 (行号, 完整模块名, 导入的具体名字)。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:  # pragma: no cover
        print(f"!! 解析失败 {path}: {exc}", file=sys.stderr)
        return []

    out: list[tuple[int, str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((node.lineno, alias.name, None))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if node.level:  # 相对导入，回溯到绝对模块
                pkg_parts = path.relative_to(PKG).with_suffix("").parts
                base = list(pkg_parts[:-1]) if pkg_parts[-1] != "__init__" else list(pkg_parts)
                if node.level > 1:
                    base = base[: -(node.level - 1)]
                mod = ".".join([*base, mod]) if mod else ".".join(base)
            for alias in node.names:
                out.append((node.lineno, mod, alias.name))
    return out


def main() -> int:
    # edges[from_layer][to_layer] = 出现次数
    edges: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # detail[from][to] = [(文件, 行号, 模块, 名字)]
    detail: dict[tuple[str, str], list[tuple[str, int, str, str]]] = defaultdict(list)
    # 外部（非 codeagent）依赖计数
    external: dict[str, set[str]] = defaultdict(set)
    # TYPE_CHECKING / 函数内延迟导入标记
    lazy: dict[tuple[str, str], int] = defaultdict(int)

    files_by_layer: dict[str, list[str]] = defaultdict(list)

    for rel, path in iter_py():
        src_layer = layer_of(rel)
        files_by_layer[src_layer].append(str(rel))
        src_text = path.read_text(encoding="utf-8")

        # 判断该行是否处于 TYPE_CHECKING 块或函数体内（延迟导入）
        lazy_lines: set[int] = set()
        try:
            tree = ast.parse(src_text)
            for node in ast.walk(tree):
                if isinstance(node, ast.If):
                    seg = ast.get_source_segment(src_text, node.test) or ""
                    if "TYPE_CHECKING" in seg:
                        for sub in ast.walk(node):
                            if isinstance(sub, (ast.Import, ast.ImportFrom)):
                                lazy_lines.add(sub.lineno)
        except SyntaxError:
            pass

        for lineno, mod, name in extract_imports(path):
            if mod.startswith("codeagent"):
                parts = mod.split(".")
                target = parts[1] if len(parts) > 1 else "root"
                if target not in LAYERS:
                    target = "root"
                edges[src_layer][target] += 1
                key = (src_layer, target)
                detail[key].append((str(rel), lineno, mod, name or ""))
                if lineno in lazy_lines:
                    lazy[key] += 1
            elif mod and not mod.startswith("_"):
                external[src_layer].add(mod.split(".")[0])

    print("=" * 72)
    print("一、跨层依赖矩阵（行=导入方，列=被导入方；数字为 import 语句条数）")
    print("=" * 72)
    header = "from\\to  " + "".join(f"{l:>11}" for l in LAYERS) + f"{'root':>8}"
    print(header)
    print("-" * len(header))
    for f in LAYERS + ("other",):
        row = edges.get(f, {})
        cells = "".join(
            f"{(row.get(t) or '.'):>11}" for t in LAYERS
        ) + f"{(row.get('root') or '.'):>8}"
        print(f"{f:<8}{cells}")

    print()
    print("=" * 72)
    print("二、各层引用的第三方/标准库顶层包（判断 core 是否真的'依赖较少'）")
    print("=" * 72)
    for f in LAYERS:
        pkgs = sorted(external.get(f, ()))
        std = {
            "__future__", "abc", "asyncio", "collections", "contextlib", "copy", "dataclasses",
            "datetime", "enum", "functools", "hashlib", "importlib", "inspect", "io", "itertools",
            "json", "logging", "math", "os", "pathlib", "re", "shlex", "string", "sys", "textwrap",
            "threading", "time", "traceback", "types", "typing", "unicodedata", "uuid", "warnings",
            "weakref", "tempfile", "subprocess", "shutil", "platform", "socket", "base64", "secrets",
            "urllib", "html", "difflib", "glob", "fnmatch", "posixpath", "ntpath", "random", "struct",
            "zoneinfo", "contextvars", "signal", "stat", "errno", "binascii", "codecs", "decimal",
        }
        third = [p for p in pkgs if p not in std]
        print(f"\n{f}: 共 {len(pkgs)} 个顶层包")
        if third:
            print(f"  非标准库: {', '.join(third)}")

    print()
    print("=" * 72)
    print("三、跨层调用明细（排除 app -> *，因为 app 允许依赖所有层）")
    print("=" * 72)
    for (f, t), items in sorted(detail.items()):
        if f == t or f == "app":
            continue
        n_lazy = lazy.get((f, t), 0)
        print(f"\n### {f} -> {t}: {len(items)} 条（其中延迟/TYPE_CHECKING 内 {n_lazy} 条）")
        by_file: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
        for fn, ln, mod, name in items:
            by_file[fn].append((ln, mod, name))
        for fn in sorted(by_file):
            mods = sorted({m for _, m, _ in by_file[fn]})
            lines = ",".join(str(ln) for ln, _, _ in sorted(by_file[fn]))
            print(f"   {fn}  (行 {lines})")
            for m in mods:
                print(f"       {m}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
