# aitool-iroiro

OpenRouter APIなどを使って、マルチモーダルAIの作業をCLIから実行するPythonツールです。

## Install

```bash
uv tool install git+https://github.com/Nu424/aitool-iroiro.git
```

一時実行する場合:

```bash
uvx --from git+https://github.com/Nu424/aitool-iroiro.git aitool --help
```

ローカル開発では次のように実行できます。

```bash
uv run aitool --help
```

## API Key And Default Models

APIキーは次の順で解決します。

1. `--api-key`
2. カレントディレクトリの `.env`
3. `~/.env.global`
4. 環境変数

```dotenv
OPENROUTER_API_KEY=sk-or-...
GEMINI_API_KEY=...
OPENAI_API_KEY=sk-...
```

既定モデルも同じ考え方で、CLIの `--model` が最優先です。未指定時は `.env`、`~/.env.global`、環境変数、最後にプログラム内定数の順で解決します。

```dotenv
AITOOL_IMAGE_GENERATION_MODEL=google/gemini-3.1-flash-image-preview
AITOOL_IMAGE_RECOGNITION_MODEL=google/gemini-3-flash-preview
AITOOL_STT_MODEL=openai/whisper-large-v3-turbo
AITOOL_STT_TIMESTAMP_MODEL=whisper-1
AITOOL_TTS_MODEL=google/gemini-3.1-flash-tts-preview
AITOOL_VIDEO_RECOGNITION_MODEL=gemini-3.5-flash
```

## Commands

### Generate Image

```bash
aitool generate-image \
  --text "この画像に、かわいい猫を追加してください" \
  --image ./table.png \
  --output ./generated.png \
  --aspect-ratio 1:1 \
  --image-size 1K
```

`--image` は複数指定できます。省略するとテキストから画像を生成します。

### Recognize Image

```bash
aitool recognize-image \
  --text "この画像を説明してください" \
  --image ./table.png
```

結果は標準出力へ出ます。保存したい場合は `--output result.txt` を指定します。

### Recognize Video

```bash
aitool recognize-video \
  --text "この動画を要約してください" \
  --video ./meeting.mp4
```

`--video` にはローカル動画パス、または公開 YouTube URL を指定できます。ローカル動画は Google GenAI の File API でアップロードしてから処理します。

```bash
aitool recognize-video \
  --text "章立てして、重要な発言を抽出してください" \
  --video "https://www.youtube.com/watch?v=..." \
  --fps 0.5 \
  --structured-output \
  --output ./video-analysis.json
```

`--structured-output` を指定すると、動画全体の要約・トピック・エンティティ・セグメント情報を含む JSON を出力します。YouTube URL は公開動画のみ対応です。

### Transcribe

```bash
aitool transcribe --audio ./voice.mp3
```

結果は標準出力へ出ます。保存したい場合は `--output transcript.txt` を指定します。

```bash
aitool transcribe \
  --audio ./voice.mp3 \
  --output ./transcript.txt
```

既定ではOpenRouterの `/audio/transcriptions` を使います。プロンプト付きでマルチモーダルLLMに処理させたい場合は `--mode llm` を使います。

```bash
aitool transcribe \
  --mode llm \
  --prompt "話者ごとに分けて文字起こししてください" \
  --audio ./meeting.mp3
```

### Transcribe With Timestamps

```bash
aitool transcribe-timestamp --audio ./voice.mp3
```

OpenAI 公式 API を直接呼び出し、segment 単位のタイムスタンプ付き文字起こしを `verbose_json` 形式で出力します。`OPENAI_API_KEY` が必要です。結果は標準出力へ出ます。保存したい場合は `--output transcript.json` を指定します。

```bash
aitool transcribe-timestamp \
  --audio ./voice.mp3 \
  --granularity segment \
  --language ja \
  --output ./transcript.json
```

`--granularity` は `segment`（既定）、`word`、`both` を指定できます。`whisper-1` モデルは 25MB までの音声ファイルに対応します。

### Text To Speech

```bash
aitool tts \
  --text "こんにちは。これは音声合成のテストです。" \
  --output ./voice.mp3 \
  --voice alloy \
  --format mp3
```

## Agent Skill

Claude Code / Cowork などのAIエージェントからこのツール群を使うためのスキルが同梱されています。

```bash
npx skills add Nu424/aitool-iroiro
```

スキルは `skills/aitool-iroiro/SKILL.md` に格納されており、各コマンドのCLI引数リファレンスや困ったときの対処法を含みます。

## Development

```bash
uv sync --dev
uv run pytest
```
