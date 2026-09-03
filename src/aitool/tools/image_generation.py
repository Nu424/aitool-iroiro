"""OpenRouter Images API による画像生成（t2i / i2i）。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aitool.errors import OpenRouterResponseError
from aitool.io import ensure_output_parent, extension_for_mime, image_data_url
from aitool.tools.base import BaseTool, ToolResult
from aitool.usage import extract_stats


@dataclass(slots=True)
class GeneratedImage:
    """画像生成 API の結果を表すデータクラス。

    Attributes:
        data: 生成された画像のバイナリデータ。
        mime: 画像の MIME タイプ。
        message: モデルが返した付随テキスト（あれば）。Images API では通常 None。
    """

    data: bytes
    mime: str
    message: str | None = None

    @property
    def suggested_extension(self) -> str:
        """MIME タイプから推奨するファイル拡張子を返す。

        Returns:
            ドット付きの拡張子（例: ``.png``）。
        """
        return extension_for_mime(self.mime)


# --- リクエストペイロード構築 ---


def build_image_generation_payload(
    text: str,
    image_paths: list[Path],
    model: str,
    *,
    aspect_ratio: str | None = None,
    image_size: str | None = None,
) -> dict[str, Any]:
    """画像生成用の Images API リクエストペイロードを組み立てる。

    入力画像が無い場合は t2i（テキストのみ）、ある場合は i2i（``input_references``）として
    ペイロードを組み立てる。CLI の ``--image-size`` は API の ``resolution`` にマッピングする。

    Args:
        text: 生成・編集の指示テキスト。
        image_paths: 入力画像のパス一覧。空なら t2i。
        model: 使用するモデル名。
        aspect_ratio: 画像のアスペクト比（例: ``1:1``）。
        image_size: 画像サイズ（例: ``1K``, ``2K``）。API では ``resolution`` として送る。

    Returns:
        ``/images`` に POST する JSON ペイロード。
    """
    payload: dict[str, Any] = {
        "model": model,
        "prompt": text,
    }

    if aspect_ratio:
        payload["aspect_ratio"] = aspect_ratio
    if image_size:
        payload["resolution"] = image_size
    if image_paths:
        payload["input_references"] = [
            {
                "type": "image_url",
                "image_url": {"url": image_data_url(path)},
            }
            for path in image_paths
        ]

    return payload


def parse_image_generation_response(response: dict[str, Any]) -> GeneratedImage:
    """Images API レスポンスから生成画像を取り出す。

    Args:
        response: ``/images`` の JSON レスポンス。

    Returns:
        生成された画像データとメタ情報。

    Raises:
        OpenRouterResponseError: レスポンスに画像が含まれない、または Base64 が不正な場合。
    """
    try:
        item = response["data"][0]
        b64_json = item["b64_json"]
        media_type = item.get("media_type") or "image/png"
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenRouterResponseError("Image generation response did not include an image.") from exc

    if not isinstance(b64_json, str):
        raise OpenRouterResponseError("Generated image data was not text.")
    if not isinstance(media_type, str):
        raise OpenRouterResponseError("Generated image media type was not text.")

    try:
        data = base64.b64decode(b64_json)
    except Exception as exc:
        raise OpenRouterResponseError("Generated image data was not valid base64.") from exc

    return GeneratedImage(data=data, mime=media_type, message=None)


# --- ツール本体 ---


@dataclass(slots=True)
class ImageGenerationTool(BaseTool):
    """テキストまたは画像から新しい画像を生成するツール。"""

    def run(
        self,
        text: str,
        image_paths: list[Path],
        *,
        aspect_ratio: str | None = None,
        image_size: str | None = None,
        fetch_generation_stats: bool = False,
    ) -> ToolResult[GeneratedImage]:
        """画像生成を実行し、結果を返す。

        Args:
            text: 生成・編集の指示テキスト。
            image_paths: 入力画像のパス一覧。
            aspect_ratio: 画像のアスペクト比。
            image_size: 画像サイズ（API の ``resolution`` に対応）。
            fetch_generation_stats: ``/generation`` も照会して provider や
                サーバー側の所要時間を補うかどうか。

        Returns:
            生成された画像データとメタ情報、およびその呼び出しの計測値。

        Raises:
            OpenRouterResponseError: レスポンスに画像が含まれない場合。
        """
        payload = build_image_generation_payload(
            text,
            image_paths,
            self.model,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
        )
        with self.create_client() as client:
            response = client.images(payload)

            # ---Images API はリクエスト指定なしで usage にコストを含む
            stats = self.complete_stats(
                client,
                extract_stats(response),
                enabled=fetch_generation_stats,
            )

        return ToolResult(parse_image_generation_response(response), stats)


def save_generated_image(image: GeneratedImage, output_path: Path) -> Path:
    """生成画像をファイルに保存する。

    Args:
        image: 保存する画像データ。
        output_path: 出力先ファイルパス。

    Returns:
        保存先のパス。

    Raises:
        FileInputError: 出力先の親ディレクトリが存在しない場合。
    """
    ensure_output_parent(output_path)
    output_path.write_bytes(image.data)
    return output_path
