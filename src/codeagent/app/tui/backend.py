"""app/tui/backend.py:TuiBackend 端口——引擎与视图逻辑的解耦缝。

职责(design D1/D8):
- 视图逻辑(view.TuiApp)只依赖本端口,不 import 具体引擎;
- 后端负责:alt 屏、把 transcript 行差分渲染到屏幕、收输入(提交/打断)、
  报告 transcript 视口尺寸、退出后打印完整文档(先恢复主屏再打印);
- 当前实现为 textual(``textual_backend.py``),将来自研引擎实现同一接口即可,
  视图与组件零改动。

分层约束:本模块只定义协议与数据结构,不 import textual(延迟到具体后端)。
"""

from __future__ import annotations

from typing import Callable, Protocol

from codeagent.app.tui.components import RichLine

#: 提交处理器:收到输入框提交的文本。
SubmitHandler = Callable[[str], None]
#: 打断/退出处理器:运行中打断、空闲退出(由视图按运行态分派)。
InterruptHandler = Callable[[], None]
#: 尺寸变化处理器(含首次挂载),用于触发重新渲染。
ResizeHandler = Callable[[], None]
#: transcript 区点击处理器:参数为相对 transcript 顶部的行号(design D4,工具点击折叠)。
ClickHandler = Callable[[int], None]
#: 输入框内容变化处理器(T-45 补全:视图据此计算建议)。
InputChangedHandler = Callable[[str], None]
#: 建议导航处理器:参数为选择位移(±1,循环)。
SuggestionNavHandler = Callable[[int], None]
#: 建议确认处理器:视图把选中建议填回输入框。
SuggestionConfirmHandler = Callable[[], None]


class TuiBackend(Protocol):
    """TUI 渲染/输入后端的最小接口。"""

    def run(self) -> None:
        """进入 alt 屏并启动事件循环(阻塞直到退出;退出后打印 exit_document 指定的文档)。"""

    def transcript_size(self) -> tuple[int, int]:
        """返回 transcript 视口的 (宽度, 高度)。"""

    def render(self, lines: list[RichLine]) -> None:
        """差分更新 transcript 区内容。"""

    def set_status(self, line: RichLine) -> None:
        """更新状态栏内容(富样式行;design D5)。"""

    def set_suggestions(self, lines: list[RichLine]) -> None:
        """更新补全建议行(空列表 = 隐藏浮层;design T-45)。"""

    def set_input_text(self, text: str) -> None:
        """替换输入框全文(建议确认填入;design T-45)。"""

    def on_submit(self, handler: SubmitHandler) -> None:
        """注册输入提交处理器。"""

    def on_interrupt(self, handler: InterruptHandler) -> None:
        """注册打断/退出处理器(如 Esc)。"""

    def on_resize(self, handler: ResizeHandler) -> None:
        """注册尺寸变化处理器(挂载时也会触发一次)。"""

    def on_click(self, handler: ClickHandler) -> None:
        """注册 transcript 区行点击处理器(相对行号;design D4)。"""

    def on_input_changed(self, handler: InputChangedHandler) -> None:
        """注册输入内容变化处理器(补全建议计算)。"""

    def on_suggestion_navigate(self, handler: SuggestionNavHandler) -> None:
        """注册建议导航处理器(↑/↓)。"""

    def on_suggestion_confirm(self, handler: SuggestionConfirmHandler) -> None:
        """注册建议确认处理器(Enter/Tab,补全激活时)。"""

    def exit_document(self, lines: list[str]) -> None:
        """记录退出文档并退出 alt 屏;run() 返回后(主屏已恢复)打印该文档(design D5)。"""

    def stop(self) -> None:
        """退出事件循环与 alt 屏(不打印文档)。"""
