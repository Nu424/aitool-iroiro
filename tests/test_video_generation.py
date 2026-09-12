import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from aitool.cli import app
from aitool.config import resolve_fal_api_key, resolve_video_backend
from aitool.discovery import fetch_video_models, format_video_model_table, parse_video_model
from aitool.errors import ConfigError, PollingTimeoutError, VideoGenerationError
from aitool.tools.base import ToolResult
from aitool.tools.video_generation import (
    FalVideoTool,
    GeneratedVideo,
    OpenRouterVideoTool,
    VideoRequest,
    build_fal_video_input,
    build_openrouter_video_payload,
    parse_params,
    resolve_fal_endpoint,
    wait_for,
)
from aitool.usage import CallStats

runner = CliRunner()


# --- --param の解釈 ---


def test_parse_params_reads_json_values_and_falls_back_to_strings() -> None:
    params = parse_params(["duration=8s", "generate_audio=false", "steps=30", 'tags=["a","b"]'])

    assert params == {"duration": "8s", "generate_audio": False, "steps": 30, "tags": ["a", "b"]}


def test_parse_params_rejects_items_without_equals() -> None:
    with pytest.raises(ConfigError):
        parse_params(["novalue"])


# --- ペイロード構築 ---


def test_build_openrouter_video_payload_omits_unset_fields(tmp_path: Path) -> None:
    payload = build_openrouter_video_payload(VideoRequest(text="a cat"), "example/video")

    assert payload == {"model": "example/video", "prompt": "a cat"}


