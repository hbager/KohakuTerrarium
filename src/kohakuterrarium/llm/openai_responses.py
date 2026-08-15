"""OpenAI Responses API-compatible provider using ordinary API keys.

This backend targets third-party or official endpoints that implement the
OpenAI ``/v1/responses`` schema.  It intentionally differs from
``CodexOAuthProvider``: authentication is a normal Bearer API key and the
``base_url`` is user configurable (for example ``https://atessa.top/v1``).
"""

import asyncio
import hashlib
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from kohakuterrarium.llm.api_keys import KeyPool, get_api_key
from kohakuterrarium.llm.base import (
    BaseLLMProvider,
    ChatResponse,
    LLMConfig,
    NativeToolCall,
    OverflowRecoveryState,
    ToolSchema,
)
from kohakuterrarium.llm.codex_format import fix_tool_call_pairing, to_responses_input
from kohakuterrarium.llm.openai import OPENAI_BASE_URL, ROOCODE_USER_AGENT
from kohakuterrarium.llm.openai_sanitize import strip_kt_extras, strip_surrogates
from kohakuterrarium.llm.recovery import (
    ErrorClass,
    RetryPolicy,
    backoff_delay,
    classify_openai_error,
    drop_last_tool_round,
)
from kohakuterrarium.utils.logging import get_logger

logger = get_logger(__name__)


