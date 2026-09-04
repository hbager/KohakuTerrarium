"""
Store provider API keys and resolve them from worker or standalone sources.
"""

import os
import threading
from collections.abc import Callable
from pathlib import Path

import yaml

from kohakuterrarium.utils.config_dir import config_dir
from kohakuterrarium.utils.logging import get_logger

logger = get_logger(__name__)

# Preserve display constants while live I/O resolves the current config root.
KT_DIR = Path.home() / ".kohakuterrarium"
KEYS_PATH = KT_DIR / "api_keys.yaml"


def _keys_path() -> Path:
    """Resolve the API key store against the current configuration root."""
    return config_dir() / "api_keys.yaml"


# Standalone fallback environment variables for built-in providers.
PROVIDER_KEY_MAP: dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "mimo": "MIMO_API_KEY",
    "kimi-code": "KIMI_CODE_API_KEY",
    "glm-coding": "GLM_CODING_API_KEY",
}

# Workers install one synchronous resolver for local and host identity caches.
_resolver: Callable[[str], str] | None = None


def register_api_key_resolver(resolver: Callable[[str], str]) -> None:
    """Install the authoritative synchronous credential resolver used by workers."""
    global _resolver
    _resolver = resolver


def clear_api_key_resolver() -> None:
    """Remove the installed credential resolver if present."""
    global _resolver
    _resolver = None


class KeyPool:
    """Thread-safe round-robin API key pool."""

    def __init__(self, keys: list[str] | tuple[str, ...]):
        self._keys = [str(key) for key in keys if str(key)]
        self._index = 0
        self._lock = threading.Lock()

    def next(self) -> str:
        if not self._keys:
            return ""
        with self._lock:
            key = self._keys[self._index % len(self._keys)]
            self._index += 1
            return key

    @property
    def first(self) -> str:
        return self._keys[0] if self._keys else ""

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._keys)

    @property
    def is_pool(self) -> bool:
        return len(self._keys) > 1

    def __bool__(self) -> bool:
        return bool(self._keys)

    def __str__(self) -> str:
        return self.first

    def __eq__(self, other: object) -> bool:
        if isinstance(other, KeyPool):
            return self.keys == other.keys
        if isinstance(other, str):
            return self.first == other
        return False


def _pool_from_value(value: object) -> KeyPool:
    if isinstance(value, KeyPool):
        return value
    if isinstance(value, (list, tuple)):
        return KeyPool([str(key) for key in value])
    return KeyPool([str(value)]) if value else KeyPool([])


def save_api_key(provider: str, key: str | list[str]) -> None:
    """Save an API key for a provider."""
    path = _keys_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = _load_api_keys()
    keys[provider] = key
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(keys, f, default_flow_style=False)
    logger.info("API key saved", provider=provider)


def get_api_key(provider_or_env: str) -> KeyPool:
    """Resolve a provider key from the worker resolver or standalone file and env."""

    provider = provider_or_env
    for prov, env in PROVIDER_KEY_MAP.items():
        if provider_or_env == env:
            provider = prov
            break

    # Worker mode delegates the complete local/host resolution policy to the resolver.
    if _resolver is not None:
        try:
            key = _resolver(provider)
        except Exception:  # pragma: no cover - resolver failures are external
            logger.exception("api-key resolver raised; treating as miss")
            key = ""
        if key:
            return _pool_from_value(key)
        # Resolver misses are terminal so credentials never leak from another source.
        logger.warning(
            "api-key resolver returned empty; set the key on this "
            "worker (KT_CONFIG_DIR/api_keys.yaml) OR on the host "
            "identity store (POST /api/settings/keys)",
            provider=provider,
        )
        return KeyPool([])

    # Standalone resolution prefers the persisted key over environment fallbacks.
    keys = _load_api_keys()
    if provider in keys and keys[provider]:
        return _pool_from_value(keys[provider])
    env_var = PROVIDER_KEY_MAP.get(provider, provider_or_env)
    key = os.environ.get(env_var, "")
    if key:
        return KeyPool([key])
    if provider_or_env != env_var:
        key = os.environ.get(provider_or_env, "")
    return KeyPool([key]) if key else KeyPool([])


def get_api_key_str(provider_or_env: str) -> str:
    """Return the first key for legacy string consumers."""
    return get_api_key(provider_or_env).first


def has_api_key(provider_or_env: str) -> bool:
    """Check credential availability without logging resolver misses."""
    provider = provider_or_env
    for prov, env in PROVIDER_KEY_MAP.items():
        if provider_or_env == env:
            provider = prov
            break
    if _resolver is not None:
        try:
            return bool(_resolver(provider))
        except Exception:  # pragma: no cover - resolver failures are external
            return False
    keys = _load_api_keys()
    if keys.get(provider):
        return True
    env_var = PROVIDER_KEY_MAP.get(provider, provider_or_env)
    return bool(os.environ.get(env_var, ""))


def list_api_keys() -> dict[str, str]:
    """List stored API keys (masked)."""
    keys = _load_api_keys()
    masked = {}
    for provider, key in keys.items():
        if isinstance(key, list):
            masked_parts = [
                f"{item[:4]}...{item[-4:]}" if len(item) > 8 else "****"
                for item in key
                if item
            ]
            if masked_parts:
                masked[provider] = ", ".join(masked_parts)
        elif key and len(key) > 8:
            masked[provider] = f"{key[:4]}...{key[-4:]}"
        elif key:
            masked[provider] = "****"
    return masked


def _load_api_keys() -> dict[str, str | list[str]]:
    """Load API keys from file."""
    path = _keys_path()
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning("Failed to load API keys file", error=str(e), exc_info=True)
        return {}
