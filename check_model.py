"""Check that the OpenRouter key and model work, and that the model can call a tool.

Run:  python check_model.py
It sends one tiny request. It NEVER prints your key (only its first 8 characters
and length, so you can see the right one was read).
"""
import json
import os
import sys

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # reads .env in this folder

key = os.getenv("OPENROUTER_API_KEY", "").strip()
model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-haiku-5.5")

if not key:
    sys.exit("No key found. Open .env and paste your key after OPENROUTER_API_KEY=")
if not key.startswith("sk-or-"):
    print("Warning: OpenRouter keys usually start with 'sk-or-'. Check you pasted the right one.")
print(f"Key read: {key[:8]}... ({len(key)} characters). Model: {model}")

client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)

# One fake tool, the same shape our real tools will have.
tools = [{
    "type": "function",
    "function": {
        "name": "get_feasible_slots",
        "description": "Return dock slots a shipment can use.",
        "parameters": {
            "type": "object",
            "properties": {"shipment_id": {"type": "string"}},
            "required": ["shipment_id"],
        },
    },
}]

try:
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Find slots for shipment SHP1010."}],
        tools=tools,
        max_tokens=200,
    )
except Exception as e:  # show the error type and message, never the key
    sys.exit(f"Request failed: {type(e).__name__}: {e}")

msg = resp.choices[0].message
if msg.tool_calls:
    call = msg.tool_calls[0]
    print(f"OK: the model called {call.function.name} with {json.loads(call.function.arguments)}")
else:
    print(f"Connected, but the model answered in text instead of calling the tool: {msg.content!r}")
if resp.usage:
    print(f"Tokens used: {resp.usage.prompt_tokens} in, {resp.usage.completion_tokens} out")
