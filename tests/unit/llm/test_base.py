"""Unit tests for ``llm/base.py`` — provider protocol + base class.

Behavior-first: assert the exact API-format conversion, JSON-argument
parsing fallback, the BaseLLMProvider message-normalisation contract,
the streaming vs non-streaming dispatch, emergency-drop callback
fan-out, and ``with_model`` reuse/refusal semantics.
"""

import pytest

from kohakuterrarium.errors import EmptyLLMResponseError
from kohakuterrarium.llm.base import (
    BaseLLMProvider,
    ChatResponse,
    LLMConfig,
    NativeToolCall,
    ToolSchema,
)
from kohakuterrarium.llm.message import FilePart, ImagePart, Message, TextPart
from kohakuterrarium.llm.recovery import RetryPolicy


class TestToolSchema:
    def test_to_api_format_wraps_function_block(self):
        schema = ToolSchema(
            name="bash",
            description="run",
            parameters={"type": "object", "properties": {"c": {"type": "string"}}},
        )
        assert schema.to_api_format() == {
            "type": "function",
            "function": {
                "name": "bash",
                "description": "run",
                "parameters": {
                    "type": "object",
                    "properties": {"c": {"type": "string"}},
                },
            },
        }

    def test_default_parameters_is_empty_object_schema(self):
        schema = ToolSchema(name="ping", description="d")
        assert schema.parameters == {"type": "object", "properties": {}}


class TestNativeToolCall:
    def test_parsed_arguments_decodes_json(self):
        call = NativeToolCall(id="c1", name="bash", arguments='{"cmd": "ls"}')
        assert call.parsed_arguments() == {"cmd": "ls"}

    def test_invalid_json_falls_back_to_raw_wrapper(self):
        call = NativeToolCall(id="c1", name="bash", arguments="not json")
        assert call.parsed_arguments() == {"_raw": "not json"}


class _StubProvider(BaseLLMProvider):
    """Concrete provider that records what _stream_chat / _complete_chat saw."""

    def __init__(self, config=None):
        super().__init__(config)
        self.streamed_messages = None
        self.completed_messages = None

    async def _stream_chat(
        self, messages, *, tools=None, provider_native_tools=None, **kw
    ):
        self.streamed_messages = messages
        yield "chunk-a"
        yield "chunk-b"

    async def _complete_chat(self, messages, **kw):
        self.completed_messages = messages
        return ChatResponse(
            content="full-response",
            finish_reason="stop",
            usage={"prompt_tokens": 1},
            model="m",
        )


class TestBaseLLMProviderNormalisation:
    def test_empty_messages_normalise_to_empty_list(self):
        provider = _StubProvider()
        assert provider._normalize_messages([]) == []

    def test_dict_messages_passed_through(self):
        provider = _StubProvider()
        dicts = [{"role": "user", "content": "hi"}]
        assert provider._normalize_messages(dicts) is dicts

    def test_message_objects_converted_to_dicts(self):
        provider = _StubProvider()
        out = provider._normalize_messages([Message(role="user", content="hi")])
        assert out == [{"role": "user", "content": "hi"}]


class TestBaseLLMProviderChat:
    async def test_streaming_chat_yields_each_chunk(self):
        provider = _StubProvider()
        chunks = [c async for c in provider.chat([{"role": "user", "content": "x"}])]
        assert chunks == ["chunk-a", "chunk-b"]
        assert provider.streamed_messages == [{"role": "user", "content": "x"}]

    async def test_non_streaming_chat_yields_single_full_response(self):
        provider = _StubProvider()
        chunks = [
            c
            async for c in provider.chat(
                [{"role": "user", "content": "x"}], stream=False
            )
        ]
        assert chunks == ["full-response"]

    async def test_chat_resets_last_tool_calls(self):
        provider = _StubProvider()
        provider._last_tool_calls = [NativeToolCall("c", "n", "{}")]
        async for _ in provider.chat([{"role": "user", "content": "x"}]):
            pass
        assert provider.last_tool_calls == []

    async def test_chat_complete_returns_full_response(self):
        provider = _StubProvider()
        resp = await provider.chat_complete([Message(role="user", content="hi")])
        assert resp.content == "full-response"
        # Message objects were normalised before reaching _complete_chat
        assert provider.completed_messages == [{"role": "user", "content": "hi"}]


