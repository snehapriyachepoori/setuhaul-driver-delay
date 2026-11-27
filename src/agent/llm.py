"""One model adapter over an OpenAI-style chat API. Swap providers here only.

MODEL_ROUTE in .env:
  openrouter : OPENROUTER_API_KEY, OPENROUTER_MODEL, OPENROUTER_FALLBACK_MODEL
  ollama     : OLLAMA_MODEL (local, free; http://localhost:11434/v1)
  rules      : no model at all (option A fallback: deterministic rules + templates)
The key is read from the environment and never printed or logged.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

TIMEOUT_S = 15


class ModelUnavailable(RuntimeError):
    pass


@dataclass
class ModelReply:
    content: str | None
    tool_calls: list[dict] = field(default_factory=list)   # [{"id","name","arguments": dict}]
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0


class OpenAIStyleModel:
    def __init__(self, base_url: str, api_key: str, models: list[str], extra_headers: dict | None = None):
        from openai import OpenAI

        from src.tracing import wrap_client

        self.client = wrap_client(OpenAI(base_url=base_url, api_key=api_key, timeout=TIMEOUT_S, max_retries=0))
        self.models = [m for m in models if m]
        self.extra_headers = extra_headers or {}

    def chat(self, messages: list[dict], tools: list[dict]) -> ModelReply:
        last_err = None
        messages = [{k: v for k, v in msg.items() if not (msg["role"] == "tool" and k == "name")}
                    for msg in messages]
        for m in self.models:                     # primary, then fallback
            t0 = time.time()
            try:
                kw = {"model": m, "messages": messages, "max_tokens": 600, "temperature": 0}
                if tools:
                    kw["tools"] = tools
                if self.extra_headers:
                    kw["extra_headers"] = self.extra_headers
                r = self.client.chat.completions.create(**kw)
            except Exception as e:                # never include the key; the SDK does not put it in messages
                last_err = f"{type(e).__name__}: {str(e)[:120]}"
                continue
            msg = r.choices[0].message
            calls = []
            for c in msg.tool_calls or []:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {"_unparseable": c.function.arguments[:200]}
                calls.append({"id": c.id, "name": c.function.name, "arguments": args})
            u = r.usage
            return ModelReply(msg.content, calls, m, getattr(u, "prompt_tokens", 0) or 0,
                              getattr(u, "completion_tokens", 0) or 0, int((time.time() - t0) * 1000))
        raise ModelUnavailable(last_err or "no model configured")


def make_model(route: str | None = None):
    route = (route or os.getenv("MODEL_ROUTE", "openrouter")).lower()
    if route == "rules":
        from src.agent.rules_model import RulesModel
        return RulesModel()
    if route == "ollama":
        return OpenAIStyleModel("http://localhost:11434/v1", "ollama", [os.getenv("OLLAMA_MODEL", "qwen3:8b")])
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        raise ModelUnavailable("OPENROUTER_API_KEY is not set in .env")
    return OpenAIStyleModel("https://openrouter.ai/api/v1", key,
                            [os.getenv("OPENROUTER_MODEL", "anthropic/claude-haiku-5.5"),
                             os.getenv("OPENROUTER_FALLBACK_MODEL", "openai/gpt-4o-mini")],
                            {"X-Title": "SetuHaul FDE prototype"})
