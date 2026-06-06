"""ファイル入出力と Base64 エンコードのヘルパーを提供するモジュール。"""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

from aitool.errors import FileInputError, OpenRouterResponseError

# --- 拡張子と MIME / フォーマットの対応表 ---

IMAGE_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
"""画像拡張子から MIME タイプへの対応。"""

AUDIO_FORMAT_BY_SUFFIX = {
    ".mp3": "mp3",
    ".wav": "wav",
    ".m4a": "m4a",
    ".flac": "flac",
    ".ogg": "ogg",
    ".webm": "webm",
}
"""音声拡張子から OpenRouter 用フォーマット名への対応。"""


# --- 入力ファイルの検証 ---


def require_input_file(path: Path) -> Path:
    """入力パスが存在する通常ファイルであることを検証する。

    Args:
        path: 検証対象のファイルパス。

    Returns:
        検証済みのパス（そのまま返す）。

    Raises:
        FileInputError: ファイルが存在しない、または通常ファイルでない場合。
    """
    if not path.exists():
        raise FileInputError(f"Input file does not exist: {path}")
    if not path.is_file():
        raise FileInputError(f"Input path is not a file: {path}")
    return path


def ensure_output_parent(path: Path) -> None:
    """出力先ファイルの親ディレクトリが存在することを確認する。

    Args:
        path: 出力ファイルのパス。

    Raises:
        FileInputError: 親ディレクトリが存在しない場合。
    """
    parent = path.expanduser().resolve().parent
    if not parent.exists():
        raise FileInputError(f"Output directory does not exist: {parent}")


# --- Base64 エンコード ---


def encode_file_base64(path: Path) -> str:
    """ファイルの内容を Base64 文字列にエンコードする。

    Args:
        path: 読み込むファイルのパス。

    Returns:
        ASCII の Base64 エンコード文字列。

    Raises:
        FileInputError: ファイルが存在しない、または通常ファイルでない場合。
    """
    require_input_file(path)
    return base64.b64encode(path.read_bytes()).decode("ascii")


def image_data_url(path: Path) -> str:
    """画像ファイルを OpenRouter 用の data URL 形式に変換する。

    Args:
        path: 画像ファイルのパス。

    Returns:
        ``data:image/<mime>;base64,<data>`` 形式の文字列。

    Raises:
        FileInputError: 未対応の画像形式の場合。
    """
    suffix = path.suffix.lower()
    mime = IMAGE_MIME_BY_SUFFIX.get(suffix)
    if not mime: # 登録されていない場合は、mimetypes から推定する
        guessed_mime, _ = mimetypes.guess_type(path)
        mime = guessed_mime if guessed_mime in IMAGE_MIME_BY_SUFFIX.values() else None
    if not mime:
        supported = ", ".join(sorted(IMAGE_MIME_BY_SUFFIX))
        raise FileInputError(f"Unsupported image format for {path}. Supported: {supported}")

    return f"data:{mime};base64,{encode_file_base64(path)}"


def audio_format(path: Path, explicit_format: str | None = None) -> str:
    """音声ファイルのフォーマット名を取得する。

    Args:
        path: 音声ファイルのパス。
        explicit_format: CLI などから明示指定されたフォーマット名。
            指定時は拡張子推定より優先される。

    Returns:
        OpenRouter API に渡すフォーマット名（例: ``mp3``, ``wav``）。

    Raises:
        FileInputError: 拡張子から推定できず、明示指定もない場合。
    """
    # ---指定があればそれを使用する
    if explicit_format:
        return explicit_format.lower().strip()

    # ---指定がない場合は拡張子から推定する
    inferred = AUDIO_FORMAT_BY_SUFFIX.get(path.suffix.lower())
    if not inferred:
        supported = ", ".join(sorted(AUDIO_FORMAT_BY_SUFFIX))
        raise FileInputError(
            f"Could not infer audio format from {path}. Pass --format explicitly. "
            f"Known extensions: {supported}"
        )
    return inferred


# --- data URL のデコード ---


def decode_data_url(data_url: str) -> tuple[bytes, str]:
    """Base64 埋め込みの data URL からバイナリデータと MIME を取り出す。

    Args:
        data_url: ``data:<mime>;base64,<data>`` 形式の文字列。

    Returns:
        デコードされたバイト列と MIME タイプのタプル。

    Raises:
        OpenRouterResponseError: data URL の形式が不正、または Base64 デコードに失敗した場合。
    """
    marker = ";base64,"
    if marker not in data_url:
        raise OpenRouterResponseError("Generated image did not contain a base64 data URL.")

    metadata, encoded = data_url.split(marker, 1)
    mime = metadata.removeprefix("data:")
    try:
        return base64.b64decode(encoded), mime
    except ValueError as exc:
        raise OpenRouterResponseError("Generated image data was not valid base64.") from exc


def extension_for_mime(mime: str) -> str:
    """MIME タイプから推奨するファイル拡張子を返す。

    Args:
        mime: MIME タイプ（例: ``image/png``）。

    Returns:
        ドット付きの拡張子（例: ``.png``）。未知の MIME は ``.bin``。
    """
    if mime == "image/jpeg":
        return ".jpg"
    return {
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(mime, ".bin")
