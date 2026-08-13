"""CLI 入口测试:headless 两种模式不崩溃、输出回复(回归:P1-4 缺 respond 崩溃)。"""

from __future__ import annotations

import io
import sys

import pytest

from codeagent.app.main import main


@pytest.fixture
def fake_provider_env(monkeypatch):
    """headless 使用 fake provider,不依赖真实 API key。"""
    monkeypatch.setenv("LLM_PROVIDER", "fake")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_prompt_mode_returns_reply(fake_provider_env, capsys):
    """``--prompt`` 不抛 AttributeError 且输出回复文本。"""
    main(["--prompt", "你好"])
    out = capsys.readouterr().out
    assert "你: 你好" in out
    assert "测试回复" in out


def test_stdin_mode_returns_reply(fake_provider_env, capsys, monkeypatch):
    """stdin 逐行模式不抛 AttributeError 且逐行输出回复。"""
    monkeypatch.setattr(sys, "stdin", io.StringIO("第一行\n第二行\n"))
    main([])
    out = capsys.readouterr().out
    assert "你: 第一行" in out
    assert "你: 第二行" in out
    assert out.count("测试回复") == 2
