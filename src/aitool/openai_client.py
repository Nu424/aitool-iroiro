"""OpenAI API への HTTP リクエストを行う薄いクライアント。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from aitool.errors import OpenAIHTTPError
from aitool.models import OPENAI_BASE_URL


class OpenAIClient:
    """OpenAI の各エンドポイントへ POST する HTTP クライアント。

    ``with`` 文で利用すると、終了時に接続を自動的に閉じる。

    Attributes:
        _client: 内部で保持する httpx.Client インスタンス。
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = OPENAI_BASE_URL,
        timeout: float = 120.0,
    ) -> None:
        """クライアントを初期化し、認証ヘッダーを設定する。

        Args:
            api_key: OpenAI API キー。
            base_url: API のベース URL。
            timeout: リクエストのタイムアウト（秒）。
        """
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
            },
        )

    def close(self) -> None:
        """保持している HTTP 接続を閉じる。"""
        self._client.close()

    def __enter__(self) -> "OpenAIClient":
        """コンテキストマネージャとして自身を返す。"""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """コンテキスト終了時に接続を閉じる。"""
        self.close()

    def _raise_for_status(self, response: httpx.Response) -> None:
        """レスポンスが成功でなければ OpenAIHTTPError を送出する。

        Args:
            response: 検査対象の HTTP レスポンス。

        Raises:
            OpenAIHTTPError: ステータスコードが成功範囲外の場合。
        """
        if response.is_success:
            return
        raise OpenAIHTTPError(response.status_code, response.text)

    def audio_transcriptions(
        self,
        data: Mapping[str, Any],
        files: Mapping[str, tuple[str, bytes, str | None]],
    ) -> dict[str, Any]:
        """音声文字起こし API を multipart/form-data で呼び出す。

        Args:
            data: フォームフィールド（model, response_format など）。
            files: ファイルフィールド。キーはフィールド名、値は
                ``(filename, content, content_type)`` のタプル。

        Returns:
            API レスポンスの JSON 辞書。

        Raises:
            OpenAIHTTPError: HTTP エラーが返った場合。
        """
        response = self._client.post("/audio/transcriptions", data=data, files=files)
        self._raise_for_status(response)
        return response.json()
