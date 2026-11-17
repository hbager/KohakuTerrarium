"""Outbound LLM request headers: browser User-Agent default and overrides."""

import importlib
import sys

import pytest

from kohakuterrarium.llm.http_headers import (
    BROWSER_USER_AGENT,
    with_browser_user_agent,
)

LITELLM_PROVIDER_MODULE = "kohakuterrarium.llm.litellm_provider"


class _MinimalLitellm:
    """Stand-in for the optional LiteLLM SDK; these tests never call it."""

    acompletion = None


class TestWithBrowserUserAgent:
    def test_defaults_to_the_browser_user_agent(self):
        assert with_browser_user_agent() == {"User-Agent": BROWSER_USER_AGENT}

    def test_fills_in_a_user_agent_beside_other_headers(self):
        headers = with_browser_user_agent({"X-Foo": "bar"})
        assert headers == {"X-Foo": "bar", "User-Agent": BROWSER_USER_AGENT}

    def test_explicit_user_agent_wins_case_insensitively(self):
        headers = with_browser_user_agent({"user-agent": "custom/1.0", "X-Foo": "bar"})
        assert headers == {"X-Foo": "bar", "User-Agent": "custom/1.0"}

    def test_does_not_mutate_the_caller_dict(self):
        original = {"X-Foo": "bar"}
        with_browser_user_agent(original)
        assert original == {"X-Foo": "bar"}


class TestProviderClientsUseIt:
    pytestmark = pytest.mark.real_llm_provider

    def test_openai_client_carries_the_browser_user_agent(self):
        from kohakuterrarium.llm.openai.provider import OpenAIProvider

        client = OpenAIProvider(api_key="sk-x", model="gpt-4o")._new_client()
        assert client.default_headers["User-Agent"] == BROWSER_USER_AGENT

    def test_openai_extra_headers_override_and_survive(self):
        from kohakuterrarium.llm.openai.provider import OpenAIProvider

        provider = OpenAIProvider(
            api_key="sk-x",
            model="gpt-4o",
            extra_headers={"User-Agent": "custom/1.0", "X-Foo": "bar"},
        )
        headers = provider._new_client().default_headers
        assert headers["User-Agent"] == "custom/1.0"
        assert headers["X-Foo"] == "bar"

    def test_litellm_request_params_carry_it(self, monkeypatch):
        parent = importlib.import_module("kohakuterrarium.llm")
        previous = sys.modules.pop(LITELLM_PROVIDER_MODULE, None)
        previous_attribute = parent.__dict__.get("litellm_provider")
        monkeypatch.setitem(sys.modules, "litellm", _MinimalLitellm())
        module = importlib.import_module(LITELLM_PROVIDER_MODULE)
        try:
            params = module.LiteLLMProvider(model="gpt-4o")._build_params(
                [{"role": "user", "content": "hi"}]
            )
            assert params["extra_headers"] == {"User-Agent": BROWSER_USER_AGENT}
        finally:
            sys.modules.pop(LITELLM_PROVIDER_MODULE, None)
            parent.__dict__.pop("litellm_provider", None)
            if previous is not None:
                sys.modules[LITELLM_PROVIDER_MODULE] = previous
                parent.__dict__["litellm_provider"] = previous_attribute
