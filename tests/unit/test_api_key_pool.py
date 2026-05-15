from kohakuterrarium.llm import api_keys
from kohakuterrarium.llm.api_keys import KeyPool
from kohakuterrarium.llm.openai import OpenAIProvider
from kohakuterrarium.llm.litellm_provider import LiteLLMProvider


def test_key_pool_round_robin():
    pool = KeyPool(["k1", "k2"])

    assert pool.first == "k1"
    assert pool.next() == "k1"
    assert pool.next() == "k2"
    assert pool.next() == "k1"


def test_get_api_key_loads_yaml_list_as_pool(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.yaml"
    path.write_text("openai:\n  - sk-one\n  - sk-two\n", encoding="utf-8")
    monkeypatch.setattr(api_keys, "KEYS_PATH", path)

    pool = api_keys.get_api_key("openai")

    assert isinstance(pool, KeyPool)
    assert pool.next() == "sk-one"
    assert pool.next() == "sk-two"


def test_list_api_keys_masks_key_lists(tmp_path, monkeypatch):
    path = tmp_path / "api_keys.yaml"
    path.write_text("openai:\n  - sk-abcdef1234\n  - sk-ghijkl5678\n", encoding="utf-8")
    monkeypatch.setattr(api_keys, "KEYS_PATH", path)

    assert api_keys.list_api_keys()["openai"] == "sk-a...1234, sk-g...5678"


def test_openai_provider_applies_rotating_authorization_header():
    provider = OpenAIProvider(api_key=KeyPool(["k1", "k2"]), model="gpt-test")
    first: dict = {}
    second: dict = {}

    provider._apply_request_api_key(first)
    provider._apply_request_api_key(second)

    assert first["extra_headers"]["Authorization"] == "Bearer k1"
    assert second["extra_headers"]["Authorization"] == "Bearer k2"


def test_litellm_provider_rotates_api_key_in_params():
    provider = LiteLLMProvider(model="openai/gpt-test", api_key=KeyPool(["k1", "k2"]))

    first = provider._build_params([], stream=False)
    second = provider._build_params([], stream=False)

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
