"""
API key storage and retrieval.

Keys are stored in ~/.kohakuterrarium/api_keys.yaml
Format:
  {
    openrouter: "sk-or-...",
    openai: "sk-...",
    anthropic: "sk-ant-...",
    gemini: "AI...",
    kimi-code: "sk-...",
    glm-coding: "...",
  }

Values can be a single string or a list of strings for round-robin key pools.

Resolution order in :func:`get_api_key`:

1. **Registered resolver** (see :func:`register_api_key_resolver`).
   Lab workers install a resolver that reads from a pre-populated
   :class:`IdentityCache`, so worker creatures making LLM calls
   transparently route through the controller's host-canonical
   identity store. Standalone Studio never registers one and falls
   straight through to the local file.
2. Stored key in ``~/.kohakuterrarium/api_keys.yaml``.
3. Environment variable.
4. Empty :class:`KeyPool` (not found).
"""

import os
import threading
from collections.abc import Callable
from pathlib import Path

import yaml

from kohakuterrarium.utils.config_dir import config_dir
from kohakuterrarium.utils.logging import get_logger

logger = get_logger(__name__)

# Import-time defaults — kept for back-compat with callers that import
# these names for *display* (``cli/identity_keys.py``, the studio
# identity routes). The actual read / write paths go through
# :func:`_keys_path`, which resolves ``config_dir()`` fresh on every
# call so ``KT_CONFIG_DIR`` (test isolation, operator re-homing) always
# wins — a module constant computed once at import would not.
KT_DIR = Path.home() / ".kohakuterrarium"
KEYS_PATH = KT_DIR / "api_keys.yaml"


def _keys_path() -> Path:
    """The live ``api_keys.yaml`` path, honouring ``KT_CONFIG_DIR``."""
    return config_dir() / "api_keys.yaml"


# Maps provider short names to env var names (for fallback)
PROVIDER_KEY_MAP: dict[str, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "mimo": "MIMO_API_KEY",
    "kimi-code": "KIMI_CODE_API_KEY",
    "glm-coding": "GLM_CODING_API_KEY",
}

# Process-wide sync resolver hook. ``Callable[[str], str]`` — given a
# provider name (already normalised), returns a key or ``""``. Set by
# :func:`register_api_key_resolver` and cleared by
# :func:`clear_api_key_resolver`. Single slot: each process has at
# most one active resolver (workers install one; the host doesn't).
_resolver: Callable[[str], str] | None = None


def register_api_key_resolver(resolver: Callable[[str], str]) -> None:
    """Install a sync resolver consulted before the file/env fallback.

    Designed for the worker side of multi-node mode: the worker
    pre-fetches keys via :class:`IdentityCache` at spawn time, then
    registers a resolver that does a sync dict lookup. See
    :class:`kohakuterrarium.laboratory.identity_cache.IdentityCache`.
    """
    global _resolver
    _resolver = resolver


def clear_api_key_resolver() -> None:
    """Remove any installed resolver. Idempotent."""
    global _resolver
    _resolver = None


class KeyPool:
    """Thread-safe round-robin API key pool.

    Compares equal to a string by its first key so legacy tests and old
    call sites that expected ``get_api_key(...) == "sk-..."`` continue
    to behave while newer providers can rotate across multiple keys.
    """

    def __init__(self, keys: list[str] | tuple[str, ...]):
        self._keys = [str(k) for k in keys if str(k)]
        self._index = 0
        self._lock = threading.Lock()

    def next(self) -> str:
        """Return the next key using round-robin order."""
        if not self._keys:
            return ""
        with self._lock:
            key = self._keys[self._index % len(self._keys)]
            self._index += 1
            return key

    @property
    def first(self) -> str:
        """Return the first key for backward-compatible call sites."""
        return self._keys[0] if self._keys else ""

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(self._keys)

    @property
    def is_pool(self) -> bool:
        """Whether this pool contains multiple keys."""
        return len(self._keys) > 1

    def __bool__(self) -> bool:
        return bool(self._keys)

    def __len__(self) -> int:
        return len(self._keys)

    def __str__(self) -> str:
        return self.first

    def __repr__(self) -> str:
        return repr(self.first)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, KeyPool):
            return self.keys == other.keys
        if isinstance(other, str):
            return self.first == other
        if isinstance(other, (list, tuple)):
            return self.keys == tuple(str(k) for k in other if str(k))
        return False


def _pool_from_value(value: object) -> KeyPool:
    if isinstance(value, KeyPool):
        return value
    if isinstance(value, list):
        return KeyPool([str(k) for k in value if str(k)])
    if isinstance(value, tuple):
        return KeyPool([str(k) for k in value if str(k)])
    if isinstance(value, str):
        return KeyPool([value]) if value else KeyPool([])
    return KeyPool([str(value)]) if value else KeyPool([])


def _serializable_key_value(key: str | list[str]) -> str | list[str]:
    if isinstance(key, list):
        values = [str(item).strip() for item in key if str(item).strip()]
        if not values:
            return ""
        return values if len(values) > 1 else values[0]
    return key


def save_api_key(provider: str, key: str | list[str]) -> None:
    """Save an API key or key pool for a provider."""
    path = _keys_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = _load_api_keys()
    keys[provider] = _serializable_key_value(key)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(keys, f, default_flow_style=False)
    logger.info("API key saved", provider=provider)


def get_api_key(provider_or_env: str) -> KeyPool:
    """Get an API key pool by provider name or env var name.

    Resolution order:
      0. Registered resolver (lab worker → IdentityCache). When a
         resolver is installed (worker mode), this is the authoritative
         source — falling through to the worker's local file / env on
         a resolver miss would silently leak whatever credentials the
         worker operator happens to have locally and violate the
         host-canonical identity design. So: resolver miss in worker
         mode returns an empty KeyPool immediately.
      1. Stored key in ~/.kohakuterrarium/api_keys.yaml (standalone /
         no-resolver only).
      2. Environment variable (standalone / no-resolver only).
      3. Empty KeyPool (not found).
    """
    provider = provider_or_env
    for prov, env in PROVIDER_KEY_MAP.items():
        if provider_or_env == env:
            provider = prov
            break

    if _resolver is not None:
        try:
            key = _resolver(provider)
        except Exception:  # pragma: no cover - defensive
            logger.exception("api-key resolver raised; treating as miss")
            key = ""
        if key:
            return _pool_from_value(key)
        logger.warning(
            "api-key resolver returned empty; set the key on this "
            "worker (KT_CONFIG_DIR/api_keys.yaml) OR on the host "
            "identity store (POST /api/settings/keys)",
            provider=provider,
        )
        return KeyPool([])

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
    """Get the first API key as a plain string for legacy call sites."""
    return get_api_key(provider_or_env).first


def list_api_keys() -> dict[str, str]:
    """List stored API keys (masked)."""
    keys = _load_api_keys()
    masked = {}
    for provider, key in keys.items():
        if isinstance(key, list):
            parts = []
            for item in key:
                if item and len(item) > 8:
                    parts.append(f"{item[:4]}...{item[-4:]}")
                elif item:
                    parts.append("****")
            if parts:
                masked[provider] = ", ".join(parts)
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
