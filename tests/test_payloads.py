from pathlib import Path

from aitool.tools.image_generation import build_image_generation_payload
from aitool.tools.image_recognition import build_image_recognition_payload
from aitool.tools.stt import build_transcription_payload
from aitool.tools.tts import build_speech_payload
from aitool.tools.video_recognition import (
    VideoAnalysis,
    VIDEO_STRUCTURE_SCHEMA,
    build_generate_content_config,
    build_video_part,
    is_youtube_url,
)
from aitool.io import video_mime_type


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


def test_is_youtube_url() -> None:
    assert is_youtube_url("https://www.youtube.com/watch?v=example")
    assert is_youtube_url("https://youtu.be/example")
    assert not is_youtube_url("https://example.com/video.mp4")
    assert not is_youtube_url("video.mp4")


def test_video_mime_type(tmp_path: Path) -> None:
    video = tmp_path / "sample.mp4"
    video.write_bytes(b"video")

    assert video_mime_type(video) == "video/mp4"


def test_build_video_part_adds_fps_metadata() -> None:
    part = build_video_part("https://youtu.be/example", fps=0.5)

    assert part.file_data is not None
    assert part.file_data.file_uri == "https://youtu.be/example"
    assert part.video_metadata is not None
    assert part.video_metadata.fps == 0.5


def test_build_generate_content_config_adds_structured_output_schema() -> None:
    config = build_generate_content_config(structured_output=True, timeout=120)

    assert config.response_mime_type == "application/json"
    assert config.response_schema == VideoAnalysis
    assert config.http_options is not None
    assert config.http_options.timeout == 120000
    assert VIDEO_STRUCTURE_SCHEMA["properties"].get("global") is not None
