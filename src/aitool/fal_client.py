"""fal のキュー API への HTTP リクエストを行う薄いクライアント。

fal は全モデルを ``https://queue.fal.run/{endpoint}`` 配下の共通キューで
提供している。リクエストを投入すると ``request_id`` と状態確認・結果取得用の
URL が返り、以後はその URL を叩く。生成物は CDN の公開 URL として返る。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from aitool.errors import FalHTTPError
from aitool.models import FAL_QUEUE_BASE_URL


class FalClient:
    """fal のキュー API を呼び出す HTTP クライアント。

    ``with`` 文で利用すると、終了時に接続を自動的に閉じる。

    Attributes:
        _client: 内部で保持する httpx.Client インスタンス。
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = FAL_QUEUE_BASE_URL,
        timeout: float = 120.0,
    ) -> None:
        """クライアントを初期化し、認証ヘッダーを設定する。

        Args:
            api_key: fal API キー。
            base_url: キュー API のベース URL。
            timeout: リクエストのタイムアウト（秒）。
        """
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={"Authorization": f"Key {api_key}"},
        )

    def close(self) -> None:
        """保持している HTTP 接続を閉じる。"""
        self._client.close()

    def __enter__(self) -> "FalClient":
        """コンテキストマネージャとして自身を返す。"""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """コンテキスト終了時に接続を閉じる。"""
        self.close()

    def _raise_for_status(self, response: httpx.Response) -> None:
        """レスポンスが成功でなければ FalHTTPError を送出する。

        Args:
            response: 検査対象の HTTP レスポンス。

        Raises:
            FalHTTPError: ステータスコードが成功範囲外の場合。
        """
        if response.is_success:
            return
        raise FalHTTPError(response.status_code, response.text)

    def submit(self, endpoint: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """リクエストをキューへ投入する。

        Args:
            endpoint: fal のエンドポイント ID（例: ``minimax/h3-max-turbo/text-to-video``）。
            payload: モデル固有の入力オブジェクト。

        Returns:
            ``request_id`` / ``status_url`` / ``response_url`` を含む JSON 辞書。

        Raises:
            FalHTTPError: HTTP エラーが返った場合。
        """
        response = self._client.post(f"/{endpoint.strip('/')}", json=payload)
        self._raise_for_status(response)
        return response.json()

    def get_json(self, url: str) -> dict[str, Any]:
        """投入時に返された URL（絶対 URL）へ GET し、JSON を返す。

        状態確認（``status_url``）と結果取得（``response_url``）の両方に使う。
        サブパス付きエンドポイントでは URL の組み立て規則が自明でないため、
        自前で組み立てず、サーバーが返した URL をそのまま使う。

        Args:
            url: 投入時に返された絶対 URL。

        Returns:
            パース済みの JSON レスポンス辞書。

        Raises:
            FalHTTPError: HTTP エラーが返った場合。
        """
        response = self._client.get(url)
        self._raise_for_status(response)
        return response.json()

    def download(self, url: str) -> tuple[bytes, httpx.Headers]:
        """生成物の公開 URL からバイナリを取得する。

        CDN は認証を要求しないため、認証ヘッダーを付けずに別接続で取得する。

        Args:
            url: 生成物の URL。

        Returns:
            レスポンス本文のバイト列とヘッダーのタプル。

        Raises:
            FalHTTPError: HTTP エラーが返った場合。
        """
        response = httpx.get(url, timeout=self._client.timeout, follow_redirects=True)
        self._raise_for_status(response)
        return response.content, response.headers
