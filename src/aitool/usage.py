"""API 呼び出しのトークン・コスト・所要時間を表すデータ構造と取得ヘルパー。

コストとトークン数の取得元は 2 系統ある。

1. **インライン** — ``/images`` と ``/audio/transcriptions`` はレスポンスの
   ``usage`` にコストを含む。``/chat/completions`` は ``usage.include`` を
   リクエストに足すとコストが返る。追加リクエストは不要。
2. **``/generation`` 照会** — ``/audio/speech`` はバイナリ応答で ``usage`` を
   持たず、``X-Generation-Id`` ヘッダーしか返らない。この場合のみ
   ``/generation`` を照会して補う。

``CallStats`` は 1 回の API 呼び出しの計測値をまとめて運ぶ器で、
CLI の出力層で ``usage`` セクションと ``timing`` セクションに振り分けられる。
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from aitool.errors import AitoolError

# --- /generation 照会のリトライ設定 ---

GENERATION_LOOKUP_ATTEMPTS = 3
"""``/generation`` 照会の最大試行回数。生成直後は記録が間に合わないことがある。"""

GENERATION_LOOKUP_DELAY_SECONDS = 0.25
"""``/generation`` 照会をリトライする際の待機時間（秒）。"""


# --- 計測値 ---


@dataclass(slots=True)
class CallStats:
    """1 回の API 呼び出しに関するトークン・コスト・時間の計測値。

    いずれのフィールドも取得できなければ None のままになる。

    Attributes:
        prompt_tokens: 入力トークン数。
        completion_tokens: 出力トークン数。
        total_tokens: 合計トークン数。
        cost_usd: 合計コスト（USD）。
        generation_id: OpenRouter の生成 ID。
        provider: 実際に処理した上流プロバイダ名。
        generation_time_ms: プロバイダ側の生成時間（ミリ秒）。
        latency_ms: プロバイダ側の初回応答までのレイテンシ（ミリ秒）。
    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    generation_id: str | None = None
    provider: str | None = None
    generation_time_ms: int | None = None
    latency_ms: int | None = None

    @property
    def has_billing_details(self) -> bool:
        """コストとトークン数が揃っているかどうかを返す。

        Returns:
            ``cost_usd`` と ``total_tokens`` の両方が取得済みなら True。
        """
        return self.cost_usd is not None and self.total_tokens is not None

    def usage_dict(self) -> dict[str, Any]:
        """JSON エンベロープの ``usage`` セクション用の辞書を返す。"""
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "generation_id": self.generation_id,
        }

    def timing_dict(self, elapsed_ms: int) -> dict[str, Any]:
        """JSON エンベロープの ``timing`` セクション用の辞書を返す。

        Args:
            elapsed_ms: CLI 側で計測した実測の所要時間（ミリ秒）。
        """
        return {
            "elapsed_ms": elapsed_ms,
            "generation_time_ms": self.generation_time_ms,
            "latency_ms": self.latency_ms,
        }


# --- インラインの usage 抽出 ---


def with_usage_accounting(payload: dict[str, Any]) -> dict[str, Any]:
    """チャット補完ペイロードにコスト返却の指定を足す。

    ``/chat/completions`` は既定ではコストを返さないため、``usage.include``
    を指定する。``/images`` と ``/audio/transcriptions`` は指定なしでコストを
    返すので、この関数を通す必要はない。

    Args:
        payload: チャット補完のリクエストペイロード。

    Returns:
        ``usage`` 指定を足した新しいペイロード。
    """
    return {**payload, "usage": {"include": True}}


def _as_int(value: Any) -> int | None:
    """値を int に変換する。変換できない場合は None を返す。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def _as_float(value: Any) -> float | None:
    """値を float に変換する。変換できない場合は None を返す。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _first_int(source: Mapping[str, Any], *keys: str) -> int | None:
    """複数の候補キーを順に見て、最初に見つかった整数値を返す。

    エンドポイントによってキー名が異なる（``prompt_tokens`` と
    ``input_tokens`` など）ため、候補を並べて吸収する。
    """
    for key in keys:
        value = _as_int(source.get(key))
        if value is not None:
            return value
    return None


