"""各ツール実装で共有する基底クラス。"""

from __future__ import annotations

from dataclasses import dataclass

from aitool.openrouter import OpenRouterClient


@dataclass(slots=True)
class BaseTool:
    """OpenRouter を利用するツールの共通設定を保持する基底クラス。

    Attributes:
        api_key: OpenRouter API キー。
        model: 使用するモデル名。
        timeout: HTTP タイムアウト（秒）。
        verbose: 詳細ログを stderr に出すかどうか。
    """

    api_key: str
    model: str
    timeout: float
    verbose: bool = False

    def create_client(self) -> OpenRouterClient:
        """このツール用の OpenRouter HTTP クライアントを生成する。

        Returns:
            設定済みの OpenRouterClient。``with`` 文での利用を想定。
        """
        return OpenRouterClient(self.api_key, timeout=self.timeout)
