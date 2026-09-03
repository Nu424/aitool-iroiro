"""Typer によるコマンドラインインターフェース。

各サブコマンドは対応するツールクラスへ処理を委譲し、
設定解決・入出力・エラー表示のみを担当する。

``--json`` を指定すると、標準出力へ共通の JSON エンベロープを 1 個だけ出す
（``reporting`` モジュールを参照）。未指定時は人間向けの表示になる。
"""

from __future__ import annotations

import json
import sys
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

import typer

from aitool.config import (
    API_KEY_ENV_VAR,
    OPENAI_API_KEY_ENV_VAR,
    describe_api_key,
    describe_model,
    resolve_api_key,
    resolve_model,
    resolve_openai_api_key,
)
from aitool.discovery import (
    FEATURE_LABELS,
    PRICING_NOTES,
    fetch_models,
    fetch_voices,
    filter_by_keyword,
    format_model_table,
    format_voice_list,
)
from aitool.errors import AitoolError
from aitool.io import ensure_output_parent
from aitool.models import (
    DEFAULT_MODELS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_VOICE,
    MODEL_ENV_VARS,
    ToolFeature,
)
from aitool.openrouter import OpenRouterClient
from aitool.reporting import (
    Stopwatch,
    build_envelope,
    build_error_envelope,
    echo_json,
    echo_stats_summary,
)
from aitool.tools.image_generation import ImageGenerationTool, save_generated_image
from aitool.tools.image_recognition import ImageRecognitionTool
from aitool.tools.stt import SpeechToTextTool, TimestampTranscriptionTool
from aitool.tools.tts import TextToSpeechTool
from aitool.usage import CallStats

# --- Typer アプリケーション ---

