"""音声文字起こし（STT）ツール。

専用エンドポイント（``/audio/transcriptions``）と、
マルチモーダル LLM 経由（``/chat/completions``）の 2 モードをサポートする。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from aitool.errors import OpenRouterResponseError
from aitool.io import audio_format, encode_file_base64
from aitool.tools.base import BaseTool

TranscriptionMode = Literal["dedicated", "llm"]
"""文字起こしモード。``dedicated`` は STT 専用 API、``llm`` はチャット補完経由。"""


# --- リクエストペイロード構築 ---


def build_transcription_payload(
    audio_path: Path,
    model: str,
    *,
    audio_format_override: str | None = None,
) -> dict[str, Any]:
    """STT 専用エンドポイント用のリクエストペイロードを組み立てる。

    Args:
        audio_path: 文字起こし対象の音声ファイルパス。
        model: 使用する STT モデル名。
        audio_format_override: 音声フォーマットの明示指定（未指定時は拡張子から推定）。

    Returns:
        ``/audio/transcriptions`` に POST する JSON ペイロード。
    """
    return {
        "model": model,
        "input_audio": {
            "data": encode_file_base64(audio_path),
            "format": audio_format(audio_path, audio_format_override),
        },
    }


def build_llm_transcription_payload(
    audio_path: Path,
    model: str,
    *,
    prompt: str,
    audio_format_override: str | None = None,
) -> dict[str, Any]:
    """マルチモーダル LLM 経由の文字起こし用ペイロードを組み立てる。

    Args:
        audio_path: 文字起こし対象の音声ファイルパス。
        model: 使用するマルチモーダルモデル名。
        prompt: 文字起こしの指示プロンプト。
        audio_format_override: 音声フォーマットの明示指定。

    Returns:
        ``/chat/completions`` に POST する JSON ペイロード。
    """
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": encode_file_base64(audio_path),
                            "format": audio_format(audio_path, audio_format_override),
                        },
                    },
                ],
            }
        ],
    }


# --- ツール本体 ---


@dataclass(slots=True)
class SpeechToTextTool(BaseTool):
    """音声ファイルをテキストに変換するツール。"""

    def run(
        self,
        audio_path: Path,
        *,
        audio_format_override: str | None = None,
        mode: TranscriptionMode = "dedicated",
        prompt: str | None = None,
    ) -> str:
        """文字起こしを実行し、テキスト結果を返す。

        Args:
            audio_path: 文字起こし対象の音声ファイルパス。
            audio_format_override: 音声フォーマットの明示指定。
            mode: ``dedicated``（STT 専用 API）または ``llm``（チャット補完経由）。
            prompt: ``llm`` モード時の指示プロンプト。未指定時は既定文を使用。

        Returns:
            文字起こし結果のテキスト。

        Raises:
            OpenRouterResponseError: レスポンスにテキストが含まれない場合。
        """
        if mode == "llm":
            return self._run_llm_mode(audio_path, audio_format_override, prompt)

        return self._run_dedicated_mode(audio_path, audio_format_override)

    def _run_llm_mode(
        self,
        audio_path: Path,
        audio_format_override: str | None,
        prompt: str | None,
    ) -> str:
        """マルチモーダル LLM 経由で文字起こしする。

        Args:
            audio_path: 音声ファイルパス。
            audio_format_override: 音声フォーマットの明示指定。
            prompt: 指示プロンプト。

        Returns:
            文字起こし結果のテキスト。
        """
        # ---ペイロードを作成し、OpenRouter API を呼び出す
        payload = build_llm_transcription_payload(
            audio_path,
            self.model,
            prompt=prompt or "この音声ファイルを文字起こししてください。",
            audio_format_override=audio_format_override,
        )
        with self.create_client() as client:
            response = client.chat_completions(payload)

        # ---レスポンスからテキストを取り出す
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterResponseError("LLM transcription response did not include text.") from exc
        if not isinstance(content, str):
            raise OpenRouterResponseError("LLM transcription response content was not text.")
        return content

    def _run_dedicated_mode(
        self,
        audio_path: Path,
        audio_format_override: str | None,
    ) -> str:
        """STT 専用エンドポイントで文字起こしする。

        Args:
            audio_path: 音声ファイルパス。
            audio_format_override: 音声フォーマットの明示指定。

        Returns:
            文字起こし結果のテキスト。
        """
        # ---ペイロードを作成し、OpenRouter API を呼び出す
        payload = build_transcription_payload(
            audio_path,
            self.model,
            audio_format_override=audio_format_override,
        )
        with self.create_client() as client:
            response = client.audio_transcriptions(payload)

        # ---レスポンスからテキストを取り出す
        text = response.get("text")
        if not isinstance(text, str):
            raise OpenRouterResponseError("Transcription response did not include text.")
        return text
