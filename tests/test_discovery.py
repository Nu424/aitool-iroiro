import json

import pytest
from typer.testing import CliRunner

from aitool.cli import app
from aitool.discovery import (
    FEATURE_FILTERS,
    fetch_models,
    fetch_voices,
    filter_by_keyword,
    format_model_table,
    format_voice_list,
    parse_model,
)
from aitool.openrouter import OpenRouterClient

runner = CliRunner()

MODELS_RESPONSE = {
    "data": [
        {
            "id": "google/gemini-3.1-flash-tts-preview",
            "name": "Google: Gemini 3.1 Flash TTS Preview",
            "context_length": 32768,
            "architecture": {
                "modality": "text->speech",
                "input_modalities": ["text"],
                "output_modalities": ["speech"],
            },
            "pricing": {"prompt": "0.000001", "completion": "0.00002"},
            "supported_voices": ["Zephyr", "Puck", "Kore"],
        },
        {
            "id": "x-ai/grok-voice-tts-1.0",
            "name": "xAI: Grok Voice TTS",
            "context_length": 8192,
            "architecture": {
                "modality": "text->speech",
                "input_modalities": ["text"],
                "output_modalities": ["speech"],
            },
            "pricing": {"prompt": "0.000002", "completion": "0.00004"},
            "supported_voices": ["eve", "ara"],
        },
        {
            "id": "fish-audio/s1",
            "name": "Fish Audio S1",
            "context_length": None,
            "architecture": {
                "modality": "text->speech",
                "input_modalities": ["text"],
                "output_modalities": ["speech"],
            },
            "pricing": {},
            "supported_voices": None,
        },
    ]
}


class _FakeClient:
    """``models()`` の呼び出しパラメータを記録するスタブ。"""

    def __init__(self, response: dict) -> None:
        self.response = response
        self.params: list[dict | None] = []

    def models(self, params=None):
        self.params.append(params)
        return self.response


def test_parse_model_converts_per_token_price_to_per_million() -> None:
    model = parse_model(MODELS_RESPONSE["data"][0])

    assert model.id == "google/gemini-3.1-flash-tts-preview"
    assert model.context_length == 32768
    assert model.prompt_price == pytest.approx(1.0)
    assert model.completion_price == pytest.approx(20.0)
    assert model.output_modalities == ["speech"]
    assert model.supported_voices == ["Zephyr", "Puck", "Kore"]


def test_parse_model_tolerates_missing_fields() -> None:
    model = parse_model({"id": "example/bare"})

    assert model.id == "example/bare"
    assert model.name == "example/bare"
    assert model.context_length is None
    assert model.prompt_price is None
    assert model.input_modalities == []
    assert model.supported_voices == []


def test_fetch_models_sends_feature_filter_and_sorts_by_id() -> None:
    client = _FakeClient(MODELS_RESPONSE)

    models = fetch_models(client, "tts")

    assert client.params == [{"output_modalities": "speech"}]
    assert [model.id for model in models] == [
        "fish-audio/s1",
        "google/gemini-3.1-flash-tts-preview",
        "x-ai/grok-voice-tts-1.0",
    ]


def test_fetch_models_without_feature_sends_no_params() -> None:
    client = _FakeClient(MODELS_RESPONSE)

    fetch_models(client)

    assert client.params == [None]


def test_fetch_models_tolerates_unexpected_payload() -> None:
    assert fetch_models(_FakeClient({})) == []


def test_feature_filters_cover_every_cli_feature() -> None:
    """TTS と STT は output_modalities を明示しないと一覧に現れない。"""
    assert FEATURE_FILTERS["tts"] == {"output_modalities": "speech"}
    assert FEATURE_FILTERS["stt"] == {"output_modalities": "transcription"}
    assert FEATURE_FILTERS["image-generation"] == {"output_modalities": "image"}
    assert FEATURE_FILTERS["image-recognition"] == {"input_modalities": "image"}
    assert FEATURE_FILTERS["stt-llm"] == {"input_modalities": "audio"}


