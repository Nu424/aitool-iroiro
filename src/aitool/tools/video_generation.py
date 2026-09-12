"""動画生成（t2v / i2v）ツール。

バックエンドは 2 つある。

- **OpenRouter** (``/videos``) — 既定。Veo / Seedance / Wan / Kling / Sora など。
- **fal** (``queue.fal.run``) — OpenRouter に無いモデル（H3 Max Turbo など）用の例外口。

どちらも「投入 → 状態をポーリング → 動画をダウンロード」という非同期の流れは
同じなので、待機の骨格を ``wait_for`` に集め、バックエンドごとの差分
（ペイロード、完了判定、動画の取り出し）だけを各ツールに持たせる。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from aitool.errors import (
    ConfigError,
    FalResponseError,
    OpenRouterResponseError,
    PollingTimeoutError,
    VideoGenerationError,
)
from aitool.fal_client import FalClient
from aitool.io import ensure_output_parent, extension_for_mime, image_data_url
from aitool.tools.base import BaseTool, ToolResult
from aitool.usage import CallStats, extract_stats

T = TypeVar("T")

ProgressCallback = Callable[[str], None]
"""ポーリング中の進捗を通知するコールバック。CLI では ``--verbose`` 時に stderr へ出す。"""

DEFAULT_VIDEO_MIME = "video/mp4"
"""MIME タイプが取得できなかったときのフォールバック。"""

FAL_TEXT_TO_VIDEO_SUFFIX = "text-to-video"
FAL_IMAGE_TO_VIDEO_SUFFIX = "image-to-video"

FAL_UPPERCASE_RESOLUTION_PUBLISHERS: tuple[str, ...] = ("minimax",)
"""解像度を ``768P`` のように大文字で要求する fal のパブリッシャー。

