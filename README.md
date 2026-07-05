# colab-local-llm-cli

Google Colab の T4 ランタイム上に GGUF 量子化 LLM を OpenAI 互換 API として起動し、
ローカル端末の CLI から質問できるようにするための、軽量なスクリプト集です。

## 1. 概要

このリポジトリは以下を行います。

- Google Colab CLI (公式CLI) を使って T4 ランタイムを起動し、`llama-cpp-python` の
  OpenAI互換サーバー (`llama_cpp.server`) 上で GGUF 量子化モデルを動かします。
- ローカル端末からは、シンプルな `curl` ベースの CLI (`scripts/ask.sh`) を使って、
  `POST /v1/chat/completions` 相当のリクエストを送り、回答を受け取ります。
- モデルのダウンロードやセットアップ、ヘルスチェックまで一通り自動化しています。

## 2. アーキテクチャ図

```
ローカル端末                            Colab T4 ランタイム
+--------------------+                +-----------------------------------+
|                    |   ポート        |                                   |
| scripts/ask.sh     |  フォワード/    |  colab/start_llm_server.py        |
| (CLIクライアント)  | <--トンネル-->  |   -> llama-cpp-python server      |
|                    | (http://:8000) |      (OpenAI互換API, :8000)       |
+--------------------+                |   -> GGUF量子化モデル (models/)   |
                                      +-----------------------------------+
```

## 3. 前提条件

- Google アカウント (Google Colab を利用できること)
- Google Colab CLI (公式CLI) がインストール・認証済みであること
  - 公式ドキュメント: https://developers.google.com/colab
  - インストール方法・認証手順はバージョンによって変わる可能性があるため、
    必ず公式ドキュメントの最新手順に従ってください
    (例として `pip install google-colab-cli` のような形になる場合があります)。
- Python 3.10 以上 (ローカル端末側、およびColabランタイム側)
- `curl` (ローカル端末側での動作確認・API呼び出しに使用)

## 4. セットアップ / T4ランタイム起動例

Colab CLI を使って、T4 GPU ランタイム上でセットアップからサーバー起動までを
一括実行する想定コマンドは以下の通りです。

```bash
colab --gpu T4 exec scripts/start_server.sh
```

リポジトリをランタイムに配置する場合の例 (git clone をランタイム上で実行):

```bash
colab --gpu T4 exec -- git clone https://github.com/<your>/colab-local-llm-cli.git
```

### フォールバック: Colab CLI が使えない場合

Colab CLI が利用できない環境では、通常の Colab ノートブックのセルから
同等の操作を行うことができます。

```python
!git clone https://github.com/<your>/colab-local-llm-cli.git
%cd colab-local-llm-cli
!bash scripts/start_server.sh
```

## 5. サーバー起動時の環境変数

`colab/start_llm_server.py` および関連スクリプトは、以下の環境変数で挙動を調整できます。

| 変数名        | 既定値                                              | 意味                                             |
|---------------|------------------------------------------------------|--------------------------------------------------|
| `MODEL_PATH`  | `models/qwen2.5-1.5b-instruct-q4_k_m.gguf` (repo基準) | 起動するGGUFモデルファイルのパス                 |
| `LLM_HOST`    | `0.0.0.0`                                             | サーバーがバインドするホスト                     |
| `LLM_PORT`    | `8000`                                                | サーバーが待ち受けるポート番号                   |
| `N_GPU_LAYERS`| `-1`                                                  | GPUにオフロードするレイヤー数 (`-1`で全レイヤー) |
| `N_CTX`       | `4096`                                                | コンテキスト長 (トークン数)                      |
| `HF_REPO_ID`  | `Qwen/Qwen2.5-1.5B-Instruct-GGUF`                     | ダウンロード元のHugging Faceリポジトリ           |
| `HF_FILENAME` | `qwen2.5-1.5b-instruct-q4_k_m.gguf`                   | ダウンロードするファイル名                       |
| `MODEL_DIR`   | `models`                                              | モデルの保存先ディレクトリ (repo基準の相対パス可)|
| `HF_TOKEN`    | (未設定)                                              | gated (要認証) モデル取得用のHugging Faceトークン|

## 6. ローカルからの接続

サーバーは Colab ランタイム上の `localhost:8000` で待ち受けます。ローカル端末から
アクセスするには、以下のいずれかの方法でランタイムの外に公開する必要があります。

- (a) Colab CLI のポートフォワード機能 (利用可能な場合はそちらを優先してください)
- (b) トンネルサービス (`cloudflared` や `ngrok` など) を使う (任意・オプション)

トンネルの例 (`cloudflared` を使う場合):

```bash
cloudflared tunnel --url http://localhost:8000
```

上記で発行されたURL (例: `https://xxxx.trycloudflare.com`) を使い、ローカル端末側で
以下のように接続します。

