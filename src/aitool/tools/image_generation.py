"""OpenRouter チャット補完 API による画像生成（t2i / i2i）。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aitool.errors import OpenRouterResponseError
from aitool.io import decode_data_url, ensure_output_parent, extension_for_mime, image_data_url
from aitool.tools.base import BaseTool


@dataclass(slots=True)
class GeneratedImage:
    """画像生成 API の結果を表すデータクラス。

    Attributes:
        data: 生成された画像のバイナリデータ。
        mime: 画像の MIME タイプ。
        message: モデルが返した付随テキスト（あれば）。
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
    """画像生成用のチャット補完リクエストペイロードを組み立てる。

    入力画像が無い場合は t2i（テキストのみ）、ある場合は i2i（画像＋テキスト）として
    ``content`` の形式を切り替える。

    Args:
        text: 生成・編集の指示テキスト。
        image_paths: 入力画像のパス一覧。空なら t2i。
        model: 使用するモデル名。
        aspect_ratio: 画像のアスペクト比（例: ``1:1``）。
        image_size: 画像サイズ（例: ``1K``, ``2K``）。

    Returns:
        ``/chat/completions`` に POST する JSON ペイロード。
    """
    content: str | list[dict[str, Any]]
    if image_paths:
        # i2i: テキストと画像 URL の配列
        content = [{"type": "text", "text": text}]
        content.extend(
            {
                "type": "image_url",
                "image_url": {"url": image_data_url(path)},
            }
            for path in image_paths
        )
    else:
        # t2i: テキストのみ
        content = text

    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
        "modalities": ["image", "text"],
    }

    image_config: dict[str, str] = {}
    if aspect_ratio:
        image_config["aspect_ratio"] = aspect_ratio
    if image_size:
        image_config["image_size"] = image_size
    if image_config:
        payload["image_config"] = image_config

    return payload


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
    ) -> GeneratedImage:
        """画像生成を実行し、結果を返す。

        Args:
            text: 生成・編集の指示テキスト。
            image_paths: 入力画像のパス一覧。
            aspect_ratio: 画像のアスペクト比。
            image_size: 画像サイズ。

        Returns:
            生成された画像データとメタ情報。

        Raises:
            OpenRouterResponseError: レスポンスに画像が含まれない場合。
        """
        # ---ペイロードを作成し、OpenRouter API を呼び出す
        payload = build_image_generation_payload(
            text,
            image_paths,
            self.model,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
        )
        with self.create_client() as client:
            response = client.chat_completions(payload)

        # レスポンスから Base64 画像 URL を取り出す
        try:
            message = response["choices"][0]["message"]
            image_url = message["images"][0]["image_url"]["url"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterResponseError("Image generation response did not include an image.") from exc

        if not isinstance(image_url, str):
            raise OpenRouterResponseError("Generated image URL was not text.")

        # ---出力された画像URLをデコードして、データとMIMEを取得する
        data, mime = decode_data_url(image_url)
        content = message.get("content")
        return GeneratedImage(
            data=data,
            mime=mime,
            message=content if isinstance(content, str) else None,
        )


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