fal はモデルごとに入力スキーマが異なり、MiniMax 系だけが大文字の ``P`` を
要求する。CLI では他バックエンドと同じ ``768p`` で指定できるよう、ここで吸収する。
"""


# --- 入力と結果 ---


@dataclass(slots=True)
class VideoRequest:
    """CLI から受け取る、バックエンドに依存しない動画生成の指定。

    ``None`` のフィールドはペイロードに含めず、モデル側の既定値に任せる。

    Attributes:
        text: 生成の指示テキスト。
        image_path: 先頭フレームとして使う画像。None なら t2v。
        duration: 動画の長さ（秒）。
        resolution: 解像度（例: ``720p``）。
        aspect_ratio: アスペクト比（例: ``16:9``）。
        generate_audio: 音声を生成するか。None なら指定しない。
        seed: 乱数シード。
        extra: ``--param`` で渡されたバックエンド固有のパラメータ。同名のキーを上書きする。
    """

    text: str
    image_path: Path | None = None
    duration: int | None = None
    resolution: str | None = None
    aspect_ratio: str | None = None
    generate_audio: bool | None = None
    seed: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GeneratedVideo:
    """動画生成の結果。

    Attributes:
        data: 動画のバイナリデータ。
        mime: 動画の MIME タイプ。
        job_id: バックエンド側のジョブ ID（OpenRouter の ``id`` / fal の ``request_id``）。
        expanded_prompt: モデルが書き換えた後のプロンプト（fal の一部モデルのみ）。
    """

    data: bytes
    mime: str
    job_id: str
    expanded_prompt: str | None = None

    @property
    def suggested_extension(self) -> str:
        """MIME タイプから推奨するファイル拡張子を返す。"""
        return extension_for_mime(self.mime)


# --- --param の解釈 ---


def parse_params(items: list[str] | None) -> dict[str, Any]:
    """``KEY=VALUE`` 形式の文字列をパラメータ辞書に変換する。

    値は JSON として解釈を試み（``true`` / ``8`` / ``["a"]`` など）、
    解釈できなければ文字列のまま扱う。``KEY=8s`` のような文字列もそのまま通る。

    Args:
        items: ``KEY=VALUE`` 形式の文字列のリスト。

    Returns:
        パラメータ辞書。

    Raises:
        ConfigError: ``=`` を含まない、またはキーが空の項目がある場合。
    """
    params: dict[str, Any] = {}
    for item in items or []:
        key, separator, raw = item.partition("=")
        key = key.strip()
        if not separator or not key:
            raise ConfigError(f"Invalid --param '{item}'. Expected KEY=VALUE.")
        try:
            params[key] = json.loads(raw)
        except ValueError:
            params[key] = raw
    return params


def _drop_none(payload: Mapping[str, Any]) -> dict[str, Any]:
    """値が None のキーを取り除いた辞書を返す。"""
    return {key: value for key, value in payload.items() if value is not None}


# --- OpenRouter 用ペイロード ---


def build_openrouter_video_payload(request: VideoRequest, model: str) -> dict[str, Any]:
    """OpenRouter ``/videos`` 用のリクエストペイロードを組み立てる。

    入力画像は ``frame_images`` の先頭フレーム（``first_frame``）として
    data URL で埋め込む。

    Args:
        request: 動画生成の指定。
        model: 使用するモデル名。

    Returns:
        ``/videos`` に POST する JSON ペイロード。
    """
    payload = _drop_none(
        {
            "model": model,
            "prompt": request.text,
            "duration": request.duration,
            "resolution": request.resolution,
            "aspect_ratio": request.aspect_ratio,
            "generate_audio": request.generate_audio,
            "seed": request.seed,
        }
    )
    if request.image_path is not None:
        payload["frame_images"] = [
            {
                "type": "image_url",
                "image_url": {"url": image_data_url(request.image_path)},
                "frame_type": "first_frame",
            }
        ]
    payload.update(request.extra)
    return payload


# --- fal 用ペイロード ---


def resolve_fal_endpoint(model: str, *, has_image: bool) -> str:
    """fal のエンドポイント ID を確定する。

    ``publisher/name`` の 2 階層で指定された場合は、入力画像の有無に応じて
    ``/text-to-video`` または ``/image-to-video`` を補う。3 階層以上は
    完全なエンドポイント ID とみなしてそのまま使う。

    Args:
        model: CLI や環境変数で指定されたモデル名。
        has_image: 入力画像が指定されているかどうか。

    Returns:
        ``queue.fal.run`` 配下のエンドポイント ID。
    """
    endpoint = model.strip("/")
    if endpoint.count("/") == 1:
        suffix = FAL_IMAGE_TO_VIDEO_SUFFIX if has_image else FAL_TEXT_TO_VIDEO_SUFFIX
        return f"{endpoint}/{suffix}"
    return endpoint


def _fal_resolution(resolution: str | None, endpoint: str) -> str | None:
    """fal のモデルごとの表記に合わせて解像度を正規化する。"""
    if resolution is None:
        return None
    publisher = endpoint.split("/", 1)[0]
    if publisher in FAL_UPPERCASE_RESOLUTION_PUBLISHERS:
        return resolution.upper()
    return resolution


def build_fal_video_input(request: VideoRequest, endpoint: str) -> dict[str, Any]:
    """fal のキュー API に投入する入力オブジェクトを組み立てる。

    fal はモデルごとに入力スキーマが異なるため、ここでは MiniMax H3 系を
    基準にした最小限の対応づけに留める。それ以外のキーは ``request.extra``
    （CLI の ``--param``）で渡す。

    Args:
        request: 動画生成の指定。
        endpoint: 確定済みのエンドポイント ID。

    Returns:
        キューに POST する入力オブジェクト。
    """
    payload = _drop_none(
        {
            "prompt": request.text,
            "duration": request.duration,
            "resolution": _fal_resolution(request.resolution, endpoint),
            "aspect_ratio": request.aspect_ratio,
            "generate_audio": request.generate_audio,
            "seed": request.seed,
        }
    )
    if request.image_path is not None:
        payload["image_url"] = image_data_url(request.image_path)
    payload.update(request.extra)
    return payload


# --- ポーリング ---


def wait_for(
    check: Callable[[], T | None],
    *,
    interval: float,
    max_wait: float,
    progress: ProgressCallback | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> T:
    """``check`` が None 以外を返すまで一定間隔で繰り返し呼び出す。

    Args:
        check: 完了していれば結果を、未完了なら None を返す関数。
        interval: 呼び出し間隔（秒）。
        max_wait: 待機の上限（秒）。
        progress: 待機のたびに経過秒数を知らせるコールバック。
        sleep: 待機に使う関数（テストで差し替える）。
        clock: 経過時間の計測に使う関数（テストで差し替える）。

    Returns:
        ``check`` が返した結果。

    Raises:
        PollingTimeoutError: ``max_wait`` 以内に完了しなかった場合。
    """
    started_at = clock()
    while True:
        result = check()
        if result is not None:
            return result

        elapsed = clock() - started_at
        if elapsed >= max_wait:
            raise PollingTimeoutError(
                f"Video generation did not finish within {max_wait:.0f}s. "
                "Increase --max-wait or retry later."
            )
        if progress is not None:
            progress(f"waiting... {elapsed:.0f}s elapsed")
        sleep(interval)


def _content_type(headers: Mapping[str, str], declared: str | None) -> str:
    """動画の MIME タイプを決める。

    API が結果として明示した MIME（fal の ``video.content_type``）を最優先し、
    無ければダウンロード時のヘッダーを使う。CDN が汎用の
    ``application/octet-stream`` を返す場合は動画とみなして既定値に倒す。
    """
    candidate = declared or headers.get("content-type") or DEFAULT_VIDEO_MIME
    mime = candidate.split(";", 1)[0].strip()
    return DEFAULT_VIDEO_MIME if mime == "application/octet-stream" else mime


# --- ツール本体 ---


@dataclass(slots=True)
class OpenRouterVideoTool(BaseTool):
    """OpenRouter ``/videos`` で動画を生成するツール。"""

    def run(
        self,
        request: VideoRequest,
        *,
        poll_interval: float,
        max_wait: float,
        progress: ProgressCallback | None = None,
    ) -> ToolResult[GeneratedVideo]:
        """動画生成を実行し、完了した動画を返す。

        Args:
            request: 動画生成の指定。
            poll_interval: 状態確認の間隔（秒）。
            max_wait: 完了を待つ上限（秒）。
            progress: 進捗を通知するコールバック。

        Returns:
            生成された動画と、その呼び出しの計測値。コストは完了応答の
            ``usage.cost`` から入る。

        Raises:
            OpenRouterResponseError: レスポンスの構造が想定と異なる場合。
            VideoGenerationError: ジョブが失敗として終了した場合。
            PollingTimeoutError: ``max_wait`` 以内に完了しなかった場合。
        """
        payload = build_openrouter_video_payload(request, self.model)
        with self.create_client() as client:
            submitted = client.videos(payload)
            job_id = submitted.get("id")
            if not isinstance(job_id, str) or not job_id:
                raise OpenRouterResponseError("Video generation response did not include a job id.")
            if progress is not None:
                progress(f"submitted job {job_id}")

            def check() -> dict[str, Any] | None:
                record = client.video(job_id)
                status = record.get("status")
                if status == "completed":
                    return record
                if status == "failed":
                    detail = record.get("error")
                    message = detail.get("message") if isinstance(detail, Mapping) else detail
                    raise VideoGenerationError(f"Video generation failed: {message or 'unknown error'}")
                if progress is not None:
                    progress(f"status: {status}")
                return None

            record = wait_for(check, interval=poll_interval, max_wait=max_wait, progress=progress)
            data, headers = client.video_content(job_id)

        # ---完了応答の usage にコストが入る。トークン数は返らない
        stats = extract_stats(record, generation_id=job_id)
        return ToolResult(
            GeneratedVideo(data=data, mime=_content_type(headers, None), job_id=job_id),
            stats,
        )


@dataclass(slots=True)
class FalVideoTool:
    """fal のキュー API で動画を生成するツール。

    Attributes:
        api_key: fal API キー。
        model: fal のエンドポイント ID（``publisher/name`` の 2 階層なら自動補完）。
        timeout: HTTP タイムアウト（秒）。
        verbose: 詳細ログを stderr に出すかどうか。
    """

    api_key: str
    model: str
    timeout: float
    verbose: bool = False

    def run(
        self,
        request: VideoRequest,
        *,
        poll_interval: float,
        max_wait: float,
        progress: ProgressCallback | None = None,
    ) -> ToolResult[GeneratedVideo]:
        """動画生成を実行し、完了した動画を返す。

        Args:
            request: 動画生成の指定。
            poll_interval: 状態確認の間隔（秒）。
            max_wait: 完了を待つ上限（秒）。
            progress: 進捗を通知するコールバック。

        Returns:
            生成された動画と計測値。fal はコストを返さないため
            ``cost_usd`` は None、``generation_time_ms`` は ``metrics.inference_time`` から入る。

        Raises:
            FalResponseError: レスポンスの構造が想定と異なる場合。
            VideoGenerationError: ジョブが失敗として終了した場合。
            PollingTimeoutError: ``max_wait`` 以内に完了しなかった場合。
        """
        endpoint = resolve_fal_endpoint(self.model, has_image=request.image_path is not None)
        payload = build_fal_video_input(request, endpoint)

        with FalClient(self.api_key, timeout=self.timeout) as client:
            submitted = client.submit(endpoint, payload)
            request_id = submitted.get("request_id")
            status_url = submitted.get("status_url")
            response_url = submitted.get("response_url")
            if not all(isinstance(value, str) and value for value in (request_id, status_url, response_url)):
                raise FalResponseError("fal submit response did not include request_id and URLs.")
            if progress is not None:
                progress(f"submitted request {request_id} to {endpoint}")

            def check() -> dict[str, Any] | None:
                record = client.get_json(status_url)
                status = record.get("status")
                if status == "COMPLETED":
                    error = record.get("error")
                    if error:
                        raise VideoGenerationError(f"Video generation failed: {error}")
                    return record
                if progress is not None:
                    position = record.get("queue_position")
                    suffix = f" (queue position {position})" if isinstance(position, int) else ""
                    progress(f"status: {status}{suffix}")
                return None

            status_record = wait_for(check, interval=poll_interval, max_wait=max_wait, progress=progress)
            result = client.get_json(response_url)

            video = result.get("video")
            url = video.get("url") if isinstance(video, Mapping) else None
            if not isinstance(url, str) or not url:
                raise FalResponseError("fal result did not include a video URL.")
            data, headers = client.download(url)

        expanded_prompt = result.get("expanded_prompt")
        declared_mime = video.get("content_type") if isinstance(video, Mapping) else None
        stats = CallStats(
            generation_id=request_id,
            provider="fal",
            generation_time_ms=_inference_time_ms(status_record),
        )
        return ToolResult(
            GeneratedVideo(
                data=data,
                mime=_content_type(headers, declared_mime if isinstance(declared_mime, str) else None),
                job_id=request_id,
                expanded_prompt=expanded_prompt if isinstance(expanded_prompt, str) else None,
            ),
            stats,
        )


def _inference_time_ms(status_record: Mapping[str, Any]) -> int | None:
    """fal の状態応答 ``metrics.inference_time``（秒）をミリ秒に変換する。"""
    metrics = status_record.get("metrics")
    if not isinstance(metrics, Mapping):
        return None
    value = metrics.get("inference_time")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value * 1000)


def save_generated_video(video: GeneratedVideo, output_path: Path) -> Path:
    """生成動画をファイルに保存する。

    Args:
        video: 保存する動画データ。
        output_path: 出力先ファイルパス。

    Returns:
        保存先のパス。

    Raises:
        FileInputError: 出力先の親ディレクトリが存在しない場合。
    """
    ensure_output_parent(output_path)
    output_path.write_bytes(video.data)
    return output_path
