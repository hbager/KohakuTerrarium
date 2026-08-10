"""
LLM Provider protocol and base types.

Defines the interface that all LLM providers must implement.
The interface is OpenAI API-oriented for consistency.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Protocol, runtime_checkable

from kohakuterrarium.errors import EmptyLLMResponseError
from kohakuterrarium.llm.message import Message
from kohakuterrarium.llm.recovery import ErrorClass, RetryPolicy, backoff_delay
from kohakuterrarium.utils.logging import get_logger

logger = get_logger(__name__)

API_KEY_FAILOVER_LIMIT = 5


@dataclass
class LLMConfig:
    """
    Configuration for an LLM provider.

    Attributes:
        model: Model identifier (e.g., "gpt-4o-mini", "claude-3-opus")
        temperature: Sampling temperature (0.0 to 2.0)
        max_tokens: Maximum tokens to generate
        top_p: Nucleus sampling parameter
        stop: Stop sequences
        extra: Provider-specific extra parameters
    """

    model: str
    temperature: float = 0.7
    max_tokens: int | None = None
    top_p: float = 1.0
    stop: list[str] | None = None
    extra: dict[str, Any] | None = None
    retry_policy: RetryPolicy | dict[str, Any] | None = None


@dataclass
class ChatChunk:
    """
    A chunk from a streaming chat response.

    Attributes:
        content: The text content of this chunk
        finish_reason: If this is the final chunk, the reason for finishing
        usage: Token usage info (usually only in final chunk)
    """

    content: str = ""
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


@dataclass
class ChatResponse:
    """
    Complete chat response (for non-streaming).

    Attributes:
        content: The full response text
        finish_reason: Reason for stopping generation
        usage: Token usage statistics
        model: Model that generated the response
    """

    content: str
    finish_reason: str
    usage: dict[str, int]
    model: str


@dataclass
class ToolSchema:
    """
    OpenAI-compatible tool schema for native function calling.

    Attributes:
        name: Tool function name
        description: Description of what the tool does
        parameters: JSON Schema for the function parameters
    """

    name: str
    description: str
    parameters: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {},
        }
    )

    def to_api_format(self) -> dict[str, Any]:
        """Convert to OpenAI API tools format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class NativeToolCall:
    """
    A tool call returned by the API (not parsed from text).

    Attributes:
        id: Unique tool call ID assigned by the API
        name: Function name to call
        arguments: JSON string of arguments
    """

    id: str
    name: str
    arguments: str  # JSON string of arguments

    def parsed_arguments(self) -> dict[str, Any]:
        """Parse the JSON arguments string."""
        try:
            return json.loads(self.arguments)
        except json.JSONDecodeError:
            logger.warning(
                "Failed to parse tool call arguments",
                tool_call_id=self.id,
                tool_name=self.name,
            )
            return {"_raw": self.arguments}


