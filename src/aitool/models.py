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
    "video_generation",
    "video_generation_fal",
]
"""ツール機能を識別するリテラル型。

``video_generation`` と ``video_generation_fal`` は同じ ``generate-video``
コマンドの OpenRouter 用・fal 用の既定モデルをそれぞれ表す。
"""

VideoBackend = Literal["openrouter", "fal"]
"""動画生成のバックエンドを識別するリテラル型。"""

# --- 既定モデル（コード内定数） ---

DEFAULT_MODELS: Final[dict[ToolFeature, str]] = {
    "image_generation": "google/gemini-3.1-flash-image-preview",
    "image_recognition": "google/gemini-3-flash-preview",
    "stt": "openai/whisper-large-v3-turbo",
    "stt_timestamp": "whisper-1",
    "tts": "google/gemini-3.1-flash-tts-preview",
    "video_generation": "minimax/hailuo-3-max",
    "video_generation_fal": "minimax/h3-max-turbo",
}
"""機能ごとの既定モデル名。env 未設定時の最終フォールバック。

``video_generation_fal`` は fal のエンドポイント ID。``publisher/name`` の
2 階層で書くと、入力画像の有無に応じて ``/text-to-video`` または
``/image-to-video`` が補われる（``tools.video_generation`` を参照）。
"""

# --- 環境変数名 ---

MODEL_ENV_VARS: Final[dict[ToolFeature, str]] = {
    "image_generation": "AITOOL_IMAGE_GENERATION_MODEL",
    "image_recognition": "AITOOL_IMAGE_RECOGNITION_MODEL",
    "stt": "AITOOL_STT_MODEL",
    "stt_timestamp": "AITOOL_STT_TIMESTAMP_MODEL",
    "tts": "AITOOL_TTS_MODEL",
    "video_generation": "AITOOL_VIDEO_GENERATION_MODEL",
    "video_generation_fal": "AITOOL_VIDEO_GENERATION_FAL_MODEL",
}
"""機能ごとのモデル上書き用環境変数名。"""

# --- 動画生成 既定値 ---

DEFAULT_VIDEO_BACKEND: Final[VideoBackend] = "openrouter"
"""動画生成の既定バックエンド。

OpenRouter を基本とし、fal は OpenRouter に無いモデル（H3 Max Turbo など）を
使うための例外口という位置づけ。
"""

VIDEO_BACKEND_ENV_VAR: Final[str] = "AITOOL_VIDEO_GENERATION_BACKEND"
"""動画生成バックエンドの上書き用環境変数名（``openrouter`` / ``fal``）。"""

DEFAULT_VIDEO_POLL_INTERVAL_SECONDS: Final[float] = 5.0
"""動画生成ジョブの状態を確認する間隔（秒）。"""

DEFAULT_VIDEO_MAX_WAIT_SECONDS: Final[float] = 900.0
"""動画生成ジョブの完了を待つ最大時間（秒）。

生成には数十秒から数分かかるため、HTTP 1 往復用の ``DEFAULT_TIMEOUT_SECONDS``
とは別に管理する。
"""

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

FAL_QUEUE_BASE_URL: Final[str] = "https://queue.fal.run"
"""fal のキュー API のベース URL。"""
