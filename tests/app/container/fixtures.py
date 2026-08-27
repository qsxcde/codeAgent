"""Shared helpers for split behavior tests."""

from __future__ import annotations
import asyncio
from pathlib import Path
from unittest.mock import patch
import httpx
import pytest
from codeagent.ai.transport.openai_compat import OpenAICompatClient

async def _run_config(config, prompt: str, *, history=None, emit=None):
    from codeagent.core import AgentContext, run_agent_loop

    previous = list(history or [])
    new_messages = await run_agent_loop(
        AgentContext(messages=previous, tools=list(config.tools)),
        config,
        prompt,
        emit=emit,
    )
    return previous + new_messages


class _StubBackend:
    """最小 TuiBackend 实现(不 import textual,离线装配断言)。"""

    def run(self) -> None:  # pragma: no cover - stub
        pass

    def transcript_size(self) -> tuple[int, int]:
        return 60, 10

    def render(self, lines) -> None:  # pragma: no cover - stub
        pass

    def set_status(self, line) -> None:  # pragma: no cover - stub
        pass

    def on_submit(self, handler) -> None:  # pragma: no cover - stub
        pass

    def on_interrupt(self, handler) -> None:  # pragma: no cover - stub
        pass

    def on_resize(self, handler) -> None:  # pragma: no cover - stub
        pass

    def on_click(self, handler) -> None:  # pragma: no cover - stub
        pass

    def exit_document(self, lines) -> None:  # pragma: no cover - stub
        pass

    def stop(self) -> None:  # pragma: no cover - stub
        pass


def _config_with_mode(approval_mode: str):
    with patch("codeagent.app.composition.model_selection.create_llm") as mock_llm:
        from codeagent.ai.providers.fake import FakeClient

        mock_llm.return_value = FakeClient(response="测试回复")
        from codeagent.app.container import create_agent_config

        config = create_agent_config(approval_mode=approval_mode)
        from codeagent.app.container import _create_policy

        return config, _create_policy(approval_mode=approval_mode)


class _StubSummarizer:
    async def summarize(self, messages, prev_summary):
        return "桩摘要" + (f"<{prev_summary}>" if prev_summary else "")


__all__ = [name for name in globals() if not name.startswith("__")]
