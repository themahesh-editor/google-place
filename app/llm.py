from __future__ import annotations

import json
import os
import re
import time
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

    def chat_json(self, system_prompt: str, user_prompt: str, *, max_tokens: int | None = None):
        key = os.getenv("NVIDIA_API_KEY", "").strip()
        if not key:
            raise LLMTemporaryError("NVIDIA_API_KEY is missing")
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            "temperature": 0.2,
            "top_p": 0.95,
            "max_tokens": max_tokens or self.default_max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=payload,
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            method="POST",
        )
        last: Exception | None = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = response.read().decode("utf-8")
                obj = json.loads(body)
                content = obj.get("choices", [{}])[0].get("message", {}).get("content", "")
                parsed = parse_json_value(content)
                if parsed is None:
                    raise LLMTemporaryError("LLM returned invalid JSON")
                return parsed
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise LLMTemporaryError(f"llm_http_{exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, LLMTemporaryError) as exc:
                last = exc
                if attempt == 2:
                    raise LLMTemporaryError(f"llm_failure_{exc.__class__.__name__}") from exc
            time.sleep(2 + attempt * 3)
        raise LLMTemporaryError(f"llm_failure_{last.__class__.__name__ if last else 'unknown'}")

    def chat_json_object(self, system_prompt: str, user_prompt: str, *, max_tokens: int | None = None) -> dict:
        value = self.chat_json(system_prompt, user_prompt, max_tokens=max_tokens)
        if not isinstance(value, dict):
            raise LLMTemporaryError("LLM returned non-object JSON")
        return value

    def chat_json_array(self, system_prompt: str, user_prompt: str, *, max_tokens: int | None = None) -> list:
        value = self.chat_json(system_prompt, user_prompt, max_tokens=max_tokens)
        if not isinstance(value, list):
            raise LLMTemporaryError("LLM returned non-array JSON")
        return value
