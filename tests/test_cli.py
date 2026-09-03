import json
from pathlib import Path

from typer.testing import CliRunner

from aitool.cli import app
from aitool.tools.base import ToolResult
from aitool.usage import CallStats

runner = CliRunner()


def test_transcribe_prints_to_stdout_by_default(monkeypatch) -> None:
    def fake_run(self, audio_path, *, audio_format_override=None, mode="dedicated", prompt=None):
        return ToolResult("transcribed text")

    monkeypatch.setattr("aitool.cli.SpeechToTextTool.run", fake_run)

    result = runner.invoke(
        app,
        [
            "transcribe",
            "--api-key",
            "test-key",
            "--audio",
            "voice.mp3",
            "--model",
            "example/stt",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == "transcribed text\n"


def test_transcribe_writes_output_when_requested(tmp_path: Path, monkeypatch) -> None:
    def fake_run(self, audio_path, *, audio_format_override=None, mode="dedicated", prompt=None):
        return ToolResult("saved text")

    monkeypatch.setattr("aitool.cli.SpeechToTextTool.run", fake_run)
    output = tmp_path / "transcript.txt"

    result = runner.invoke(
        app,
        [
            "transcribe",
            "--api-key",
            "test-key",
            "--audio",
            "voice.mp3",
            "--output",
            str(output),
            "--model",
            "example/stt",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    assert output.read_text(encoding="utf-8") == "saved text"


def test_recognize_image_prints_to_stdout(monkeypatch) -> None:
    def fake_run(self, text, image_paths):
        return ToolResult("image description")

    monkeypatch.setattr("aitool.cli.ImageRecognitionTool.run", fake_run)

    result = runner.invoke(
        app,
        [
            "recognize-image",
            "--api-key",
            "test-key",
            "--text",
            "describe",
            "--image",
            "image.png",
            "--model",
            "example/vision",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == "image description\n"


def test_recognize_image_json_emits_single_envelope(monkeypatch) -> None:
    """--json 指定時は、テキストと混ざらない JSON エンベロープ 1 個だけを出す。"""

    def fake_run(self, text, image_paths):
        return ToolResult(
            "image description",
            CallStats(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
                cost_usd=0.00012,
                generation_id="gen-abc",
                provider="Google",
            ),
        )

    monkeypatch.setattr("aitool.cli.ImageRecognitionTool.run", fake_run)

    result = runner.invoke(
        app,
        [
            "recognize-image",
            "--api-key",
            "test-key",
            "--text",
            "describe",
            "--image",
            "image.png",
            "--model",
            "example/vision",
            "--json",
        ],
    )

    assert result.exit_code == 0

    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    assert envelope["command"] == "recognize-image"
    assert envelope["model"] == "example/vision"
    assert envelope["provider"] == "Google"
    assert envelope["result"] == {"text": "image description", "output": None}
    assert envelope["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "total_tokens": 15,
        "cost_usd": 0.00012,
        "generation_id": "gen-abc",
    }
    assert isinstance(envelope["timing"]["elapsed_ms"], int)


def test_transcribe_json_reports_mode_and_null_usage(monkeypatch) -> None:
    """usage が取得できなくても、キーは null で揃った形で出る。"""

    def fake_run(self, audio_path, *, audio_format_override=None, mode="dedicated", prompt=None):
        return ToolResult("transcribed text")

    monkeypatch.setattr("aitool.cli.SpeechToTextTool.run", fake_run)

    result = runner.invoke(
        app,
        [
            "transcribe",
            "--api-key",
            "test-key",
            "--audio",
            "voice.mp3",
            "--mode",
            "llm",
            "--model",
            "example/stt",
            "--json",
        ],
    )

    assert result.exit_code == 0

    envelope = json.loads(result.stdout)
    assert envelope["result"]["mode"] == "llm"
    assert envelope["result"]["text"] == "transcribed text"
    assert envelope["usage"]["cost_usd"] is None
    assert envelope["usage"]["total_tokens"] is None


def test_json_error_is_reported_as_envelope(monkeypatch) -> None:
    """失敗時も --json なら JSON エンベロープで返し、終了コードは 1。"""
    from aitool.errors import OpenRouterHTTPError

    def fake_run(self, text, image_paths):
        raise OpenRouterHTTPError(429, "rate limited")

    monkeypatch.setattr("aitool.cli.ImageRecognitionTool.run", fake_run)

    result = runner.invoke(
        app,
        [
            "recognize-image",
            "--api-key",
            "test-key",
            "--text",
            "describe",
            "--image",
            "image.png",
            "--model",
            "example/vision",
            "--json",
        ],
    )

    assert result.exit_code == 1

    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["command"] == "recognize-image"
    assert envelope["error"]["type"] == "OpenRouterHTTPError"
    assert envelope["error"]["status_code"] == 429


def test_error_without_json_goes_to_stderr(monkeypatch) -> None:
    from aitool.errors import OpenRouterResponseError

    def fake_run(self, text, image_paths):
        raise OpenRouterResponseError("no text in response")

    monkeypatch.setattr("aitool.cli.ImageRecognitionTool.run", fake_run)

    result = runner.invoke(
        app,
        [
            "recognize-image",
            "--api-key",
            "test-key",
            "--text",
            "describe",
            "--image",
            "image.png",
            "--model",
            "example/vision",
        ],
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert "no text in response" in result.stderr


def test_tts_json_includes_generation_stats(tmp_path: Path, monkeypatch) -> None:
    from aitool.tools.tts import SpeechGenerationResult

    def fake_run(self, text, *, voice, response_format, speed=None):
        return ToolResult(
            SpeechGenerationResult(data=b"audio-bytes", content_type="audio/mpeg"),
            CallStats(
                total_tokens=480,
                cost_usd=0.0000108,
                generation_id="gen-tts",
                provider="Google",
                generation_time_ms=1200,
                latency_ms=250,
            ),
        )

    monkeypatch.setattr("aitool.cli.TextToSpeechTool.run", fake_run)
    output = tmp_path / "voice.mp3"

    result = runner.invoke(
        app,
        [
            "tts",
            "--api-key",
            "test-key",
            "--text",
            "hello",
            "--output",
            str(output),
            "--model",
            "example/tts",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert output.read_bytes() == b"audio-bytes"

    envelope = json.loads(result.stdout)
    assert envelope["result"] == {"output": str(output), "content_type": "audio/mpeg"}
    assert envelope["usage"]["cost_usd"] == 0.0000108
    assert envelope["timing"]["generation_time_ms"] == 1200
    assert envelope["timing"]["latency_ms"] == 250


def test_transcribe_timestamp_prints_json_to_stdout(monkeypatch) -> None:
    def fake_run(
        self,
        audio_path,
        *,
        audio_format_override=None,
        granularity="segment",
        language=None,
        prompt=None,
    ):
        return ToolResult(
            {
                "text": "hello",
                "segments": [{"start": 0.0, "end": 1.0, "text": " hello"}],
            }
        )

    monkeypatch.setattr("aitool.cli.TimestampTranscriptionTool.run", fake_run)

    result = runner.invoke(
        app,
        [
            "transcribe-timestamp",
            "--api-key",
            "test-key",
            "--audio",
            "voice.mp3",
            "--model",
            "whisper-1",
        ],
    )

    assert result.exit_code == 0

    transcript = json.loads(result.stdout)
    assert transcript["text"] == "hello"
    assert transcript["segments"][0]["end"] == 1.0


def test_transcribe_timestamp_writes_output_when_requested(tmp_path: Path, monkeypatch) -> None:
    def fake_run(
        self,
        audio_path,
        *,
        audio_format_override=None,
        granularity="segment",
        language=None,
        prompt=None,
    ):
        return ToolResult({"text": "saved", "words": [{"word": "saved", "start": 0.0, "end": 0.5}]})

    monkeypatch.setattr("aitool.cli.TimestampTranscriptionTool.run", fake_run)
    output = tmp_path / "transcript.json"

    result = runner.invoke(
        app,
        [
            "transcribe-timestamp",
            "--api-key",
            "test-key",
            "--audio",
            "voice.mp3",
            "--granularity",
            "word",
            "--output",
            str(output),
            "--model",
            "whisper-1",
        ],
    )

    assert result.exit_code == 0
    assert result.stdout == ""
    assert '"text": "saved"' in output.read_text(encoding="utf-8")


def test_transcribe_timestamp_json_wraps_transcript_in_envelope(monkeypatch) -> None:
    def fake_run(
        self,
        audio_path,
        *,
        audio_format_override=None,
        granularity="segment",
        language=None,
        prompt=None,
    ):
        return ToolResult({"text": "hello", "segments": []})

    monkeypatch.setattr("aitool.cli.TimestampTranscriptionTool.run", fake_run)

    result = runner.invoke(
        app,
        [
            "transcribe-timestamp",
            "--api-key",
            "test-key",
            "--audio",
            "voice.mp3",
            "--model",
            "whisper-1",
            "--json",
        ],
    )

    assert result.exit_code == 0

    envelope = json.loads(result.stdout)
    assert envelope["command"] == "transcribe-timestamp"
    assert envelope["result"]["transcript"] == {"text": "hello", "segments": []}
