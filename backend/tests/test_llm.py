"""LLM client behaviour with the HTTP endpoint mocked: caching, JSON repair,
usage logging, and the residual-classification contract."""
import json

import httpx

from finn import config, db, llm


class FakeResp:
    def __init__(self, content, status=200):
        self.status_code = status
        self._content = content
        self.headers = {}
        self.text = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30}}


def _enable(monkeypatch):
    monkeypatch.setattr(config, "LLM_FAST", config.LLMTier("http://fake/v1", "k", "fake-model"))


def test_cache_and_usage(monkeypatch):
    _enable(monkeypatch)
    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(k) or FakeResp('{"a": 1}'))
    msgs = [{"role": "user", "content": "hi"}]
    assert llm.complete_json("t", "v1", msgs) == {"a": 1}
    assert llm.complete_json("t", "v1", msgs) == {"a": 1}      # served from cache
    assert len(calls) == 1
    assert llm.complete_json("t", "v2", msgs) == {"a": 1}      # new prompt version → new call
    assert len(calls) == 2
    u = llm.usage_summary()["by_task"][0]
    assert u["calls"] == 3 and u["cache_hits"] == 1 and u["prompt_tokens"] == 240


def test_json_repair(monkeypatch):
    _enable(monkeypatch)
    replies = iter(["not json at all", '```json\n{"ok": true}\n```'])
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(next(replies)))
    assert llm.complete_json("t", "v1", [{"role": "user", "content": "x"}]) == {"ok": True}


def test_residual_classification_validates_output(monkeypatch):
    _enable(monkeypatch)
    from finn.pipeline.llm_classify import classify_batch
    reply = {"items": [
        {"id": "nse:1", "category": "press_release", "sub_type": "order_win", "summary": "Won a ₹500 cr metro order."},
        {"id": "nse:2", "category": "made_up_category", "sub_type": "", "summary": "x"},   # rejected
        {"id": "nse:999", "category": "results", "sub_type": "outcome", "summary": "x"},   # unknown id, rejected
    ]}
    monkeypatch.setattr(httpx, "post", lambda *a, **k: FakeResp(json.dumps(reply)))
    out = classify_batch([{"id": "nse:1", "symbol": "LT", "subject": "General Updates", "body": "..."},
                          {"id": "nse:2", "symbol": "LT", "subject": "Updates", "body": "..."}])
    assert out == {"nse:1": {"category": "press_release", "sub_type": "order_win",
                             "summary": "Won a ₹500 cr metro order."}}


def test_no_key_raises_cleanly(monkeypatch):
    import pytest
    with pytest.raises(llm.LLMUnavailable):
        llm.complete_json("t", "v1", [{"role": "user", "content": "x"}])
    with db.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0] == 0


def test_fallback_tier_used_when_primary_times_out(monkeypatch):
    monkeypatch.setattr(config, "LLM_FAST", config.LLMTier("http://fast/v1", "k", "fast-model"))
    deep = config.LLMTier("http://deep/v1", "k", "deep-model", timeout=1)

    def post(url, json=None, **kw):
        if "deep" in url:
            raise httpx.ReadTimeout("slow")
        return FakeResp('{"ok": 1}')
    monkeypatch.setattr(httpx, "post", post)
    assert llm.complete_json("t", "v1", [{"role": "user", "content": "x"}], tier=deep,
                             fallback=config.LLM_FAST) == {"ok": 1}


def test_interrupted_build_is_not_stuck(monkeypatch):
    """A dossier left 'running' by a killed process must be rebuilt, not returned as running forever."""
    from finn.research import build as B
    with db.connect() as conn:
        conn.execute("INSERT INTO dossiers(symbol, status, progress, started_at) VALUES('DIXON','running','[]',?)",
                     (db.utcnow(),))
    started = []
    monkeypatch.setattr(B, "_run", lambda sym, client=None: started.append(sym))
    B.request("DIXON", run_async=False)
    assert started == ["DIXON"]