class OpenAIResponsesProvider(BaseLLMProvider):
    """OpenAI Responses API-compatible provider.

    Uses ``AsyncOpenAI.responses.create`` against ``base_url`` with a regular
    API key.  This is for OpenAI-compatible Responses endpoints, not ChatGPT /
    Codex OAuth.
    """

    def __init__(
        self,
        api_key: str | KeyPool | None = None,
        model: str = "",
        base_url: str = OPENAI_BASE_URL,
        *,
        temperature: float | None = 0.7,
        max_tokens: int | None = None,
        reasoning_effort: str = "",
        service_tier: str | None = None,
        timeout: float = 300.0,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, Any] | None = None,
        max_retries: int = 3,
        retry_policy: RetryPolicy | dict[str, Any] | None = None,
    ):
        super().__init__(
            LLMConfig(
                model=model,
                temperature=temperature if temperature is not None else 0.7,
                max_tokens=max_tokens,
                retry_policy=retry_policy,
            )
        )
        self.model = model
        self.base_url = base_url or OPENAI_BASE_URL
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort or ""
        self.service_tier = service_tier
        self.extra_body = extra_body or {}
        self._retry_policy = RetryPolicy.from_value(retry_policy)
        self._api_key_pool = api_key if isinstance(api_key, KeyPool) else None
        api_key_for_client = api_key.first if isinstance(api_key, KeyPool) else api_key
        self._api_key = api_key_for_client
        self._base_url_input = self.base_url
        self._timeout = timeout
        self._extra_headers = extra_headers or {}
        self._max_retries = max_retries
        self._last_usage: dict[str, int] = {}
        self._last_tool_calls: list[NativeToolCall] = []
        self._last_assistant_parts: list[Any] = []
        self.prompt_cache_key: str | None = None

        if not api_key_for_client:
            raise ValueError(
                "API key is required for OpenAI Responses provider. "
                "Set the backend key via Settings/kt login or its api_key_env."
            )

        self._client = AsyncOpenAI(
            api_key=api_key_for_client,
            base_url=self.base_url,
            timeout=timeout,
            max_retries=max_retries,
            default_headers={"User-Agent": ROOCODE_USER_AGENT, **self._extra_headers},
        )
        logger.debug(
            "OpenAIResponsesProvider initialized",
            model=model,
            base_url=self.base_url,
        )

    async def close(self) -> None:
        await self._client.close()

    def with_model(self, name: str) -> "OpenAIResponsesProvider":
        """Return a sibling provider using the same SDK client."""
        if not name or name == self.config.model:
            return self
        clone = object.__new__(OpenAIResponsesProvider)
        BaseLLMProvider.__init__(
            clone,
            LLMConfig(
                model=name,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                retry_policy=self._retry_policy,
            ),
        )
        clone.model = name
        clone.base_url = self.base_url
        clone.temperature = self.temperature
        clone.max_tokens = self.max_tokens
        clone.reasoning_effort = self.reasoning_effort
        clone.service_tier = self.service_tier
        clone.extra_body = dict(self.extra_body)
        clone._retry_policy = self._retry_policy
        clone._api_key_pool = self._api_key_pool
        clone._api_key = self._api_key
        clone._base_url_input = self._base_url_input
        clone._timeout = self._timeout
        clone._extra_headers = dict(self._extra_headers)
        clone._max_retries = self._max_retries
        clone._last_usage = {}
        clone._last_tool_calls = []
        clone._last_assistant_parts = []
        clone._emergency_drop_callbacks = list(self._emergency_drop_callbacks)
        clone.prompt_cache_key = self.prompt_cache_key
        clone._client = self._client
        clone.provider_name = getattr(self, "provider_name", clone.provider_name)
        clone.provider_native_tools = getattr(
            self, "provider_native_tools", clone.provider_native_tools
        )
        credential_provider = getattr(self, "_credential_provider", "")
        if credential_provider:
            clone._credential_provider = credential_provider
        if hasattr(self, "_profile_max_context"):
            clone._profile_max_context = self._profile_max_context
        return clone

    def reload_credentials(self) -> bool:
        """Re-resolve API key and rebuild SDK client after settings changes."""
        lookup_key = getattr(self, "_credential_provider", "") or self.provider_name
        if not lookup_key:
            return False
        new_key_pool = get_api_key(lookup_key)
        if not new_key_pool:
            return False
        new_key = new_key_pool.first
        old_key = self._api_key_pool.first if self._api_key_pool else self._api_key
        if new_key == old_key and new_key_pool == (
            self._api_key_pool or KeyPool([self._api_key or ""])
        ):
            return False
        old = self._client
        self._api_key_pool = new_key_pool if new_key_pool.is_pool else None
        self._api_key = new_key
        self._client = AsyncOpenAI(
            api_key=new_key,
            base_url=self._base_url_input,
            timeout=self._timeout,
            max_retries=self._max_retries,
            default_headers={"User-Agent": ROOCODE_USER_AGENT, **self._extra_headers},
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(old.close())
        except RuntimeError:
            pass
        logger.info("OpenAIResponsesProvider credentials reloaded", provider=lookup_key)
        return True

    def _apply_request_api_key(self, create_kwargs: dict[str, Any]) -> None:
        """Attach per-request auth headers when a key pool is configured."""
        if not self._api_key_pool:
            return
        key = self._api_key_pool.next()
        if not key:
            return
        headers = dict(create_kwargs.get("extra_headers") or {})
        headers["Authorization"] = f"Bearer {key}"
        create_kwargs["extra_headers"] = headers

    def _api_key_failover_limit(self) -> int:
        return min(5, len(self._api_key_pool.keys)) if self._api_key_pool else 0

    def _should_failover_api_key(self, error_class: ErrorClass, failures: int) -> bool:
        return (
            bool(self._api_key_pool)
            and error_class in {ErrorClass.USER_ERROR, ErrorClass.RATE_LIMIT}
            and failures < self._api_key_failover_limit()
        )

    def _log_api_key_failover(
        self, error_class: ErrorClass, failure_number: int, exc: Exception
    ) -> None:
        logger.warning(
            "provider_api_key_failover",
            attempt=failure_number,
            error_class=error_class.value,
            error=str(exc),
        )

    def _sanitize_extra_body(self, extra: dict[str, Any]) -> dict[str, Any]:
        """Drop KT-internal knobs that are not Responses API fields."""
        return {k: v for k, v in extra.items() if k != "disable_prompt_caching"}

    def _split_instructions(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        instructions: list[str] = []
        input_messages: list[dict[str, Any]] = []
        for msg in messages:
            if msg.get("role") == "system":
                content = msg.get("content", "")
                if isinstance(content, str):
                    instructions.append(content)
                elif isinstance(content, list):
                    text = "\n".join(
                        str(part.get("text", ""))
                        for part in content
                        if isinstance(part, dict) and part.get("type") == "text"
                    )
                    if text:
                        instructions.append(text)
            else:
                input_messages.append(msg)
        return "\n\n".join(part for part in instructions if part), input_messages

    def _build_create_kwargs(
        self,
        messages: list[dict[str, Any]],
        *,
        stream: bool,
        tools: list[ToolSchema] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        cleaned_messages = strip_kt_extras(messages)
        instructions, input_messages = self._split_instructions(cleaned_messages)
        api_input = fix_tool_call_pairing(to_responses_input(input_messages))

        api_tools: list[dict[str, Any]] | None = None
        if tools:
            api_tools = [
                {
                    "type": "function",
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                }
                for t in tools
            ]

        create_kwargs: dict[str, Any] = {
            "model": kwargs.get("model", self.model or self.config.model),
            "input": api_input,
            "store": False,
            "stream": stream,
        }
        if instructions:
            create_kwargs["instructions"] = instructions
        if api_tools:
            create_kwargs["tools"] = api_tools

        temp = kwargs.get("temperature", self.temperature)
        if temp is not None:
            create_kwargs["temperature"] = temp

        max_tok = kwargs.get(
            "max_tokens", kwargs.get("max_output_tokens", self.max_tokens)
        )
        if max_tok is not None:
            create_kwargs["max_output_tokens"] = max_tok

        if "top_p" in kwargs:
            create_kwargs["top_p"] = kwargs["top_p"]

        merged_extra = {**self.extra_body}
        if "extra_body" in kwargs and isinstance(kwargs["extra_body"], dict):
            merged_extra.update(kwargs["extra_body"])
        if "stop" in kwargs:
            # The Responses SDK surface does not expose ``stop`` as a typed
            # parameter. Compatible proxies may still support it, so pass it
            # through the SDK's raw-body extension hook.
            merged_extra["stop"] = kwargs["stop"]
        merged_extra = self._sanitize_extra_body(merged_extra)

        reasoning_effort = kwargs.get("reasoning_effort", self.reasoning_effort)
        if reasoning_effort and reasoning_effort != "none":
            create_kwargs["reasoning"] = {"effort": reasoning_effort}
        service_tier = kwargs.get("service_tier", self.service_tier)
        if service_tier:
            create_kwargs["service_tier"] = service_tier

        if merged_extra:
            create_kwargs["extra_body"] = merged_extra

        cache_key = self.prompt_cache_key
        if not cache_key and instructions:
            cache_key = hashlib.sha256(instructions.encode()).hexdigest()[:32]
        if cache_key:
            create_kwargs.setdefault("prompt_cache_key", cache_key)

        self._apply_request_api_key(create_kwargs)
        logger.debug(
            "OpenAI Responses API request",
            model=create_kwargs["model"],
            input_items=len(api_input),
            stream=stream,
        )
        return create_kwargs

    async def _stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[ToolSchema] | None = None,
        provider_native_tools: list[Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        current = messages
        attempt = 0
        api_key_failures = 0
        overflow_state = OverflowRecoveryState()
        while True:
            try:
                async for chunk in self._raw_stream_chat(
                    current, tools=tools, **kwargs
                ):
                    yield chunk
                return
            except Exception as exc:
                cls = classify_openai_error(exc)
                if cls is ErrorClass.OVERFLOW:
                    replacement = await self._recover_from_overflow(
                        current, overflow_state
                    )
                    if replacement is not None:
                        current = replacement
                        continue
                if cls is not ErrorClass.OVERFLOW:
                    api_key_failures += 1
                    if self._should_failover_api_key(cls, api_key_failures - 1):
                        self._log_api_key_failover(cls, api_key_failures, exc)
                        continue
                    if self._api_key_failover_limit() > 1:
                        raise
                if (
                    cls in self._retry_policy.retry_classes
                    and attempt < self._retry_policy.max_retries
                ):
                    attempt += 1
                    delay = backoff_delay(attempt, self._retry_policy)
                    logger.warning(
                        "provider_retry",
                        attempt=attempt,
                        error_class=cls.value,
                        delay=delay,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

    async def _raw_stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[ToolSchema] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        self._last_tool_calls = []
        self._last_usage = {}
        self._last_assistant_parts = []
        create_kwargs = self._build_create_kwargs(
            messages, stream=True, tools=tools, **kwargs
        )
        stream = await self._client.responses.create(**create_kwargs)
        collected_tool_calls: list[NativeToolCall] = []

        async for event in stream:
            event_type = getattr(event, "type", "")
            if event_type == "response.output_text.delta":
                yield strip_surrogates(getattr(event, "delta", "") or "")
            elif event_type == "response.output_item.done":
                item = getattr(event, "item", None)
                if getattr(item, "type", "") == "function_call":
                    collected_tool_calls.append(
                        NativeToolCall(
                            id=getattr(item, "call_id", "") or "",
                            name=getattr(item, "name", "") or "",
                            arguments=getattr(item, "arguments", "") or "",
                        )
                    )
            elif event_type == "response.completed":
                resp = getattr(event, "response", None)
                self._capture_usage(resp)

        self._last_tool_calls = collected_tool_calls

    async def _complete_chat(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> ChatResponse:
        current = messages
        attempt = 0
        api_key_failures = 0
        overflow_state = OverflowRecoveryState()
        while True:
            try:
                return await self._raw_complete_chat(current, **kwargs)
            except Exception as exc:
                cls = classify_openai_error(exc)
                if cls is ErrorClass.OVERFLOW:
                    replacement = await self._recover_from_overflow(
                        current, overflow_state
                    )
                    if replacement is not None:
                        current = replacement
                        continue
                if cls is not ErrorClass.OVERFLOW:
                    api_key_failures += 1
                    if self._should_failover_api_key(cls, api_key_failures - 1):
                        self._log_api_key_failover(cls, api_key_failures, exc)
                        continue
                    if self._api_key_failover_limit() > 1:
                        raise
                if (
                    cls in self._retry_policy.retry_classes
                    and attempt < self._retry_policy.max_retries
                ):
                    attempt += 1
                    delay = backoff_delay(attempt, self._retry_policy)
                    logger.warning(
                        "provider_retry",
                        attempt=attempt,
                        error_class=cls.value,
                        delay=delay,
                        error=str(exc),
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

    async def _raw_complete_chat(
        self, messages: list[dict[str, Any]], **kwargs: Any
    ) -> ChatResponse:
        self._last_tool_calls = []
        self._last_usage = {}
        self._last_assistant_parts = []
        create_kwargs = self._build_create_kwargs(messages, stream=False, **kwargs)
        response = await self._client.responses.create(**create_kwargs)
        self._capture_usage(response)
        self._capture_tool_calls_from_response(response)
        content = self._response_output_text(response)
        status = getattr(response, "status", None) or "completed"
        model = getattr(response, "model", None) or self.model
        return ChatResponse(
            content=strip_surrogates(content),
            finish_reason=status,
            usage=self._last_usage,
            model=model,
        )

    def _capture_usage(self, response: Any) -> None:
        if response is None:
            return
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        details = getattr(usage, "input_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) if details is not None else 0
        self._last_usage = {
            "prompt_tokens": getattr(usage, "input_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "output_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
            "cached_tokens": cached or 0,
        }

    def _capture_tool_calls_from_response(self, response: Any) -> None:
        calls: list[NativeToolCall] = []
        for item in getattr(response, "output", None) or []:
            if getattr(item, "type", "") != "function_call":
                continue
            calls.append(
                NativeToolCall(
                    id=getattr(item, "call_id", "") or "",
                    name=getattr(item, "name", "") or "",
                    arguments=getattr(item, "arguments", "") or "",
                )
            )
        self._last_tool_calls = calls

    def _response_output_text(self, response: Any) -> str:
        direct = getattr(response, "output_text", None)
        if isinstance(direct, str):
            return direct
        parts: list[str] = []
        for item in getattr(response, "output", None) or []:
            if getattr(item, "type", "") != "message":
                continue
            for content in getattr(item, "content", None) or []:
                ctype = getattr(content, "type", "")
                if ctype in {"output_text", "text"}:
                    text = getattr(content, "text", None)
                    if isinstance(text, str):
                        parts.append(text)
        return "".join(parts)

    async def __aenter__(self) -> "OpenAIResponsesProvider":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
