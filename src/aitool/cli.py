"""Typer によるコマンドラインインターフェース。

各サブコマンドは対応するツールクラスへ処理を委譲し、
設定解決・入出力・エラー表示のみを担当する。
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from aitool.config import resolve_api_key, resolve_google_api_key, resolve_model, resolve_openai_api_key
from aitool.errors import AitoolError
from aitool.io import ensure_output_parent
from aitool.models import DEFAULT_TIMEOUT_SECONDS, ToolFeature
from aitool.tools.image_generation import ImageGenerationTool, save_generated_image
from aitool.tools.image_recognition import ImageRecognitionTool
from aitool.tools.stt import SpeechToTextTool, TimestampTranscriptionTool
from aitool.tools.tts import TextToSpeechTool
from aitool.tools.video_recognition import VideoRecognitionTool

# --- Typer アプリケーション ---

app = typer.Typer(
    help="Run multimodal AI tasks from the command line through OpenRouter.",
    no_args_is_help=True,
)


class STTMode(str, Enum):
    """文字起こしの実行モード。"""

    dedicated = "dedicated"
    """STT 専用エンドポイント（``/audio/transcriptions``）を使用。"""
    llm = "llm"
    """マルチモーダル LLM 経由（``/chat/completions``）で文字起こし。"""


class STTGranularity(str, Enum):
    """タイムスタンプ付き文字起こしの粒度。"""

    segment = "segment"
    """セグメント単位のタイムスタンプ。"""
    word = "word"
    """単語単位のタイムスタンプ（セグメントも含む）。"""
    both = "both"
    """セグメントと単語の両方のタイムスタンプ。"""


# --- CLI 共通ヘルパー ---


def _resolve_tool_settings(
    feature: ToolFeature,
    *,
    api_key: str | None,
    model: str | None,
) -> tuple[str, str]:
    """サブコマンド実行前に API キーとモデル名を解決する。

    Args:
        feature: 対象ツール機能。
        api_key: CLI から渡された API キー（任意）。
        model: CLI から渡されたモデル名（任意）。

    Returns:
        解決済みの ``(api_key, model)`` タプル。
    """
    return resolve_api_key(api_key), resolve_model(feature, model)


def _resolve_google_tool_settings(
    feature: ToolFeature,
    *,
    api_key: str | None,
    model: str | None,
) -> tuple[str, str]:
    """Google GenAI を使うサブコマンド用に API キーとモデル名を解決する。"""
    return resolve_google_api_key(api_key), resolve_model(feature, model)


def _resolve_openai_tool_settings(
    feature: ToolFeature,
    *,
    api_key: str | None,
    model: str | None,
) -> tuple[str, str]:
    """OpenAI を使うサブコマンド用に API キーとモデル名を解決する。"""
    return resolve_openai_api_key(api_key), resolve_model(feature, model)


def _write_text_result(text: str, output: Path | None) -> None:
    """テキスト結果を標準出力またはファイルに書き出す。

    ``output`` 未指定時は標準出力へ、指定時は UTF-8 でファイル保存する。

    Args:
        text: 出力するテキスト。
        output: 保存先ファイルパス。None の場合は標準出力。
    """
    # ---outputがNoneの場合は標準出力に出力する
    if output is None:
        typer.echo(text)
        return

    # ---親フォルダがあることを確認して、ファイルに書き出す
    ensure_output_parent(output)
    output.write_text(text, encoding="utf-8")


def _echo_json(data: dict[str, object]) -> None:
    """メタ情報を JSON 形式で標準出力へ表示する。

    Args:
        data: 出力する辞書データ。
    """
    typer.echo(json.dumps(data, ensure_ascii=False, indent=2))


def _fail(error: AitoolError) -> None:
    """ユーザー向けエラーを stderr に表示し、終了コード 1 で終了する。

    Args:
        error: 表示する例外。

    Raises:
        typer.Exit: 常に終了コード 1 で送出される。
    """
    typer.echo(f"Error: {error}", err=True)
    raise typer.Exit(code=1) from error


# --- サブコマンド: 画像生成 ---


@app.command("generate-image")
def generate_image(
    text: Annotated[str, typer.Option("--text", "-t", help="Prompt text.")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Path to save the generated image.")],
    image: Annotated[
        list[Path] | None,
        typer.Option("--image", "-i", help="Input image path. Repeat for multiple images."),
    ] = None,
    aspect_ratio: Annotated[str | None, typer.Option("--aspect-ratio", help="Image aspect ratio.")] = None,
    image_size: Annotated[str | None, typer.Option("--image-size", help="Image size such as 1K, 2K, 4K.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Override the image generation model.")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", help="OpenRouter API key.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="HTTP timeout in seconds.")] = DEFAULT_TIMEOUT_SECONDS,
    json_output: Annotated[bool, typer.Option("--json", help="Print metadata as JSON.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """テキストまたは画像から新しい画像を生成する。

    ``--image`` を省略すると t2i、指定すると i2i として処理する。
    """
    try:
        # 設定解決
        resolved_api_key, resolved_model = _resolve_tool_settings(
            "image_generation",
            api_key=api_key,
            model=model,
        )
        if verbose:
            typer.echo(f"Using model: {resolved_model}", err=True)

        # API 呼び出しとファイル保存
        tool = ImageGenerationTool(resolved_api_key, resolved_model, timeout, verbose)
        result = tool.run(
            text,
            image or [],
            aspect_ratio=aspect_ratio,
            image_size=image_size,
        )
        save_generated_image(result, output)

        # 結果表示
        if json_output:
            _echo_json(
                {
                    "output": str(output),
                    "model": resolved_model,
                    "mime": result.mime,
                    "message": result.message,
                }
            )
        else:
            typer.echo(f"Saved image to {output}")
    except AitoolError as error:
        _fail(error)


# --- サブコマンド: 画像認識 ---


@app.command("recognize-image")
def recognize_image(
    text: Annotated[str, typer.Option("--text", "-t", help="Prompt text.")],
    image: Annotated[
        list[Path],
        typer.Option("--image", "-i", help="Input image path. Repeat for multiple images."),
    ],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Optional text output path.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Override the image recognition model.")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", help="OpenRouter API key.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="HTTP timeout in seconds.")] = DEFAULT_TIMEOUT_SECONDS,
    json_output: Annotated[bool, typer.Option("--json", help="Print metadata as JSON.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """画像とテキストから説明・回答テキストを得る。

    ``--output`` 未指定時は標準出力、指定時はファイルへ保存する。
    """
    try:
        resolved_api_key, resolved_model = _resolve_tool_settings(
            "image_recognition",
            api_key=api_key,
            model=model,
        )
        if verbose:
            typer.echo(f"Using model: {resolved_model}", err=True)

        tool = ImageRecognitionTool(resolved_api_key, resolved_model, timeout, verbose)
        result = tool.run(text, image)
        _write_text_result(result, output)

        if json_output:
            _echo_json({"output": str(output) if output else None, "model": resolved_model})
    except AitoolError as error:
        _fail(error)


# --- サブコマンド: 動画理解 ---


@app.command("recognize-video")
def recognize_video(
    text: Annotated[str, typer.Option("--text", "-t", help="Prompt text.")],
    video: Annotated[str, typer.Option("--video", "-v", help="Input video file path or YouTube URL.")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Optional text output path.")] = None,
    structured_output: Annotated[
        bool,
        typer.Option("--structured-output", help="Request JSON output using the built-in video schema."),
    ] = False,
    fps: Annotated[float | None, typer.Option("--fps", help="Custom video sampling frame rate.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Override the video recognition model.")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", help="Google GenAI API key.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="HTTP timeout in seconds.")] = DEFAULT_TIMEOUT_SECONDS,
    json_output: Annotated[bool, typer.Option("--json", help="Print metadata as JSON.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """動画とテキストから説明・回答テキストを得る。

    ローカル動画は File API でアップロードし、YouTube URL は直接 Gemini API に渡す。
    """
    try:
        resolved_api_key, resolved_model = _resolve_google_tool_settings(
            "video_recognition",
            api_key=api_key,
            model=model,
        )
        if verbose:
            typer.echo(f"Using model: {resolved_model}", err=True)

        tool = VideoRecognitionTool(resolved_api_key, resolved_model, timeout, verbose)
        result = tool.run(
            video,
            prompt=text,
            structured_output=structured_output,
            fps=fps,
        )
        _write_text_result(result, output)

        if json_output:
            _echo_json(
                {
                    "output": str(output) if output else None,
                    "model": resolved_model,
                    "structured_output": structured_output,
                    "fps": fps,
                }
            )
    except AitoolError as error:
        _fail(error)


# --- サブコマンド: 文字起こし ---


@app.command("transcribe")
def transcribe(
    audio: Annotated[Path, typer.Option("--audio", "-a", help="Input audio file path.")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Optional transcript output path.")] = None,
    audio_format: Annotated[str | None, typer.Option("--format", help="Audio format. Defaults to extension.")] = None,
    mode: Annotated[STTMode, typer.Option("--mode", help="Transcription mode.")] = STTMode.dedicated,
    prompt: Annotated[str | None, typer.Option("--prompt", help="Prompt for --mode llm.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Override the STT model.")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", help="OpenRouter API key.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="HTTP timeout in seconds.")] = DEFAULT_TIMEOUT_SECONDS,
    json_output: Annotated[bool, typer.Option("--json", help="Print metadata as JSON.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """音声ファイルをテキストに文字起こしする。

    既定は STT 専用 API（``--mode dedicated``）。
    ``--output`` 未指定時は標準出力、指定時はファイルへ保存する。
    """
    try:
        resolved_api_key, resolved_model = _resolve_tool_settings("stt", api_key=api_key, model=model)
        if verbose:
            typer.echo(f"Using model: {resolved_model}", err=True)

        tool = SpeechToTextTool(resolved_api_key, resolved_model, timeout, verbose)
        result = tool.run(
            audio,
            audio_format_override=audio_format,
            mode=mode.value,
            prompt=prompt,
        )
        _write_text_result(result, output)

        if json_output:
            _echo_json({"output": str(output) if output else None, "model": resolved_model, "mode": mode.value})
    except AitoolError as error:
        _fail(error)


# --- サブコマンド: タイムスタンプ付き文字起こし ---


@app.command("transcribe-timestamp")
def transcribe_timestamp(
    audio: Annotated[Path, typer.Option("--audio", "-a", help="Input audio file path.")],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Optional transcript JSON output path."),
    ] = None,
    audio_format: Annotated[str | None, typer.Option("--format", help="Audio format. Defaults to extension.")] = None,
    granularity: Annotated[
        STTGranularity,
        typer.Option("--granularity", help="Timestamp granularity."),
    ] = STTGranularity.segment,
    language: Annotated[
        str | None,
        typer.Option("--language", help="Input language ISO-639-1 code."),
    ] = None,
    prompt: Annotated[
        str | None,
        typer.Option("--prompt", help="Optional style-guiding prompt."),
    ] = None,
    model: Annotated[str | None, typer.Option("--model", help="Override the STT model.")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", help="OpenAI API key.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="HTTP timeout in seconds.")] = DEFAULT_TIMEOUT_SECONDS,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """OpenAI 公式 API でタイムスタンプ付き文字起こしを行う。

    結果は ``verbose_json`` 形式の JSON を標準出力または ``--output`` へ出力する。
    """
    try:
        resolved_api_key, resolved_model = _resolve_openai_tool_settings(
            "stt_timestamp",
            api_key=api_key,
            model=model,
        )
        if verbose:
            typer.echo(f"Using model: {resolved_model}", err=True)

        tool = TimestampTranscriptionTool(resolved_api_key, resolved_model, timeout, verbose)
        result = tool.run(
            audio,
            audio_format_override=audio_format,
            granularity=granularity.value,
            language=language,
            prompt=prompt,
        )
        _write_text_result(json.dumps(result, ensure_ascii=False, indent=2), output)
    except AitoolError as error:
        _fail(error)


# --- サブコマンド: 音声合成 ---


@app.command("tts")
def tts(
    text: Annotated[str, typer.Option("--text", "-t", help="Text to synthesize.")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Path to save audio output.")],
    voice: Annotated[str, typer.Option("--voice", help="Voice identifier.")] = "alloy",
    response_format: Annotated[str, typer.Option("--format", help="Output audio format.")] = "mp3",
    speed: Annotated[float | None, typer.Option("--speed", help="Playback speed if supported.")] = None,
    model: Annotated[str | None, typer.Option("--model", help="Override the TTS model.")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", help="OpenRouter API key.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="HTTP timeout in seconds.")] = DEFAULT_TIMEOUT_SECONDS,
    json_output: Annotated[bool, typer.Option("--json", help="Print metadata as JSON.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """テキストから合成音声ファイルを生成する。"""
    try:
        resolved_api_key, resolved_model = _resolve_tool_settings("tts", api_key=api_key, model=model)
        if verbose:
            typer.echo(f"Using model: {resolved_model}", err=True)

        tool = TextToSpeechTool(resolved_api_key, resolved_model, timeout, verbose)
        result = tool.run(text, voice=voice, response_format=response_format, speed=speed)

        ensure_output_parent(output)
        output.write_bytes(result.data)

        if json_output:
            _echo_json(
                {
                    "output": str(output),
                    "model": resolved_model,
                    "content_type": result.content_type,
                    "generation_id": result.generation_id,
                }
            )
        else:
            typer.echo(f"Saved audio to {output}")
    except AitoolError as error:
        _fail(error)


if __name__ == "__main__":
    app()
