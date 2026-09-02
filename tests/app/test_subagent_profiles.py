"""V5-10 canonical Subagent profile contract tests."""

from __future__ import annotations

import pytest

from codeagent.core.contracts.subagents import SubagentRequest, SubagentStatus


@pytest.mark.unit
def test_profile_registry_exposes_canonical_read_only_profiles() -> None:
    from codeagent.app.composition.subagent.profiles import (
        READ_ONLY_TOOL_NAMES,
        profile_for,
        profile_names,
    )

    assert profile_names() == ("explore", "review")
    assert set(READ_ONLY_TOOL_NAMES) == {"read", "grep", "find", "ls", "skill"}
    for name in profile_names():
        profile = profile_for(name)
        assert profile.name == name
        assert profile.instructions.strip()
        assert profile.output_guidance.strip()
        assert set(profile.tool_names) == set(READ_ONLY_TOOL_NAMES)
        assert not set(profile.tool_names) & {
            "write",
            "edit",
            "bash",
            "delegate",
        }


@pytest.mark.unit
def test_removed_read_only_profile_fails_closed() -> None:
    from codeagent.app.composition.subagent.profiles import profile_for

    with pytest.raises(ValueError, match="read_only"):
        profile_for("read_only")


@pytest.mark.unit
def test_subagent_request_defaults_to_explore() -> None:
    request = SubagentRequest(
        delegation_id="delegation",
        parent_run_id="parent-run",
        task="inspect the repository",
    )

    assert request.profile == "explore"


@pytest.mark.unit
def test_delegate_schema_matches_profile_registry() -> None:
    from codeagent.app.composition.subagent.delegate_tool import DelegateTool
    from codeagent.app.composition.subagent.profiles import profile_names

    schema = DelegateTool(object()).parameters

    assert schema["properties"]["profile"]["enum"] == list(profile_names())
    assert schema["properties"]["profile"]["default"] == "explore"


@pytest.mark.unit
async def test_delegate_rejects_removed_read_only_before_running_child() -> None:
    from codeagent.app.composition.subagent.delegate_tool import DelegateTool

    class Runner:
        def __init__(self) -> None:
            self.calls = 0

        async def execute(self, request, *, on_event=None):
            del request, on_event
            self.calls += 1
            raise AssertionError("removed profile must not start a child")

        async def cancel(self, delegation_id: str) -> bool:
            del delegation_id
            return False

    runner = Runner()
    result = await DelegateTool(runner).bind_parent_run_id("parent-run").execute(
        "call-1",
        {"task": "inspect", "profile": "read_only"},
    )

    assert result.error is True
    assert result.rejected is True
    assert result.details["reason_code"] == "permission_denied"
    assert "explore" in result.details["error_message"]
    assert runner.calls == 0


@pytest.mark.unit
async def test_runner_rejects_removed_read_only_before_child_creation() -> None:
    from codeagent.app.composition.subagent.runner import SerialSubagentRunner

    created = False

    def factory(request):
        nonlocal created
        del request
        created = True
        raise AssertionError("removed profile must not create a child")

    result = await SerialSubagentRunner(factory).execute(
        SubagentRequest(
            delegation_id="delegation-legacy",
            parent_run_id="parent-run",
            task="inspect",
            profile="read_only",
        )
    )

    assert result.status is SubagentStatus.REJECTED
    assert result.failure is not None
    assert result.failure.reason_code == "permission_denied"
    assert "explore" in result.failure.message
    assert created is False
