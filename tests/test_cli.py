from pathlib import Path

from typer.testing import CliRunner

from aitool.cli import app

runner = CliRunner()


def test_transcribe_prints_to_stdout_by_default(monkeypatch) -> None:
    def fake_run(self, audio_path, *, audio_format_override=None, mode="dedicated", prompt=None):
        return "transcribed text"

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
        return "saved text"

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
        return "image description"

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
