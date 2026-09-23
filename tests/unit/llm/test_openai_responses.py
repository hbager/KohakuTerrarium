"""Unit tests for ``llm/openai_responses.py`` reasoning capture and replay.

The provider must round-trip Responses-API reasoning for thinking models:
capture reasoning items from stream/complete responses into
``last_assistant_extra_fields``, and replay stored reasoning as input
items for models that require it (DeepSeek-style auto-detection plus the
explicit ``responses_reasoning_replay`` knob).
"""

from dataclasses import dataclass, field

import pytest

from kohakuterrarium.llm.openai_responses import OpenAIResponsesProvider

pytestmark = pytest.mark.skipif(
    not pytest.importorskip("openai"), reason="openai SDK not installed"
)


class _Ev:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


@dataclass
class _Resp:
    output: list = field(default_factory=list)
    usage: object = None
    status: str = "completed"
    model: str = "deepseek-v4.1-flash"


class _FakeResponses:
    def __init__(self, outcome):
        self._outcome = outcome
        self.kwargs: dict | None = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self._outcome


class _FakeClient:
    def __init__(self, outcome):
        self.responses = _FakeResponses(outcome)


def _provider(model: str, extra_body: dict | None = None) -> OpenAIResponsesProvider:
    p = OpenAIResponsesProvider(
        api_key="sk-test",
        model=model,
        base_url="https://fake.host/v1",
        extra_body=extra_body,
    )
    return p


async def _stream_events(events: list) -> object:
    for e in events:
        yield e


class TestReasoningReplay:
    @pytest.mark.parametrize(
        "model, expected_reasoning",
        [
            ("deepseek-v4.1-flash", True),
            ("gpt-5-mini", False),
        ],
    )
    async def test_replay_follows_target_model(self, model, expected_reasoning):
        p = _provider(model)
        p._client = _FakeClient(_stream_events([]))
        messages = [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "Done",
                "reasoning_content": "Inspect files",
            },
            {"role": "user", "content": "again"},
        ]
        async for _ in p._raw_stream_chat(messages):
            pass
        items = p._client.responses.kwargs["input"]
        reasoning_items = [i for i in items if i.get("type") == "reasoning"]
        assert bool(reasoning_items) is expected_reasoning
        if expected_reasoning:
            assert reasoning_items[0]["content"] == [
                {"type": "reasoning_text", "text": "Inspect files"}
            ]

    async def test_summary_falls_back_when_content_missing(self):
        p = _provider("deepseek-v4.1-flash")
        p._client = _FakeClient(_stream_events([]))
        messages = [
            {
                "role": "assistant",
                "content": "Done",
                "reasoning_summary": "We need answer in Chinese",
            }
        ]
        async for _ in p._raw_stream_chat(messages):
            pass
        items = p._client.responses.kwargs["input"]
        assert items[0]["type"] == "reasoning"
        assert items[0]["content"] == [
            {"type": "reasoning_text", "text": "We need answer in Chinese"}
        ]

    async def test_explicit_knob_forces_replay_and_stays_off_wire(self):
        p = _provider("kimi-k2", extra_body={"responses_reasoning_replay": True})
        p._client = _FakeClient(_stream_events([]))
        messages = [
            {
                "role": "assistant",
                "content": "",
                "reasoning_content": "Think",
            }
        ]
        async for _ in p._raw_stream_chat(messages):
            pass
        body = p._client.responses.kwargs
        assert body["input"][0]["content"] == [
            {"type": "reasoning_text", "text": "Think"}
        ]
        assert "responses_reasoning_replay" not in body
        assert "responses_reasoning_replay" not in body.get("extra_body", {})


class TestReasoningCapture:
    async def test_stream_summary_deltas_are_captured(self):
        p = _provider("deepseek-v4.1-flash")
        events = [
            _Ev(type="response.reasoning_summary_text.delta", delta="We "),
            _Ev(type="response.reasoning_summary_text.delta", delta="think"),
            _Ev(type="response.output_text.delta", delta="391"),
            _Ev(type="response.completed", response=None),
        ]
        p._client = _FakeClient(_stream_events(events))
        chunks = [
            c async for c in p._raw_stream_chat([{"role": "user", "content": "q"}])
        ]
        assert "".join(chunks) == "391"
        assert p._last_assistant_extra_fields["reasoning_summary"] == "We think"

    async def test_stream_reasoning_text_deltas_are_captured(self):
        p = _provider("deepseek-v4.1-flash")
        events = [
            _Ev(type="response.reasoning_text.delta", delta="think ", item_id="rs_1"),
            _Ev(type="response.reasoning_text.delta", delta="hard", item_id="rs_1"),
            _Ev(type="response.completed", response=None),
        ]
        p._client = _FakeClient(_stream_events(events))
        async for _ in p._raw_stream_chat([{"role": "user", "content": "q"}]):
            pass
        assert p._last_assistant_extra_fields["reasoning_content"] == "think hard"

    async def test_complete_response_reasoning_item_is_captured(self):
        p = _provider("deepseek-v4.1-flash")

        class _Part:
            type = "summary_text"
            text = "Computed 17*23"

        class _Item:
            type = "reasoning"
            id = "rs_9"
            status = "completed"
            summary = [_Part()]
            content = []

        class _MsgItem:
            type = "message"
            content = []

        response = _Resp(output=[_Item(), _MsgItem()])
        p._client = _FakeClient(response)
        await p._raw_complete_chat([{"role": "user", "content": "q"}])
        assert p._last_assistant_extra_fields["reasoning_summary"] == "Computed 17*23"

    async def test_no_reasoning_leaves_fields_empty(self):
        p = _provider("gpt-5-mini")
        p._client = _FakeClient(
            _stream_events([_Ev(type="response.completed", response=None)])
        )
        async for _ in p._raw_stream_chat([{"role": "user", "content": "q"}]):
            pass
        assert p._last_assistant_extra_fields == {}


class TestReasoningRoundTrip:
    async def test_captured_summary_is_replayed_next_turn(self):
        p = _provider("deepseek-v4.1-flash")
        events = [
            _Ev(type="response.reasoning_summary_text.delta", delta="Chain of thought"),
            _Ev(type="response.output_text.delta", delta="Answer"),
            _Ev(type="response.completed", response=None),
        ]
        p._client = _FakeClient(_stream_events(events))
        async for _ in p._raw_stream_chat([{"role": "user", "content": "q1"}]):
            pass

        history = [
            {"role": "user", "content": "q1"},
            {
                "role": "assistant",
                "content": "Answer",
                **p._last_assistant_extra_fields,
            },
            {"role": "user", "content": "q2"},
        ]
        p._client = _FakeClient(_stream_events([]))
        async for _ in p._raw_stream_chat(history):
            pass
        items = p._client.responses.kwargs["input"]
        assert items[1]["type"] == "reasoning"
        assert items[1]["content"] == [
            {"type": "reasoning_text", "text": "Chain of thought"}
        ]
