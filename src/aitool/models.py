"""各ツールの既定モデルと関連定数を定義するモジュール。

環境変数で上書きできない場合のフォールバック値をここに集約する。
"""

from __future__ import annotations

from typing import Final, Literal

# --- 型エイリアス ---

ToolFeature = Literal[
    "image_generation",
    "image_recognition",
    "stt",
    "stt_timestamp",
    "tts",
]
"""ツール機能を識別するリテラル型。"""

# --- 既定モデル（コード内定数） ---

DEFAULT_MODELS: Final[dict[ToolFeature, str]] = {
    "image_generation": "google/gemini-3.1-flash-image-preview",
    "image_recognition": "google/gemini-3-flash-preview",
    "stt": "openai/whisper-large-v3-turbo",
    "stt_timestamp": "whisper-1",
    "tts": "google/gemini-3.1-flash-tts-preview",
}
"""機能ごとの既定モデル名。env 未設定時の最終フォールバック。"""

# --- 環境変数名 ---

MODEL_ENV_VARS: Final[dict[ToolFeature, str]] = {
    "image_generation": "AITOOL_IMAGE_GENERATION_MODEL",
    "image_recognition": "AITOOL_IMAGE_RECOGNITION_MODEL",
    "stt": "AITOOL_STT_MODEL",
    "stt_timestamp": "AITOOL_STT_TIMESTAMP_MODEL",
    "tts": "AITOOL_TTS_MODEL",
}
"""機能ごとのモデル上書き用環境変数名。"""

# --- TTS 既定値 ---

DEFAULT_VOICE: Final[str] = "Zephyr"
"""TTS の既定ボイス。``DEFAULT_MODELS["tts"]`` が対応する識別子に合わせている。

使用可能なボイスはモデルごとに異なる（``aitool voices`` で確認できる）。
モデルを変えた場合は ``--voice`` も合わせて指定する必要がある。
"""

# --- OpenRouter 接続設定 ---

DEFAULT_TIMEOUT_SECONDS: Final[float] = 120.0
"""HTTP リクエストの既定タイムアウト（秒）。"""

OPENROUTER_BASE_URL: Final[str] = "https://openrouter.ai/api/v1"
"""OpenRouter API のベース URL。"""

OPENAI_BASE_URL: Final[str] = "https://api.openai.com/v1"
"""OpenAI API のベース URL。"""
