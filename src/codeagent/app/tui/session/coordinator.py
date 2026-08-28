"""TUI 会话协调器。

切换、异步动作和快照恢复分别由职责单一的 mixin 承担。
"""

from .action_runner import SessionActionRunnerMixin
from .actions import SessionActionsMixin
from .commands import SessionCommandsMixin
from .restore import RestoreCost, SessionRestoreMixin

__all__ = ["RestoreCost", "TuiSessionCoordinator"]


class TuiSessionCoordinator(
    SessionCommandsMixin,
    SessionActionsMixin,
    SessionActionRunnerMixin,
    SessionRestoreMixin,
):
    """组合各类会话协调职责。"""
