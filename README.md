# aitool-iroiro

OpenRouterの各モデルをCLIから呼び出すためのPythonツールです。画像生成・動画生成・画像認識・文字起こし・音声合成に対応しています。

バックエンドは基本的に OpenRouter ですが、OpenRouter で提供されないモデルが必要なコマンドに限って別サービスを直接呼びます（`transcribe-timestamp` → OpenAI、`generate-video --backend fal` → fal）。

## Install

```bash
uv tool install git+https://github.com/Nu424/aitool-iroiro.git
```

アップデードする場合:

```bash
uv tool install --force git+https://github.com/Nu424/aitool-iroiro.git
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
OPENAI_API_KEY=sk-...
FAL_KEY=...
```

既定モデルも同じ考え方で、CLIの `--model` が最優先です。未指定時は `.env`、`~/.env.global`、環境変数、最後にプログラム内定数の順で解決します。

```dotenv
AITOOL_IMAGE_GENERATION_MODEL=google/gemini-3.1-flash-image-preview
AITOOL_IMAGE_RECOGNITION_MODEL=google/gemini-3-flash-preview
AITOOL_STT_MODEL=openai/whisper-large-v3-turbo
AITOOL_STT_TIMESTAMP_MODEL=whisper-1
AITOOL_TTS_MODEL=google/gemini-3.1-flash-tts-preview
AITOOL_VIDEO_GENERATION_MODEL=minimax/hailuo-3-max
AITOOL_VIDEO_GENERATION_FAL_MODEL=minimax/h3-max-turbo
AITOOL_VIDEO_GENERATION_BACKEND=openrouter
```

## Commands

コマンドは、実際にモデルを呼ぶ**実行系**（`generate-image` / `generate-video` / `recognize-image` / `transcribe` / `transcribe-timestamp` / `tts`）と、使えるモデルや設定を調べる**情報系**（`models` / `voices` / `config`）に分かれます。

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

### Generate Video

```bash
aitool generate-video \
  --text "海辺を走る犬" \
  --output ./dog.mp4 \
  --duration 5 \
  --resolution 720p \
  --aspect-ratio 16:9
```

`--image` に画像を渡すと、その画像を先頭フレームにした image-to-video になります。

生成は非同期で、ジョブを投入したあと `--poll-interval`（既定 5 秒）間隔で完了を確認し、`--max-wait`（既定 900 秒）まで待ちます。`--timeout` は HTTP 1 往復のタイムアウトで、生成待ちの上限ではありません。`--verbose` を付けると進捗が stderr に出ます。

#### バックエンド

| `--backend` | 既定モデル | API キー | 用途 |
|---|---|---|---|
| `openrouter`（既定） | `minimax/hailuo-3-max` | `OPENROUTER_API_KEY` | Veo / Seedance / Wan / Kling / Sora / H3 Max など。`aitool models --feature video-generation` で一覧できます |
| `fal` | `minimax/h3-max-turbo` | `FAL_KEY` | OpenRouter に無いモデル（H3 Max Turbo など）を使うとき |

```bash
aitool generate-video --backend fal --text "海辺を走る犬" --output ./dog.mp4 --resolution 768p
```

fal のモデル ID は `publisher/name` の 2 階層で書くと、`--image` の有無に応じて `/text-to-video` または `/image-to-video` が補われます（`minimax/h3-max-turbo` → `minimax/h3-max-turbo/text-to-video`）。3 階層以上（`fal-ai/veo3.1/fast` など）はそのままエンドポイント ID として使います。既定バックエンドは `AITOOL_VIDEO_GENERATION_BACKEND=fal` で切り替えられます。

#### `--param` によるモデル固有パラメータ

`--duration` / `--resolution` / `--aspect-ratio` / `--audio` / `--seed` は共通オプションですが、fal はモデルごとに入力スキーマが異なります（Veo は `duration: "8s"`、Seedance は `duration: "auto"` など）。共通オプションで表せないものは `--param KEY=VALUE` で渡します。値は JSON として解釈され、解釈できなければ文字列になります。同名のキーは共通オプションより優先されます。

