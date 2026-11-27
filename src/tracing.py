"""Optional LangSmith tracing (bonus E5). OFF unless .env sets LANGSMITH_TRACING=true.

What gets traced: each driver turn (the LangGraph run: entry, agent, tools, guard, finish) and,
nested inside it, every model call with its messages and tool calls.
Privacy: phone numbers are masked BEFORE the graph runs, so they never reach LangSmith.
Synthetic/snapshot data only. Variable names follow docs.langchain.com/langsmith (read 27 Nov 2026):
LANGSMITH_TRACING, LANGSMITH_API_KEY, LANGSMITH_AGENT_ID, LANGSMITH_AGENT_ENVIRONMENT, LANGSMITH_ENDPOINT.
"""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def tracing_on() -> bool:
    return os.environ.get("LANGSMITH_TRACING", "").strip().lower() == "true" and bool(
        os.environ.get("LANGSMITH_API_KEY", "").strip())


def wrap_client(client):
    """Wrap an OpenAI SDK client so its calls appear as LLM runs in LangSmith (no-op when off)."""
    if not tracing_on():
        return client
    from langsmith.wrappers import wrap_openai
    return wrap_openai(client)


def flush() -> None:
    """Short scripts exit fast; wait until queued traces are sent (no-op when off)."""
    if not tracing_on():
        return
    try:
        from langchain_core.tracers.langchain import wait_for_all_tracers
        wait_for_all_tracers()
    except Exception as e:                       # tracing must never break the service
        print(f"(tracing flush skipped: {type(e).__name__})")
