# アーキテクチャ

このドキュメントは、`colab-local-llm-cli` を構成する3つの「面」
(Colab T4ランタイム / ローカルCLI / プロキシ経由の他アプリ) が
どう繋がっているか、リクエストがどう流れるか、設定はどの順序で
解決されるかをまとめたものです。全体像は [README.md](../README.md) の
[3. アーキテクチャ図](../README.md#3-アーキテクチャ図)・
[9. 他のアプリ向けOpenAI互換プロキシ (ゲートウェイ)](../README.md#9-他のアプリ向けopenai互換プロキシ-ゲートウェイ)
も参照してください。

## 全体構成

### (a) Colab T4ランタイム: サーバーの起動

```
scripts/start_server.sh
  │
  ├─[1/3]─> bash scripts/setup_colab.sh
  │           - nvidia-smi でGPU可視性を確認
  │           - requirements.txt を pip install
  │           - INSTALL_CUDA_LLAMA=1 のときのみ CUDA版 llama-cpp-python を再インストール
  │           - models/ ディレクトリを作成
  │
  ├─[2/3]─> python3 scripts/download_model.py
  │           - huggingface_hub.hf_hub_download で GGUF モデルを取得
  │           - 既に存在すればスキップ
  │
  └─[3/3]─> exec python3 colab/start_llm_server.py
              - python3 -m llama_cpp.server を起動 (execなのでシグナルは直接サーバーへ)
              -> llama-cpp-python の OpenAI互換サーバー (既定 0.0.0.0:8000)
              -> GGUF量子化モデル (models/*.gguf) をロード
```

GUIから同じ流れを実行することもできます。`colab/dashboard.ipynb` を開いて
`dashboard_ui.show()` を実行すると、「実行」タブの起動ボタンが
`colab/dashboard.py` の `ServerManager.start()` を呼び出します。
`ServerManager` は `build_server_command()` で `start_llm_server.py` と
同一の引数列 (`python3 -m llama_cpp.server --model ... --host ... --port ...`) を
組み立て、`logs/llm_server.log` へ出力しつつサブプロセスとして起動するため、
CLI経由の起動と同じ挙動になります (「モデル」タブの取得も同様に
`download_model()` が `scripts/download_model.py` と同じ役割を担います)。

### (b) ローカルCLI: 質問を送る

```
ローカル端末
+---------------------------+
| scripts/ask.sh             |  --profile/-p でバックエンドを切り替え
| scripts/healthcheck.sh     |  --profile/-p で疎通確認先を切り替え
|   ↑ source                 |
| scripts/lib/common.sh      |  load_profile(): profiles/*.env を読み込み
+---------------------------+
             │ HTTP (ポートフォワード / トンネル)
             ▼
   Colab T4ランタイム (:8000) または任意のOpenAI互換バックエンド
```

### (c) プロキシ経由の他アプリ

```
他のアプリ (任意のOpenAI SDK)
             │ HTTP (base_url=http://127.0.0.1:8765/v1)
             ▼
scripts/openai_proxy.py (scripts/serve_proxy.sh はその薄いラッパー)
  - profiles/<name>.env または環境変数で中継先バックエンドを決定
  - 実際のAPIキー (LLM_API_KEY) を内部で注入
  - PROXY_FORCE_MODEL=1 なら model フィールドを LLM_MODEL に強制上書き
             │ HTTP
             ▼
   選択されたバックエンド (Colabローカル / OpenAI / Groq / Ollama 等)
```

## コンポーネント詳細

| コンポーネント | 何をするか | 主な環境変数 | いつ動くか |
|---|---|---|---|
| `scripts/setup_colab.sh` | GPU確認・pip install・(任意) CUDA版llama-cpp-python再インストール・`models/`作成 | `INSTALL_CUDA_LLAMA` | Colabランタイム上、`start_server.sh` の最初のステップとして |
| `scripts/download_model.py` | Hugging Face HubからGGUFモデルをダウンロード (既に存在すればスキップ) | `HF_REPO_ID`, `HF_FILENAME`, `MODEL_DIR`, `HF_TOKEN` | Colabランタイム上、モデルを取得/変更するとき |
| `colab/start_llm_server.py` | `llama_cpp.server` をサブプロセスとして起動するラッパー (モデルパス検証・引数組み立て・バナー表示) | `MODEL_PATH`, `LLM_HOST`, `LLM_PORT`, `N_GPU_LAYERS`, `N_CTX` | Colabランタイム上、サーバー起動時 |
| `colab/dashboard.py` | ダッシュボードのコアロジック層 (`ServerManager`によるサーバー起動/停止/監視、モデルダウンロード、ヘルスチェック、チャット送信、GPU情報取得) | (なし。`ServerConfig`/関数引数で設定し、環境変数は使わない) | `dashboard_ui.py` から呼ばれる、またはテストから直接import |
| `colab/dashboard_ui.py` | ipywidgetsによるGUI層 (モデル/サーバー設定/実行/モニタ/テストチャットの5タブ)。実処理は`dashboard.py`に委譲 | - | Colab/Jupyterのノートブックセルで `dashboard_ui.show()` を実行したとき |
| `colab/dashboard.ipynb` | clone→セットアップ→ダッシュボード表示までを行うColabノートブックのエントリポイント | - | Colab上で本ノートブックを開いて上から実行するとき |
| `scripts/start_server.sh` | 上記3つ (セットアップ→ダウンロード→起動) を一括実行するオーケストレーション | (上記すべてを継承) | `colab --gpu T4 exec scripts/start_server.sh` 実行時 |
| `scripts/lib/common.sh` | `load_profile()` を提供する共通ライブラリ (source専用、直接実行しない) | `LLM_API_KEY_ENV` | `ask.sh` / `healthcheck.sh` から source される |
| `scripts/ask.sh` | 質問文をOpenAI互換の `/chat/completions` に送信し、回答テキストを表示 | `LLM_PROFILE`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_SYSTEM_PROMPT`, `LLM_TEMPERATURE`, `LLM_MAX_TOKENS` | ローカル端末で質問するとき |
| `scripts/healthcheck.sh` | `/models` エンドポイントにアクセスして疎通確認 | `LLM_PROFILE`, `LLM_BASE_URL` | サーバー起動後の動作確認時 |
| `scripts/openai_proxy.py` | ローカルにOpenAI互換のHTTPエンドポイントを立て、プロファイルで選んだバックエンドへ中継 (SSEストリーミング対応、APIキー注入) | `LLM_PROFILE`, `PROXY_PORT`, `PROXY_HOST`, `PROXY_API_KEY`, `PROXY_FORCE_MODEL`, `PROXY_ALLOW_CORS`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_API_KEY_ENV` | 他のOpenAI SDK対応アプリから使いたいとき |
| `scripts/serve_proxy.sh` | `openai_proxy.py` を起動する薄いラッパー (引数をそのまま渡すだけ) | (`openai_proxy.py` と同じ) | プロキシを起動するとき |
| `profiles/*.env` (実体) / `*.env.example` (テンプレート) | バックエンドごとの接続設定 (`LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY`または`LLM_API_KEY_ENV`) | - | `-p`/`--profile` または `LLM_PROFILE` 指定時に読み込まれる |

## リクエストの流れ

### (a) `./scripts/ask.sh -p groq "質問文"`

1. `ask.sh` が `-p groq` を解釈し、`PROFILE_NAME=groq` を確定する
   (優先順位: `-p`/`--profile` フラグ > `LLM_PROFILE` 環境変数)。
2. `scripts/lib/common.sh` の `load_profile groq` が
   `profiles/groq.env` を `set -a` 付きで `source` し、
   `LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY_ENV` 等を環境変数としてexportする。
   このとき、事前にシェルでexportしていた同名の環境変数は上書きされる。
3. `profiles/groq.env` は `LLM_API_KEY_ENV=GROQ_API_KEY` の形でキー本体を持たない。
   `load_profile` はここで `GROQ_API_KEY` (ユーザーが事前にexportした環境変数) の値を読み、
   `LLM_API_KEY` に解決してexportする。未設定なら日本語エラーで終了する。
4. `ask.sh` が既定値を適用したのち (プロファイル/環境変数が優先)、
   `-m`/`-s` フラグがあればそれで最終上書きする。
5. `build_request_body()` が (python3があれば) JSONを安全に組み立て、
   `curl -X POST "$LLM_BASE_URL/chat/completions" -H "Authorization: Bearer $LLM_API_KEY" ...`
   でGroqのAPIへ直接リクエストを送信する (プロキシは経由しない)。
6. レスポンスは `jq` (優先) または `python3` で `.choices[0].message.content` を抽出して表示する。

### (b) 他アプリ → プロキシ → バックエンド

1. 事前に `./scripts/serve_proxy.sh -p openai` 等でプロキシを起動しておく。
   `openai_proxy.py` の `build_config()` が、
   `-p`/`--profile` (最優先) → `LLM_PROFILE` 環境変数 → プロファイルなし、の順で
   プロファイル名を決定し、`profiles/openai.env` を読み込んで環境変数を上書きする。
   `LLM_API_KEY_ENV` が指定されていれば、ここで実際のAPIキーを解決して
   `backend_api_key` (内部設定) に格納する。
2. 他のアプリ (例: `OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="dummy")`) が
   `/v1/chat/completions` にリクエストを送る。クライアントが渡す `api_key` は
   `PROXY_API_KEY` が設定されている場合のみ照合に使われ、バックエンドには渡らない。
3. `ProxyHandler._route()` がパスを見て `/v1/...` ならプロキシ処理、`/healthz` なら
   ヘルスチェック応答に振り分ける。`PROXY_API_KEY` が設定されていれば
   `Authorization: Bearer <PROXY_API_KEY>` を `hmac.compare_digest` で定数時間比較する。
4. `_handle_proxy()` が中継先URLを組み立てる (`LLM_BASE_URL` の末尾 `/v1` を取り除き、
   受信した `/v1/...` パスをそのまま連結)。`PROXY_FORCE_MODEL=1` の場合はここで
   リクエストボディをJSONとして読み、`model` フィールドを `LLM_MODEL` に強制上書きする。
5. `Authorization: Bearer <backend_api_key>` を付けてバックエンドへ
   `urllib.request.urlopen()` でリクエストを転送する (実キーはここで初めて外部に出る)。
6. `_relay_response()` がステータス・Content-Typeを転送し、`resp.read1(8192)` で
   「今読める分だけ」を都度 `self.wfile.write()` + `flush()` する。これにより
   バックエンドがSSEでストリーミング応答する場合も、チャンクをリアルタイムで
   クライアントへ中継できる (`stream: true` のリクエストもこの経路をそのまま通る)。

## 設定の優先順位

`ask.sh` と `openai_proxy.py` は同じ考え方で優先順位を解決します。

1. **コマンドライン引数が最優先**
   - `ask.sh`: `-m`/`--model`、`-s`/`--system` は常に最優先 (プロファイルや環境変数を上書き)。
   - `openai_proxy.py`: `--profile`/`--port`/`--host` は常に最優先。
2. **プロファイル選択そのものの優先順位**: `-p`/`--profile` フラグ >
   `LLM_PROFILE` 環境変数 > 指定なし (プロファイル未使用、従来通り環境変数のみ)。
3. **プロファイルの値は、実行前にexportしていた環境変数より優先される**
   (プロファイルファイルを `source`/読み込みして上書きするため)。
   例: `LLM_BASE_URL` を事前にexportしていても、`-p groq` を指定すれば
   `profiles/groq.env` の `LLM_BASE_URL` で上書きされる。
4. **プロファイルにも環境変数にも値が無ければ、スクリプト内の既定値が使われる**
   (`LLM_BASE_URL=http://localhost:8000/v1`、`LLM_API_KEY=dummy`、`LLM_MODEL=local` など)。
5. **`LLM_API_KEY_ENV` によるキー解決は、プロファイル適用の直後に行われる**
   (プロファイルに `LLM_API_KEY_ENV=OPENAI_API_KEY` のように書かれていれば、
   `OPENAI_API_KEY` の値を読んで `LLM_API_KEY` に反映する。これは
   上記3の「プロファイルが環境変数を上書きする」の一部として働く)。

まとめると: `flags > profile (via source/load) > pre-exported env > script defaults`
であり、`-m`/`-s` (ask.sh) や `--profile`/`--port`/`--host` (openai_proxy.py) は
この順序の外側にある「常に最優先」の例外です。

## セキュリティモデル

- **キー管理**
  - クラウドバックエンド (OpenAI/Groq/OpenRouter) 向けのプロファイルは、
    APIキーの実体をファイルに書かず `LLM_API_KEY_ENV=<環境変数名>` で
    間接参照する方式を採用しています。キー本体はシェル環境にのみ置きます。
  - `profiles/*.env` (プロファイルの実体ファイル) は `.gitignore` で除外されており、
    コミット対象になるのはテンプレートの `*.env.example` のみです。
  - `scripts/openai_proxy.py` はログ出力 (`log_message`) でHTTPヘッダーやボディを
    一切出力しません (`self.command self.path -> status` のみ記録)。これは
    Authorizationヘッダー (APIキー) がログに漏れるのを防ぐためです。
- **ネットワーク露出**
  - `scripts/openai_proxy.py` は既定で `127.0.0.1` のみでリッスンするため、
    同一端末上のアプリからしかアクセスできません。
  - `PROXY_HOST` を `0.0.0.0` 等に変更するとLANに公開されます。この場合、
    `PROXY_API_KEY` を設定しないと、同一ネットワーク上の誰でも
    バックエンドのAPIキーを使ってリクエストを送信できてしまいます。
  - Colab側のサーバー (`colab/start_llm_server.py`) は既定で `LLM_HOST=0.0.0.0` で
    リッスンしますが、これはColabランタイム内部のバインドであり、
    ローカル端末から見えるようにするには別途ポートフォワードやトンネル
    (`cloudflared`/`ngrok` 等) が必要です。トンネルで発行される公開URLは
    知っている人なら誰でもアクセスできる可能性があるため注意してください。
- **ダミーキーの位置づけ**
  - `LLM_API_KEY` / クライアントが指定する `api_key` の既定値 `dummy` は、
    OpenAI互換クライアントが「値が空でないこと」を要求するために存在する
    形式的な値であり、実際の認証機能ではありません。
  - プロキシ側の認証は `PROXY_API_KEY` (Authorizationヘッダーの定数時間比較) で
    制御されます。これが未設定の場合、`/v1/...` へのアクセスは誰でも可能です
    (=クライアント認証なし)。バックエンドの実APIキーはプロキシ内部でのみ使用され、
    クライアントアプリへ渡ることはありません。
