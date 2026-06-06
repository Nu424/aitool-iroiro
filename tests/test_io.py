from pathlib import Path

import pytest

from aitool.errors import FileInputError
from aitool.io import audio_format, decode_data_url, image_data_url


def test_image_data_url_encodes_supported_image(tmp_path: Path) -> None:
    image = tmp_path / "sample.png"
    image.write_bytes(b"png-bytes")

    assert image_data_url(image) == "data:image/png;base64,cG5nLWJ5dGVz"


def test_image_data_url_rejects_unsupported_image(tmp_path: Path) -> None:
    image = tmp_path / "sample.gif"
    image.write_bytes(b"gif-bytes")

    with pytest.raises(FileInputError):
        image_data_url(image)


def test_audio_format_infers_from_extension(tmp_path: Path) -> None:
    assert audio_format(tmp_path / "voice.mp3") == "mp3"


def test_audio_format_allows_override(tmp_path: Path) -> None:
    assert audio_format(tmp_path / "voice.unknown", "wav") == "wav"


def test_decode_data_url_returns_bytes_and_mime() -> None:
    data, mime = decode_data_url("data:image/png;base64,aGVsbG8=")

    assert data == b"hello"
    assert mime == "image/png"
