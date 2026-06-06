"""CLI 向けに整形して表示する例外クラスを定義するモジュール。"""

from __future__ import annotations


class AitoolError(Exception):
    """CLI でユーザーに分かりやすく表示する例外の基底クラス。"""


class ConfigError(AitoolError):
    """必須の設定が見つからない、または不正な場合に送出する。"""


class FileInputError(AitoolError):
    """入出力ファイルの検証や読み書きに失敗した場合に送出する。"""


class OpenRouterHTTPError(AitoolError):
    """OpenRouter が非成功の HTTP ステータスを返した場合に送出する。"""

    def __init__(self, status_code: int, body: str) -> None:
        """HTTP エラー情報を保持して初期化する。

        Args:
            status_code: HTTP ステータスコード。
            body: レスポンス本文（エラー詳細）。
        """
        self.status_code = status_code
        self.body = body
        super().__init__(f"OpenRouter request failed with status {status_code}: {body}")


class OpenRouterResponseError(AitoolError):
    """HTTP は成功したが、レスポンスの構造が想定と異なる場合に送出する。"""
