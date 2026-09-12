---
name: aitool-iroiro
description: |
  OpenRouterの各モデルをCLIから呼び出すツール群 (aitool-iroiro) の使い方スキル。
  画像生成・動画生成・画像認識・音声文字起こし・音声合成が必要なとき、または `aitool` コマンドを使うタスクが来たときは必ずこのスキルを参照すること。
  具体的には「画像を編集して」「この画像を動かして」「短い動画を作って」「この音声をテキストにして」「テキストを読み上げて」「画像を説明して」などのリクエストが対象。
  「どのモデルが使える？」「どんな声が選べる？」といった確認にも `aitool models` / `aitool voices` で答えられる。
---

# aitool-iroiro スキル

OpenRouterの各モデルをCLIから呼び出すツール群。`aitool` コマンド1本で画像生成・動画生成・画像認識・文字起こし・タイムスタンプ付き文字起こし・音声合成を実行できる。

コマンドは2種類ある。

- **実行系** — 実際にモデルを呼ぶ: `generate-image` / `generate-video` / `recognize-image` / `transcribe` / `transcribe-timestamp` / `tts`
- **情報系** — 使えるモデルや設定を調べる（コストなし）: `models` / `voices` / `config`

`--model` に何を指定できるか迷ったら、まず `aitool models --feature <機能>` を見る。

## コマンドリファレンス

### 共通オプション（全コマンドで使用可能）

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--model TEXT` | 使用モデルを上書き | 環境変数またはプログラム内定数 |
| `--api-key TEXT` | APIキーを指定（タイムスタンプ付き文字起こしはOpenAI、`generate-video --backend fal` はfal、それ以外はOpenRouter） | `.env` / 環境変数 |
| `--timeout FLOAT` | HTTPタイムアウト（秒） | `120.0` |
| `--json` | 結果とメタ情報をJSONエンベロープ1個として標準出力に出す（人間向け表示は抑制） | `False` |
| `--verbose` | 使用モデルと、所要時間・コストの1行サマリをstderrに表示 | `False` |
| `--stats` | `/generation` を照会して正確なコストとサーバー側の所要時間を補う。**約10秒余分にかかる**（`transcribe-timestamp` / `generate-video` を除く） | `False` |

**重要:** `--json` を付けると標準出力はJSONエンベロープ**だけ**になる。テキスト結果は `result.text` に入るので、`--output` を使わずにパースできる。付けない場合は従来どおりテキストがそのまま出る。

---

### `generate-image` — 画像生成

テキストプロンプトから画像生成（t2i）、または入力画像を編集（i2i）する。

```bash
aitool generate-image \
  --text "かわいい猫を追加してください" \
  --output ./output.png \
  [--image ./input.png] \   # 省略するとt2i、指定するとi2i
  [--aspect-ratio 1:1] \
  [--image-size 1K]
```

| オプション | 短縮 | 必須 | 説明 |
|-----------|------|------|------|
| `--text TEXT` | `-t` | ✅ | プロンプトテキスト |
| `--output PATH` | `-o` | ✅ | 生成画像の保存先パス |
| `--image PATH` | `-i` | — | 入力画像パス（複数回指定可） |
| `--aspect-ratio TEXT` | — | — | アスペクト比（例: `1:1`, `16:9`） |
| `--image-size TEXT` | — | — | 画像サイズ（例: `1K`, `2K`, `4K`） |
| + 共通オプション | | | |

**`--json` の `result` キー:** `output`, `mime`, `message`

---

### `generate-video` — 動画生成

テキストプロンプトから動画生成（t2v）、または入力画像を先頭フレームにした動画生成（i2v）を行う。**生成には数十秒〜数分かかる**ので、エージェントは完了までブロックされることを前提にする。

```bash
# OpenRouter（既定）
aitool generate-video \
  --text "海辺を走る犬" \
  --output ./dog.mp4 \
  [--image ./first-frame.png] \   # 指定するとi2v
  [--duration 5] \
  [--resolution 720p] \
  [--aspect-ratio 16:9] \
  [--audio | --no-audio]

# fal（H3 Max Turbo など OpenRouter に無いモデル）
aitool generate-video --backend fal \
  --text "海辺を走る犬" \
  --output ./dog.mp4 \
  --resolution 768p
