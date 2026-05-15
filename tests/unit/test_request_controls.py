"""Tests for OpenAI request controls and User-Agent header."""

from kohakuterrarium.llm.openai import ROOCODE_USER_AGENT, OpenAIProvider
from kohakuterrarium.llm.openai_helpers import (
    apply_request_controls,
    lift_legacy_reasoning_effort,
)


# =========================================================================
# ROOCODE_USER_AGENT constant
# =========================================================================


def test_roocode_user_agent_constant():
    assert ROOCODE_USER_AGENT == "RooCode/3.52.1"


# =========================================================================
# OpenAIProvider sends User-Agent header
# =========================================================================


def test_openai_provider_sets_user_agent_header():
    provider = OpenAIProvider(api_key="test-key", model="gpt-test")
    headers = provider._client._custom_headers
    assert headers.get("User-Agent") == ROOCODE_USER_AGENT


def test_openai_provider_preserves_extra_headers_alongside_user_agent():
    provider = OpenAIProvider(
        api_key="test-key",
        model="gpt-test",
        extra_headers={"X-Custom": "value"},
    )
    headers = provider._client._custom_headers
    assert headers.get("User-Agent") == ROOCODE_USER_AGENT
    assert headers.get("X-Custom") == "value"


# =========================================================================
# OpenAIProvider stores reasoning_effort / service_tier
# =========================================================================


def test_openai_provider_stores_reasoning_effort():
    provider = OpenAIProvider(
        api_key="test-key", model="gpt-test", reasoning_effort="high"
    )
    assert provider.reasoning_effort == "high"


def test_openai_provider_stores_service_tier():
    provider = OpenAIProvider(
        api_key="test-key", model="gpt-test", service_tier="priority"
    )
    assert provider.service_tier == "priority"


def test_openai_provider_defaults_reasoning_effort_empty():
    provider = OpenAIProvider(api_key="test-key", model="gpt-test")
    assert provider.reasoning_effort == ""
    assert provider.service_tier is None


def test_with_model_preserves_request_controls():
    provider = OpenAIProvider(
        api_key="test-key",
        model="gpt-test",
        reasoning_effort="high",
        service_tier="priority",
    )
    clone = provider.with_model("gpt-other")
    assert clone.reasoning_effort == "high"
    assert clone.service_tier == "priority"


# =========================================================================
# lift_legacy_reasoning_effort
# =========================================================================


def test_lift_legacy_reasoning_effort_openai():
    extra = {"reasoning": {"enabled": True, "effort": "high"}}
    new_extra, effort = lift_legacy_reasoning_effort(
        extra, base_url="https://api.openai.com/v1"
    )
    assert effort == "high"
    assert "reasoning" not in new_extra


def test_lift_legacy_reasoning_effort_preserves_remaining_keys():
    extra = {"reasoning": {"enabled": True, "effort": "high", "budget_tokens": 1024}}
    new_extra, effort = lift_legacy_reasoning_effort(
        extra, base_url="https://api.openai.com/v1"
    )
    assert effort == "high"
    assert new_extra["reasoning"] == {"budget_tokens": 1024}


def test_lift_legacy_reasoning_effort_skips_openrouter():
    extra = {"reasoning": {"effort": "high"}}
    new_extra, effort = lift_legacy_reasoning_effort(
        extra, base_url="https://openrouter.ai/api/v1"
    )
    assert effort == ""
    assert new_extra is extra


def test_lift_legacy_reasoning_effort_skips_anthropic():
    extra = {"reasoning": {"effort": "high"}}
    new_extra, effort = lift_legacy_reasoning_effort(
        extra, base_url="https://api.anthropic.com/v1"
    )
    assert effort == ""
    assert new_extra is extra


def test_lift_legacy_reasoning_effort_skips_disabled():
    extra = {"reasoning": {"enabled": False, "effort": "high"}}
    new_extra, effort = lift_legacy_reasoning_effort(
        extra, base_url="https://api.openai.com/v1"
    )
    assert effort == ""


def test_lift_legacy_reasoning_effort_no_reasoning_key():
    extra = {"some_other": "value"}
    new_extra, effort = lift_legacy_reasoning_effort(
        extra, base_url="https://api.openai.com/v1"
    )
    assert effort == ""
    assert new_extra is extra


# =========================================================================
# apply_request_controls
# =========================================================================


def test_apply_request_controls_sets_reasoning_effort():
    kwargs: dict = {}
    extra: dict = {}
    result = apply_request_controls(
        kwargs, extra, base_url="https://api.openai.com/v1", reasoning_effort="high"
    )
    assert kwargs["reasoning_effort"] == "high"
    assert result == {}


def test_apply_request_controls_sets_service_tier():
    kwargs: dict = {}
    extra: dict = {}
    apply_request_controls(
        kwargs, extra, base_url="https://api.openai.com/v1", service_tier="priority"
    )
    assert kwargs["service_tier"] == "priority"


def test_apply_request_controls_promotes_legacy_effort():
    kwargs: dict = {}
    extra = {"reasoning": {"effort": "medium"}}
    result = apply_request_controls(
        kwargs, extra, base_url="https://api.openai.com/v1"
    )
    assert kwargs["reasoning_effort"] == "medium"
    assert "reasoning" not in result


def test_apply_request_controls_explicit_effort_overrides_legacy():
    kwargs: dict = {}
    extra = {"reasoning": {"effort": "low"}}
    apply_request_controls(
        kwargs,
        extra,
        base_url="https://api.openai.com/v1",
        reasoning_effort="high",
    )
    assert kwargs["reasoning_effort"] == "high"