app = typer.Typer(
    help="Call OpenRouter models from the command line: images, vision, STT and TTS.",
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


class ModelFeature(str, Enum):
    """``models`` サブコマンドで絞り込める機能。"""

    image_generation = "image-generation"
    """画像出力に対応したモデル。"""
    image_recognition = "image-recognition"
    """画像入力に対応したモデル。"""
    stt = "stt"
    """文字起こし専用モデル。"""
    stt_llm = "stt-llm"
    """音声入力に対応したマルチモーダル LLM。"""
    tts = "tts"
    """音声出力に対応したモデル。"""


# --- 出力ストリームの設定 ---


def _configure_output_streams() -> None:
    """標準出力・標準エラーの文字化けとエンコードエラーを防ぐ。

    Windows の既定コンソールは cp932 などで、モデルが返した文字を
    エンコードできずに落ちることがある。そこで

    - リダイレクト・パイプ時は UTF-8 に切り替える
      （``--json`` の出力を受け取る側が UTF-8 を前提にできるようにする）
    - 対話コンソールでは端末のエンコーディングのまま
      （日本語が化けないようにする）

    とし、いずれの場合もエンコードできない文字は例外にせず置換する。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue

        is_tty = bool(getattr(stream, "isatty", lambda: False)())
        try:
            reconfigure(encoding=None if is_tty else "utf-8", errors="replace")
        except (ValueError, OSError):
            continue


@app.callback()
def main() -> None:
    """OpenRouter のモデルを CLI から呼び出す。"""
    _configure_output_streams()


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


def _resolve_openai_tool_settings(
    feature: ToolFeature,
    *,
    api_key: str | None,
    model: str | None,
) -> tuple[str, str]:
    """OpenAI を使うサブコマンド用に API キーとモデル名を解決する。"""
    return resolve_openai_api_key(api_key), resolve_model(feature, model)


def _echo_model(model: str, verbose: bool) -> None:
    """``--verbose`` 指定時に使用モデルを stderr へ表示する。"""
    if verbose:
        typer.echo(f"Using model: {model}", err=True)


def _save_text(text: str, output: Path | None) -> None:
    """テキストをファイルへ保存する。``output`` が None の場合は何もしない。

    標準出力への表示は呼び出し側が行う。``--json`` 指定時に
    テキストとエンベロープが混ざるのを避けるための分離。

    Args:
        text: 保存するテキスト。
        output: 保存先ファイルパス。None なら保存しない。
    """
    if output is None:
        return

    ensure_output_parent(output)
    output.write_text(text, encoding="utf-8")


def _report(
    command: str,
    *,
    model: str | None,
    result: Any,
    stats: CallStats,
    watch: Stopwatch,
    json_output: bool,
    verbose: bool,
    human_message: str | None = None,
) -> None:
    """コマンドの結果を JSON エンベロープまたは人間向け表示として出力する。

    Args:
        command: サブコマンド名。
        model: 解決済みのモデル名。情報系コマンドでは None。
        result: エンベロープの ``result`` セクション。
        stats: 呼び出しの計測値。
        watch: 所要時間の計測に使ったストップウォッチ。
        json_output: JSON エンベロープを出すかどうか。
        verbose: 計測値のサマリを stderr へ出すかどうか。
        human_message: JSON 未指定時に標準出力へ出す文字列。None なら何も出さない。
    """
    elapsed_ms = watch.elapsed_ms

    if json_output:
        echo_json(
            build_envelope(command, model=model, result=result, stats=stats, elapsed_ms=elapsed_ms)
        )
        return

    if human_message is not None:
        typer.echo(human_message)
    if verbose:
        echo_stats_summary(stats, elapsed_ms)


def _fail(command: str, error: AitoolError, json_output: bool) -> None:
    """ユーザー向けエラーを表示し、終了コード 1 で終了する。

    ``--json`` 指定時は失敗も JSON エンベロープとして標準出力へ出す。

    Args:
        command: サブコマンド名。
        error: 表示する例外。
        json_output: JSON エンベロープを出すかどうか。

    Raises:
        typer.Exit: 常に終了コード 1 で送出される。
    """
    if json_output:
        echo_json(build_error_envelope(command, error))
    else:
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
        stats: Annotated[
        bool,
        typer.Option(
            "--stats",
            help="Query /generation for authoritative cost and server-side timing. Adds ~10s.",
        ),
    ] = False,
model: Annotated[str | None, typer.Option("--model", help="Override the image generation model.")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", help="OpenRouter API key.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="HTTP timeout in seconds.")] = DEFAULT_TIMEOUT_SECONDS,
    json_output: Annotated[bool, typer.Option("--json", help="Print a JSON envelope instead of text.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """テキストまたは画像から新しい画像を生成する。

    ``--image`` を省略すると t2i、指定すると i2i として処理する。
    """
    watch = Stopwatch()
    try:
        # 設定解決
        resolved_api_key, resolved_model = _resolve_tool_settings(
            "image_generation",
            api_key=api_key,
            model=model,
        )
        _echo_model(resolved_model, verbose)

        # API 呼び出しとファイル保存
        tool = ImageGenerationTool(resolved_api_key, resolved_model, timeout, verbose)
        result = tool.run(
            text,
            image or [],
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            fetch_generation_stats=stats,
        )
        save_generated_image(result.value, output)

        # 結果表示
        _report(
            "generate-image",
            model=resolved_model,
            result={
                "output": str(output),
                "mime": result.value.mime,
                "message": result.value.message,
            },
            stats=result.stats,
            watch=watch,
            json_output=json_output,
            verbose=verbose,
            human_message=f"Saved image to {output}",
        )
    except AitoolError as error:
        _fail("generate-image", error, json_output)


# --- サブコマンド: 画像認識 ---


@app.command("recognize-image")
def recognize_image(
    text: Annotated[str, typer.Option("--text", "-t", help="Prompt text.")],
    image: Annotated[
        list[Path],
        typer.Option("--image", "-i", help="Input image path. Repeat for multiple images."),
    ],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Optional text output path.")] = None,
        stats: Annotated[
        bool,
        typer.Option(
            "--stats",
            help="Query /generation for authoritative cost and server-side timing. Adds ~10s.",
        ),
    ] = False,
model: Annotated[str | None, typer.Option("--model", help="Override the image recognition model.")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", help="OpenRouter API key.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="HTTP timeout in seconds.")] = DEFAULT_TIMEOUT_SECONDS,
    json_output: Annotated[bool, typer.Option("--json", help="Print a JSON envelope instead of text.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """画像とテキストから説明・回答テキストを得る。

    ``--output`` 未指定時は標準出力、指定時はファイルへ保存する。
    """
    watch = Stopwatch()
    try:
        resolved_api_key, resolved_model = _resolve_tool_settings(
            "image_recognition",
            api_key=api_key,
            model=model,
        )
        _echo_model(resolved_model, verbose)

        tool = ImageRecognitionTool(resolved_api_key, resolved_model, timeout, verbose)
        result = tool.run(text, image, fetch_generation_stats=stats)
        _save_text(result.value, output)

        _report(
            "recognize-image",
            model=resolved_model,
            result={"text": result.value, "output": str(output) if output else None},
            stats=result.stats,
            watch=watch,
            json_output=json_output,
            verbose=verbose,
            human_message=result.value if output is None else None,
        )
    except AitoolError as error:
        _fail("recognize-image", error, json_output)


# --- サブコマンド: 文字起こし ---


@app.command("transcribe")
def transcribe(
    audio: Annotated[Path, typer.Option("--audio", "-a", help="Input audio file path.")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="Optional transcript output path.")] = None,
    audio_format: Annotated[str | None, typer.Option("--format", help="Audio format. Defaults to extension.")] = None,
    mode: Annotated[STTMode, typer.Option("--mode", help="Transcription mode.")] = STTMode.dedicated,
    prompt: Annotated[str | None, typer.Option("--prompt", help="Prompt for --mode llm.")] = None,
        stats: Annotated[
        bool,
        typer.Option(
            "--stats",
            help="Query /generation for authoritative cost and server-side timing. Adds ~10s.",
        ),
    ] = False,
model: Annotated[str | None, typer.Option("--model", help="Override the STT model.")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", help="OpenRouter API key.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="HTTP timeout in seconds.")] = DEFAULT_TIMEOUT_SECONDS,
    json_output: Annotated[bool, typer.Option("--json", help="Print a JSON envelope instead of text.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """音声ファイルをテキストに文字起こしする。

    既定は STT 専用 API（``--mode dedicated``）。
    ``--output`` 未指定時は標準出力、指定時はファイルへ保存する。
    """
    watch = Stopwatch()
    try:
        resolved_api_key, resolved_model = _resolve_tool_settings("stt", api_key=api_key, model=model)
        _echo_model(resolved_model, verbose)

        tool = SpeechToTextTool(resolved_api_key, resolved_model, timeout, verbose)
        result = tool.run(
            audio,
            audio_format_override=audio_format,
            mode=mode.value,
            prompt=prompt,
            fetch_generation_stats=stats,
        )
        _save_text(result.value, output)

        _report(
            "transcribe",
            model=resolved_model,
            result={
                "text": result.value,
                "output": str(output) if output else None,
                "mode": mode.value,
            },
            stats=result.stats,
            watch=watch,
            json_output=json_output,
            verbose=verbose,
            human_message=result.value if output is None else None,
        )
    except AitoolError as error:
        _fail("transcribe", error, json_output)


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
    json_output: Annotated[bool, typer.Option("--json", help="Print a JSON envelope instead of the raw transcript.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """OpenAI 公式 API でタイムスタンプ付き文字起こしを行う。

    既定では ``verbose_json`` 形式の文字起こしをそのまま出力する。
    ``--json`` 指定時は他コマンドと同じエンベロープに包んで出力する。
    OpenAI API はコスト情報を返さないため、計測値は所要時間のみが埋まる。
    """
    watch = Stopwatch()
    try:
        resolved_api_key, resolved_model = _resolve_openai_tool_settings(
            "stt_timestamp",
            api_key=api_key,
            model=model,
        )
        _echo_model(resolved_model, verbose)

        tool = TimestampTranscriptionTool(resolved_api_key, resolved_model, timeout, verbose)
        result = tool.run(
            audio,
            audio_format_override=audio_format,
            granularity=granularity.value,
            language=language,
            prompt=prompt,
        )

        transcript = json.dumps(result.value, ensure_ascii=False, indent=2)
        _save_text(transcript, output)

        _report(
            "transcribe-timestamp",
            model=resolved_model,
            result={"transcript": result.value, "output": str(output) if output else None},
            stats=result.stats,
            watch=watch,
            json_output=json_output,
            verbose=verbose,
            human_message=transcript if output is None else None,
        )
    except AitoolError as error:
        _fail("transcribe-timestamp", error, json_output)


# --- サブコマンド: 音声合成 ---


@app.command("tts")
def tts(
    text: Annotated[str, typer.Option("--text", "-t", help="Text to synthesize.")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Path to save audio output.")],
    voice: Annotated[str, typer.Option("--voice", help="Voice identifier. See `aitool voices`.")] = DEFAULT_VOICE,
    response_format: Annotated[str, typer.Option("--format", help="Output audio format.")] = "mp3",
    speed: Annotated[float | None, typer.Option("--speed", help="Playback speed if supported.")] = None,
        stats: Annotated[
        bool,
        typer.Option(
            "--stats",
            help="Query /generation for authoritative cost and server-side timing. Adds ~10s.",
        ),
    ] = False,
model: Annotated[str | None, typer.Option("--model", help="Override the TTS model.")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", help="OpenRouter API key.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="HTTP timeout in seconds.")] = DEFAULT_TIMEOUT_SECONDS,
    json_output: Annotated[bool, typer.Option("--json", help="Print a JSON envelope instead of text.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """テキストから合成音声ファイルを生成する。"""
    watch = Stopwatch()
    try:
        resolved_api_key, resolved_model = _resolve_tool_settings("tts", api_key=api_key, model=model)
        _echo_model(resolved_model, verbose)

        tool = TextToSpeechTool(resolved_api_key, resolved_model, timeout, verbose)
        result = tool.run(
            text,
            voice=voice,
            response_format=response_format,
            speed=speed,
            fetch_generation_stats=stats,
        )

        ensure_output_parent(output)
        output.write_bytes(result.value.data)

        _report(
            "tts",
            model=resolved_model,
            result={"output": str(output), "content_type": result.value.content_type},
            stats=result.stats,
            watch=watch,
            json_output=json_output,
            verbose=verbose,
            human_message=f"Saved audio to {output}",
        )
    except AitoolError as error:
        _fail("tts", error, json_output)


# --- サブコマンド: モデル一覧 ---


@app.command("models")
def models(
    feature: Annotated[
        ModelFeature | None,
        typer.Option("--feature", "-f", help="Filter models by the feature they can serve."),
    ] = None,
    search: Annotated[
        str | None,
        typer.Option("--search", "-s", help="Filter by substring of the model id or name."),
    ] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", help="OpenRouter API key.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="HTTP timeout in seconds.")] = DEFAULT_TIMEOUT_SECONDS,
    json_output: Annotated[bool, typer.Option("--json", help="Print a JSON envelope instead of a table.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """OpenRouter で使用できるモデルを一覧表示する。

    ``--feature`` 未指定時は API 既定の一覧（テキスト出力モデル）を表示する。
    TTS・STT のモデルは ``--feature tts`` / ``--feature stt`` を付けないと現れない。
    """
    watch = Stopwatch()
    try:
        resolved_api_key = resolve_api_key(api_key)
        feature_value = feature.value if feature else None

        with OpenRouterClient(resolved_api_key, timeout=timeout) as client:
            found = filter_by_keyword(fetch_models(client, feature_value), search)

        if json_output:
            _report(
                "models",
                model=None,
                result={
                    "feature": feature_value,
                    "count": len(found),
                    "models": [entry.to_dict() for entry in found],
                },
                stats=CallStats(),
                watch=watch,
                json_output=True,
                verbose=verbose,
            )
            return

        # ---人間向けには機能ラベルを添えた表を出す
        heading = FEATURE_LABELS.get(feature_value or "", "All text-output models")
        typer.echo(f"{heading} - {len(found)} model(s)\n")
        typer.echo(format_model_table(found))

        # ---価格の単位がトークンでない機能には注記を添える
        note = PRICING_NOTES.get(feature_value or "")
        if note and found:
            typer.echo(f"\n{note}")
    except AitoolError as error:
        _fail("models", error, json_output)


# --- サブコマンド: ボイス一覧 ---


@app.command("voices")
def voices(
    model: Annotated[
        str | None,
        typer.Option("--model", "-m", help="Only show voices for models matching this substring."),
    ] = None,
    api_key: Annotated[str | None, typer.Option("--api-key", help="OpenRouter API key.")] = None,
    timeout: Annotated[float, typer.Option("--timeout", help="HTTP timeout in seconds.")] = DEFAULT_TIMEOUT_SECONDS,
    json_output: Annotated[bool, typer.Option("--json", help="Print a JSON envelope instead of a list.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", help="Print extra status to stderr.")] = False,
) -> None:
    """TTS モデルごとに使用できる声質（voice）を一覧表示する。

    ここで表示される識別子を ``tts --voice`` にそのまま渡せる。
    対応ボイスを公開していないモデルは一覧に現れない。
    """
    watch = Stopwatch()
    try:
        resolved_api_key = resolve_api_key(api_key)

        with OpenRouterClient(resolved_api_key, timeout=timeout) as client:
            found = fetch_voices(client, model)

        if json_output:
            _report(
                "voices",
                model=None,
                result={
                    "count": len(found),
                    "models": [
                        {"id": entry.id, "name": entry.name, "voices": entry.supported_voices}
                        for entry in found
                    ],
                },
                stats=CallStats(),
                watch=watch,
                json_output=True,
                verbose=verbose,
            )
            return

        typer.echo(f"TTS models with published voices - {len(found)} model(s)\n")
        typer.echo(format_voice_list(found))
    except AitoolError as error:
        _fail("voices", error, json_output)


# --- サブコマンド: 設定確認 ---


@app.command("config")
def config(
    json_output: Annotated[bool, typer.Option("--json", help="Print a JSON envelope instead of text.")] = False,
) -> None:
    """API キーの設定状況と、機能ごとの既定モデルを表示する。

    ``--model`` や ``--api-key`` を渡さずに実行したときに何が使われるか、
    またその値がどこから読まれているかを確認できる。API キーの値そのものは
    表示しない。
    """
    watch = Stopwatch()

    # ---API キーは有無と取得元のみを収集する
    keys = []
    for env_var in (API_KEY_ENV_VAR, OPENAI_API_KEY_ENV_VAR):
        is_set, source = describe_api_key(env_var)
        keys.append({"env_var": env_var, "is_set": is_set, "source": source})

    # ---既定モデルは解決結果と取得元を収集する
    features = []
    for feature in DEFAULT_MODELS:
        resolved, source = describe_model(feature)
        features.append(
            {
                "feature": feature,
                "env_var": MODEL_ENV_VARS[feature],
                "model": resolved,
                "source": source,
            }
        )

    if json_output:
        _report(
            "config",
            model=None,
            result={"api_keys": keys, "models": features},
            stats=CallStats(),
            watch=watch,
            json_output=True,
            verbose=False,
        )
        return

    typer.echo("API keys:")
    for key in keys:
        state = f"set ({key['source']})" if key["is_set"] else "not set"
        typer.echo(f"  {key['env_var']:<20} {state}")

    typer.echo("\nDefault models:")
    feature_width = max(len(entry["feature"]) for entry in features)
    model_width = max(len(entry["model"]) for entry in features)
    for entry in features:
        feature_cell = f"{entry['feature']:<{feature_width}}"
        model_cell = f"{entry['model']:<{model_width}}"
        typer.echo(f"  {feature_cell}  {model_cell}  ({entry['source']})")


if __name__ == "__main__":
    app()