```

| オプション | 短縮 | 必須 | 説明 |
|-----------|------|------|------|
| `--text TEXT` | `-t` | ✅ | プロンプトテキスト |
| `--output PATH` | `-o` | ✅ | 生成動画の保存先パス（通常 `.mp4`） |
| `--image PATH` | `-i` | — | 先頭フレームにする画像（指定するとi2v） |
| `--duration INT` | — | — | 動画の長さ（秒）。省略時はモデル既定 |
| `--resolution TEXT` | — | — | 解像度（`480p` / `720p` / `768p` / `1080p` など。対応はモデルによる） |
| `--aspect-ratio TEXT` | — | — | アスペクト比（`16:9` / `9:16` / `1:1` など） |
| `--audio` / `--no-audio` | — | — | 音声生成の有無。省略時はモデル既定 |
| `--seed INT` | — | — | 乱数シード |
| `--param KEY=VALUE` | `-p` | — | バックエンド固有パラメータ。複数回指定可。値はJSONとして解釈（例: `--param duration=8s`） |
| `--backend TEXT` | `-b` | — | `openrouter`（既定）または `fal` |
| `--poll-interval FLOAT` | — | — | 状態確認の間隔（秒）。既定 `5` |
| `--max-wait FLOAT` | — | — | 完了を待つ上限（秒）。既定 `900` |
| + 共通オプション | | | |

**`--json` の `result` キー:** `output`, `mime`, `backend`, `job_id`, `expanded_prompt`

**バックエンドの選び方:**

| バックエンド | 既定モデル | 必要なキー | 使いどころ |
|---|---|---|---|
| `openrouter` | `minimax/hailuo-3-max` | `OPENROUTER_API_KEY` | 基本はこちら。Veo 3.1 / Seedance 2.x / Wan 3.0 / Kling v3 / Sora 2 Pro / H3 Max。`aitool models --feature video-generation` で一覧できる |
| `fal` | `minimax/h3-max-turbo` | `FAL_KEY` | H3 Max Turbo（H3 Max の半額・同等品質）など、OpenRouter に無いモデルが必要なとき |

- ユーザーが特にモデルを指定しなければ既定（OpenRouter）でよい。「安く・速く」を求められたら `--backend fal`（H3 Max Turbo）を提案する。
- `--backend fal` で `FAL_KEY` が無いとエラーになる。無ければ OpenRouter の `minimax/hailuo-3-max` で代替できる（Turbo ではないが同系統）。
- fal のモデル ID は `publisher/name` の2階層で書くと `--image` の有無に応じて `/text-to-video` / `/image-to-video` が自動で補われる。`fal-ai/veo3.1/fast` のような3階層以上はそのまま使われる。
- fal はモデルごとに入力スキーマが異なる。共通オプションは MiniMax H3 系に合わせてあり（`--resolution 768p` は自動で `768P` になる）、Veo（`duration: "8s"`）や Seedance（`duration: "auto"`）のような形式は `--param duration=8s` で渡す。400/422 エラーの本文に有効な値が書かれているので、それを見て `--param` で渡し直す。
- `--timeout` は HTTP 1往復のタイムアウトで、生成待ちの上限ではない。長い動画で待ちきれない場合は `--max-wait` を延ばす。
- コスト: OpenRouter は `usage.cost_usd` にコストが入る（トークン数は無い）。fal はコストを返さないので `cost_usd` は `null`。`--stats` は不要（効かない）。

### `recognize-image` — 画像認識

画像に対してテキストで質問し、回答を得る。

```bash
aitool recognize-image \
  --text "この画像を説明してください" \
  --image ./photo.png \
  [--output ./result.txt]  # 省略すると標準出力
```

| オプション | 短縮 | 必須 | 説明 |
|-----------|------|------|------|
| `--text TEXT` | `-t` | ✅ | プロンプトテキスト |
| `--image PATH` | `-i` | ✅ | 入力画像パス（複数回指定可） |
| `--output PATH` | `-o` | — | テキスト結果の保存先（省略→標準出力） |
| + 共通オプション | | | |

**`--json` の `result` キー:** `text`, `output`

---

### `transcribe` — 音声文字起こし

音声ファイルをテキストに変換する。

```bash
# STT専用APIを使う（デフォルト）
aitool transcribe --audio ./voice.mp3 [--output ./transcript.txt]