@runtime_checkable
class LLMProvider(Protocol):
    """
    Protocol for LLM providers.

    All LLM implementations must follow this interface.
    The interface is OpenAI API-oriented but can wrap other providers.
    """

    @property
    def last_tool_calls(self) -> list[NativeToolCall]:
        """
        Tool calls from the last streaming response (native mode only).

        Only populated after a chat() call with tools provided.
        """
        ...

    async def chat(
        self,
        messages: list[Message] | list[dict[str, Any]],
        *,
        stream: bool = True,
        tools: list[ToolSchema] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """
        Send a chat request to the LLM.

        Args:
            messages: List of conversation messages (Message objects or dicts)
            stream: Whether to stream the response
            tools: Optional list of ToolSchema for native function calling
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Yields:
            Text chunks as they arrive (if streaming)

        Returns:
            Full response text (if not streaming, via single yield)

        Usage:
            # Streaming
            async for chunk in provider.chat(messages, stream=True):
                print(chunk, end="")

            # Non-streaming
            async for response in provider.chat(messages, stream=False):
                full_text = response

            # With native tool calling
            async for chunk in provider.chat(messages, tools=schemas):
                print(chunk, end="")
            tool_calls = provider.last_tool_calls
        """
        ...

    async def chat_complete(
        self,
        messages: list[Message] | list[dict[str, Any]],
        **kwargs: Any,
    ) -> ChatResponse:
        """
        Send a chat request and get complete response.

        Non-streaming convenience method.

        Args:
            messages: List of conversation messages
            **kwargs: Additional parameters

        Returns:
            Complete ChatResponse with content and metadata
        """
        ...

    def reload_credentials(self) -> bool:
        """Re-resolve API credentials + rebuild the SDK client.

        Returns ``True`` when the credential rotated. See
        :meth:`BaseLLMProvider.reload_credentials` for the default
        (no-op) implementation.
        """
        ...


class BaseLLMProvider:
    """
    Base class for LLM providers with common utilities.

    Provides default implementations and helper methods.
    Subclasses should implement _stream_chat and _complete_chat.
    """

    # Canonical short name used by provider-native tools to declare
    # compatibility. Subclasses override (e.g. ``"codex"``, ``"openai"``).
    # Empty string means "this provider does not support any
    # provider-native tools" — the agent-start validator treats an
    # empty value as non-matching.
    provider_name: str = ""

    # Names (as registered in the builtin tool catalog) of provider-
    # native tools this provider can serve. These are **opt-out** —
    # at agent start the mixin auto-registers every entry in this
    # set unless the creature's ``disable_provider_tools`` list names
    # it. Subclasses override (e.g. Codex sets ``{"image_gen"}``).
    provider_native_tools: frozenset[str] = frozenset()

    def __init__(self, config: LLMConfig | None = None):
        self.config = config or LLMConfig(model="")
        self._last_tool_calls: list[NativeToolCall] = []
        self._emergency_drop_callbacks: list[Callable[[list[dict[str, Any]]], None]] = (
            []
        )

    @property
    def last_tool_calls(self) -> list[NativeToolCall]:
        """Tool calls from the last streaming response (native mode only)."""
        return self._last_tool_calls

    @property
    def last_usage(self) -> dict[str, int]:
        """Token usage from the last completion call.

        Returns dict with prompt_tokens, completion_tokens, total_tokens
        (keys depend on provider). Empty dict if not available.
        """
        return getattr(self, "_last_usage", {})

    @property
    def last_assistant_content_parts(self) -> list[Any] | None:
        """Structured assistant content parts from the last turn.

        Returns a list of ``ContentPart`` instances (text + images +
        anything else the provider chose to surface) when the provider
        emitted non-text output during the last stream. Returns ``None``
        when the turn was text-only — the controller then falls back
        to the accumulated text delta path.

        Providers override by storing parts on an instance attribute
        during stream handling. The base class returns ``None`` so
        text-only providers need zero changes.
        """
        return getattr(self, "_last_assistant_parts", None) or None

    @property
    def last_assistant_extra_fields(self) -> dict[str, Any]:
        """Non-standard fields captured off the last assistant message.

        Holds provider-specific top-level keys like ``reasoning_content``
        (DeepSeek / Qwen / Grok), ``reasoning_details`` (OpenRouter /
        MiMo), or anything else the backend appends to the assistant
        message. The controller attaches these to the conversation so
        they round-trip back into the outgoing wire format on the next
        turn — required for stateful-chain reasoning models.

        Providers populate ``self._last_assistant_extra_fields`` during
        stream / complete handling. The base property returns ``{}``
        so providers that don't capture anything stay a no-op.
        """
        return getattr(self, "_last_assistant_extra_fields", {}) or {}

    def reload_credentials(self) -> bool:
        """Re-resolve the API key from the launcher's resolver + rebuild
        the underlying SDK client. Default: no-op.

        Subclasses that hold a cached SDK client built around a baked-in
        API key (``OpenAIProvider``, ``AnthropicProvider``) override
        this to handle live key updates from the frontend's provider
        page. Returns ``True`` when the credential actually rotated;
        ``False`` when unchanged, unresolvable, or not applicable to
        this provider class (Codex OAuth, FakeLLM, etc.).

        Engine fan-out on key save calls this on every live agent's
        provider — the next chat request then uses the new credential
        with no creature restart.
        """
        return False

    def _api_key_failover_limit(self) -> int:
        pool = getattr(self, "_api_key_pool", None)
        if not pool or not getattr(pool, "is_pool", False):
            return 1
        return min(len(pool), API_KEY_FAILOVER_LIMIT)

    def _should_failover_api_key(
        self, error_class: ErrorClass, failed_keys: int
    ) -> bool:
        return (
            error_class is not ErrorClass.OVERFLOW
            and failed_keys < self._api_key_failover_limit() - 1
        )

    def _log_api_key_failover(
        self, error_class: ErrorClass, failed_keys: int, error: BaseException
    ) -> None:
        logger.warning(
            "provider_api_key_failover",
            failed_keys=failed_keys,
            max_keys=self._api_key_failover_limit(),
            error_class=error_class.value,
            error=str(error),
        )

    def translate_provider_native_tool(self, tool: Any) -> dict | None:
        """Translate a KT provider-native tool into a wire-format tool spec.

        Return a dict that the provider can insert directly into the
        outbound API ``tools`` list (in place of the normal
        ``{"type":"function",...}`` block), or ``None`` if this
        provider does not support the given tool. The base default is
        ``None`` — every existing provider keeps shipping only
        function tools until it opts in.
        """
        return None

    def on_emergency_drop(
        self, callback: Callable[[list[dict[str, Any]]], None]
    ) -> None:
        """Register a callback invoked with recovered messages after a drop."""
        self._emergency_drop_callbacks.append(callback)

    def _notify_emergency_drop(self, messages: list[dict[str, Any]]) -> None:
        """Notify callbacks that provider-side recovery changed context."""
        for callback in list(self._emergency_drop_callbacks):
            try:
                callback(messages)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Emergency-drop callback failed", error=str(exc), exc_info=True
                )

    def with_model(self, name: str) -> "BaseLLMProvider":
        """Return a sibling provider configured for ``name``.

        Providers with external clients should override this to preserve
        connection pools. The base implementation only supports no-op reuse.
        """
        if not name or name == self.config.model:
            return self
        raise ValueError(f"Provider {type(self).__name__} cannot switch to {name}")

    def _normalize_messages(
        self,
        messages: list[Message] | list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Convert messages to API format."""
        if not messages:
            return []

        # Check if already dicts
        if isinstance(messages[0], dict):
            return messages  # type: ignore

        # Convert Message objects to dicts
        return [msg.to_dict() for msg in messages]  # type: ignore

    async def chat(
        self,
        messages: list[Message] | list[dict[str, Any]],
        *,
        stream: bool = True,
        tools: list[ToolSchema] | None = None,
        provider_native_tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Delegate to the provider and retry successful-but-empty responses."""
        self._last_tool_calls = []
        normalized = self._normalize_messages(messages)

        if stream:
            async for chunk in self._stream_chat_with_empty_retry(
                normalized,
                tools=tools,
                provider_native_tools=provider_native_tools,
                **kwargs,
            ):
                yield chunk
        else:
            response = await self._complete_chat_with_empty_retry(normalized, **kwargs)
            yield response.content

    async def chat_complete(
        self,
        messages: list[Message] | list[dict[str, Any]],
        **kwargs: Any,
    ) -> ChatResponse:
        """Default complete implementation (with empty-response retry)."""
        normalized = self._normalize_messages(messages)
        return await self._complete_chat_with_empty_retry(normalized, **kwargs)

    def _effective_retry_policy(self) -> RetryPolicy:
        """Return the provider policy, falling back to config defaults."""
        policy = getattr(self, "_retry_policy", None)
        if isinstance(policy, RetryPolicy):
            return policy
        return RetryPolicy.from_value(self.config.retry_policy)

    def _reset_attempt_state(self) -> None:
        """Clear result state that could mask or contaminate an attempt."""
        self._last_tool_calls = []
        self._last_usage = {}
        self._last_assistant_parts = []
        self._last_assistant_extra_fields = {}

    def _has_presentable_parts(self) -> bool:
        """Return whether structured parts contain visible output."""
        parts = self.last_assistant_content_parts
        if not parts:
            return False
        for part in parts:
            if getattr(part, "type", "") == "text":
                text = getattr(part, "text", "")
                if text and str(text).strip():
                    return True
            else:
                return True  # image / file / unknown non-text part
        return False

    def _is_empty_response(self, content: str) -> bool:
        """Return whether an attempt produced no visible output or tool call."""
        if (content or "").strip():
            return False
        if getattr(self, "_last_tool_calls", None):
            return False
        if self._has_presentable_parts():
            return False
        return True

    async def _stream_chat_with_empty_retry(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[ToolSchema] | None = None,
        provider_native_tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Retry streams that finish without presentable output."""
        policy = self._effective_retry_policy()
        attempt = 0
        while True:
            self._reset_attempt_state()
            pending_chunks: list[str] = []
            saw_text = False
            async for chunk in self._stream_chat(
                messages,
                tools=tools,
                provider_native_tools=provider_native_tools,
                **kwargs,
            ):
                if saw_text:
                    yield chunk
                    continue
                pending_chunks.append(chunk)
                if chunk and str(chunk).strip():
                    saw_text = True
                    for pending_chunk in pending_chunks:
                        yield pending_chunk
            # Provider state now reflects this completed attempt.
            if saw_text or not self._is_empty_response(""):
                return
            # Empty responses use the TRANSIENT retry policy.
            if (
                ErrorClass.TRANSIENT not in policy.retry_classes
                or attempt >= policy.max_retries
            ):
                raise EmptyLLMResponseError(
                    f"{type(self).__name__} returned an empty response after "
                    f"{attempt + 1} attempt(s)"
                )
            attempt += 1
            delay = backoff_delay(attempt, policy)
            logger.warning(
                "provider_empty_response_retry",
                attempt=attempt,
                max_retries=policy.max_retries,
                delay=delay,
            )
            await asyncio.sleep(delay)

    async def _complete_chat_with_empty_retry(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ChatResponse:
        """Non-streaming completion with empty-response retry."""
        policy = self._effective_retry_policy()
        attempt = 0
        while True:
            self._reset_attempt_state()
            response = await self._complete_chat(messages, **kwargs)
            if not self._is_empty_response(response.content):
                return response
            if (
                ErrorClass.TRANSIENT not in policy.retry_classes
                or attempt >= policy.max_retries
            ):
                raise EmptyLLMResponseError(
                    f"{type(self).__name__} returned an empty response after "
                    f"{attempt + 1} attempt(s)"
                )
            attempt += 1
            delay = backoff_delay(attempt, policy)
            logger.warning(
                "provider_empty_response_retry",
                attempt=attempt,
                max_retries=policy.max_retries,
                delay=delay,
            )
            await asyncio.sleep(delay)

    async def _stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[ToolSchema] | None = None,
        provider_native_tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """
        Stream chat implementation. Must be overridden by subclass.

        Subclasses that don't support provider-native tools can simply
        ignore the ``provider_native_tools`` argument — the base
        signature accepts it for compatibility.
        """
        raise NotImplementedError("Subclass must implement _stream_chat")
        yield  # Make this a generator

    async def _complete_chat(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> ChatResponse:
        """
        Complete chat implementation. Must be overridden by subclass.
        """
        raise NotImplementedError("Subclass must implement _complete_chat")
