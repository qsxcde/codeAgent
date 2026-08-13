"""搜索忽略策略:噪声目录黑名单(design D4)。

不实现完整 .gitignore 语义(锚定/取反/逐级覆盖是独立复杂体),用黑名单覆盖
真实噪声目录;模型可经 ``path`` 参数自行定位被跳过的目录。find/grep 共用。
"""

from __future__ import annotations

__all__ = ["NOISE_DIRS", "prune_noise_dirs"]

#: 默认跳过的噪声目录名(不进入递归)。
NOISE_DIRS = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
)


def prune_noise_dirs(dirs: list[str]) -> None:
    """就地裁剪 os.walk 风格的 dirs 列表,跳过噪声目录。"""
    dirs[:] = [d for d in dirs if d not in NOISE_DIRS]
