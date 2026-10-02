from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request


class LLMTemporaryError(RuntimeError):
    pass


def parse_json_object(raw: str) -> dict | None:
    text=(raw or "").strip()
    text=re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text=re.sub(r"\s*```$", "", text)
    try:
        obj=json.loads(text)
        return obj if isinstance(obj,dict) else None
    except json.JSONDecodeError:
        pass
    m=re.search(r"\{.*\}",text,re.S)
    if not m:return None
    try:
        obj=json.loads(m.group(0)); return obj if isinstance(obj,dict) else None
    except json.JSONDecodeError:
        return None


class LLMClient:
    def __init__(self,base_url,model,timeout_seconds=90):
        self.base_url=base_url.rstrip("/"); self.model=model; self.timeout_seconds=timeout_seconds

    def chat_json(self,system_prompt,user_prompt,*,max_tokens=1400):
        key=os.getenv("NVIDIA_API_KEY","").strip()
        if not key: raise LLMTemporaryError("NVIDIA_API_KEY is missing")
        payload=json.dumps({"model":self.model,"messages":[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}],"temperature":0.2,"top_p":0.95,"max_tokens":max_tokens,"chat_template_kwargs":{"enable_thinking":False}}).encode()
        req=urllib.request.Request(f"{self.base_url}/chat/completions",data=payload,headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},method="POST")
        try:
            with urllib.request.urlopen(req,timeout=self.timeout_seconds) as resp:
                body=resp.read().decode("utf-8")
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError) as exc:
            raise LLMTemporaryError(f"llm_transport_{exc.__class__.__name__}") from exc
        obj=json.loads(body)
        content=obj.get("choices",[{}])[0].get("message",{}).get("content","")
        result=parse_json_object(content)
        if result is None: raise LLMTemporaryError("LLM returned invalid JSON")
        return result
