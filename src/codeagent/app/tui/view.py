"""app/tui/view.py:TuiApp——订阅会话事件、驱动组件渲染、处理输入/打断/退出。

职责(design D3/D4/D5):
- 订阅 ``AgentSession``,事件回调只调 ``TuiModel.apply`` 变更组件状态,再
  ``_schedule_render`` 合并渲染(每循环迭代最多一次,≥30fps);
- ``Esc`` 按运行态分派:运行中 → ``session.abort()``(RUN_CANCELLED 回状态栏
  IDLE);空闲 → 退出并打印完整文档(design D5);
- 只依赖 ``TuiBackend`` 端口(不 import textual),可注入 stub 后端离线测试。

分层约束:本模块可 import session/core/backend,禁止 import 具体引擎。
"""

from __future__ import annotations

import asyncio
from typing import Any

from codeagent.app.tui.backend import TuiBackend
from codeagent.app.tui.components import FooterInfo, TuiModel, ToolCallBlock

#: 退出文档的兜底宽度(视口尺寸不可用时)。
_DEFAULT_EXIT_WIDTH = 120


class TuiApp:
    """把会话事件流驱动成组件渲染 + 输入/打断/退出的视图逻辑。"""

    def __init__(
        self,
        session: Any,
        backend: TuiBackend,
        footer: FooterInfo | None = None,
    ) -> None:
        self._session = session
        self._backend = backend
        self.model = TuiModel()
        if footer is not None:
            # footer 右端的 model · effort 在装配时解析固化(design D5)。
            self.model.footer.model = footer.model
            self.model.footer.effort = footer.effort
        self._render_pending = False
        self._session.subscribe(self._on_event)

    # -- 生命周期 ----------------------------------------------------------

    def start(self) -> None:
        """注册后端回调并进入事件循环(阻塞直到退出)。"""
        self._backend.on_submit(self._submit)
        self._backend.on_interrupt(self._interrupt)
        self._backend.on_resize(self._schedule_render)
        self._backend.on_click(self._click)
        self._backend.run()

    def _click(self, row: int) -> None:
        """点击 transcript 某行:若命中工具块则切换折叠(design D4)。"""
        block = self.model.transcript.block_at(row)
        if isinstance(block, ToolCallBlock):
            block.toggle_expand()
            self._schedule_render()

    # -- 输入 / 打断 / 退出 ------------------------------------------------

    def _submit(self, text: str) -> None:
        """输入框提交:空闲时发起一轮对话。"""
        if self.model.running:
            return
        text = text.strip()
        if not text:
            return
        loop = asyncio.get_running_loop()
        loop.create_task(self._session.run(text))

    def _interrupt(self) -> None:
        """Esc 按运行态分派:运行中打断,空闲退出。"""
        if self.model.running:
            self._session.abort()
        else:
            self._exit()

    def _exit(self) -> None:
        width = self._transcript_width()
        self._backend.exit_document(self.model.transcript.all_lines(width))

    # -- 事件 → 渲染 -------------------------------------------------------

    def _on_event(self, event: Any) -> None:
        self.model.apply(event)
        self._schedule_render()

    def _schedule_render(self) -> None:
        """合并渲染请求:同一循环迭代内到达的事件合并成一次渲染(design D4)。"""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._flush_render()
            return
        if self._render_pending:
            return
        self._render_pending = True
        loop.call_soon(self._flush_render)

    def _flush_render(self) -> None:
        self._render_pending = False
        width, height = self._backend.transcript_size()
        if width <= 0 or height <= 0:
            return  # 尚未布局完成,等待下次 resize/事件
        lines = self.model.transcript.render(width, height)
        self._backend.render(lines)
        # 状态栏与 footer 均传富样式行(design D5:修复此前 RichLine 被当 str 传)。
        self._backend.set_status(self.model.status.render(width)[0])
        self._backend.set_footer(self.model.footer.render(width)[0])

    def _transcript_width(self) -> int:
        width, _ = self._backend.transcript_size()
        return width or _DEFAULT_EXIT_WIDTH