```bash
aitool generate-video --backend fal --model fal-ai/veo3.1/fast \
  --text "..." --output ./out.mp4 \
  --param duration=8s --param generate_audio=false
```

**価格の目安:** 多くのモデルは OpenRouter と fal で同額です。Veo 3.1 Fast と Seedance 2.0 は OpenRouter のほうが安く、H3 Max Turbo は fal のみで H3 Max の半額です。

### Recognize Image

```bash
aitool recognize-image \
  --text "この画像を説明してください" \
  --image ./table.png
```

結果は標準出力へ出ます。保存したい場合は `--output result.txt` を指定します。

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
  --output ./voice.pcm \
  --voice Zephyr \
  --format pcm
```

使える声質はモデルごとに異なります。`aitool voices` で確認できます。既定の `Zephyr` は既定モデル `google/gemini-3.1-flash-tts-preview` 用なので、`--model` を変えたときは `--voice` も合わせて指定してください。

**`--format` の注意:** 既定モデルの `google/gemini-3.1-flash-tts-preview` は `pcm` にしか対応しておらず、`--format` の既定値である `mp3` のままだと400エラーになります。既定モデルでは上のように `--format pcm` を明示してください。mp3が欲しい場合はmp3対応モデルを指定します。

```bash
aitool tts \
  --text "こんにちは。" \
  --output ./voice.mp3 \
  --model openai/gpt-4o-mini-tts \
  --voice alloy
```

### List Models

使用できるモデルを一覧します。

```bash
aitool models --feature tts
aitool models --feature image-generation --search gemini
```

`--feature` には次を指定できます。

| 値 | 対象 |
|---|---|
| `video-generation` | 動画生成モデル（`generate-video`、OpenRouter バックエンドのみ） |
| `image-generation` | 画像を出力できるモデル（`generate-image`） |
| `image-recognition` | 画像を入力できるモデル（`recognize-image`） |
| `stt` | 文字起こし専用モデル（`transcribe --mode dedicated`） |
| `stt-llm` | 音声を入力できるLLM（`transcribe --mode llm`） |
| `tts` | 音声を出力できるモデル（`tts`） |

`--feature` を省略するとテキスト出力モデルの一覧になります。TTS・STTのモデルはOpenRouter APIの仕様上、`--feature` を付けないと一覧に現れません。

`--feature video-generation` は `/videos/models` から取得するため列が異なり、対応解像度・尺と価格 SKU（キー名に単位が入る）を表示します。fal 限定モデルは一覧に含まれません。

**価格の注意:** STT・TTSのモデルはトークン単位で課金されません（音声の秒数や分数、文字数など）。OpenRouter APIは単位を返さないため、表の `$IN/1M` 列はテキストモデルと比較できません。正確な単価が必要な場合は `--json` の `pricing`（APIの生の値）を使ってください。

### List Voices

TTSモデルごとに使える声質（voice）を一覧します。ここに出た識別子をそのまま `tts --voice` に渡せます。

```bash
aitool voices
aitool voices --model gemini
```

```
google/gemini-3.1-flash-tts-preview  (30 voices)
  Zephyr, Puck, Charon, Kore, Fenrir, Leda, Orus, Aoede, ...
```

一覧はOpenRouter APIの `supported_voices` から取得するため、常に最新です。対応ボイスを公開していないモデルは表示されません。

### Config

APIキーの設定状況と、`--model` を省略したときに使われる既定モデルを、その取得元つきで表示します。APIキーの値そのものは表示しません。

```bash
aitool config
```

```
API keys:
  OPENROUTER_API_KEY   set (~/.env.global)
  OPENAI_API_KEY       not set
  FAL_KEY              not set