class TestBaseLLMProviderProperties:
    def test_last_usage_defaults_to_empty_dict(self):
        assert _StubProvider().last_usage == {}

    def test_last_assistant_content_parts_defaults_to_none(self):
        assert _StubProvider().last_assistant_content_parts is None

    def test_last_assistant_extra_fields_defaults_to_empty_dict(self):
        assert _StubProvider().last_assistant_extra_fields == {}

    def test_translate_provider_native_tool_default_is_none(self):
        assert _StubProvider().translate_provider_native_tool(object()) is None


class TestEmergencyDropCallbacks:
    def test_registered_callback_invoked_with_messages(self):
        provider = _StubProvider()
        seen = []
        provider.on_emergency_drop(lambda msgs: seen.append(msgs))
        recovered = [{"role": "user", "content": "recovered"}]
        provider._notify_emergency_drop(recovered)
        assert seen == [recovered]

    def test_failing_callback_does_not_break_others(self):
        provider = _StubProvider()
        seen = []

        def boom(_msgs):
            raise RuntimeError("callback failed")

        provider.on_emergency_drop(boom)
        provider.on_emergency_drop(lambda msgs: seen.append("ok"))
        # one callback raising must not stop the fan-out
        provider._notify_emergency_drop([])
        assert seen == ["ok"]


class TestWithModel:
    def test_same_model_returns_self(self):
        provider = _StubProvider(LLMConfig(model="gpt-x"))
        assert provider.with_model("gpt-x") is provider

    def test_empty_name_returns_self(self):
        provider = _StubProvider(LLMConfig(model="gpt-x"))
        assert provider.with_model("") is provider

    def test_different_model_refused_by_base_implementation(self):
        provider = _StubProvider(LLMConfig(model="gpt-x"))
        with pytest.raises(ValueError, match="cannot switch"):
            provider.with_model("gpt-y")


class TestBaseProviderAbstractMethods:
    async def test_stream_chat_not_implemented_on_base(self):
        base = BaseLLMProvider()
        with pytest.raises(NotImplementedError):
            async for _ in base._stream_chat([]):
                pass

    async def test_complete_chat_not_implemented_on_base(self):
        base = BaseLLMProvider()
        with pytest.raises(NotImplementedError):
            await base._complete_chat([])


class _EmptyRetryProvider(BaseLLMProvider):
    """Scripted provider for empty-response retry tests.

    ``script`` entries are the chunk lists yielded by ``_stream_chat``;
    an entry may be a callable ``(provider) -> list[str]`` so a test
    can simulate provider side effects (native tool calls / assistant
    parts) that happen after the stream ends. ``complete_script``
    entries are either a content string or a callable returning a
    ``ChatResponse``.
    """

    def __init__(self, script, *, complete_script=None, config=None):
        # Default policy keeps the 1+3 attempt budget (max_retries=3)
        # but zeroes delay so exhaustion tests never actually sleep.
        if config is None:
            config = LLMConfig(
                model="m",
                retry_policy={"max_retries": 3, "base_delay": 0, "jitter": 0},
            )
        super().__init__(config)
        self.script = list(script)
        self.complete_script = (
            list(complete_script) if complete_script is not None else list(script)
        )
        self.stream_calls = 0
        self.complete_calls = 0

    async def _stream_chat(
        self, messages, *, tools=None, provider_native_tools=None, **kw
    ):
        entry = self.script[min(self.stream_calls, len(self.script) - 1)]
        self.stream_calls += 1
        if callable(entry):
            entry = entry(self)
        for chunk in entry:
            yield chunk

    async def _complete_chat(self, messages, **kw):
        entry = self.complete_script[
            min(self.complete_calls, len(self.complete_script) - 1)
        ]
        self.complete_calls += 1
        if callable(entry):
            entry = entry(self)
        if isinstance(entry, str):
            return ChatResponse(
                content=entry, finish_reason="stop", usage={}, model="m"
            )
        return entry


def _empty_chunks(_provider) -> list[str]:
    return []