```bash
export LLM_BASE_URL="http://localhost:8000/v1"   # トンネル利用時は https://xxxx.trycloudflare.com/v1 などに置き換える
export LLM_API_KEY="dummy"
export LLM_MODEL="local"
./scripts/ask.sh "量子化LLMとは？"
```

動作確認 (ヘルスチェック):

```bash
LLM_BASE_URL="http://localhost:8000/v1" ./scripts/healthcheck.sh
```

## 7. 複数バックエンドの切り替え (プロファイル)

`scripts/ask.sh` / `scripts/healthcheck.sh` は、`profiles/` ディレクトリの
設定ファイル (プロファイル) を使うことで、このリポジトリ本来のColab T4サーバー
だけでなく、OpenAI・Groq・OpenRouter・Ollama・LM Studio・vLLM など任意の
OpenAI互換バックエンドに簡単に切り替えられます。プロファイルを何も指定しなければ、
これまで通り環境変数 (`LLM_BASE_URL` 等) だけで動作します (後方互換)。

### 同梱プロファイルテンプレート

| プロファイル名   | ベースURL                              | APIキーの環境変数    |
|------------------|------------------------------------------|-----------------------|
| `colab-local`    | `http://localhost:8000/v1`               | (不要、`dummy`固定)   |
| `openai`         | `https://api.openai.com/v1`              | `OPENAI_API_KEY`      |
| `groq`           | `https://api.groq.com/openai/v1`         | `GROQ_API_KEY`        |
| `openrouter`     | `https://openrouter.ai/api/v1`           | `OPENROUTER_API_KEY`  |
| `ollama`         | `http://localhost:11434/v1`              | (不要、`dummy`固定)   |
| `lmstudio`       | `http://localhost:1234/v1`               | (不要、`dummy`固定)   |

vLLM等その他のOpenAI互換サーバーを使う場合も、上記テンプレートのいずれかを
コピーして `LLM_BASE_URL`/`LLM_MODEL` を書き換えるだけで対応できます。

### セットアップ例 (OpenAI)

```bash
cp profiles/openai.env.example profiles/openai.env
export OPENAI_API_KEY="sk-..."   # キー本体はシェル環境にのみ置く
./scripts/ask.sh -p openai "こんにちは"
```

`profiles/*.env` は `.gitignore` で除外されているため、実体ファイルが
誤ってコミットされることはありません。詳細は [`profiles/README.md`](profiles/README.md)
を参照してください。

`LLM_PROFILE` 環境変数でも同様に切り替えられます (`-p`/`--profile` フラグの方が優先されます):

```bash
LLM_PROFILE=groq ./scripts/ask.sh "量子化LLMとは？"
```

`scripts/healthcheck.sh` も同じ `-p`/`--profile`・`LLM_PROFILE` に対応しています:

```bash
./scripts/healthcheck.sh -p ollama
```

### モデル・systemプロンプト・生成パラメータの指定

```bash
# モデル・systemプロンプトを上書き
./scripts/ask.sh -m gpt-4o-mini -s "あなたは簡潔に回答するアシスタントです。" "1+1は？"

# temperature / max_tokens は環境変数で指定 (未設定なら送信しない)
LLM_TEMPERATURE=0.2 LLM_MAX_TOKENS=100 ./scripts/ask.sh "量子化LLMとは？"
```

| オプション/変数     | 説明                                                     |
|---------------------|------------------------------------------------------------|
| `-p`, `--profile`   | `profiles/NAME.env` を読み込んでバックエンドを切り替える  |
| `-m`, `--model`     | `model` フィールドを上書き (常に最優先)                    |
| `-s`, `--system`    | systemプロンプトを指定 (常に最優先、`LLM_SYSTEM_PROMPT`を上書き) |
| `LLM_PROFILE`       | `--profile`未指定時に使うプロファイル名                    |
| `LLM_SYSTEM_PROMPT` | systemメッセージの内容                                     |
| `LLM_TEMPERATURE`   | `temperature`フィールド (未設定なら送信しない)             |
| `LLM_MAX_TOKENS`    | `max_tokens`フィールド (未設定なら送信しない)               |

**優先順位に関する注意:**

- プロファイル解決: `-p`/`--profile` フラグ > `LLM_PROFILE` 環境変数 > 指定なし。
- プロファイルを読み込んだ場合、プロファイルファイル内の値
  (`LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY`等) が、実行前にexportしていた
  環境変数より優先されます (sourceして上書きするため)。
- ただし `-m`/`-s` フラグは、プロファイルの値よりも常に優先されます。

## 8. モデルの変更方法

`HF_REPO_ID` / `HF_FILENAME` (必要なら `MODEL_PATH` も) を変更して
`scripts/download_model.py` を再実行するだけで、別のGGUFモデルに切り替えられます。

