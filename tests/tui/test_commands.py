"""命令注册表与解析测试(纯函数,离线):parse 三类结果、// 转义、未知命令、
未接线命令(/undo)提示、/help 全文帮助覆盖全部注册命令。"""

from codeagent.app.tui.commands import (
    Command,
    Literal,
    UnknownCommand,
    default_registry,
    help_text,
    parse,
)

REGISTRY = default_registry()


def test_plain_text_is_literal():
    assert parse("你好 world", REGISTRY) == Literal("你好 world")


def test_slash_only_is_literal():
    """单独 / 不触发命令解析(用户真的想发 /)。"""
    assert parse("/", REGISTRY) == Literal("/")


def test_double_slash_escapes_literal():
    """// 转义:去掉一个 /,按字面量发送(不触发命令解析)。"""
    assert parse("//help", REGISTRY) == Literal("/help")


def test_double_slash_with_text_escapes():
    assert parse("//你好 /foo", REGISTRY) == Literal("/你好 /foo")


def test_registered_command_without_args():
    assert parse("/help", REGISTRY) == Command("help")


def test_registered_command_with_args():
    assert parse("/sessions new", REGISTRY) == Command("sessions", ("new",), "new")


def test_command_args_extra_spaces():
    assert parse("/model   deepseek:high  ", REGISTRY) == Command(
        "model", ("deepseek:high",), "deepseek:high"
    )


def test_unknown_command():
    assert parse("/foobar x", REGISTRY) == UnknownCommand("foobar")


def test_registry_covers_expected_commands():
    """T-44 命令表全部注册(含未接线的 /undo 槽位)。"""
    names = set(REGISTRY)
    assert {
        "help",
        "clear",
        "status",
        "sessions",
        "tools",
        "provider",
        "model",
        "effort",
        "undo",
    } <= names


def test_undo_registered_but_not_available():
    """/undo 注册槽位但未接线(T-42 前提示未可用,不静默忽略)。"""
    assert REGISTRY["undo"].available is False


def test_help_text_covers_all_commands():
    text = help_text(REGISTRY)
    for spec in REGISTRY.values():
        assert f"/{spec.name}" in text
    assert "(未可用)" in text  # /undo 的未接线状态可见(NFR-U7 可发现性)


def test_help_text_markup_available():
    assert "可用命令:" in help_text(REGISTRY)
