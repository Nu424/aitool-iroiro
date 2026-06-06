from pathlib import Path

from aitool.tools.image_generation import build_image_generation_payload
from aitool.tools.image_recognition import build_image_recognition_payload
from aitool.tools.stt import build_transcription_payload
from aitool.tools.tts import build_speech_payload


def test_build_image_recognition_payload(tmp_path: Path) -> None:
    image = tmp_path / "image.png"
    image.write_bytes(b"image")

    payload = build_image_recognition_payload("describe", [image], "example/vision")

    assert payload["model"] == "example/vision"
    content = payload["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_build_image_generation_payload_adds_image_config(tmp_path: Path) -> None:
    image = tmp_path / "image.webp"
    image.write_bytes(b"image")

    payload = build_image_generation_payload(
        "edit",
        [image],
        "example/image",
        aspect_ratio="1:1",
        image_size="1K",
    )

    assert payload["modalities"] == ["image", "text"]
    assert payload["image_config"] == {"aspect_ratio": "1:1", "image_size": "1K"}
    assert isinstance(payload["messages"][0]["content"], list)


def test_build_transcription_payload(tmp_path: Path) -> None:
    audio = tmp_path / "voice.mp3"
    audio.write_bytes(b"audio")

    payload = build_transcription_payload(audio, "example/stt")

    assert payload == {
        "model": "example/stt",
        "input_audio": {
            "data": "YXVkaW8=",
            "format": "mp3",
        },
    }


def test_build_speech_payload() -> None:
    payload = build_speech_payload(
        "hello",
        "example/tts",
        voice="alloy",
        response_format="mp3",
        speed=1.1,
    )

    assert payload == {
        "model": "example/tts",
        "input": "hello",
        "voice": "alloy",
        "response_format": "mp3",
        "speed": 1.1,
    }
