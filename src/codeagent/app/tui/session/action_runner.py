"""会话管理器异步生命周期调用。"""

from __future__ import annotations

import asyncio
from typing import Any

from codeagent.app.errors.reporting import report_unexpected_error


class SessionActionRunnerMixin:
    def _schedule_session_action(
        self,
        method_name: str,
        message: Any,
        *args: Any,
    ) -> bool:
        """在 TUI 事件循环中优先使用管理器的异步生命周期 API。"""
        method = getattr(self._manager, method_name, None)
        if not callable(method):
            return False
        task = getattr(self, "_session_action_task", None)
        if task is not None and not task.done():
            self.model.append_info("正在等待上一个会话操作完成")
            self._schedule_render()
            return True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False

        async def run_action() -> None:
            try:
                session = await method(*args)
            except ValueError as exc:
                self.model.append_info(str(exc))
            except Exception as exc:
                self.model.append_info(report_unexpected_error("会话操作", exc))
            else:
                self._hydrate_current_session()
                self.model.append_info(message(session))
            finally:
                self._session_action_task = None
                self._schedule_render()

        self.model.append_info("正在等待当前运行收尾并切换会话...")
        self._session_action_task = self._track_task(loop.create_task(run_action()))
        self._schedule_render()
        return True
