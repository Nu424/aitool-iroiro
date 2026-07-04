"""音声文字起こし（STT）ツール。

専用エンドポイント（``/audio/transcriptions``）と、
マルチモーダル LLM 経由（``/chat/completions``）の 2 モードをサポートする。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from aitool.errors import OpenAIResponseError, OpenRouterResponseError
from aitool.io import audio_format, encode_file_base64, require_input_file
from aitool.openai_client import OpenAIClient
from aitool.tools.base import BaseTool

TranscriptionMode = Literal["dedicated", "llm"]
"""文字起こしモード。``dedicated`` は STT 専用 API、``llm`` はチャット補完経由。"""

TimestampGranularity = Literal["segment", "word", "both"]
"""タイムスタンプの粒度。``segment`` / ``word`` / ``both``。"""


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


def _timestamp_granularities(granularity: TimestampGranularity) -> list[str]:
    """粒度指定から OpenAI API 用の ``timestamp_granularities`` 配列を返す。"""
    if granularity == "segment":
        return ["segment"]
    if granularity == "word":
        return ["segment", "word"]
    return ["segment", "word"]


def _upload_filename(audio_path: Path, audio_format_override: str | None) -> str:
    """multipart 送信用のファイル名を組み立てる。

    ``--format`` 指定時は拡張子を差し替え、OpenAI の形式判定に合わせる。
    """
    fmt = audio_format(audio_path, audio_format_override)
    return f"audio.{fmt}"


def build_timestamp_transcription_form(
    audio_path: Path,
    model: str,
    *,
    granularity: TimestampGranularity = "segment",
    language: str | None = None,
    prompt: str | None = None,
    audio_format_override: str | None = None,
) -> tuple[dict[str, Any], dict[str, tuple[str, bytes, str | None]]]:
    """OpenAI 公式 API 用の multipart フォームデータを組み立てる。

    Args:
        audio_path: 文字起こし対象の音声ファイルパス。
        model: 使用する STT モデル名（既定は ``whisper-1``）。
        granularity: タイムスタンプの粒度。
        language: 入力言語の ISO-639-1 コード（任意）。
        prompt: 文字起こしのスタイルを誘導するプロンプト（任意）。
        audio_format_override: 音声フォーマットの明示指定。

    Returns:
        ``(data, files)`` のタプル。``data`` はフォームフィールド、
        ``files`` は multipart のファイルフィールド。
    """
    require_input_file(audio_path)
    data: dict[str, Any] = {
        "model": model,
        "response_format": "verbose_json",
    }
    for index, value in enumerate(_timestamp_granularities(granularity)):
        data[f"timestamp_granularities[{index}]"] = value
    if language:
        data["language"] = language
    if prompt:
        data["prompt"] = prompt

    files = {
        "file": (
            _upload_filename(audio_path, audio_format_override),
            audio_path.read_bytes(),
            None,
        ),
    }
    return data, files


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


@dataclass(slots=True)
class TimestampTranscriptionTool:
    """OpenAI 公式 API でタイムスタンプ付き文字起こしを行うツール。"""

    api_key: str
    model: str
    timeout: float
    verbose: bool = False

    def run(
        self,
        audio_path: Path,
        *,
        audio_format_override: str | None = None,
        granularity: TimestampGranularity = "segment",
        language: str | None = None,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        """タイムスタンプ付き文字起こしを実行し、verbose_json を返す。

        Args:
            audio_path: 文字起こし対象の音声ファイルパス。
            audio_format_override: 音声フォーマットの明示指定。
            granularity: タイムスタンプの粒度。
            language: 入力言語の ISO-639-1 コード（任意）。
            prompt: 文字起こしのスタイルを誘導するプロンプト（任意）。

        Returns:
            OpenAI ``verbose_json`` レスポンス辞書。

        Raises:
            OpenAIResponseError: レスポンスに ``text`` が含まれない場合。
        """
        data, files = build_timestamp_transcription_form(
            audio_path,
            self.model,
            granularity=granularity,
            language=language,
            prompt=prompt,
            audio_format_override=audio_format_override,
        )
        with OpenAIClient(self.api_key, timeout=self.timeout) as client:
            response = client.audio_transcriptions(data, files)

        text = response.get("text")
        if not isinstance(text, str):
            raise OpenAIResponseError("Timestamp transcription response did not include text.")
        return response