# マルチモーダルLLMに処理させる（プロンプト付き）
aitool transcribe \
  --mode llm \
  --prompt "話者ごとに分けてください" \
  --audio ./meeting.mp3
```

| オプション | 短縮 | 必須 | 説明 |
|-----------|------|------|------|
| `--audio PATH` | `-a` | ✅ | 入力音声ファイルパス |
| `--output PATH` | `-o` | — | テキスト結果の保存先（省略→標準出力） |
| `--format TEXT` | — | — | 音声フォーマット（省略→拡張子から推定） |
| `--mode TEXT` | — | — | `dedicated`（デフォルト）または `llm` |
| `--prompt TEXT` | — | — | `--mode llm` 使用時のプロンプト |
| + 共通オプション | | | |

**`--json` の `result` キー:** `text`, `output`, `mode`

---

### `transcribe-timestamp` — タイムスタンプ付き文字起こし

OpenAI 公式 API を直接呼び出し、segment（または word）単位のタイムスタンプ付き文字起こしを行う。結果は `verbose_json` 形式の JSON。

```bash
# セグメント単位（デフォルト）
aitool transcribe-timestamp --audio ./voice.mp3 [--output ./transcript.json]

# 単語単位のタイムスタンプも含める
aitool transcribe-timestamp \
  --audio ./voice.mp3 \
  --granularity segment \
  --language ja \
  --output ./transcript.json
```

| オプション | 短縮 | 必須 | 説明 |
|-----------|------|------|------|
| `--audio PATH` | `-a` | ✅ | 入力音声ファイルパス |
| `--output PATH` | `-o` | — | JSON結果の保存先（省略→標準出力） |
| `--format TEXT` | — | — | 音声フォーマット（省略→拡張子から推定） |
| `--granularity TEXT` | — | — | `segment`（デフォルト）、`word`、`both` |
| `--language TEXT` | — | — | 入力言語の ISO-639-1 コード |
| `--prompt TEXT` | — | — | スタイル誘導用プロンプト |
| + 共通オプション | | | |

**`--json` の `result` キー:** `transcript`, `output`

注意: `OPENAI_API_KEY` が必要。既定モデルは `whisper-1`（25MB まで）。`gpt-4o-transcribe` 系は `verbose_json` 非対応のため使用不可。OpenAI APIはコスト情報を返さないため、`usage` は `null` 埋めで `timing.elapsed_ms` のみ入る。

---

### `tts` — 音声合成

テキストから音声ファイルを生成する。

```bash
aitool tts \
  --text "こんにちは。テストです。" \
  --output ./voice.mp3 \
  [--voice Zephyr] \
  [--format mp3] \
  [--speed 1.0]
