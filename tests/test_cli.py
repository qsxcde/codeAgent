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


# -- session-manager change:会话入口(--list-sessions / --session / -c) ---------
#
# 注:conftest._isolate_config_dir(autouse)已把 CONFIG_DIR 重定向到临时目录,
# main 函数内 `from codeagent.app.config import CONFIG_DIR` 取到的即隔离值。


def test_list_sessions_empty(fake_provider_env, capsys):
    main(["--list-sessions"])
    assert "(无会话)" in capsys.readouterr().out


def test_list_sessions_shows_refs(fake_provider_env, capsys):
    from codeagent.app.config import CONFIG_DIR
    from codeagent.core.messages import Message
    from codeagent.session.store import JsonFileStore

    store = JsonFileStore(CONFIG_DIR / "sessions")
    store.create("s1", model="deepseek-v4-flash")
    store.append_message("s1", Message(role="user", content="你好,帮我看看这个项目"))
    main(["--list-sessions"])
    out = capsys.readouterr().out
    assert "s1" in out
    assert "deepseek-v4-flash" in out
    assert "你好" in out  # 派生标题


def test_session_flag_resumes_existing(fake_provider_env, capsys):
    """--session <id>:恢复既有会话,新消息追加到同一会话文件。"""
    from codeagent.app.config import CONFIG_DIR
    from codeagent.core.messages import Message
    from codeagent.session.store import JsonFileStore

    store = JsonFileStore(CONFIG_DIR / "sessions")
    store.create("s1")
    store.append_message("s1", Message(role="user", content="旧消息"))
    path = CONFIG_DIR / "sessions" / "s1.jsonl"
    lines_before = len(path.read_text(encoding="utf-8").splitlines())

    main(["--session", "s1", "--prompt", "继续聊"])
    out = capsys.readouterr().out
    assert "你: 继续聊" in out
    assert "测试回复" in out
    lines_after = len(path.read_text(encoding="utf-8").splitlines())
    assert lines_after > lines_before  # 新消息追加到同一会话


def test_continue_flag_appends_to_recent(fake_provider_env, capsys):
    """-c:继续最近会话(唯一会话时即该会话),新消息追加到同一文件。"""
    from codeagent.app.config import CONFIG_DIR
    from codeagent.core.messages import Message
    from codeagent.session.store import JsonFileStore

    store = JsonFileStore(CONFIG_DIR / "sessions")
    store.create("recent1")
    store.append_message("recent1", Message(role="user", content="旧消息"))

    main(["-c", "--prompt", "继续"])
    out = capsys.readouterr().out
    assert "你: 继续" in out
    loaded = store.load_messages("recent1")
    assert [m.content for m in loaded if m.role == "user"][-1] == "继续"
