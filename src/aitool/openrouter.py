"""OpenRouter API への HTTP リクエストを行う薄いクライアント。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from aitool.errors import OpenRouterHTTPError
from aitool.models import OPENROUTER_BASE_URL


class OpenRouterClient:
    """OpenRouter の各エンドポイントへ POST する HTTP クライアント。

    ``with`` 文で利用すると、終了時に接続を自動的に閉じる。

    Attributes:
        _client: 内部で保持する httpx.Client インスタンス。
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = OPENROUTER_BASE_URL,
        timeout: float = 120.0,
    ) -> None:
        """クライアントを初期化し、認証ヘッダーを設定する。

        Args:
            api_key: OpenRouter API キー。
            base_url: API のベース URL。
            timeout: リクエストのタイムアウト（秒）。
        """
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    def close(self) -> None:
        """保持している HTTP 接続を閉じる。"""
        self._client.close()

    def __enter__(self) -> "OpenRouterClient":
        """コンテキストマネージャとして自身を返す。"""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """コンテキスト終了時に接続を閉じる。"""
        self.close()

    # --- 低レベル HTTP ---

    def _raise_for_status(self, response: httpx.Response) -> None:
        """レスポンスが成功でなければ OpenRouterHTTPError を送出する。

        Args:
            response: 検査対象の HTTP レスポンス。

        Raises:
            OpenRouterHTTPError: ステータスコードが成功範囲外の場合。
        """
        if response.is_success:
            return
        raise OpenRouterHTTPError(response.status_code, response.text)

    def get_json(self, endpoint: str, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """JSON レスポンスを期待する GET リクエストを送る。

        Args:
            endpoint: API エンドポイントパス（例: ``/models``）。
            params: クエリパラメータ。

        Returns:
            パース済みの JSON レスポンス辞書。

        Raises:
            OpenRouterHTTPError: HTTP エラーが返った場合。
        """
        response = self._client.get(endpoint, params=dict(params) if params else None)
        self._raise_for_status(response)
        return response.json()

    def post_json(self, endpoint: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        """JSON レスポンスを期待する POST リクエストを送る。

        Args:
            endpoint: API エンドポイントパス（例: ``/chat/completions``）。
            payload: リクエストボディとして送る JSON オブジェクト。

        Returns:
            パース済みの JSON レスポンス辞書。

        Raises:
            OpenRouterHTTPError: HTTP エラーが返った場合。
        """
        response = self._client.post(endpoint, json=payload)
        self._raise_for_status(response)
        return response.json()

    def post_bytes(
        self,
        endpoint: str,
        payload: Mapping[str, Any],
    ) -> tuple[bytes, httpx.Headers]:
        """バイナリ本文を期待する POST リクエストを送る。

        Args:
            endpoint: API エンドポイントパス（例: ``/audio/speech``）。
            payload: リクエストボディとして送る JSON オブジェクト。

        Returns:
            レスポンス本文のバイト列とヘッダーのタプル。

        Raises:
            OpenRouterHTTPError: HTTP エラーが返った場合。
        """
        response = self._client.post(endpoint, json=payload)
        self._raise_for_status(response)
        return response.content, response.headers

    # --- エンドポイント別ラッパー ---

    def chat_completions(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """チャット補完 API を呼び出す。

        Args:
            payload: チャット補完リクエストの JSON ペイロード。

        Returns:
            API レスポンスの JSON 辞書。
        """
        return self.post_json("/chat/completions", payload)

    def images(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """画像生成 API を呼び出す。

        Args:
            payload: 画像生成リクエストの JSON ペイロード。

        Returns:
            API レスポンスの JSON 辞書。
        """
        return self.post_json("/images", payload)

    def audio_transcriptions(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """音声文字起こし API を呼び出す。

        Args:
            payload: 文字起こしリクエストの JSON ペイロード。

        Returns:
            API レスポンスの JSON 辞書。
        """
        return self.post_json("/audio/transcriptions", payload)

    def audio_speech(self, payload: Mapping[str, Any]) -> tuple[bytes, httpx.Headers]:
        """音声合成 API を呼び出す。

        Args:
            payload: 音声合成リクエストの JSON ペイロード。

        Returns:
            生成された音声データとレスポンスヘッダーのタプル。
        """
        return self.post_bytes("/audio/speech", payload)

    def models(self, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """モデル一覧 API を呼び出す。

        ``input_modalities`` / ``output_modalities`` クエリで機能ごとに絞り込める。
        既定の一覧はテキスト出力モデルのみで、TTS・STT モデルは
        ``output_modalities`` を明示しないと返らない点に注意。

        Args:
            params: クエリパラメータ。

        Returns:
            API レスポンスの JSON 辞書。
        """
        return self.get_json("/models", params)

    def generation(self, generation_id: str) -> dict[str, Any]:
        """生成記録 API を呼び出し、コストや所要時間を取得する。

        Args:
            generation_id: 対象の生成 ID。

        Returns:
            API レスポンスの JSON 辞書。
        """
        return self.get_json("/generation", {"id": generation_id})
