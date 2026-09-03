---
name: aitool-iroiro
description: |
  OpenRouter API / OpenAI API経由でマルチモーダルAIタスクをCLIから実行するツール群 (aitool-iroiro) の使い方スキル。
  画像生成・画像認識・音声文字起こし・音声合成が必要なとき、または `aitool` コマンドを使うタスクが来たときは必ずこのスキルを参照すること。
  具体的には「画像を編集して」「この音声をテキストにして」「テキストを読み上げて」「画像を説明して」などのリクエストが対象。
---

# aitool-iroiro スキル

OpenRouter API と OpenAI API を使ったマルチモーダルAI CLIツール群。`aitool` コマンド1本で画像生成・画像認識・文字起こし・タイムスタンプ付き文字起こし・音声合成を実行できる。

## コマンドリファレンス

### 共通オプション（全コマンドで使用可能）

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--model TEXT` | 使用モデルを上書き | 環境変数またはプログラム内定数 |
| `--api-key TEXT` | APIキーを指定（タイムスタンプ付き文字起こしはOpenAI、それ以外はOpenRouter） | `.env` / 環境変数 |
| `--timeout FLOAT` | HTTPタイムアウト（秒） | `120.0` |
| `--json` | メタ情報をJSON形式で標準出力に表示 | `False` |
| `--verbose` | 追加ステータスをstderrに表示 | `False` |

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

**`--json` 出力のキー:** `output`, `model`, `mime`, `message`

---

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

**`--json` 出力のキー:** `output`, `model`

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

**`--json` 出力のキー:** `output`, `model`, `mode`

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
| + 共通オプション（`--json` 除く） | | | |

注意: `OPENAI_API_KEY` が必要。既定モデルは `whisper-1`（25MB まで）。`gpt-4o-transcribe` 系は `verbose_json` 非対応のため使用不可。

---

### `tts` — 音声合成

テキストから音声ファイルを生成する。

```bash
aitool tts \
  --text "こんにちは。テストです。" \
  --output ./voice.mp3 \
  [--voice alloy] \
  [--format mp3] \
  [--speed 1.0]
```

| オプション | 短縮 | 必須 | 説明 |
|-----------|------|------|------|
| `--text TEXT` | `-t` | ✅ | 合成するテキスト |
| `--output PATH` | `-o` | ✅ | 音声ファイルの保存先パス |
| `--voice TEXT` | — | — | ボイス識別子（デフォルト: `alloy`） |
| `--format TEXT` | — | — | 出力音声フォーマット（デフォルト: `mp3`） |
| `--speed FLOAT` | — | — | 再生速度（モデルが対応している場合） |
| + 共通オプション | | | |

**`--json` 出力のキー:** `output`, `model`, `content_type`, `generation_id`

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

# モデルを変えたい場合（省略時はプログラム内定数が使われる）
AITOOL_IMAGE_GENERATION_MODEL=google/gemini-3.1-flash-image-preview
AITOOL_IMAGE_RECOGNITION_MODEL=google/gemini-3-flash-preview
AITOOL_STT_MODEL=openai/whisper-large-v3-turbo
AITOOL_STT_TIMESTAMP_MODEL=whisper-1
AITOOL_TTS_MODEL=google/gemini-3.1-flash-tts-preview
```