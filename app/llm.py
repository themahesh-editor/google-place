from __future__ import annotations

import json
import re
import time
import threading
from typing import Any

import requests


class LLMTemporaryError(RuntimeError):
    pass


class LLMInvalidResponse(RuntimeError):
    pass


class LLMPermanentError(RuntimeError):
    pass


def parse_json_value(raw: str) -> Any:
    text = (raw or "").strip()
    if not text:
        raise LLMInvalidResponse("empty LLM response")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        starts = [m.start() for m in re.finditer(r"[\[{]", text)]
        for start in starts:
            for end in range(len(text), start + 1, -1):
                candidate = text[start:end].strip()
                if not candidate or candidate[-1] not in "]}":
                    continue
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue
        raise LLMInvalidResponse("response did not contain valid JSON")


class LLMClient:
    """The single canonical NVIDIA/OpenAI-compatible JSON client."""

    def __init__(self, api_key: str, base_url: str, model: str, timeout_seconds: int, max_retries: int = 2, backoff_seconds: int = 2):
        if not api_key:
            raise ValueError("NVIDIA_API_KEY is missing")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self._local = threading.local()

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"})
            self._local.session = session
        return session

    def chat_json(self, system: str, user: str, *, max_tokens: int | None = None, operation: str = "llm") -> Any:
        payload = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": max_tokens or 1200,
            "response_format": {"type": "json_object"},
        }
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._session().post(f"{self.base_url}/chat/completions", json=payload, timeout=self.timeout_seconds)
                if response.status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
                    raise LLMTemporaryError(f"{operation}: provider HTTP {response.status_code}")
                if response.status_code in {400, 401, 403, 404, 422}:
                    raise LLMPermanentError(f"{operation}: provider HTTP {response.status_code}")
                response.raise_for_status()
                body = response.json()
                content = (((body.get("choices") or [{}])[0]).get("message") or {}).get("content", "")
                return parse_json_value(content)
            except LLMTemporaryError as exc:
                last_error = exc
            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = LLMTemporaryError(f"{operation}: {exc.__class__.__name__}")
            except LLMInvalidResponse as exc:
                last_error = exc
            except ValueError as exc:
                last_error = LLMInvalidResponse(f"{operation}: invalid provider JSON: {exc}")
            except requests.RequestException as exc:
                last_error = LLMPermanentError(f"{operation}: {exc}")
            if attempt < self.max_retries:
                time.sleep(self.backoff_seconds * (2 ** attempt))
                continue
            break
        assert last_error is not None
        raise last_error

    def chat_json_object(self, system: str, user: str, **kwargs: Any) -> dict[str, Any]:
        obj = self.chat_json(system, user, **kwargs)
        if not isinstance(obj, dict):
            raise LLMInvalidResponse("expected JSON object")
        return obj

    def chat_json_array(self, system: str, user: str, **kwargs: Any) -> list[Any]:
        obj = self.chat_json(system, user, **kwargs)
        if not isinstance(obj, list):
            raise LLMInvalidResponse("expected JSON array")
        return obj
