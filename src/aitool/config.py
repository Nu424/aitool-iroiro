"""CLI オプションと環境ファイルから設定値を解決するモジュール。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

from aitool.errors import ConfigError
from aitool.models import DEFAULT_MODELS, MODEL_ENV_VARS, ToolFeature

# --- 環境変数名 ---

API_KEY_ENV_VAR = "OPENROUTER_API_KEY"
"""OpenRouter API キーを格納する環境変数名。"""

GOOGLE_API_KEY_ENV_VAR = "GEMINI_API_KEY"
"""Google GenAI API キーを格納する環境変数名。"""


# --- 内部ヘルパー ---


def _clean(value: str | None) -> str | None:
    """文字列をトリムし、空文字列は None として扱う。

    Args:
        value: トリム対象の文字列。None の場合はそのまま返す。

    Returns:
        トリム後の非空文字列。空または None の場合は None。
    """
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _env_file_values(path: Path) -> dict[str, str]:
    """指定パスの .env ファイルからキーと値の辞書を読み込む。

    Args:
        path: .env ファイルのパス。

    Returns:
        値が None でないエントリのみを含む辞書。ファイルが存在しない場合は空辞書。
    """
    if not path.exists():
        return {}
    values = dotenv_values(path)
    return {key: value for key, value in values.items() if value is not None}


def _lookup_env_chain(key: str, cwd: Path) -> str | None:
    """cwd の .env → ~/.env.global → プロセス環境変数の順で値を解決する。

    Args:
        key: 取得する環境変数名。
        cwd: カレントディレクトリ（.env の探索起点）。

    Returns:
        最初に見つかった非空の値。いずれにも無い場合は None。
    """
    for env_path in (cwd / ".env", Path.home() / ".env.global"):
        value = _clean(_env_file_values(env_path).get(key))
        if value:
            return value

    return _clean(os.environ.get(key))


# --- 公開 API ---


def resolve_api_key(explicit_api_key: str | None = None, cwd: Path | None = None) -> str:
    """OpenRouter API キーを優先順位に従って解決する。

    解決順: ``--api-key`` → cwd の ``.env`` → ``~/.env.global`` → 環境変数。

    Args:
        explicit_api_key: CLI などから明示的に渡された API キー。
        cwd: .env を探す起点ディレクトリ。省略時はカレントディレクトリ。

    Returns:
        解決された API キー文字列。

    Raises:
        ConfigError: いずれのソースからもキーが取得できない場合。
    """
    # --- --api-key が指定されている場合はそれを使用する
    explicit = _clean(explicit_api_key)
    if explicit:
        return explicit

    # ---.env または ~/.env.global から API キーを取得する
    value = _lookup_env_chain(API_KEY_ENV_VAR, cwd or Path.cwd())
    if value:
        return value

    # ---いずれのソースからもキーが取得できない場合はエラーを送出する
    raise ConfigError(
        "OpenRouter API key was not found. Pass --api-key or set "
        "OPENROUTER_API_KEY in .env or ~/.env.global."
    )


def resolve_google_api_key(explicit_api_key: str | None = None, cwd: Path | None = None) -> str:
    """Google GenAI API キーを優先順位に従って解決する。

    解決順: ``--api-key`` → cwd の ``.env`` → ``~/.env.global`` → 環境変数。

    Args:
        explicit_api_key: CLI などから明示的に渡された API キー。
        cwd: .env を探す起点ディレクトリ。省略時はカレントディレクトリ。

    Returns:
        解決された API キー文字列。

    Raises:
        ConfigError: いずれのソースからもキーが取得できない場合。
    """
    explicit = _clean(explicit_api_key)
    if explicit:
        return explicit

    value = _lookup_env_chain(GOOGLE_API_KEY_ENV_VAR, cwd or Path.cwd())
    if value:
        return value

    raise ConfigError(
        "Google GenAI API key was not found. Pass --api-key or set "
        "GEMINI_API_KEY in .env or ~/.env.global."
    )


def resolve_model(
    feature: ToolFeature,
    explicit_model: str | None = None,
    cwd: Path | None = None,
) -> str:
    """機能ごとのモデル名を優先順位に従って解決する。

    解決順: ``--model`` → 機能別 env 変数（.env / ~/.env.global / 環境変数）
    → ``models.DEFAULT_MODELS`` のコード内定数。

    Args:
        feature: 対象ツール機能（image_generation など）。
        explicit_model: CLI などから明示的に渡されたモデル名。
        cwd: .env を探す起点ディレクトリ。省略時はカレントディレクトリ。

    Returns:
        解決されたモデル名。
    """
    explicit = _clean(explicit_model)
    if explicit:
        return explicit

    # ---機能別 env 変数からモデル名を取得する
    env_var = MODEL_ENV_VARS[feature] # 機能のキー名を取得
    value = _lookup_env_chain(env_var, cwd or Path.cwd()) # 環境変数からモデル名を取得
    if value:
        return value

    # 解決できなかった場合、DEFAULT_MODELS から既定モデル名を取得する
    return DEFAULT_MODELS[feature]
