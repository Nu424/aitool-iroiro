"""各ツール実装で共有する基底クラスと戻り値の器。"""

from __future__ import annotations

from dataclasses import dataclass, field

from aitool.openrouter import OpenRouterClient
from aitool.usage import CallStats, enrich_from_generation


@dataclass(slots=True)
class ToolResult[T]:
    """ツールの実行結果と、その呼び出しの計測値をまとめた器。

    Attributes:
        value: ツール固有の結果本体（テキスト、生成画像など）。
        stats: トークン・コスト・所要時間の計測値。
    """

    value: T
    stats: CallStats = field(default_factory=CallStats)


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

    def complete_stats(self, client: OpenRouterClient, stats: CallStats) -> CallStats:
        """コストが欠けていれば ``/generation`` を照会して計測値を補う。

        レスポンスに ``usage`` を含まない ``/audio/speech`` のためのフォールバック。
        クライアントを閉じる前に呼ぶ必要がある。

        Args:
            client: 呼び出しに使用したクライアント。
            stats: インラインで取得済みの計測値。

        Returns:
            補完後の計測値。補完できなかった場合は入力と同じ内容。
        """
        return enrich_from_generation(client, stats)
