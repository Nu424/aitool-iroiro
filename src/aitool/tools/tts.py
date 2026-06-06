"""OpenRouter 音声合成（TTS）API によるテキスト読み上げ。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from aitool.tools.base import BaseTool


@dataclass(slots=True)
class SpeechGenerationResult:
    """音声合成 API の結果を表すデータクラス。

    Attributes:
        data: 生成された音声のバイナリデータ。
        content_type: レスポンスの Content-Type ヘッダー値。
        generation_id: OpenRouter の生成 ID（X-Generation-Id ヘッダー）。
    """

    data: bytes
    content_type: str | None
    generation_id: str | None


# --- リクエストペイロード構築 ---


def build_speech_payload(
    text: str,
    model: str,
    *,
    voice: str,
    response_format: str,
    speed: float | None = None,
) -> dict[str, Any]:
    """音声合成用のリクエストペイロードを組み立てる。

    Args:
        text: 読み上げるテキスト。
        model: 使用する TTS モデル名。
        voice: 音声の種類（モデルごとに利用可能な値が異なる）。
        response_format: 出力形式（``mp3`` または ``pcm``）。
        speed: 再生速度。モデルが対応している場合のみ有効。

    Returns:
        ``/audio/speech`` に POST する JSON ペイロード。
    """
    payload: dict[str, Any] = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": response_format,
    }
    if speed is not None:
        payload["speed"] = speed
    return payload


# --- ツール本体 ---


@dataclass(slots=True)
class TextToSpeechTool(BaseTool):
    """テキストから合成音声を生成するツール。"""

    def run(
        self,
        text: str,
        *,
        voice: str,
        response_format: str,
        speed: float | None = None,
    ) -> SpeechGenerationResult:
        """音声合成を実行し、バイナリデータとメタ情報を返す。

        Args:
            text: 読み上げるテキスト。
            voice: 音声の種類。
            response_format: 出力形式（``mp3`` または ``pcm``）。
            speed: 再生速度。

        Returns:
            生成された音声データとレスポンスヘッダー情報。
        """
        # ---ペイロードを作成し、OpenRouter API を呼び出す
        payload = build_speech_payload(
            text,
            self.model,
            voice=voice,
            response_format=response_format,
            speed=speed,
        )
        with self.create_client() as client:
            data, headers = client.audio_speech(payload)

        # ---レスポンスから音声データとメタ情報を取り出し、構造的に返却する
        return SpeechGenerationResult(
            data=data,
            content_type=_get_header(headers, "Content-Type"),
            generation_id=_get_header(headers, "X-Generation-Id"),
        )


def _get_header(headers: httpx.Headers, key: str) -> str | None:
    """レスポンスヘッダーから指定キーの値を取得する。

    Args:
        headers: HTTP レスポンスヘッダー。
        key: 取得するヘッダー名。

    Returns:
        ヘッダー値。存在しないか空の場合は None。
    """
    value = headers.get(key)
    return value or None