class TestEmptyResponseRetry:
    """HTTP-200-but-empty responses retry per RetryPolicy at the base boundary."""

    async def test_stream_empty_then_text_retries_and_yields(self):
        provider = _EmptyRetryProvider([_empty_chunks, ["hello"]])
        chunks = [c async for c in provider.chat([{"role": "user", "content": "x"}])]
        assert chunks == ["hello"]
        assert provider.stream_calls == 2

    async def test_stream_reasoning_extra_fields_do_not_count_as_output(self):
        def reasoning_only(p):
            p._last_assistant_extra_fields = {"reasoning_content": "think steps"}
            return []

        provider = _EmptyRetryProvider([reasoning_only, ["ok"]])
        chunks = [c async for c in provider.chat([{"role": "user", "content": "x"}])]
        assert chunks == ["ok"]
        assert provider.stream_calls == 2
        assert provider.last_assistant_extra_fields == {}

    async def test_stream_retry_clears_failed_attempt_usage(self):
        def usage_only(p):
            p._last_usage = {"total_tokens": 12}
            return []

        provider = _EmptyRetryProvider([usage_only, ["ok"]])
        chunks = [c async for c in provider.chat([{"role": "user", "content": "x"}])]
        assert chunks == ["ok"]
        assert provider.last_usage == {}

    async def test_stream_persistent_empty_exhausts_default_retries(self):
        # Default test policy: 1 initial + 3 retries = 4 attempts (no sleep).
        provider = _EmptyRetryProvider([_empty_chunks] * 4)
        with pytest.raises(
            EmptyLLMResponseError, match="empty response after 4 attempt"
        ):
            async for _ in provider.chat([{"role": "user", "content": "x"}]):
                pass
        assert provider.stream_calls == 4

    async def test_stream_empty_with_transient_disabled_fails_fast(self):
        # retry_classes=[] excludes TRANSIENT -> empty response must raise
        # immediately: no sleep, no recall (base_delay=1.0 proves the
        # test would be slow if it wrongly slept/recalled).
        provider = _EmptyRetryProvider(
            [_empty_chunks, ["ok"]],
            config=LLMConfig(
                model="m",
                retry_policy={
                    "max_retries": 3,
                    "base_delay": 1.0,
                    "jitter": 0.0,
                    "retry_classes": [],
                },
            ),
        )
        with pytest.raises(EmptyLLMResponseError, match="after 1 attempt"):
            async for _ in provider.chat([{"role": "user", "content": "x"}]):
                pass
        assert provider.stream_calls == 1

    async def test_stream_blank_deltas_do_not_count_as_output(self):
        provider = _EmptyRetryProvider([["", "   ", ""], ["ok"]])
        chunks = [c async for c in provider.chat([{"role": "user", "content": "x"}])]
        assert chunks == ["ok"]
        assert provider.stream_calls == 2

    async def test_stream_tool_call_only_is_valid_no_retry(self):
        def tool_call_only(p):
            p._last_tool_calls = [
                NativeToolCall(id="c1", name="bash", arguments='{"cmd": "ls"}')
            ]
            return []

        provider = _EmptyRetryProvider([tool_call_only])
        chunks = [c async for c in provider.chat([{"role": "user", "content": "x"}])]
        assert chunks == []
        assert provider.stream_calls == 1
        assert provider.last_tool_calls == [
            NativeToolCall(id="c1", name="bash", arguments='{"cmd": "ls"}')
        ]

    async def test_stream_structured_part_only_is_valid_no_retry(self):
        def parts_only(pu):
            pu._last_assistant_parts = [
                ImagePart(url="data:image/png;base64,AAAA", source_type="generated")
            ]
            return []

        provider = _EmptyRetryProvider([parts_only])
        chunks = [c async for c in provider.chat([{"role": "user", "content": "x"}])]
        assert chunks == []
        assert provider.stream_calls == 1
        assert provider.last_assistant_content_parts is not None

    async def test_stream_blank_text_part_does_not_count_as_output(self):
        def blank_text_part(p):
            p._last_assistant_parts = [TextPart(text="")]
            return []

        provider = _EmptyRetryProvider([blank_text_part, ["ok"]])
        chunks = [c async for c in provider.chat([{"role": "user", "content": "x"}])]
        assert chunks == ["ok"]
        assert provider.stream_calls == 2

    async def test_stream_non_blank_text_part_counts_as_output(self):
        def text_part(p):
            p._last_assistant_parts = [TextPart(text="  visible  ")]
            return []

        provider = _EmptyRetryProvider([text_part])
        chunks = [c async for c in provider.chat([{"role": "user", "content": "x"}])]
        assert chunks == []
        assert provider.stream_calls == 1

    async def test_stream_file_part_counts_as_output(self):
        def file_part(p):
            p._last_assistant_parts = [
                FilePart(path="x.txt", name="x.txt", content="hi", mime="text/plain")
            ]
            return []

        provider = _EmptyRetryProvider([file_part])
        chunks = [c async for c in provider.chat([{"role": "user", "content": "x"}])]
        assert chunks == []
        assert provider.stream_calls == 1

    async def test_stream_clears_stale_parts_before_attempt(self):
        # A structured part from a previous round must not mask this
        # attempt's empty response as a success.
        provider = _EmptyRetryProvider(
            [_empty_chunks],
            config=LLMConfig(
                model="m", retry_policy={"max_retries": 0, "base_delay": 0, "jitter": 0}
            ),
        )
        provider._last_assistant_parts = [
            ImagePart(url="data:image/png;base64,AAAA", source_type="generated")
        ]
        with pytest.raises(EmptyLLMResponseError):
            async for _ in provider.chat([{"role": "user", "content": "x"}]):
                pass
        assert provider.stream_calls == 1

    async def test_non_streaming_empty_then_text_retries(self):
        provider = _EmptyRetryProvider([], complete_script=["", "full"])
        chunks = [
            c
            async for c in provider.chat(
                [{"role": "user", "content": "x"}], stream=False
            )
        ]
        assert chunks == ["full"]
        assert provider.complete_calls == 2

    async def test_non_streaming_whitespace_only_counts_as_empty(self):
        provider = _EmptyRetryProvider([], complete_script=["   ", "real"])
        chunks = [
            c
            async for c in provider.chat(
                [{"role": "user", "content": "x"}], stream=False
            )
        ]
        assert chunks == ["real"]
        assert provider.complete_calls == 2

    async def test_non_streaming_persistent_empty_exhausts_policy(self):
        provider = _EmptyRetryProvider(
            [],
            complete_script=["", "", ""],
            config=LLMConfig(
                model="m", retry_policy={"max_retries": 1, "base_delay": 0, "jitter": 0}
            ),
        )
        with pytest.raises(
            EmptyLLMResponseError, match="empty response after 2 attempt"
        ):
            async for _ in provider.chat(
                [{"role": "user", "content": "x"}], stream=False
            ):
                pass
        assert provider.complete_calls == 2

    async def test_non_streaming_empty_with_transient_disabled_fails_fast(self):
        provider = _EmptyRetryProvider(
            [],
            complete_script=["", "full"],
            config=LLMConfig(
                model="m",
                retry_policy={
                    "max_retries": 3,
                    "base_delay": 1.0,
                    "jitter": 0.0,
                    "retry_classes": [],
                },
            ),
        )
        with pytest.raises(EmptyLLMResponseError, match="after 1 attempt"):
            async for _ in provider.chat(
                [{"role": "user", "content": "x"}], stream=False
            ):
                pass
        assert provider.complete_calls == 1

    async def test_chat_complete_clears_stale_tool_calls(self):
        # LiteLLM-style completion only *sets* _last_tool_calls when tool
        # calls arrive; a stale tool call from a previous round must not
        # turn this round's empty content into a success.
        provider = _EmptyRetryProvider(
            [],
            complete_script=[""],
            config=LLMConfig(
                model="m", retry_policy={"max_retries": 1, "base_delay": 0, "jitter": 0}
            ),
        )
        provider._last_tool_calls = [
            NativeToolCall(id="stale", name="bash", arguments="{}")
        ]
        with pytest.raises(EmptyLLMResponseError):
            await provider.chat_complete([{"role": "user", "content": "x"}])
        assert provider.complete_calls == 2
        assert provider.last_tool_calls == []

    async def test_non_streaming_tool_call_only_is_valid_no_retry(self):
        def tool_only(p):
            p._last_tool_calls = [NativeToolCall(id="c1", name="bash", arguments="{}")]
            return ChatResponse(
                content="", finish_reason="tool_calls", usage={}, model="m"
            )

        provider = _EmptyRetryProvider([], complete_script=[tool_only])
        chunks = [
            c
            async for c in provider.chat(
                [{"role": "user", "content": "x"}], stream=False
            )
        ]
        assert chunks == [""]
        assert provider.complete_calls == 1

    async def test_chat_complete_empty_then_text_retries(self):
        provider = _EmptyRetryProvider([], complete_script=["", "full"])
        resp = await provider.chat_complete([{"role": "user", "content": "x"}])
        assert resp.content == "full"
        assert provider.complete_calls == 2

    async def test_stream_respects_retry_policy_max_retries(self):
        provider = _EmptyRetryProvider(
            [_empty_chunks, _empty_chunks, ["ok"]],
            config=LLMConfig(
                model="m", retry_policy={"max_retries": 1, "base_delay": 0, "jitter": 0}
            ),
        )
        with pytest.raises(EmptyLLMResponseError):
            async for _ in provider.chat([{"role": "user", "content": "x"}]):
                pass
        assert provider.stream_calls == 2

    async def test_stream_empty_retry_uses_policy_backoff(self, monkeypatch):
        backoff_calls = []

        def fake_backoff(attempt, policy):
            backoff_calls.append(attempt)
            return 0.0

        sleeps: list[float] = []

        async def fake_sleep(delay):
            sleeps.append(delay)

        monkeypatch.setattr("kohakuterrarium.llm.base.backoff_delay", fake_backoff)
        monkeypatch.setattr("kohakuterrarium.llm.base.asyncio.sleep", fake_sleep)

        provider = _EmptyRetryProvider(
            [_empty_chunks, _empty_chunks, ["ok"]],
            config=LLMConfig(
                model="m", retry_policy={"base_delay": 1.0, "jitter": 0.0}
            ),
        )
        chunks = [c async for c in provider.chat([{"role": "user", "content": "x"}])]
        assert chunks == ["ok"]
        assert backoff_calls == [1, 2]
        assert sleeps == [0.0, 0.0]


