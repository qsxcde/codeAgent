"""事件总线:subscribe / emit。

session 层的事件路由设施——把图运行翻译成的事件分发给订阅方(TUI/CLI/测试)。
bus 本身不持有图/模型/工具,只负责扇出事件,保持"薄"。
"""

from __future__ import annotations

from typing import Any, Callable

# 订阅回调签名:接收一个 AgentEvent
Subscriber = Callable[[Any], None]


class EventBus:
    """极简同步事件总线(订阅回调视为同步函数,适合事件扇出)。"""

    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self._emit_errors: list[tuple[Any, Exception]] = []

    def subscribe(self, fn: Subscriber) -> Callable[[], None]:
        """注册订阅回调,返回取消订阅函数。"""
        self._subscribers.append(fn)

        def unsubscribe() -> None:
            if fn in self._subscribers:
                self._subscribers.remove(fn)

        return unsubscribe

    def emit(self, event: Any) -> None:
        """按注册顺序向所有订阅方分发事件。

        任一订阅方抛异常不影响后续订阅方收到事件;被捕获的异常
        以 (event, exception) 形式记录在 ``emit_errors`` 供查询。
        """
        for fn in list(self._subscribers):
            try:
                fn(event)
            except Exception as exc:  # noqa: BLE001 - 订阅方异常隔离
                self._emit_errors.append((event, exc))

    @property
    def emit_errors(self) -> list[tuple[Any, Exception]]:
        """返回 emit 期间被隔离的订阅方异常列表(事件, 异常)。"""
        return list(self._emit_errors)

    def clear(self) -> None:
        self._subscribers.clear()
        self._emit_errors.clear()

    def __len__(self) -> int:
        return len(self._subscribers)
