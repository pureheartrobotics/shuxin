from __future__ import annotations

from types import SimpleNamespace

import pytest

from shuxin.core.identity import IdentityEngine, load_mbti_profiles
from shuxin.core.soul import SoulEngine
from shuxin.plugins.companion import CompanionPlugin
from shuxin.voice.persistence.agents import AgentRecord
from shuxin.voice.config.config import DeviceConfig
from shuxin.voice.service import VoiceService

SAMPLE_TYPES = ("INFJ", "ENFP", "ISTJ")

STYLE_KEYWORDS = {
    "INFJ": "温柔克制",
    "ENFP": "轻快",
    "ISTJ": "沉稳",
}


@pytest.fixture
def profiles():
    return load_mbti_profiles()


def test_yaml_loads_16_types(profiles) -> None:
    assert len(profiles) == 16
    for mbti, entry in profiles.items():
        assert mbti.isupper() and len(mbti) == 4
        assert str(entry.get("style_anchor") or "").strip()
        assert str(entry.get("micro_anchor") or "").strip()
        factors = entry.get("companion_factors") or {}
        assert isinstance(factors, dict) and len(factors) == 6


@pytest.mark.parametrize("mbti", SAMPLE_TYPES)
def test_slot2_contains_style_anchor(mbti: str) -> None:
    engine = IdentityEngine(mbti)
    block = engine.get_system_prompt_block()

    assert "### MBTI 风格锚点" in block
    assert mbti in block
    assert "### 表达禁忌" in block
    assert STYLE_KEYWORDS[mbti] in block
    assert engine.profile.style_anchor.strip() in block
    assert engine.profile.soul_snippet.strip() in block
    assert "【口头标记】" in block
    assert "【行为触发】" in block
    assert "【专属动作】" in block


@pytest.mark.parametrize("mbti", SAMPLE_TYPES)
def test_slot4_micro_anchor_injected(tmp_path, mbti: str) -> None:
    plugin = CompanionPlugin(data_dir=tmp_path)
    plugin.initialize()
    agent = SimpleNamespace(identity=IdentityEngine(mbti))

    block = plugin.on_pre_llm_call(agent=agent)

    assert block is not None
    assert "## 风格微型锚点" in block
    assert agent.identity.get_micro_anchor() in block
    assert agent.identity.get_micro_anchor().startswith("风格锚点：")


def test_three_types_prompt_distinct() -> None:
    slot2_blocks = [IdentityEngine(mbti).get_system_prompt_block() for mbti in SAMPLE_TYPES]
    micro_anchors = [IdentityEngine(mbti).get_micro_anchor() for mbti in SAMPLE_TYPES]

    assert len(set(slot2_blocks)) == len(SAMPLE_TYPES)
    assert len(set(micro_anchors)) == len(SAMPLE_TYPES)


def test_apply_device_mbti_rebuilds_prompt(tmp_path) -> None:
    from shuxin.core.agent import Agent

    plugin = CompanionPlugin(data_dir=tmp_path)
    plugin.initialize()

    class HookPlugins:
        def invoke_hook(self, hook_name: str, **kwargs):
            if hook_name == "pre_llm_call":
                return [("companion", plugin.on_pre_llm_call(**kwargs))]
            return []

    agent = Agent.__new__(Agent)
    agent.identity = IdentityEngine("INFJ")
    agent.soul = SimpleNamespace(get_system_prompt_block=lambda: "## SOUL")
    agent.memory = SimpleNamespace(get_facts_summary=lambda: "")
    agent.plugins = HookPlugins()
    agent._initialized = True

    device = DeviceConfig(device_id="d1", metadata={"mbti": "ENFP"})
    agent_record = AgentRecord(agent_id="shuxin", metadata={"default_mbti": "INFJ"})

    VoiceService.apply_device_mbti(agent, device, agent_record)
    agent._build_system_prompt()

    prompt = agent.get_system_prompt()
    assert "ENFP" in prompt
    assert STYLE_KEYWORDS["ENFP"] in prompt
    assert agent.identity.get_micro_anchor() in prompt
    assert STYLE_KEYWORDS["INFJ"] not in prompt


def test_soul_slot_has_no_mbti() -> None:
    soul_path = "data/agents/shuxin/SOUL.md"
    engine = SoulEngine(soul_path)
    engine.load()
    block = engine.get_system_prompt_block()

    assert "MBTI 人格类型" not in block
    assert "INFJ" not in block


def test_slot1_slot2_no_conflict() -> None:
    soul = SoulEngine("data/agents/shuxin/SOUL.md")
    soul.load()
    identity = IdentityEngine("ISTP")
    combined = soul.get_system_prompt_block() + identity.get_system_prompt_block()

    assert "INFJ" not in combined
    assert "ISTP" in combined


def test_reveal_script_minimal(profiles) -> None:
    for mbti, entry in profiles.items():
        reveal = str(entry.get("reveal_script") or "")
        assert reveal == f"你好！绑定成功，我是 {mbti} 型的初心。"


def test_micro_anchor_no_type_prefix(profiles) -> None:
    for mbti, entry in profiles.items():
        micro = str(entry.get("micro_anchor") or "")
        assert micro.startswith("风格锚点："), micro
        assert not micro.startswith(f"{mbti} ")