class TestProviderSharedLayerCoverage:
    """LiteLLM goes through the shared base layer; Fake / Deferred are
    standalone doubles — confirm that split stays reasonable."""

    def test_litellm_provider_inherits_shared_layer_and_policy(self):
        from kohakuterrarium.llm.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(
            model="openai/gpt-test",
            config=LLMConfig(model="openai/gpt-test", retry_policy={"max_retries": 2}),
        )
        assert isinstance(provider, BaseLLMProvider)
        assert provider._effective_retry_policy().max_retries == 2

    def test_litellm_provider_default_policy_falls_back_to_config(self):
        from kohakuterrarium.llm.litellm_provider import LiteLLMProvider

        provider = LiteLLMProvider(model="openai/gpt-test")
        policy = provider._effective_retry_policy()
        assert isinstance(policy, RetryPolicy)
        assert policy.max_retries == 3

    async def test_fake_provider_standalone_has_no_shared_empty_retry(self, tmp_path):
        from kohakuterrarium.testing.fake_llm_provider import FakeLLMProvider

        script = tmp_path / "script.json"
        script.write_text('{"script": [""]}', encoding="utf-8")
        provider = FakeLLMProvider(api_key="k", script_path=str(script))
        assert not isinstance(provider, BaseLLMProvider)
        # Deterministic test double: an empty scripted reply passes
        # through untouched instead of looping through shared retries.
        chunks = [c async for c in provider.chat([{"role": "user", "content": "x"}])]
        assert chunks == [""]
        assert provider.call_count == 1

    async def test_deferred_provider_standalone_raises_on_chat(self):
        from kohakuterrarium.llm.deferred_provider import DeferredLLMProvider

        provider = DeferredLLMProvider(reason="no key")
        assert not isinstance(provider, BaseLLMProvider)
        with pytest.raises(RuntimeError, match="no usable LLM provider"):
            async for _ in provider.chat([{"role": "user", "content": "x"}]):
                pass
