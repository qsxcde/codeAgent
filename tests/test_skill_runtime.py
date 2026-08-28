"""CodeAgent Skill Adapter / Bootstrap runtime tests."""

from codeagent.app.skills.models import Skill
from codeagent.app.skills.runtime import (
    BOOTSTRAP_TAG,
    CodeAgentAdapter,
    SkillRuntimeState,
    build_bootstrap_prompt,
)


def _bootstrap_skill() -> Skill:
    return Skill(
        name="using-superpowers",
        description="任务开始前检查相关技能。",
        path="/packages/superpowers/skills/using-superpowers/SKILL.md",
        content="每次开始任务前检查相关 Skill。",
        package_id="superpowers",
        package_version="6.3.0",
        package_scope="user",
        bootstrap=True,
    )


def test_codeagent_adapter_maps_available_and_missing_capabilities():
    adapter = CodeAgentAdapter()

    mapping = adapter.tool_mapping()
    capabilities = adapter.capabilities()

    assert "read" in mapping and "skill" in mapping
    assert capabilities["read"] is True
    assert capabilities["subagents"] is False
    assert capabilities["todo"] is False
    assert capabilities["web"] is False


def test_bootstrap_prompt_contains_only_bootstrap_body_and_tool_mapping():
    bootstrap = _bootstrap_skill()
    ordinary = Skill("fmt", "格式化", "/fmt/SKILL.md", "不应预载")

    prompt = build_bootstrap_prompt("基础", [bootstrap, ordinary])

    assert BOOTSTRAP_TAG in prompt
    assert "每次开始任务前检查相关 Skill" in prompt
    assert "不应预载" not in prompt
    assert "skill" in prompt


def test_bootstrap_absent_does_not_change_base_prompt():
    assert build_bootstrap_prompt("基础", [Skill("fmt", "格式化", "/fmt/SKILL.md", "正文")]) == "基础"


def test_runtime_state_injects_once_until_context_resets():
    state = SkillRuntimeState(adapter_version="codeagent-v1", bootstrap_name="using-superpowers")

    assert state.claim("session-1") is True
    assert state.claim("session-1") is False
    assert state.claim("session-2") is True
    state.reset("session-1")
    assert state.claim("session-1") is True

    status = state.status()
    assert status["adapter"] == "codeagent-v1"
    assert status["bootstrap"] == "using-superpowers"


def test_container_system_prompt_places_bootstrap_before_skill_catalog():
    from codeagent.app.container import _build_system_prompt

    prompt = _build_system_prompt(
        skills=[_bootstrap_skill(), Skill("fmt", "格式化", "/fmt/SKILL.md", "UNIQUE-ORDINARY-BODY")]
    )

    assert prompt.index(BOOTSTRAP_TAG) < prompt.index("<available_skills>")
    assert "using-superpowers" in prompt
    assert "UNIQUE-ORDINARY-BODY" not in prompt
    catalog = prompt[prompt.index("<available_skills>") :]
    assert "- using-superpowers:" not in catalog
