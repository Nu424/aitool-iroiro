"""OpenRouter のモデル一覧と対応ボイスを取得するモジュール。

``GET /models`` は既定ではテキスト出力モデルしか返さない。TTS・STT の
モデルは ``output_modalities`` クエリを明示して初めて一覧に現れる。
このモジュールは、CLI の機能名からその絞り込みクエリへの対応づけを持つ。

対応ボイスは各モデルの ``supported_voices`` から取得できるため、
リポジトリ側に静的なボイス表を持つ必要はない。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from aitool.openrouter import OpenRouterClient

# --- 機能とモデル絞り込みクエリの対応 ---

FEATURE_FILTERS: Final[dict[str, dict[str, str]]] = {
    "image-generation": {"output_modalities": "image"},
    "image-recognition": {"input_modalities": "image"},
    "stt": {"output_modalities": "transcription"},
    "stt-llm": {"input_modalities": "audio"},
    "tts": {"output_modalities": "speech"},
}
"""CLI の ``--feature`` 値から ``/models`` のクエリパラメータへの対応。"""

FEATURE_LABELS: Final[dict[str, str]] = {
    "image-generation": "Image generation (generate-image)",
    "image-recognition": "Image recognition (recognize-image)",
    "stt": "Speech to text (transcribe --mode dedicated)",
    "stt-llm": "Speech to text via LLM (transcribe --mode llm)",
    "tts": "Text to speech (tts)",
}
"""機能名の人間向けラベル。"""

TOKENS_PER_UNIT: Final[int] = 1_000_000
"""価格表示の単位。API は 1 トークンあたりの価格を返すため 100 万倍して表示する。"""


# --- モデル情報 ---


@dataclass(slots=True)
class ModelInfo:
    """``/models`` が返すモデル 1 件分の情報。

    Attributes:
        id: モデルスラッグ（``--model`` に渡す値）。
        name: 表示用のモデル名。
        context_length: コンテキスト長。取得できない場合は None。
        prompt_price: 入力 100 万トークンあたりの価格（USD）。
        completion_price: 出力 100 万トークンあたりの価格（USD）。
        input_modalities: 入力モダリティ一覧。
        output_modalities: 出力モダリティ一覧。
        supported_voices: 対応ボイス識別子の一覧（TTS モデルのみ）。
    """

    id: str
    name: str
    context_length: int | None
    prompt_price: float | None
    completion_price: float | None
    input_modalities: list[str]
    output_modalities: list[str]
    supported_voices: list[str]

    def to_dict(self) -> dict[str, Any]:
        """JSON 出力用の辞書に変換する。"""
        return {
            "id": self.id,
            "name": self.name,
            "context_length": self.context_length,
            "prompt_price_per_1m": self.prompt_price,
            "completion_price_per_1m": self.completion_price,
            "input_modalities": self.input_modalities,
            "output_modalities": self.output_modalities,
            "supported_voices": self.supported_voices,
        }


def _price_per_million(pricing: Mapping[str, Any], key: str) -> float | None:
    """価格文字列を 100 万トークンあたりの USD 価格に変換する。

    Args:
        pricing: モデルの ``pricing`` オブジェクト。
        key: 参照する価格キー（``prompt`` など）。

    Returns:
        100 万トークンあたりの価格。数値として解釈できない場合は None。
    """
    try:
        return float(pricing[key]) * TOKENS_PER_UNIT
    except (KeyError, TypeError, ValueError):
        return None


def _str_list(value: Any) -> list[str]:
    """値が文字列のリストであればそれを返し、そうでなければ空リストを返す。"""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def parse_model(record: Mapping[str, Any]) -> ModelInfo:
    """``/models`` の 1 レコードを ``ModelInfo`` に変換する。

    Args:
        record: モデル 1 件分の JSON オブジェクト。

    Returns:
        変換後のモデル情報。
    """
    architecture = record.get("architecture")
    architecture = architecture if isinstance(architecture, Mapping) else {}
    pricing = record.get("pricing")
    pricing = pricing if isinstance(pricing, Mapping) else {}

    context_length = record.get("context_length")

    return ModelInfo(
        id=str(record.get("id", "")),
        name=str(record.get("name") or record.get("id", "")),
        context_length=context_length if isinstance(context_length, int) else None,
        prompt_price=_price_per_million(pricing, "prompt"),
        completion_price=_price_per_million(pricing, "completion"),
        input_modalities=_str_list(architecture.get("input_modalities")),
        output_modalities=_str_list(architecture.get("output_modalities")),
        supported_voices=_str_list(record.get("supported_voices")),
    )


# --- 取得 ---


def fetch_models(client: OpenRouterClient, feature: str | None = None) -> list[ModelInfo]:
    """モデル一覧を取得する。

    Args:
        client: OpenRouter クライアント。
        feature: 絞り込む機能名（``FEATURE_FILTERS`` のキー）。
            None の場合は API 既定の一覧（テキスト出力モデル）を返す。

    Returns:
        モデル情報のリスト。ID の昇順にソート済み。
    """
    params = FEATURE_FILTERS.get(feature) if feature else None
    response = client.models(params)

    records = response.get("data")
    if not isinstance(records, list):
        return []

    models = [parse_model(record) for record in records if isinstance(record, Mapping)]
    return sorted(models, key=lambda model: model.id)


def filter_by_keyword(models: list[ModelInfo], keyword: str | None) -> list[ModelInfo]:
    """モデル ID と表示名に対する部分一致でモデルを絞り込む。

    Args:
        models: 絞り込み対象のモデル一覧。
        keyword: 検索キーワード。None または空文字なら絞り込まない。

    Returns:
        キーワードを含むモデルのリスト。
    """
    if not keyword:
        return models

    needle = keyword.lower()
    return [model for model in models if needle in model.id.lower() or needle in model.name.lower()]


def fetch_voices(client: OpenRouterClient, model: str | None = None) -> list[ModelInfo]:
    """対応ボイスを持つ TTS モデルの一覧を取得する。

    Args:
        client: OpenRouter クライアント。
        model: 特定モデルに絞る場合のモデル ID（部分一致）。

    Returns:
        ``supported_voices`` が空でない TTS モデルのリスト。
    """
    models = [entry for entry in fetch_models(client, "tts") if entry.supported_voices]
    return filter_by_keyword(models, model)


# --- 表形式の整形 ---


def _format_price(price: float | None) -> str:
    """100 万トークンあたりの価格を表示用文字列に整形する。"""
    if price is None:
        return "-"
    return f"${price:,.2f}"


def _format_context(context_length: int | None) -> str:
    """コンテキスト長を表示用文字列に整形する。"""
    if not context_length:
        return "-"
    return f"{context_length:,}"


def format_model_table(models: list[ModelInfo]) -> str:
    """モデル一覧を等幅の表として整形する。

    Args:
        models: 表示するモデル一覧。

    Returns:
        改行区切りの表文字列。モデルが無い場合は案内文。
    """
    if not models:
        return "(no models matched)"

    header = ("MODEL", "CONTEXT", "$IN/1M", "$OUT/1M")
    rows = [
        (
            model.id,
            _format_context(model.context_length),
            _format_price(model.prompt_price),
            _format_price(model.completion_price),
        )
        for model in models
    ]

    # ---各列の最大幅に合わせて桁を揃える
    widths = [max(len(row[index]) for row in (header, *rows)) for index in range(len(header))]
    lines = [
        "  ".join(cell.ljust(widths[index]) for index, cell in enumerate(row)).rstrip()
        for row in (header, *rows)
    ]
    return "\n".join(lines)


def format_voice_list(models: list[ModelInfo]) -> str:
    """TTS モデルごとの対応ボイスを整形する。

    Args:
        models: ``supported_voices`` を持つモデル一覧。

    Returns:
        改行区切りの一覧文字列。モデルが無い場合は案内文。
    """
    if not models:
        return "(no TTS models matched)"

    blocks = []
    for model in models:
        voices = ", ".join(model.supported_voices)
        blocks.append(f"{model.id}  ({len(model.supported_voices)} voices)\n  {voices}")
    return "\n\n".join(blocks)
