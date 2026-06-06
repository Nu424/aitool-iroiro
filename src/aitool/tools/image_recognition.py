"""OpenRouter チャット補完 API による画像認識。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aitool.errors import OpenRouterResponseError
from aitool.io import image_data_url
from aitool.tools.base import BaseTool


# --- リクエストペイロード構築 ---


def build_image_recognition_payload(text: str, image_paths: list[Path], model: str) -> dict[str, Any]:
    """画像認識用のチャット補完リクエストペイロードを組み立てる。

    Args:
        text: 画像に対する質問・指示テキスト。
        image_paths: 認識対象の画像パス一覧。
        model: 使用するモデル名。

    Returns:
        ``/chat/completions`` に POST する JSON ペイロード。
    """
    content: list[dict[str, Any]] = [{"type": "text", "text": text}]
    content.extend(
        {
            "type": "image_url",
            "image_url": {"url": image_data_url(path)},
        }
        for path in image_paths
    )

    return {
        "model": model,
        "messages": [{"role": "user", "content": content}],
    }


# --- ツール本体 ---


@dataclass(slots=True)
class ImageRecognitionTool(BaseTool):
    """テキストと画像から説明・回答テキストを得るツール。"""

    def run(self, text: str, image_paths: list[Path]) -> str:
        """画像認識を実行し、モデルのテキスト応答を返す。

        Args:
            text: 画像に対する質問・指示テキスト。
            image_paths: 認識対象の画像パス一覧。

        Returns:
            モデルが返したテキスト応答。

        Raises:
            OpenRouterResponseError: レスポンスにテキストが含まれない場合。
        """
        # ---ペイロードを作成し、OpenRouter API を呼び出す
        payload = build_image_recognition_payload(text, image_paths, self.model)
        with self.create_client() as client:
            response = client.chat_completions(payload)

        # ---レスポンスからテキストを取り出す
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterResponseError("Image recognition response did not include text.") from exc

        if not isinstance(content, str):
            raise OpenRouterResponseError("Image recognition response content was not text.")

        # ---テキストを返す
        return content
