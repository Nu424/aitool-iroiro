"""CLI の出力整形を担うモジュール。

``--json`` 指定時は、全サブコマンドが共通の JSON エンベロープを
標準出力へ 1 個だけ出す。人間向けの表示と混ざらないので、
そのままパイプして ``jq`` などで処理できる。

成功時::

    {
      "ok": true,
      "command": "recognize-image",
      "model": "google/gemini-3-flash-preview",
      "provider": "Google",
      "result": {"text": "...", "output": null},
      "usage": {"prompt_tokens": 12, ..., "cost_usd": 0.0012, "generation_id": "gen-x"},
      "timing": {"elapsed_ms": 2143, "generation_time_ms": 1200, "latency_ms": 250}
    }

失敗時::

    {
      "ok": false,
      "command": "recognize-image",
      "error": {"type": "OpenRouterHTTPError", "message": "...", "status_code": 429}
    }
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import typer

from aitool.errors import AitoolError
from aitool.usage import CallStats


# --- 経過時間の計測 ---


@dataclass(slots=True)
class Stopwatch:
    """処理の実測時間を測るための単純なストップウォッチ。

    Attributes:
        _started_at: 計測開始時点の ``perf_counter`` 値。
    """

    _started_at: float = 0.0

    def __post_init__(self) -> None:
        """生成時点から計測を開始する。"""
        self._started_at = time.perf_counter()

    @property
    def elapsed_ms(self) -> int:
        """開始からの経過時間をミリ秒で返す。"""
        return int((time.perf_counter() - self._started_at) * 1000)


# --- JSON エンベロープ ---


def build_envelope(
    command: str,
    *,
    model: str | None,
    result: Any,
    stats: CallStats,
    elapsed_ms: int,
) -> dict[str, Any]:
    """成功時の JSON エンベロープを組み立てる。

    Args:
        command: サブコマンド名。
        model: 解決済みのモデル名。情報系コマンドでは None。
        result: コマンド固有の結果セクション。
        stats: 呼び出しの計測値。
        elapsed_ms: CLI 側で計測した所要時間（ミリ秒）。

    Returns:
        標準出力へ書き出す辞書。
    """
    return {
        "ok": True,
        "command": command,
        "model": model,
        "provider": stats.provider,
        "result": result,
        "usage": stats.usage_dict(),
        "timing": stats.timing_dict(elapsed_ms),
    }


def build_error_envelope(command: str, error: AitoolError) -> dict[str, Any]:
    """失敗時の JSON エンベロープを組み立てる。

    Args:
        command: サブコマンド名。
        error: 発生した例外。

    Returns:
        標準出力へ書き出す辞書。
    """
    payload: dict[str, Any] = {
        "type": type(error).__name__,
        "message": str(error),
    }

    # ---HTTP 系のエラーはステータスコードも添える
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        payload["status_code"] = status_code

    return {"ok": False, "command": command, "error": payload}


def echo_json(data: dict[str, Any]) -> None:
    """辞書を JSON として標準出力へ書き出す。

    Args:
        data: 出力する辞書データ。
    """
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


# --- 人間向けの補助表示 ---


def _format_cost(cost_usd: float | None) -> str:
    """コストを表示用の文字列に整形する。"""
    if cost_usd is None:
        return "cost n/a"
    return f"${cost_usd:.6f}"


def echo_stats_summary(stats: CallStats, elapsed_ms: int) -> None:
    """計測値の 1 行サマリを stderr へ表示する。

    ``--verbose`` 指定時に、人間向け表示の補助として使う。

    Args:
        stats: 呼び出しの計測値。
        elapsed_ms: CLI 側で計測した所要時間（ミリ秒）。
    """
    parts = [f"{elapsed_ms} ms", _format_cost(stats.cost_usd)]
    if stats.total_tokens is not None:
        parts.append(f"{stats.total_tokens} tokens")
    if stats.provider:
        parts.append(stats.provider)
    typer.echo(f"[{' | '.join(parts)}]", err=True)