def extract_stats(
    response: Mapping[str, Any],
    *,
    generation_id: str | None = None,
) -> CallStats:
    """API レスポンスの ``usage`` から計測値を取り出す。

    ``usage`` が無い、または想定外の形でも例外は投げず、
    取れたフィールドだけを埋めた ``CallStats`` を返す。

    Args:
        response: JSON レスポンス辞書。
        generation_id: 明示的に渡す生成 ID。未指定時はレスポンスの ``id`` を使う。

    Returns:
        取得できた範囲を埋めた計測値。
    """
    resolved_id = generation_id
    if resolved_id is None:
        raw_id = response.get("id")
        resolved_id = raw_id if isinstance(raw_id, str) else None

    provider = response.get("provider")

    usage = response.get("usage")
    if not isinstance(usage, Mapping):
        return CallStats(
            generation_id=resolved_id,
            provider=provider if isinstance(provider, str) else None,
        )

    return CallStats(
        prompt_tokens=_first_int(usage, "prompt_tokens", "input_tokens"),
        completion_tokens=_first_int(usage, "completion_tokens", "output_tokens"),
        total_tokens=_first_int(usage, "total_tokens"),
        cost_usd=_as_float(usage.get("cost")),
        generation_id=resolved_id,
        provider=provider if isinstance(provider, str) else None,
    )


# --- /generation 照会によるフォールバック ---


def _merge_generation_record(base: CallStats, record: Mapping[str, Any]) -> CallStats:
    """``/generation`` の記録を既存の計測値にマージする。

    既に埋まっているフィールドは上書きせず、欠けている分だけを補う。

    Args:
        base: インラインで取得済みの計測値。
        record: ``/generation`` レスポンスの ``data`` 部分。

    Returns:
        マージ後の計測値。
    """
    return CallStats(
        prompt_tokens=base.prompt_tokens
        if base.prompt_tokens is not None
        else _first_int(record, "tokens_prompt", "native_tokens_prompt"),
        completion_tokens=base.completion_tokens
        if base.completion_tokens is not None
        else _first_int(record, "tokens_completion", "native_tokens_completion"),
        total_tokens=base.total_tokens,
        cost_usd=base.cost_usd if base.cost_usd is not None else _as_float(record.get("total_cost")),
        generation_id=base.generation_id,
        provider=base.provider or (record.get("provider_name") if isinstance(record.get("provider_name"), str) else None),
        generation_time_ms=_as_int(record.get("generation_time")),
        latency_ms=_as_int(record.get("latency")),
    )


def _fill_total_tokens(stats: CallStats) -> CallStats:
    """``total_tokens`` が欠けていれば入出力トークン数の和で補う。"""
    if stats.total_tokens is not None:
        return stats
    if stats.prompt_tokens is None and stats.completion_tokens is None:
        return stats
    stats.total_tokens = (stats.prompt_tokens or 0) + (stats.completion_tokens or 0)
    return stats


def enrich_from_generation(
    client: Any,
    stats: CallStats,
    *,
    attempts: int = GENERATION_LOOKUP_ATTEMPTS,
    delay: float = GENERATION_LOOKUP_DELAY_SECONDS,
) -> CallStats:
    """コストが欠けている場合に ``/generation`` を照会して計測値を補う。

    生成直後は記録が間に合わないことがあるため、短い間隔でリトライする。
    照会に失敗しても本処理の結果は既に得られているため、例外は投げずに
    入力の計測値をそのまま返す。

    Args:
        client: ``generation()`` を持つ OpenRouter クライアント。
        stats: インラインで取得済みの計測値。
        attempts: 最大試行回数。
        delay: リトライ間隔（秒）。

    Returns:
        補完後の計測値。補完できなかった場合は入力と同じ内容。
    """
    # ---既に十分な情報がある、または照会の手掛かりが無ければ何もしない
    if stats.has_billing_details or not stats.generation_id:
        return stats

    for attempt in range(attempts):
        try:
            response = client.generation(stats.generation_id)
        except (AitoolError, httpx.HTTPError):
            response = None

        record = response.get("data") if isinstance(response, Mapping) else None
        if isinstance(record, Mapping):
            return _fill_total_tokens(_merge_generation_record(stats, record))

        # ---最後の試行以外は少し待ってから再試行する
        if attempt < attempts - 1:
            time.sleep(delay)

    return stats