def test_build_openrouter_video_payload_embeds_first_frame_and_extra(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(b"image")

    payload = build_openrouter_video_payload(
        VideoRequest(
            text="animate",
            image_path=image,
            duration=6,
            resolution="720p",
            aspect_ratio="16:9",
            generate_audio=False,
            seed=7,
            extra={"provider": {"order": ["Google"]}, "duration": 8},
        ),
        "example/video",
    )

    assert payload["duration"] == 8  # --param が同名キーを上書きする
    assert payload["resolution"] == "720p"
    assert payload["generate_audio"] is False
    assert payload["seed"] == 7
    assert payload["provider"] == {"order": ["Google"]}
    frame = payload["frame_images"][0]
    assert frame["frame_type"] == "first_frame"
    assert frame["image_url"]["url"].startswith("data:image/png;base64,")


def test_resolve_fal_endpoint_appends_suffix_for_two_segment_ids() -> None:
    assert resolve_fal_endpoint("minimax/h3-max-turbo", has_image=False) == "minimax/h3-max-turbo/text-to-video"
    assert resolve_fal_endpoint("minimax/h3-max-turbo", has_image=True) == "minimax/h3-max-turbo/image-to-video"


def test_resolve_fal_endpoint_keeps_full_ids() -> None:
    assert resolve_fal_endpoint("fal-ai/veo3.1/fast", has_image=True) == "fal-ai/veo3.1/fast"


def test_build_fal_video_input_uppercases_resolution_for_minimax(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"image")

    payload = build_fal_video_input(
        VideoRequest(text="animate", image_path=image, duration=5, resolution="768p"),
        "minimax/h3-max-turbo/image-to-video",
    )

    assert payload["resolution"] == "768P"
    assert payload["duration"] == 5
    assert payload["image_url"].startswith("data:image/jpeg;base64,")
    assert "generate_audio" not in payload


def test_build_fal_video_input_keeps_resolution_for_other_publishers() -> None:
    payload = build_fal_video_input(
        VideoRequest(text="a cat", resolution="720p", extra={"audio": True}),
        "alibaba/wan-3.0/text-to-video",
    )

    assert payload == {"prompt": "a cat", "resolution": "720p", "audio": True}


# --- ポーリング ---


def test_wait_for_polls_until_result_and_reports_progress() -> None:
    answers = iter([None, None, {"done": True}])
    sleeps: list[float] = []
    messages: list[str] = []
    clock = iter([0.0, 0.0, 5.0, 10.0])

    result = wait_for(
        lambda: next(answers),
        interval=5.0,
        max_wait=60.0,
        progress=messages.append,
        sleep=sleeps.append,
        clock=lambda: next(clock),
    )

    assert result == {"done": True}
    assert sleeps == [5.0, 5.0]
    assert len(messages) == 2


def test_wait_for_raises_after_max_wait() -> None:
    clock = iter([0.0, 100.0])

    with pytest.raises(PollingTimeoutError):
        wait_for(lambda: None, interval=1.0, max_wait=60.0, sleep=lambda _: None, clock=lambda: next(clock))


# --- OpenRouter ツール ---


class _FakeOpenRouterClient:
    """``/videos`` 系の呼び出しを記録するスタブ。"""

    def __init__(self, statuses: list[dict]) -> None:
        self.statuses = iter(statuses)
        self.submitted: dict | None = None
        self.content_requests: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def videos(self, payload):
        self.submitted = payload
        return {"id": "job-1", "status": "pending"}

    def video(self, job_id):
        return next(self.statuses)

    def video_content(self, job_id, index=0):
        self.content_requests.append(job_id)
        return b"MP4", {"content-type": "video/mp4"}


def test_openrouter_video_tool_polls_and_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeOpenRouterClient(
        [
            {"status": "in_progress"},
            {"status": "completed", "unsigned_urls": ["u"], "usage": {"cost": 0.4}},
        ]
    )
    monkeypatch.setattr("aitool.tools.video_generation.time.sleep", lambda _: None)
    monkeypatch.setattr(OpenRouterVideoTool, "create_client", lambda self: client)
    tool = OpenRouterVideoTool("key", "example/video", 30.0)

    result = tool.run(VideoRequest(text="a cat"), poll_interval=0.0, max_wait=60.0)

    assert client.submitted == {"model": "example/video", "prompt": "a cat"}
    assert client.content_requests == ["job-1"]
    assert result.value.data == b"MP4"
    assert result.value.mime == "video/mp4"
    assert result.value.job_id == "job-1"
    assert result.stats.cost_usd == 0.4
    assert result.stats.generation_id == "job-1"


def test_openrouter_video_tool_raises_when_job_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeOpenRouterClient([{"status": "failed", "error": {"message": "content policy"}}])
    monkeypatch.setattr(OpenRouterVideoTool, "create_client", lambda self: client)
    tool = OpenRouterVideoTool("key", "example/video", 30.0)

    with pytest.raises(VideoGenerationError, match="content policy"):
        tool.run(VideoRequest(text="a cat"), poll_interval=0.0, max_wait=60.0)


# --- fal ツール ---


class _FakeFalClient:
    """fal のキュー API の呼び出しを記録するスタブ。"""

    instances: list["_FakeFalClient"] = []

    def __init__(self, api_key, *, timeout):
        self.api_key = api_key
        self.submitted: tuple[str, dict] | None = None
        self.gets: list[str] = []
        self.downloads: list[str] = []
        type(self).instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return None

    def submit(self, endpoint, payload):
        self.submitted = (endpoint, payload)
        return {
            "request_id": "req-1",
            "status_url": "https://queue.fal.run/x/requests/req-1/status",
            "response_url": "https://queue.fal.run/x/requests/req-1",
        }

    def get_json(self, url):
        self.gets.append(url)
        if url.endswith("/status"):
            if len(self.gets) == 1:
                return {"status": "IN_QUEUE", "queue_position": 3}
            return {"status": "COMPLETED", "metrics": {"inference_time": 1.54}}
        return {
            "video": {"url": "https://cdn.fal.media/out.mp4", "content_type": "video/mp4"},
            "expanded_prompt": "a fluffy cat",
        }

    def download(self, url):
        self.downloads.append(url)
        return b"MP4", {"content-type": "application/octet-stream"}


def test_fal_video_tool_submits_polls_and_downloads(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeFalClient.instances.clear()
    monkeypatch.setattr("aitool.tools.video_generation.FalClient", _FakeFalClient)
    monkeypatch.setattr("aitool.tools.video_generation.time.sleep", lambda _: None)
    tool = FalVideoTool("fal-key", "minimax/h3-max-turbo", 30.0)

    result = tool.run(
        VideoRequest(text="a cat", duration=5, resolution="768p"),
        poll_interval=0.0,
        max_wait=60.0,
    )

    client = _FakeFalClient.instances[0]
    assert client.api_key == "fal-key"
    assert client.submitted == (
        "minimax/h3-max-turbo/text-to-video",
        {"prompt": "a cat", "duration": 5, "resolution": "768P"},
    )
    assert client.downloads == ["https://cdn.fal.media/out.mp4"]
    assert result.value.data == b"MP4"
    # ---CDN のヘッダーが汎用でも、結果に書かれた content_type を優先する
    assert result.value.mime == "video/mp4"
    assert result.value.expanded_prompt == "a fluffy cat"
    assert result.stats.provider == "fal"
    assert result.stats.cost_usd is None
    assert result.stats.generation_time_ms == 1540


# --- 設定 ---


def test_resolve_video_backend_defaults_and_reads_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AITOOL_VIDEO_GENERATION_BACKEND", raising=False)
    monkeypatch.setattr("aitool.config.Path.home", lambda: tmp_path / "home")
    assert resolve_video_backend(cwd=tmp_path) == "openrouter"

    (tmp_path / ".env").write_text("AITOOL_VIDEO_GENERATION_BACKEND=fal\n", encoding="utf-8")
    assert resolve_video_backend(cwd=tmp_path) == "fal"
    assert resolve_video_backend("OpenRouter", cwd=tmp_path) == "openrouter"


def test_resolve_video_backend_rejects_unknown_value(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        resolve_video_backend("replicate", cwd=tmp_path)


def test_resolve_fal_api_key_reads_fal_key(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("FAL_KEY=from-cwd\n", encoding="utf-8")

    assert resolve_fal_api_key(cwd=tmp_path) == "from-cwd"


# --- モデル一覧 ---


VIDEO_MODELS_RESPONSE = {
    "data": [
        {
            "id": "minimax/hailuo-3-max",
            "supported_resolutions": ["768p", "480p"],
            "supported_durations": [5, 6, 7, 8, 9, 10],
            "supported_aspect_ratios": ["16:9"],
            "pricing_skus": {"duration_seconds_480p": "0.05", "duration_seconds_768p": "0.08"},
        },
        {
            "id": "google/veo-3.1-lite",
            "supported_resolutions": ["720p", "1080p"],
            "supported_durations": [8, 4, 6],
            "pricing_skus": {"duration_seconds_with_audio": "0.08"},
        },
    ]
}


class _FakeModelsClient:
    def video_models(self):
        return VIDEO_MODELS_RESPONSE


def test_fetch_video_models_sorts_and_filters() -> None:
    models = fetch_video_models(_FakeModelsClient())
    assert [model.id for model in models] == ["google/veo-3.1-lite", "minimax/hailuo-3-max"]

    filtered = fetch_video_models(_FakeModelsClient(), "hailuo")
    assert [model.id for model in filtered] == ["minimax/hailuo-3-max"]


def test_format_video_model_table_shows_duration_range() -> None:
    table = format_video_model_table([parse_video_model(VIDEO_MODELS_RESPONSE["data"][0])])

    assert "minimax/hailuo-3-max" in table
    assert "5-10s" in table
    assert "duration_seconds_480p=0.05" in table


# --- CLI ---


def _fake_video_result() -> ToolResult[GeneratedVideo]:
    return ToolResult(
        GeneratedVideo(data=b"MP4", mime="video/mp4", job_id="job-1"),
        CallStats(cost_usd=0.25, generation_id="job-1"),
    )


def test_generate_video_saves_file_and_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    def fake_run(self, request, *, poll_interval, max_wait, progress=None):
        captured["model"] = self.model
        captured["request"] = request
        captured["max_wait"] = max_wait
        return _fake_video_result()

    monkeypatch.setattr("aitool.cli.OpenRouterVideoTool.run", fake_run)
    output = tmp_path / "out.mp4"

    result = runner.invoke(
        app,
        [
            "generate-video",
            "--api-key",
            "test-key",
            "--text",
            "a cat",
            "--output",
            str(output),
            "--model",
            "example/video",
            "--duration",
            "6",
            "--no-audio",
            "--param",
            "seed=3",
            "--max-wait",
            "30",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.read_bytes() == b"MP4"
    assert captured["model"] == "example/video"
    assert captured["request"].duration == 6
    assert captured["request"].generate_audio is False
    assert captured["request"].extra == {"seed": 3}
    assert captured["max_wait"] == 30.0
    assert "Saved video to" in result.stdout


def test_generate_video_json_envelope_includes_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(self, request, *, poll_interval, max_wait, progress=None):
        return _fake_video_result()

    monkeypatch.setattr("aitool.cli.FalVideoTool.run", fake_run)
    output = tmp_path / "out.mp4"

    result = runner.invoke(
        app,
        [
            "generate-video",
            "--backend",
            "fal",
            "--api-key",
            "fal-key",
            "--text",
            "a cat",
            "--output",
            str(output),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    assert envelope["command"] == "generate-video"
    assert envelope["model"] == "minimax/h3-max-turbo"
    assert envelope["result"]["backend"] == "fal"
    assert envelope["result"]["job_id"] == "job-1"
    assert envelope["usage"]["cost_usd"] == 0.25


def test_generate_video_rejects_unknown_backend(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["generate-video", "--backend", "nope", "--text", "x", "--output", str(tmp_path / "o.mp4"), "--json"],
    )

    assert result.exit_code == 1
    assert json.loads(result.stdout)["error"]["type"] == "ConfigError"


def test_models_video_feature_uses_video_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("aitool.cli.fetch_video_models", lambda client, keyword=None: [
        parse_video_model(VIDEO_MODELS_RESPONSE["data"][0])
    ])

    result = runner.invoke(app, ["models", "--feature", "video-generation", "--api-key", "k"])

    assert result.exit_code == 0, result.output
    assert "Video generation" in result.stdout
    assert "minimax/hailuo-3-max" in result.stdout
