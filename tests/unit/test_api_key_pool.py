import pytest

from kohakuterrarium.llm import api_keys
from kohakuterrarium.llm.api_keys import KeyPool
from kohakuterrarium.llm.litellm_provider import LiteLLMProvider
from kohakuterrarium.llm.openai import OpenAIProvider
from kohakuterrarium.llm.openai_responses import OpenAIResponsesProvider


class _StatusError(Exception):
    def __init__(self, status_code: int):
        super().__init__(f"HTTP {status_code}")
        self.status_code = status_code


def test_key_pool_round_robin():
    pool = KeyPool(["k1", "k2"])

    assert pool.first == "k1"
    assert pool.next() == "k1"
    assert pool.next() == "k2"
    assert pool.next() == "k1"


def test_get_api_key_loads_yaml_list_as_pool(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.yaml"
    path.write_text("openai:\n  - sk-one\n  - sk-two\n", encoding="utf-8")
    monkeypatch.setenv("KT_CONFIG_DIR", str(tmp_path))

    pool = api_keys.get_api_key("openai")

    assert isinstance(pool, KeyPool)
    assert pool.next() == "sk-one"
    assert pool.next() == "sk-two"


def test_list_api_keys_masks_key_lists(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.yaml"
    path.write_text("openai:\n  - sk-abcdef1234\n  - sk-ghijkl5678\n", encoding="utf-8")
    monkeypatch.setenv("KT_CONFIG_DIR", str(tmp_path))

    assert api_keys.list_api_keys()["openai"] == "sk-a...1234, sk-g...5678"


def test_openai_provider_applies_rotating_authorization_header():
    provider = OpenAIProvider(api_key=KeyPool(["k1", "k2"]), model="gpt-test")
    first: dict = {}
    second: dict = {}

    provider._apply_request_api_key(first)
    provider._apply_request_api_key(second)

    assert first["extra_headers"]["Authorization"] == "Bearer k1"
    assert second["extra_headers"]["Authorization"] == "Bearer k2"


def test_openai_responses_provider_omits_codex_session_id_header():
    provider = OpenAIResponsesProvider(api_key="k1", model="gpt-test")
    provider.prompt_cache_key = "cache-key"

    create_kwargs = provider._build_create_kwargs(
        [{"role": "user", "content": "hi"}],
        stream=True,
    )

    assert create_kwargs["prompt_cache_key"] == "cache-key"
    assert "extra_headers" not in create_kwargs


@pytest.mark.asyncio
async def test_openai_provider_user_error_failover_stops_after_five_keys():
    provider = OpenAIProvider(
        api_key=KeyPool(["k1", "k2", "k3", "k4", "k5", "k6"]),
        model="gpt-test",
    )
    seen_keys: list[str] = []

    async def always_unauthorized(messages):
        create_kwargs: dict = {}
        provider._apply_request_api_key(create_kwargs)
        seen_keys.append(create_kwargs["extra_headers"]["Authorization"])
        raise _StatusError(401)

    provider._raw_complete_chat = always_unauthorized

    with pytest.raises(_StatusError):
        await provider._complete_chat([])

    assert seen_keys == [
        "Bearer k1",
        "Bearer k2",
        "Bearer k3",
        "Bearer k4",
        "Bearer k5",
    ]

    next_request: dict = {}
    provider._apply_request_api_key(next_request)
    assert next_request["extra_headers"]["Authorization"] == "Bearer k6"


@pytest.mark.asyncio
async def test_openai_provider_rate_limit_failover_stops_after_five_keys(monkeypatch):
    provider = OpenAIProvider(
        api_key=KeyPool(["k1", "k2", "k3", "k4", "k5", "k6"]),
        model="gpt-test",
        retry_policy={"base_delay": 0, "jitter": 0, "max_retries": 20},
    )
    seen_keys: list[str] = []
    sleeps: list[float] = []

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("kohakuterrarium.llm.openai.asyncio.sleep", fake_sleep)

    async def always_rate_limited(messages):
        create_kwargs: dict = {}
        provider._apply_request_api_key(create_kwargs)
        seen_keys.append(create_kwargs["extra_headers"]["Authorization"])
        raise _StatusError(429)

    provider._raw_complete_chat = always_rate_limited

    with pytest.raises(_StatusError):
        await provider._complete_chat([])

    assert seen_keys == [
        "Bearer k1",
        "Bearer k2",
        "Bearer k3",
        "Bearer k4",
        "Bearer k5",
    ]
    assert sleeps == []

    next_request: dict = {}
    provider._apply_request_api_key(next_request)
    assert next_request["extra_headers"]["Authorization"] == "Bearer k6"


@pytest.mark.asyncio
async def test_openai_provider_user_error_failover_returns_when_later_key_succeeds():
    provider = OpenAIProvider(api_key=KeyPool(["k1", "k2", "k3"]), model="gpt-test")
    seen_keys: list[str] = []

    async def succeeds_on_third_key(messages):
        create_kwargs: dict = {}
        provider._apply_request_api_key(create_kwargs)
        key = create_kwargs["extra_headers"]["Authorization"]
        seen_keys.append(key)
        if key != "Bearer k3":
            raise _StatusError(403)
        return "ok"

    provider._raw_complete_chat = succeeds_on_third_key

    assert await provider._complete_chat([]) == "ok"
    assert seen_keys == ["Bearer k1", "Bearer k2", "Bearer k3"]


def test_litellm_provider_rotates_api_key_in_params():
    provider = LiteLLMProvider(model="openai/gpt-test", api_key=KeyPool(["k1", "k2"]))

    first = provider._build_params([], stream=False)
    second = provider._build_params([], stream=False)

    assert first["api_key"] == "k1"
    assert second["api_key"] == "k2"


def test_litellm_provider_with_model_preserves_rotating_key_pool():
    provider = LiteLLMProvider(model="openai/gpt-test", api_key=KeyPool(["k1", "k2"]))

    clone = provider.with_model("openai/gpt-other")

    first = clone._build_params([], stream=False)
    second = clone._build_params([], stream=False)

    assert first["api_key"] == "k1"
    assert second["api_key"] == "k2"


def test_studio_set_key_normalizes_comma_separated_pool(monkeypatch):
    from kohakuterrarium.studio.identity import api_keys as studio_api_keys

    saved = {}
    monkeypatch.setattr(studio_api_keys, "load_backends", lambda: {"openai": object()})
    monkeypatch.setattr(
        studio_api_keys,
        "save_api_key",
        lambda provider, key: saved.update(provider=provider, key=key),
    )

    studio_api_keys.set_key("openai", "sk-one, sk-two")

    assert saved == {"provider": "openai", "key": ["sk-one", "sk-two"]}
