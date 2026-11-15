"""Minimal LLM client over the OpenAI-compatible Chat Completions API.

Gemini, Groq, OpenRouter, OpenAI etc. all speak this protocol, so switching
provider is a base URL + model name in .env — no SDKs, no code change.

Cost discipline built in:
  * Every response is cached in SQLite, keyed by
    sha256(task, prompt_version, model, messages). The same document is never
    sent twice; bumping a task's prompt_version invalidates only that task.
  * Every call (hit or miss) is logged with token counts → /api/llm/usage.
  * JSON is requested and validated; one repair retry, then give up cleanly.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
from typing import Any

import httpx

from . import config, db


log = logging.getLogger("finn.llm")


class LLMUnavailable(RuntimeError):
    pass


def _key(task: str, version: str, model: str, messages: list[dict]) -> str:
    blob = json.dumps([task, version, model, messages], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def _extract_json(text: str) -> Any:
    text = text.strip()
    # Tolerate ```json fences some models add even in JSON mode.
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1)
    return json.loads(text)


def complete_json(task: str, version: str, messages: list[dict], *,
                  tier: config.LLMTier | None = None, temperature: float = 0.0,
                  max_tokens: int = 4096, timeout: float | None = None,
                  fallback: config.LLMTier | None = None) -> Any:
    """Return parsed JSON for a chat request, using the cache when possible.
    If the call fails (timeout, rate limit, bad JSON) and a fallback tier is
    given, the same request is tried once on that tier."""
    try:
        return _complete_json(task, version, messages, tier=tier, temperature=temperature,
                              max_tokens=max_tokens, timeout=timeout)
    except LLMUnavailable:
        if fallback is None or not fallback.enabled or (tier and fallback.model == tier.model):
            raise
        log.warning("%s: primary model failed, falling back to %s", task, fallback.model)
        return _complete_json(task, version, messages, tier=fallback, temperature=temperature,
                              max_tokens=max_tokens, timeout=None)


def _complete_json(task: str, version: str, messages: list[dict], *,
                   tier: config.LLMTier | None = None, temperature: float = 0.0,
                   max_tokens: int = 4096, timeout: float | None = None) -> Any:
    tier = tier or config.LLM_FAST
    if not tier.enabled:
        raise LLMUnavailable("no API key configured")
    key = _key(task, version, tier.model, messages)

    with db.connect() as conn:
        row = conn.execute("SELECT response FROM llm_cache WHERE key=?", (key,)).fetchone()
        if row:
            conn.execute("INSERT INTO llm_calls(task, model, cached, ok, created_at) VALUES(?,?,1,1,?)",
                         (task, tier.model, db.utcnow()))
            return json.loads(row["response"])

    timeout = timeout or tier.timeout
    payload = {"model": tier.model, "messages": messages, "temperature": temperature,
               "max_tokens": max_tokens, "response_format": {"type": "json_object"}}
    if tier.reasoning_effort:
        payload["reasoning_effort"] = tier.reasoning_effort
    headers = {"Authorization": f"Bearer {tier.api_key}"}
    url = f"{tier.base_url}/chat/completions"

    err: str | None = None
    parsed: Any = None
    usage: dict = {}
    t0 = time.time()
    timeouts = 0
    for attempt in range(4):
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        except httpx.TimeoutException as e:
            err = f"timed out after {int(timeout)} s ({e})"
            timeouts += 1
            if timeouts >= 2:     # a second timeout won't be different; give up rather than wait minutes more
                break
            continue
        except httpx.HTTPError as e:
            err = f"network: {e}"
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code == 400 and "reasoning" in r.text.lower() and "reasoning_effort" in payload:
            payload.pop("reasoning_effort")   # provider doesn't support it: retry without
            err = "reasoning_effort unsupported"
            continue
        if r.status_code == 429 or r.status_code >= 500:
            # Free tiers rate-limit aggressively; honour Retry-After when given.
            wait = float(r.headers.get("retry-after") or 0) or 5 * (attempt + 1)
            err = f"HTTP {r.status_code}"
            time.sleep(min(wait, 30))
            continue
        if r.status_code != 200:
            err = f"HTTP {r.status_code}: {r.text[:300]}"
            break
        data = r.json()
        usage = data.get("usage") or {}
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        try:
            parsed = _extract_json(content)
            err = None
            break
        except (json.JSONDecodeError, TypeError):
            err = "invalid JSON from model"
            # one repair attempt: show the model its own output
            payload["messages"] = messages + [
                {"role": "assistant", "content": content[:4000]},
                {"role": "user", "content": "That was not valid JSON. Reply with only the corrected JSON object."}]
    latency = int((time.time() - t0) * 1000)

    try:
        _record(task, tier, usage, latency, err, key, parsed)
    except sqlite3.OperationalError as e:   # bookkeeping must never break the caller
        log.warning("could not record LLM call: %s", e)
    if err is not None:
        raise LLMUnavailable(err)
    return parsed


def _record(task, tier, usage, latency, err, key, parsed) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO llm_calls(task, model, prompt_tokens, completion_tokens, cached, latency_ms, ok, error, created_at) "
            "VALUES(?,?,?,?,0,?,?,?,?)",
            (task, tier.model, usage.get("prompt_tokens"), usage.get("completion_tokens"),
             latency, int(err is None), err, db.utcnow()))
        if err is None:
            conn.execute("INSERT OR REPLACE INTO llm_cache(key, task, model, response, created_at) VALUES(?,?,?,?,?)",
                         (key, task, tier.model, json.dumps(parsed), db.utcnow()))
            db.mark_source(conn, "llm", True, detail=tier.model)
        else:
            db.mark_source(conn, "llm", False, error=err, detail=tier.model)


def usage_summary() -> dict:
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT task, model, COUNT(*) calls, SUM(cached) cache_hits, "
            "COALESCE(SUM(prompt_tokens),0) prompt_tokens, COALESCE(SUM(completion_tokens),0) completion_tokens, "
            "SUM(1-ok) failures FROM llm_calls GROUP BY task, model ORDER BY task").fetchall()
    return {"by_task": [dict(r) for r in rows],
            "fast_model": config.LLM_FAST.model if config.LLM_FAST.enabled else None,
            "deep_model": config.LLM_DEEP.model if config.LLM_DEEP.enabled else None}
