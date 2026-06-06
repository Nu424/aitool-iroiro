from pathlib import Path

import pytest

from aitool.config import resolve_api_key, resolve_model
from aitool.errors import ConfigError


def test_resolve_api_key_prefers_explicit(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=from-file\n", encoding="utf-8")

    assert resolve_api_key("from-cli", cwd=tmp_path) == "from-cli"


def test_resolve_api_key_prefers_cwd_env_over_process_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "from-process")
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=from-cwd\n", encoding="utf-8")

    assert resolve_api_key(cwd=tmp_path) == "from-cwd"


def test_resolve_api_key_raises_when_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(ConfigError):
        resolve_api_key(cwd=tmp_path)


def test_resolve_model_prefers_feature_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "AITOOL_STT_MODEL=example/stt-model\n",
        encoding="utf-8",
    )

    assert resolve_model("stt", cwd=tmp_path) == "example/stt-model"


def test_resolve_model_prefers_cli_over_feature_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "AITOOL_TTS_MODEL=example/env-model\n",
        encoding="utf-8",
    )

    assert resolve_model("tts", "example/cli-model", cwd=tmp_path) == "example/cli-model"