```bash
export HF_REPO_ID="bartowski/Llama-3.2-1B-Instruct-GGUF"
export HF_FILENAME="Llama-3.2-1B-Instruct-Q4_K_M.gguf"
python3 scripts/download_model.py

export MODEL_PATH="models/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
python3 colab/start_llm_server.py
```

Qwen2.5-3B系などより大きいモデルに変更する場合も同様に、`HF_REPO_ID`/`HF_FILENAME`
を切り替えるだけで対応できます (VRAM容量には注意してください)。

## 9. トラブルシューティング

### CUDA / GPUが見えない

- Colabの「ランタイムのタイプを変更」からGPU (T4) が選択されているか確認してください。
- `nvidia-smi` がエラーになる場合は、ランタイムがGPUに接続されていません。
- `llama-cpp-python` がCPUのみでビルドされている場合、`INSTALL_CUDA_LLAMA=1` を
  指定して `scripts/setup_colab.sh` を実行し、CUDA対応版を再インストールしてください。

```bash
INSTALL_CUDA_LLAMA=1 bash scripts/setup_colab.sh
```

### モデルが大きすぎる / OOM (メモリ不足)

- より小さい量子化 (例: Q4_K_M → Q3_K_M など) やパラメータ数の少ないモデルを使用してください。
- `N_CTX` (コンテキスト長) を下げてメモリ使用量を減らしてください。
- `N_GPU_LAYERS` を減らし、一部のレイヤーをCPUにオフロードしてVRAM使用量を抑えてください。

### ポートに接続できない

- `scripts/healthcheck.sh` でサーバーが起動しているか確認してください。
- サーバー自体がColabランタイム上で起動しているか確認してください
  (`scripts/start_server.sh` の実行ログを確認)。
- トンネル利用時はトンネルのURLが変わっていないか確認してください。
- `LLM_BASE_URL` の末尾に `/v1` を付け忘れていないか確認してください。

### Colabセッションが切れた

- ランタイムを再接続し、`scripts/start_server.sh` を再実行してください。
- ランタイムがリセットされた場合、ダウンロード済みモデルも消えていることがあるため、
  `scripts/download_model.py` によるモデルの再ダウンロードが必要になる場合があります。

## 10. セキュリティ注意事項

- トンネル (`cloudflared`/`ngrok` 等) で発行される公開URLは、知っている人なら誰でも
  アクセスできる可能性があります。認証の仕組みや一時的なURLの利用を検討し、
  使い終わったら速やかにトンネルを停止してください。
- APIキーやHugging Faceトークンを `.env` に記載する場合も、絶対にコミットしないで
  ください (`.gitignore` で `.env` は既に除外されています)。
- `LLM_API_KEY` の既定値である `dummy` は、あくまでOpenAI互換クライアント向けの
  形式的な値であり、実際の認証機能ではありません。公開環境で使う場合は
  別途アクセス制御を用意してください。
- プロファイル実体 (`profiles/*.env`) も `.gitignore` で除外済みですが、
  OpenAI/Groq/OpenRouter等のクラウドAPIキーについては、そもそもファイルに
  書かずに済む `LLM_API_KEY_ENV` 方式 (環境変数名だけをプロファイルに書き、
  キー本体はシェル環境にのみ置く) の利用を推奨します。詳細は
  [`profiles/README.md`](profiles/README.md) を参照してください。

## 11. リポジトリ構成

```
.
├── README.md                     # このファイル
├── requirements.txt              # Python依存パッケージ
├── .gitignore                    # Git管理から除外するファイル/ディレクトリ
├── scripts/
│   ├── lib/
│   │   └── common.sh             # プロファイル読み込み等の共通ライブラリ (source専用)
│   ├── setup_colab.sh            # Colabランタイムでの依存パッケージセットアップ
│   ├── download_model.py         # Hugging Face HubからGGUFモデルをダウンロード
│   ├── start_server.sh           # セットアップ→モデル取得→サーバー起動を一括実行
│   ├── healthcheck.sh            # サーバーの疎通確認 (-p/--profile 対応)
│   └── ask.sh                    # ローカルCLIから質問を送るスクリプト (-p/-m/-s 対応)
├── colab/
│   └── start_llm_server.py       # llama-cpp-pythonサーバーの起動ラッパー
├── profiles/
│   ├── README.md                 # プロファイル機能の説明
│   ├── colab-local.env.example    # Colabローカルサーバー向けテンプレート
│   ├── openai.env.example        # OpenAI向けテンプレート
│   ├── groq.env.example          # Groq向けテンプレート
│   ├── openrouter.env.example    # OpenRouter向けテンプレート
│   ├── ollama.env.example        # Ollama向けテンプレート
│   └── lmstudio.env.example      # LM Studio向けテンプレート
└── examples/
    ├── ask_example.sh            # ask.sh の基本的な実行例
    └── ask_multi_backend.sh      # ask.sh のプロファイル切り替え実行例
```
