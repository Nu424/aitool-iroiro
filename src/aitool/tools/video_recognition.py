"""Google GenAI API による動画理解。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from google import genai
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

from aitool.errors import FileInputError, GoogleGenAIResponseError
from aitool.io import video_mime_type

# ------------------------------
# ---動画理解の出力スキーマ
# ------------------------------
class VideoEntity(BaseModel):
    """動画内に登場する人物・物体などのエンティティ。"""

    id: str = Field(description="Entity identifier, such as person_1.")
    type: str = Field(description="Entity type, such as person or product.")
    label: str = Field(description="Entity label, such as person_1.")


class VideoUtterance(BaseModel):
    """動画内の発話単位。"""

    start_sec: float = Field(description="Utterance start time in seconds.")
    end_sec: float = Field(description="Utterance end time in seconds.")
    speaker: str = Field(description="Speaker entity identifier.")
    text: str = Field(description="Transcribed utterance text.")


class VideoSpeech(BaseModel):
    """動画セグメント内の音声・発話情報。"""

    speakers: list[str] = Field(description="Speaker entity identifiers present in the segment.")
    utterances: list[VideoUtterance] = Field(description="Timestamped utterances in the segment.")


class VideoGlobalInfo(BaseModel):
    """動画全体の分析結果。"""

    summary: str = Field(description="Brief summary of the whole video.")
    topics: list[str] = Field(description="Major topics covered in the video.")
    entities: list[VideoEntity] = Field(description="Entities detected across the video.")


class VideoSegment(BaseModel):
    """動画内の時系列セグメント分析。"""

    start_sec: float = Field(description="Segment start time in seconds.")
    end_sec: float = Field(description="Segment end time in seconds.")
    title: str = Field(description="Short segment title.")
    summary: str = Field(description="Detailed segment summary.")
    visual: str = Field(description="Visual details such as place, objects, and actions.")
    audio: str = Field(description="Audio characteristics and relevant non-speech information.")
    speech: VideoSpeech = Field(description="Speech information in the segment.")
    entities_present: list[str] = Field(description="Entity identifiers present in the segment.")


class VideoAnalysis(BaseModel):
    """構造化動画理解の出力形式。"""

    model_config = ConfigDict(populate_by_name=True)

    global_: VideoGlobalInfo = Field(alias="global", description="Whole-video analysis.")
    segments: list[VideoSegment] = Field(description="Chronological video segments.")


VIDEO_STRUCTURE_SCHEMA = VideoAnalysis.model_json_schema()
"""動画構造化出力の JSON Schema。テストや参照用に Pydantic モデルから生成する。"""

# ------------------------------
# ---動画理解のツール
# ------------------------------
def is_youtube_url(video: str) -> bool:
    """入力文字列が YouTube URL かどうかを判定する。"""
    parsed = urlparse(video)
    if parsed.scheme not in {"http", "https"}:
        return False

    host = parsed.netloc.lower()
    return host == "youtu.be" or host.endswith(".youtube.com") or host == "youtube.com"


def build_video_part(file_uri: str, mime_type: str | None = None, fps: float | None = None) -> types.Part:
    """動画URIから Gemini 入力用 Part を組み立てる。"""
    video_metadata = types.VideoMetadata(fps=fps) if fps is not None else None
    return types.Part(
        file_data=types.FileData(file_uri=file_uri, mime_type=mime_type),
        video_metadata=video_metadata,
    )


def build_generate_content_config(
    *,
    structured_output: bool,
    timeout: float,
) -> types.GenerateContentConfig:
    """動画理解リクエスト用の生成設定を組み立てる。"""
    if structured_output:
        return types.GenerateContentConfig(
            http_options=types.HttpOptions(timeout=int(timeout * 1000)),
            response_mime_type="application/json",
            response_schema=VideoAnalysis,
        )

    return types.GenerateContentConfig(
        http_options=types.HttpOptions(timeout=int(timeout * 1000)),
    )


@dataclass(slots=True)
class VideoRecognitionTool:
    """動画とテキストから説明・回答テキストを得るツール。"""

    api_key: str
    model: str
    timeout: float
    verbose: bool = False

    def run(
        self,
        video: str,
        *,
        prompt: str,
        structured_output: bool = False,
        fps: float | None = None,
    ) -> str:
        """動画理解を実行し、モデルのテキスト応答を返す。

        Args:
            video: 入力動画のローカルパス、または YouTube URL。
            prompt: 動画に対する質問・指示テキスト。
            structured_output: 参照スキーマに沿った JSON 出力を要求するかどうか。
            fps: 動画サンプリングのカスタムフレームレート。

        Returns:
            モデルが返したテキスト応答。
        """
        # ---LLMを呼び出す
        client = self._create_client()
        try:
            video_part = self._build_input_part(client, video, fps)
            response = client.models.generate_content(
                model=self.model,
                contents=[video_part, types.Part(text=prompt)],
                config=build_generate_content_config(
                    structured_output=structured_output,
                    timeout=self.timeout,
                ),
            )
        finally:
            client.close()

        # ---出力を抽出する
        text = getattr(response, "text", None)
        if not isinstance(text, str):
            raise GoogleGenAIResponseError("Video recognition response did not include text.")

        # ---構造化出力を解析する
        if structured_output:
            try:
                VideoAnalysis.model_validate_json(text)
            except ValueError as exc:
                raise GoogleGenAIResponseError(
                    "Structured video response did not match the expected schema."
                ) from exc

        return text

    def _create_client(self) -> genai.Client:
        """このツール用の Google GenAI クライアントを生成する。"""
        return genai.Client(
            api_key=self.api_key,
            http_options=types.HttpOptions(timeout=int(self.timeout * 1000)),
        )

    def _build_input_part(self, client: genai.Client, video: str, fps: float | None) -> types.Part:
        """ローカル動画または YouTube URL から入力 Part を作る。"""
        # ---YouTube URL の場合は、そのままPartを作る
        if is_youtube_url(video):
            return build_video_part(video, fps=fps)

        # ---ローカル動画の場合は、File API でアップロードする
        parsed = urlparse(video)
        if parsed.scheme in {"http", "https"}:
            raise FileInputError("Only public YouTube URLs are supported for URL video input.")

        video_path = Path(video)
        mime_type = video_mime_type(video_path)
        uploaded_file = client.files.upload( # アップロード
            file=video_path,
            config=types.UploadFileConfig(mime_type=mime_type),
        )
        active_file = self._wait_until_active(client, uploaded_file)

        if not active_file.uri:
            raise GoogleGenAIResponseError("Uploaded video file did not include a file URI.")

        # アップロード後、File API からファイルURIを取得して、Partを作る
        return build_video_part(active_file.uri, active_file.mime_type or mime_type, fps)

    def _wait_until_active(self, client: genai.Client, uploaded_file: types.File) -> types.File:
        """File API の動画処理が完了するまで必要に応じて待機する。"""
        state = getattr(uploaded_file.state, "name", None)
        if state in {None, "ACTIVE"}:
            return uploaded_file
        if state == "FAILED":
            raise GoogleGenAIResponseError("Uploaded video file processing failed.")
        if state != "PROCESSING":
            return uploaded_file
        if not uploaded_file.name:
            raise GoogleGenAIResponseError("Uploaded video file did not include a file name.")

        deadline = time.monotonic() + self.timeout
        current_file = uploaded_file
        while time.monotonic() < deadline:
            time.sleep(2)
            current_file = client.files.get(name=uploaded_file.name)
            state = getattr(current_file.state, "name", None)
            if state in {None, "ACTIVE"}:
                return current_file
            if state == "FAILED":
                raise GoogleGenAIResponseError("Uploaded video file processing failed.")

        raise GoogleGenAIResponseError("Timed out waiting for uploaded video file processing.")