def test_filter_by_keyword_matches_id_and_name_case_insensitively() -> None:
    models = fetch_models(_FakeClient(MODELS_RESPONSE), "tts")

    assert [model.id for model in filter_by_keyword(models, "GEMINI")] == [
        "google/gemini-3.1-flash-tts-preview"
    ]
    assert [model.id for model in filter_by_keyword(models, "grok voice")] == [
        "x-ai/grok-voice-tts-1.0"
    ]
    assert [model.id for model in filter_by_keyword(models, "Fish Audio")] == ["fish-audio/s1"]
    assert filter_by_keyword(models, "nonexistent") == []
    assert len(filter_by_keyword(models, None)) == 3


def test_fetch_voices_drops_models_without_published_voices() -> None:
    client = _FakeClient(MODELS_RESPONSE)

    models = fetch_voices(client)

    assert [model.id for model in models] == [
        "google/gemini-3.1-flash-tts-preview",
        "x-ai/grok-voice-tts-1.0",
    ]


def test_fetch_voices_filters_by_model_substring() -> None:
    models = fetch_voices(_FakeClient(MODELS_RESPONSE), "grok")

    assert [model.id for model in models] == ["x-ai/grok-voice-tts-1.0"]


def test_format_model_table_aligns_columns() -> None:
    models = fetch_models(_FakeClient(MODELS_RESPONSE), "tts")

    table = format_model_table(models)
    lines = table.splitlines()

    assert lines[0].startswith("MODEL")
    assert "$1.00" in table
    assert "32,768" in table
    # ---価格やコンテキスト長が無いモデルは "-" で埋める
    assert any(line.startswith("fish-audio/s1") and "-" in line for line in lines)


def test_format_helpers_report_empty_results() -> None:
    assert format_model_table([]) == "(no models matched)"
    assert format_voice_list([]) == "(no TTS models matched)"


def test_models_command_json_envelope(monkeypatch) -> None:
    monkeypatch.setattr(OpenRouterClient, "models", lambda self, params=None: MODELS_RESPONSE)

    result = runner.invoke(
        app, ["models", "--api-key", "test-key", "--feature", "tts", "--json"]
    )

    assert result.exit_code == 0

    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    assert envelope["command"] == "models"
    assert envelope["result"]["feature"] == "tts"
    assert envelope["result"]["count"] == 3
    assert envelope["result"]["models"][0]["id"] == "fish-audio/s1"


def test_voices_command_lists_voice_identifiers(monkeypatch) -> None:
    monkeypatch.setattr(OpenRouterClient, "models", lambda self, params=None: MODELS_RESPONSE)

    result = runner.invoke(app, ["voices", "--api-key", "test-key"])

    assert result.exit_code == 0
    assert "google/gemini-3.1-flash-tts-preview" in result.stdout
    assert "Zephyr, Puck, Kore" in result.stdout
    # ---対応ボイスを公開していないモデルは出さない
    assert "fish-audio/s1" not in result.stdout


def test_voices_command_json_envelope(monkeypatch) -> None:
    monkeypatch.setattr(OpenRouterClient, "models", lambda self, params=None: MODELS_RESPONSE)

    result = runner.invoke(
        app, ["voices", "--api-key", "test-key", "--model", "gemini", "--json"]
    )

    assert result.exit_code == 0

    envelope = json.loads(result.stdout)
    assert envelope["result"]["count"] == 1
    assert envelope["result"]["models"][0]["voices"] == ["Zephyr", "Puck", "Kore"]


def test_config_command_reports_sources(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("aitool.config.Path.home", lambda: tmp_path / "home")
    (tmp_path / ".env").write_text(
        "OPENROUTER_API_KEY=sk-or-secret\nAITOOL_TTS_MODEL=example/custom-tts\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(app, ["config", "--json"])

    assert result.exit_code == 0

    envelope = json.loads(result.stdout)
    keys = {entry["env_var"]: entry for entry in envelope["result"]["api_keys"]}
    assert keys["OPENROUTER_API_KEY"] == {
        "env_var": "OPENROUTER_API_KEY",
        "is_set": True,
        "source": ".env",
    }
    assert keys["OPENAI_API_KEY"]["is_set"] is False

    models = {entry["feature"]: entry for entry in envelope["result"]["models"]}
    assert models["tts"]["model"] == "example/custom-tts"
    assert models["tts"]["source"] == ".env"
    assert models["stt"]["source"] == "built-in default"

    # ---API キーの値そのものは決して出さない
    assert "sk-or-secret" not in result.stdout
