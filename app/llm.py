from __future__ import annotations

import json
import os
import re
import time
from app.debug import debug
import urllib.error
import urllib.request


class LLMTemporaryError(RuntimeError):
    pass


def parse_json_value(raw: str):
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for pattern in (r"\{.*\}", r"\[.*\]"):
        match = re.search(pattern, text, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
    return None


class LLMClient:
    def __init__(self, base_url: str, model: str, timeout_seconds: int, default_max_tokens: int):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.default_max_tokens = default_max_tokens

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
        operation: str = "generic",
    ):
        key = os.getenv("NVIDIA_API_KEY", "").strip()
        if not key:
            raise LLMTemporaryError("NVIDIA_API_KEY is missing")
    
        effective_max_tokens = max_tokens or self.default_max_tokens
    
        payload = json.dumps({
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.2,
            "top_p": 0.95,
            "max_tokens": effective_max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode("utf-8")
    
        debug(
            "LLM_START",
            operation=operation,
            model=self.model,
            timeout_seconds=self.timeout_seconds,
            max_tokens=effective_max_tokens,
            system_chars=len(system_prompt),
            user_chars=len(user_prompt),
            payload_bytes=len(payload),
        )
    
        max_attempts = 2
        last: Exception | None = None
        overall_started = time.monotonic()
    
        for attempt in range(max_attempts):
            attempt_started = time.monotonic()
    
            debug(
                "LLM_ATTEMPT_START",
                operation=operation,
                attempt=f"{attempt + 1}/{max_attempts}",
            )
    
            request = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
    
            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout_seconds,
                ) as response:
                    body = response.read().decode("utf-8")
    
                    debug(
                        "LLM_HTTP_RESPONSE",
                        operation=operation,
                        attempt=f"{attempt + 1}/{max_attempts}",
                        status=response.status,
                        elapsed_seconds=round(time.monotonic() - attempt_started, 2),
                        response_chars=len(body),
                    )
    
                try:
                    obj = json.loads(body)
                except json.JSONDecodeError as exc:
                    debug(
                        "LLM_OUTER_JSON_ERROR",
                        operation=operation,
                        attempt=f"{attempt + 1}/{max_attempts}",
                        elapsed_seconds=round(time.monotonic() - attempt_started, 2),
                        response_chars=len(body),
                    )
                    raise LLMTemporaryError("LLM HTTP response was not valid JSON") from exc
    
                content = (
                    obj.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
    
                debug(
                    "LLM_CONTENT_RECEIVED",
                    operation=operation,
                    attempt=f"{attempt + 1}/{max_attempts}",
                    content_chars=len(content),
                    content_first_char=(content.strip()[:1] if content else ""),
                )
    
                parsed = parse_json_value(content)
    
                debug(
                    "LLM_JSON_PARSE",
                    operation=operation,
                    attempt=f"{attempt + 1}/{max_attempts}",
                    ok=parsed is not None,
                    parsed_type=type(parsed).__name__ if parsed is not None else "None",
                )
    
                if parsed is None:
                    raise LLMTemporaryError("LLM returned invalid JSON")
    
                debug(
                    "LLM_SUCCESS",
                    operation=operation,
                    attempt=f"{attempt + 1}/{max_attempts}",
                    elapsed_seconds=round(time.monotonic() - overall_started, 2),
                )
    
                return parsed
    
            except urllib.error.HTTPError as exc:
                last = exc
    
                try:
                    error_body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    error_body = ""
    
                debug(
                    "LLM_HTTP_ERROR",
                    operation=operation,
                    attempt=f"{attempt + 1}/{max_attempts}",
                    status=exc.code,
                    elapsed_seconds=round(time.monotonic() - attempt_started, 2),
                    response_chars=len(error_body),
                    provider_error_preview=error_body[:300],
                )
    
                if exc.code not in {429, 500, 502, 503, 504}:
                    raise LLMTemporaryError(
                        f"llm_http_{exc.code}"
                    ) from exc
    
                if attempt == max_attempts - 1:
                    raise LLMTemporaryError(
                        f"llm_http_{exc.code}"
                    ) from exc
    
                retry_after = exc.headers.get("Retry-After")
    
                try:
                    delay = max(1, min(int(retry_after), 10))
                except (TypeError, ValueError):
                    delay = 2
    
                debug(
                    "LLM_RETRY_SLEEP",
                    operation=operation,
                    attempt=f"{attempt + 1}/{max_attempts}",
                    sleep_seconds=delay,
                    reason=f"http_{exc.code}",
                )
    
                time.sleep(delay)
    
            except (
                urllib.error.URLError,
                TimeoutError,
                json.JSONDecodeError,
                LLMTemporaryError,
            ) as exc:
                last = exc
    
                debug(
                    "LLM_ERROR",
                    operation=operation,
                    attempt=f"{attempt + 1}/{max_attempts}",
                    type=exc.__class__.__name__,
                    message=str(exc)[:300],
                    elapsed_seconds=round(time.monotonic() - attempt_started, 2),
                )
    
                if attempt == max_attempts - 1:
                    raise LLMTemporaryError(
                        f"llm_failure_{exc.__class__.__name__}"
                    ) from exc
    
                debug(
                    "LLM_RETRY_SLEEP",
                    operation=operation,
                    attempt=f"{attempt + 1}/{max_attempts}",
                    sleep_seconds=2,
                    reason=exc.__class__.__name__,
                )
    
                time.sleep(2)
    
        raise LLMTemporaryError(
            f"llm_failure_{last.__class__.__name__ if last else 'unknown'}"
        )

    def chat_json_object(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
        operation: str = "generic_object",
    ) -> dict:
        value = self.chat_json(
            system_prompt,
            user_prompt,
            max_tokens=max_tokens,
            operation=operation,
        )
    
        if not isinstance(value, dict):
            raise LLMTemporaryError("LLM returned non-object JSON")
    
        return value

    def chat_json_array(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        max_tokens: int | None = None,
        operation: str = "generic_array",
    ) -> list:
        value = self.chat_json(
            system_prompt,
            user_prompt,
            max_tokens=max_tokens,
            operation=operation,
        )
    
        if not isinstance(value, list):
            raise LLMTemporaryError("LLM returned non-array JSON")
    
        return value
