"""
llm.py — LLM client for the re-run, ported from the original code's legacy
`openai.ChatCompletion.create` (removed in openai-python >= 1.0) to the current
SDK, and made GPT-5-aware.

GPT-5 / o-series are reasoning models: via chat.completions they reject
`temperature` (only the default is allowed) and use `max_completion_tokens`
instead of `max_tokens`; they accept `reasoning_effort`. This client branches
on the model name so the same code works for both gpt-4o-style and gpt-5-style
models.

Config via env:
  OPENAI_API_KEY   (required)          your key
  LLM_MODEL        (default gpt-5)     main analysis/generation model
  LLM_MODEL_FAST   (default gpt-5-mini) cheaper model for call-graph extraction
  LLM_EFFORT       (default medium)    reasoning_effort for reasoning models
"""
import hashlib
import json
import os
import re
from openai import OpenAI

_client = None
_cache = None
CALLS = 0  # number of chat queries issued this run (live or replayed)


def _cache_dict():
    """Lazy-load the response cache from $LLM_CACHE (JSON), if set."""
    global _cache
    if _cache is None:
        _cache = {}
        path = os.environ.get("LLM_CACHE")
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                _cache = json.load(f)
    return _cache


def _cache_key(model, messages):
    blob = model + "\n" + json.dumps(messages, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _cache_put(key, text):
    path = os.environ.get("LLM_CACHE")
    if not path:
        return
    c = _cache_dict()
    c[key] = text
    with open(path, "w", encoding="utf-8") as f:
        json.dump(c, f, ensure_ascii=False, indent=0)


def client() -> OpenAI:
    global _client
    if _client is None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set in the environment.")
        _client = OpenAI()
    return _client


def _is_reasoning(model: str) -> bool:
    m = model.lower()
    return m.startswith("gpt-5") or m.startswith("o1") or m.startswith("o3") or m.startswith("o4")


def chat(messages, model: str = None, effort: str = None):
    """Send a chat and return (text, assistant_message_dict).

    The dict is appended back into the running `messages` list by callers to
    preserve multi-turn context, exactly like the original code did.
    """
    global CALLS
    CALLS += 1
    model = model or os.environ.get("LLM_MODEL", "gpt-5")

    # response cache: enables "record once, replay instantly" for a reliable,
    # deterministic screen recording (set $LLM_CACHE to a JSON path).
    key = _cache_key(model, messages)
    cached = _cache_dict().get(key)
    if cached is not None:
        return cached, {"role": "assistant", "content": cached}
    if os.environ.get("LLM_CACHE_STRICT") == "1":
        raise RuntimeError(
            "replay mode: prompt not found in cache. Record a live run with "
            "--cache first, then replay it.")

    kwargs = dict(model=model, messages=messages)
    if _is_reasoning(model):
        eff = effort or os.environ.get("LLM_EFFORT", "medium")
        if eff:
            kwargs["reasoning_effort"] = eff
        # temperature intentionally omitted (reasoning models require default)
    else:
        kwargs["temperature"] = 0
    resp = client().chat.completions.create(**kwargs)
    text = resp.choices[0].message.content or ""
    _cache_put(key, text)
    return text, {"role": "assistant", "content": text}


def chat_fast(messages):
    """Cheaper model for high-volume, low-stakes calls (call-graph extraction)."""
    return chat(messages, model=os.environ.get("LLM_MODEL_FAST", "gpt-5-mini"))


_FENCE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text: str) -> str:
    """Pull a python code block out of an LLM reply.

    Robust replacement for the original `response.split('\\n')[1:-1]` trick,
    which broke whenever the model added or omitted the ``` fences.
    """
    m = _FENCE.search(text)
    if m:
        return m.group(1).strip("\n")
    # no fences: assume the whole reply is code
    return text.strip().strip("`").strip("\n")


if __name__ == "__main__":
    # Tiny connectivity smoke test (uses your key + a few tokens).
    txt, _ = chat([{"role": "user", "content": "Reply with exactly: ok"}])
    print("model reply:", repr(txt))