```

| オプション | 短縮 | 必須 | 説明 |
|-----------|------|------|------|
| `--text TEXT` | `-t` | ✅ | 合成するテキスト |
| `--output PATH` | `-o` | ✅ | 音声ファイルの保存先パス |
| `--voice TEXT` | — | — | ボイス識別子（デフォルト: `Zephyr`）。`aitool voices` で確認する |
| `--format TEXT` | — | — | 出力音声フォーマット（デフォルト: `mp3`） |
| `--speed FLOAT` | — | — | 再生速度（モデルが対応している場合） |
| `--format TEXT` | — | — | `mp3` または `pcm`。**モデルによって対応が異なる** |
| + 共通オプション | | | |

**`--json` の `result` キー:** `output`, `content_type`

**重要な注意:**
- 既定モデル `google/gemini-3.1-flash-tts-preview` は `pcm` にしか対応していない。`--format mp3`（既定値）だと400エラーになるので、既定モデルでは `--format pcm` を明示すること。mp3が必要なら `--model openai/gpt-4o-mini-tts` のようにmp3対応モデルを指定する。
- 声質はモデルごとに異なる。`aitool voices --model <モデルID>` で確認してから `--voice` に渡す。
- `tts` はレスポンスがバイナリで `usage` を持たないため、`--json` だけではコストが `null` になる。コストが必要なら `--stats` を足す（約10秒余分にかかる）。

---

## 情報系サブコマンド

「どのモデルが使える？」「どんな声が選べる？」「今どのモデルが既定？」に答えるためのコマンド。実行系と違ってモデルを呼ばないので、コストはかからない。

### `models` — 使用できるモデルの確認

```bash
aitool models --feature tts
aitool models --feature image-generation --search gemini
aitool models --feature stt --json
```

| オプション | 短縮 | 説明 |
|-----------|------|------|
| `--feature TEXT` | `-f` | 機能で絞り込む（下表） |
| `--search TEXT` | `-s` | モデルIDまたは表示名の部分一致で絞り込む |

`--feature` に指定できる値:

| 値 | 対象 | 対応コマンド |
|---|---|---|
| `video-generation` | 動画生成モデル（OpenRouter バックエンドのみ） | `generate-video` |
| `image-generation` | 画像を出力できるモデル | `generate-image` |
| `image-recognition` | 画像を入力できるモデル | `recognize-image` |
| `stt` | 文字起こし専用モデル | `transcribe --mode dedicated` |
| `stt-llm` | 音声を入力できるLLM | `transcribe --mode llm` |
| `tts` | 音声を出力できるモデル | `tts` |

**注意:** `--feature` を省略するとテキスト出力モデルの一覧になる。TTS・STTのモデルはOpenRouter APIの仕様上、`--feature` を付けないと一覧に現れない。

**価格の注意:** STT・TTSのモデルはトークン単位で課金されない（音声の秒数・分数、文字数など）。OpenRouter APIは単位を返さないため、表の `$IN/1M` 列をテキストモデルと比較してはいけない。正確な単価が必要なら `--json` の `pricing`（APIの生の値）を見る。

**`--json` の `result` キー:** `feature`, `count`, `models`（各要素は `id`, `name`, `context_length`, `prompt_price_per_1m`, `completion_price_per_1m`, `input_modalities`, `output_modalities`, `supported_voices`）

`--feature video-generation` だけは別エンドポイント（`/videos/models`）から取るので要素が異なる: `id`, `supported_resolutions`, `supported_durations`, `supported_aspect_ratios`, `pricing_skus`（キー名に単位が入る。例: `duration_seconds_720p=0.10` は 720p で 1 秒あたり $0.10）。fal 限定モデルは出ない。

---

### `voices` — 使用できるTTS声質の確認

TTSモデルごとに使える声質を一覧する。ここに出た識別子をそのまま `tts --voice` に渡せる。

```bash
aitool voices
aitool voices --model gemini
aitool voices --json
```

| オプション | 短縮 | 説明 |
|-----------|------|------|
| `--model TEXT` | `-m` | モデルIDの部分一致で絞り込む |

一覧はOpenRouter APIの `supported_voices` から取得するので常に最新。対応ボイスを公開していないモデルは表示されない。

**`--json` の `result` キー:** `count`, `models`（各要素は `id`, `name`, `voices`）

---

### `config` — 設定の確認

APIキーの設定状況と、`--model` を省略したときに使われる既定モデルを、その取得元つきで表示する。APIキーの値そのものは表示しない。

```bash
aitool config
aitool config --json
```

モデル指定まわりで想定と違う挙動をしたときは、まずこれを見る。

**`--json` の `result` キー:** `api_keys`（`env_var`, `is_set`, `source`）, `models`（`feature`, `env_var`, `model`, `source`）, `video_backend`（`env_var`, `backend`, `source`）

---

## JSON出力（`--json`）

すべてのコマンドで共通のエンベロープが標準出力に**1個だけ**出る。人間向け表示は抑制されるので、そのままパースできる。

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

失敗時も同じ形で返り、終了コードは `1`。

```json
{
  "ok": false,
  "command": "recognize-image",
  "error": { "type": "OpenRouterHTTPError", "message": "...", "status_code": 429 }
}
```

取得できなかった値は `null` になる。コストを知りたいときは `usage.cost_usd`、実測の所要時間は `timing.elapsed_ms` を見る。

### コストが取れる条件

| コマンド | `--json` だけ | `--stats` を足すと |
|---|---|---|
| `generate-image` | コストが入る | + provider / サーバー側の所要時間 |
| `generate-video`（openrouter） | コストが入る（トークン数は `null`） | `--stats` 非対応 |
| `generate-video`（fal） | コストなし（fal直叩き）。`timing.generation_time_ms` に推論時間 | `--stats` 非対応 |
| `recognize-image` | コストが入る | + provider / サーバー側の所要時間 |
| `transcribe --mode llm` | コストが入る | + provider / サーバー側の所要時間 |
| `transcribe --mode dedicated` | コストが入る（トークン数は `null`） | 変化なし（生成IDが返らないため） |
| `tts` | **コストは `null`** | コストが入る |
| `transcribe-timestamp` | コストなし（OpenAI直叩き） | `--stats` 非対応 |

`tts` だけレスポンスに `usage` が無く、OpenRouterの `/generation` を照会するしかない。この記録は生成直後には引けず、実測で約10秒かかる。そのため既定では照会しない。

`transcribe --mode dedicated` は `usage` に秒数ベースのコストを返すが、トークン数と生成IDは返さないため `total_tokens` は `null` になる。

`--json` を付けない場合は、`--verbose` で所要時間とコストの1行サマリがstderrに出る。

```
[2143 ms | $0.000011 | 492 tokens | Google]
```

---

## 困ったときは

### `aitool: command not found` — 未インストールの場合

インストールせずに一時実行する:

```bash
uvx --from git+https://github.com/Nu424/aitool-iroiro.git aitool <サブコマンド> [オプション]
```

または恒久インストール:

```bash
uv tool install git+https://github.com/Nu424/aitool-iroiro.git
```

### `Error: OPENROUTER_API_KEY not found` — OpenRouter APIキー未設定の場合

ユーザーに以下のいずれかを案内する:

**A. カレントディレクトリに `.env` を作る（推奨）:**

```dotenv
OPENROUTER_API_KEY=sk-or-xxxxxxxxxxxxxxxx
```

**B. ホームの `~/.env.global` に書く（グローバル設定）:**

```dotenv
OPENROUTER_API_KEY=sk-or-xxxxxxxxxxxxxxxx
```

**C. CLI引数で直接渡す（一時的な使用）:**

```bash
aitool generate-image --api-key sk-or-xxx --text "..." --output ./out.png
```

APIキーは https://openrouter.ai/keys で取得できる。

### `Error: OPENAI_API_KEY not found` — OpenAI APIキー未設定の場合

タイムスタンプ付き文字起こしを使う場合は、以下のいずれかで OpenAI API キーを設定する:

```dotenv
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
```

またはCLI引数で直接渡す:

```bash
aitool transcribe-timestamp --api-key sk-xxx --audio ./voice.mp3
```

APIキーは https://platform.openai.com/api-keys で取得できる。

### `Error: fal API key was not found` — fal APIキー未設定の場合

`generate-video --backend fal` を使う場合は `FAL_KEY` を設定する:

```dotenv
FAL_KEY=xxxxxxxx-...:...
```

またはCLI引数で直接渡す:

```bash
aitool generate-video --backend fal --api-key xxx --text "..." --output ./out.mp4
```

APIキーは https://fal.ai/dashboard/keys で取得できる。キーが用意できない場合は `--backend` を省略して OpenRouter の `minimax/hailuo-3-max` を使う。

### `Video generation did not finish within ...` — 生成待ちのタイムアウト

`--max-wait` を延ばして再実行する（既定は 900 秒）。`--verbose` を付けると進捗が stderr に出る。

---

## 参考: API キー・モデルの設定

APIキーとモデルは以下の優先順で解決される（上ほど優先）。

| 優先度 | 方法 |
|--------|------|
| 1 | `--api-key` CLI引数 |
| 2 | カレントディレクトリの `.env` |
| 3 | `~/.env.global` |
| 4 | 環境変数 |

**.env の例:**

```dotenv
OPENROUTER_API_KEY=sk-or-...
OPENAI_API_KEY=sk-...
FAL_KEY=...

# モデルを変えたい場合（省略時はプログラム内定数が使われる）
AITOOL_IMAGE_GENERATION_MODEL=google/gemini-3.1-flash-image-preview
AITOOL_IMAGE_RECOGNITION_MODEL=google/gemini-3-flash-preview
AITOOL_STT_MODEL=openai/whisper-large-v3-turbo
AITOOL_STT_TIMESTAMP_MODEL=whisper-1
AITOOL_TTS_MODEL=google/gemini-3.1-flash-tts-preview
AITOOL_VIDEO_GENERATION_MODEL=minimax/hailuo-3-max
AITOOL_VIDEO_GENERATION_FAL_MODEL=minimax/h3-max-turbo

# 動画生成の既定バックエンド（openrouter / fal）
AITOOL_VIDEO_GENERATION_BACKEND=openrouter
```