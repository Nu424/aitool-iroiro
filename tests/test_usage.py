import httpx
import pytest

from aitool.errors import OpenRouterHTTPError
from aitool.usage import (
    CallStats,
    enrich_from_generation,
    extract_stats,
    with_usage_accounting,
)


def test_with_usage_accounting_adds_include_flag() -> None:
    payload = {"model": "example/chat", "messages": []}

    enriched = with_usage_accounting(payload)

    assert enriched["usage"] == {"include": True}
    # ---元のペイロードは変更しない
    assert "usage" not in payload


def test_extract_stats_reads_chat_completions_usage() -> None:
    response = {
        "id": "gen-abc",
        "provider": "Google",
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 20,
            "total_tokens": 120,
            "cost": 0.0015,
        },
    }

    stats = extract_stats(response)

    assert stats.prompt_tokens == 100
    assert stats.completion_tokens == 20
    assert stats.total_tokens == 120
    assert stats.cost_usd == 0.0015
    assert stats.generation_id == "gen-abc"
    assert stats.provider == "Google"
    assert stats.has_billing_details


def test_extract_stats_accepts_transcription_key_names() -> None:
    """/audio/transcriptions は input_tokens / output_tokens で返す。"""
    response = {
        "text": "hello",
        "usage": {
            "seconds": 3,
            "input_tokens": 40,
            "output_tokens": 8,
            "total_tokens": 48,
            "cost": 0.0002,
        },
    }

    stats = extract_stats(response)

    assert stats.prompt_tokens == 40
    assert stats.completion_tokens == 8
    assert stats.total_tokens == 48
    assert stats.cost_usd == 0.0002


def test_extract_stats_tolerates_missing_usage() -> None:
    stats = extract_stats({"text": "hello"})

    assert stats.total_tokens is None
    assert stats.cost_usd is None
    assert stats.generation_id is None
    assert not stats.has_billing_details


def test_extract_stats_uses_explicit_generation_id() -> None:
    stats = extract_stats({}, generation_id="gen-from-header")

    assert stats.generation_id == "gen-from-header"


class _FakeClient:
    """``generation()`` の呼び出し回数と応答を制御するスタブ。"""

    def __init__(self, responses: list[object]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def generation(self, generation_id: str):
        self.calls.append(generation_id)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


GENERATION_RECORD = {
    "data": {
        "total_cost": 0.0000108,
        "provider_name": "Google",
        "latency": 250,
        "generation_time": 1200,
        "tokens_prompt": 12,
        "tokens_completion": 480,
    }
}


def test_enrich_from_generation_fills_missing_cost() -> None:
    client = _FakeClient([GENERATION_RECORD])

    stats = enrich_from_generation(client, CallStats(generation_id="gen-tts"))

    assert client.calls == ["gen-tts"]
    assert stats.cost_usd == 0.0000108
    assert stats.provider == "Google"
    assert stats.latency_ms == 250
    assert stats.generation_time_ms == 1200
    assert stats.prompt_tokens == 12
    assert stats.completion_tokens == 480
    # ---total_tokens は記録に無いので入出力の和で補う
    assert stats.total_tokens == 492


def test_enrich_from_generation_skips_when_already_complete() -> None:
    client = _FakeClient([GENERATION_RECORD])
    base = CallStats(total_tokens=15, cost_usd=0.001, generation_id="gen-abc")

    stats = enrich_from_generation(client, base)

    assert client.calls == []
    assert stats is base


def test_enrich_from_generation_skips_without_generation_id() -> None:
    client = _FakeClient([GENERATION_RECORD])

    stats = enrich_from_generation(client, CallStats())

    assert client.calls == []
    assert stats.cost_usd is None


def test_enrich_from_generation_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """生成直後は記録が間に合わないことがあるため、少し待って再試行する。"""
    monkeypatch.setattr("aitool.usage.time.sleep", lambda _seconds: None)
    client = _FakeClient([OpenRouterHTTPError(404, "not found"), GENERATION_RECORD])

    stats = enrich_from_generation(client, CallStats(generation_id="gen-tts"))

    assert len(client.calls) == 2
    assert stats.cost_usd == 0.0000108


def test_enrich_from_generation_gives_up_quietly(monkeypatch: pytest.MonkeyPatch) -> None:
    """照会に失敗しても本処理の結果は得られているので、例外は投げない。"""
    monkeypatch.setattr("aitool.usage.time.sleep", lambda _seconds: None)
    client = _FakeClient([httpx.ConnectError("boom")] * 3)

    stats = enrich_from_generation(client, CallStats(generation_id="gen-tts"))

    assert len(client.calls) == 3
    assert stats.cost_usd is None
    assert stats.generation_id == "gen-tts"


def test_call_stats_splits_into_usage_and_timing_sections() -> None:
    stats = CallStats(
        prompt_tokens=1,
        completion_tokens=2,
        total_tokens=3,
        cost_usd=0.5,
        generation_id="gen-x",
        provider="Google",
        generation_time_ms=1200,
        latency_ms=250,
    )

    assert stats.usage_dict() == {
        "prompt_tokens": 1,
        "completion_tokens": 2,
        "total_tokens": 3,
        "cost_usd": 0.5,
        "generation_id": "gen-x",
    }
    assert stats.timing_dict(2143) == {
        "elapsed_ms": 2143,
        "generation_time_ms": 1200,
        "latency_ms": 250,
    }