Default models:
  image_generation      google/gemini-3.1-flash-image-preview  (~/.env.global)
  stt_timestamp         whisper-1                              (built-in default)
  video_generation      minimax/hailuo-3-max                   (built-in default)
  video_generation_fal  minimax/h3-max-turbo                   (built-in default)

Video backend:
  openrouter  (built-in default)
```

## JSON Output

すべてのコマンドで `--json` を指定すると、標準出力に共通のJSONエンベロープが**1個だけ**出ます。人間向けの表示は抑制されるため、そのまま `jq` などに渡せます。

```bash
aitool recognize-image --text "説明して" --image ./photo.png --json
```

```json
{
  "ok": true,
  "command": "recognize-image",
  "model": "google/gemini-3-flash-preview",
  "provider": "Google",
  "result": { "text": "机の上に...", "output": null },
  "usage": {
    "prompt_tokens": 1234,
    "completion_tokens": 56,
    "total_tokens": 1290,
    "cost_usd": 0.00123,
    "generation_id": "gen-xxx"
  },
  "timing": { "elapsed_ms": 2143, "generation_time_ms": 1200, "latency_ms": 250 }
}
```

失敗時も同じ形で返り、終了コードは `1` になります。

```json
{
  "ok": false,
  "command": "recognize-image",
  "error": { "type": "OpenRouterHTTPError", "message": "...", "status_code": 429 }
}
```

コマンド別の `result` は次のとおりです。

| コマンド | `result` のキー |
|---|---|
| `generate-image` | `output`, `mime`, `message` |
| `generate-video` | `output`, `mime`, `backend`, `job_id`, `expanded_prompt` |
| `recognize-image` | `text`, `output` |
| `transcribe` | `text`, `output`, `mode` |
| `transcribe-timestamp` | `transcript`, `output` |
| `tts` | `output`, `content_type` |
| `models` | `feature`, `count`, `models` |
| `voices` | `count`, `models` |
| `config` | `api_keys`, `models`, `video_backend` |

取得できなかった値は `null` になります。`transcribe-timestamp` はOpenAI APIを直接呼ぶためコスト情報が無く、`usage` は `null` 埋めで `timing.elapsed_ms` のみが入ります。`generate-video` は OpenRouter バックエンドなら完了応答の `usage.cost` からコストが入ります（トークン数は無し）。fal バックエンドはコストを返さないため `cost_usd` は `null`、`provider` は `fal`、`timing.generation_time_ms` に推論時間が入ります。

### コストが取れる条件（`--stats`）

`generate-image` / `recognize-image` / `transcribe` はレスポンス自体に `usage` が含まれるため、**何もしなくてもコストが入ります**。

`tts` だけはレスポンスがバイナリで `usage` を持たず、コストを知るにはOpenRouterの `/generation` を照会する必要があります。ただしこの記録は生成直後には引けず、**引けるようになるまで実測で約10秒かかります**。そのため既定では照会せず、`--stats` を付けたときだけ行います。

```bash
# 速い。tts の usage は null（generation_id だけ入る）
aitool tts --text "テスト" --output ./v.pcm --format pcm --json

# 約10秒余分にかかるが、コストが入る
aitool tts --text "テスト" --output ./v.pcm --format pcm --stats --json
```

`--stats` は他のコマンドでも使えます（`generate-video` を除く。動画はコストが完了応答に含まれるため不要です）。その場合はサーバー側の `provider` / `latency_ms` / `generation_time_ms` が追加で埋まります。ただし `transcribe --mode dedicated` は生成IDを返さないため `--stats` を付けても変化しません（コストは付けなくても入ります）。

`--json` を付けない場合は、`--verbose` で所要時間とコストの1行サマリをstderrに出せます。

```bash
aitool recognize-image --text "説明して" --image ./photo.png --verbose
# stderr: Using model: google/gemini-3-flash-preview
# stderr: [5134 ms | $0.000550 | 1095 tokens | Google]
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
