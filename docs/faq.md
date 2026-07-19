# よくある質問 (FAQ)

### Q: Google Colab無料枠のT4には制限がありますか? セッションが切れたらどうすればいいですか?

A: 無料枠のColabはGPUの割り当て時間やセッションの継続時間に制限があり、
一定時間の無操作や利用状況によってランタイムが切断されることがあります。
切断された場合は、ランタイムを再接続してから
`colab --gpu T4 exec scripts/start_server.sh` (または `bash scripts/start_server.sh`)
を再実行してください。ランタイムがリセットされていると、ダウンロード済みの
モデルファイルも消えていることがあるため、`scripts/download_model.py` による
再ダウンロードが必要になる場合があります。詳細はREADMEの
[トラブルシューティング](../README.ja.md#11-トラブルシューティング)を参照してください。

### Q: どのGGUF量子化を選べばいいですか? なぜ既定はQ4_K_Mなのですか?

A: 既定モデル (`Qwen/Qwen2.5-1.5B-Instruct-GGUF` の
`qwen2.5-1.5b-instruct-q4_k_m.gguf`) はQ4_K_M量子化です。Q4_K_Mは、
モデルサイズ・VRAM使用量と生成品質のバランスが良く、T4 (16GB VRAM) のような
制約のあるGPUでも動かしやすいため、量子化の選択に迷ったときの一般的な
出発点としてよく使われます。VRAMが厳しい場合はより軽いQ3_K_M等へ、
品質を優先したい場合はQ5_K_M/Q6_K等へ切り替えてください
(README [トラブルシューティング](../README.ja.md#11-トラブルシューティング)の
「モデルが大きすぎる / OOM」も参照)。

### Q: 使用するモデルを変更するにはどうすればいいですか?

A: `HF_REPO_ID`/`HF_FILENAME` (必要なら `MODEL_PATH` も) を変更して
`scripts/download_model.py` を再実行してください。詳細な手順とコマンド例は
README [10. モデルの変更方法](../README.ja.md#10-モデルの変更方法)にあります。

### Q: `scripts/ask.sh` と `scripts/openai_proxy.py` はどう使い分ければいいですか?

A: `ask.sh` は「ローカル端末からシンプルに1回質問して回答を受け取る」ための
CLIです。一方 `scripts/openai_proxy.py` (`scripts/serve_proxy.sh`) は、
`ask.sh` 以外の任意のOpenAI SDK対応アプリ (チャットUI、エディタ拡張、
自作アプリ等) からこのリポジトリのバックエンドを使いたい場合に、
ローカルにOpenAI互換のHTTPエンドポイントを常駐させるためのものです。
CLIで手軽に質問したいだけなら `ask.sh`、他のアプリ/SDKから継続的に
接続したいなら `openai_proxy.py` を使ってください。

### Q: プロファイルとは何ですか? どうやって作りますか?

A: プロファイルは `profiles/` ディレクトリに置く、バックエンドごとの接続設定
ファイルです。`profiles/<名前>.env.example` をコピーして `profiles/<名前>.env`
を作り、中身の `LLM_BASE_URL`/`LLM_MODEL` 等を編集してから
`./scripts/ask.sh -p <名前> "質問"` のように `-p`/`--profile` (または
`LLM_PROFILE` 環境変数) で指定します。同梱テンプレートは
`colab-local`/`openai`/`groq`/`openrouter`/`ollama`/`lmstudio` の6種類で、
vLLM等その他のOpenAI互換サーバーもテンプレートをコピーして
`LLM_BASE_URL`/`LLM_MODEL` を書き換えれば使えます。詳細は
[`profiles/README.md`](../profiles/README.md)を参照してください。

### Q: APIキーはどこに置けばいいですか?

A: クラウド系バックエンド (OpenAI/Groq/OpenRouter) 向けのプロファイルは、
`LLM_API_KEY=...` のようにキー本体を直接書く代わりに、
`LLM_API_KEY_ENV=OPENAI_API_KEY` のように「キー本体を保持する別の環境変数名」
を指定する方式を使っています。キー本体は `export OPENAI_API_KEY="sk-..."` の
ようにシェル環境にのみ置き、`profiles/*.env` ファイル自体には書きません。
`scripts/lib/common.sh` の `load_profile` (`ask.sh`/`healthcheck.sh` 用) や
`openai_proxy.py` の `build_config` (プロキシ用) が、この環境変数名から
実際のキーを自動解決します。未設定の場合は分かりやすい日本語エラーで
終了します。ローカルで完結するバックエンド (Colab, Ollama, LM Studio) は
認証が実質不要なため、テンプレートに直接 `LLM_API_KEY=dummy` と書かれています。

### Q: OpenAI公式SDK以外でも使えますか?

A: はい。`scripts/ask.sh` も `scripts/openai_proxy.py` も
「OpenAI互換の `/v1/chat/completions` エンドポイント」であることだけを
前提にしているため、OpenAI公式SDKに限らず、OpenAI互換のAPI形式に
対応した任意のクライアント/SDK/アプリから利用できます。

### Q: ストリーミング応答は使えますか?

A: 使えます。CLIでは `scripts/ask.sh --stream "質問"` を指定すると、
リクエストに `"stream": true` を付け、SSE (Server-Sent Events) の
`delta.content` を受信順に表示します。SSE解析には `python3` が必要です。

`scripts/openai_proxy.py` 経由でも使えます。プロキシはアップストリームからの応答を
`read1()` で読める分だけ即座に転送するため、リクエストで `"stream": true` を
指定したSSE応答もリアルタイムで中継されます。詳細はREADME
[9. 他のアプリ向けOpenAI互換プロキシ (ゲートウェイ) > ストリーミング (SSE)](../README.ja.md#9-他のアプリ向けopenai互換プロキシ-ゲートウェイ)
を参照してください。

### Q: ポートが衝突してしまいます。どうすればいいですか?

A: Colabサーバー側は `LLM_PORT` 環境変数でポートを変更できます
(既定: `8000`)。ローカルのプロキシ側は `PROXY_PORT` 環境変数、または
`serve_proxy.sh`/`openai_proxy.py` の `--port` 引数でポートを変更できます
(既定: `8765`)。例: `PROXY_PORT=9000 ./scripts/serve_proxy.sh -p colab-local`。

### Q: `jq` がインストールされていない環境ではどうなりますか?

A: `scripts/ask.sh` はレスポンスから回答テキストを抽出する際、
`jq` が使えればそれを優先して使い、無ければ `python3` (`json.loads` で
`choices[0].message.content` を取り出す処理) にフォールバックします。
`jq` も `python3` も無い場合は、レスポンスのJSON全体をそのまま
標準出力に表示します。

### Q: `python3` が無い環境ではどうなりますか? sedフォールバックにはどんな制約がありますか?

A: `scripts/ask.sh` はリクエストボディの組み立てに `python3` を優先して使い
(JSONとして安全にエスケープし、`system`/`temperature`/`max_tokens` も反映)、
`python3` が無い場合は `sed` によるフォールバック
(`printf ... | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'`) を使います。この
フォールバックはバックスラッシュとダブルクォートのみをエスケープするため、
制御文字や改行までは完全にケアできません。また `python3` が無いと
`LLM_SYSTEM_PROMPT`/`LLM_TEMPERATURE`/`LLM_MAX_TOKENS` の指定は無視され、
警告メッセージが表示されます。可能な限り `python3` がある環境での実行を
推奨します。

### Q: CORSはいつ有効にすればいいですか?

A: ブラウザ上で動くアプリ (Webフロントエンド等) から直接
`scripts/openai_proxy.py` にアクセスしたい場合に、`PROXY_ALLOW_CORS=1` を
指定してください。CORSヘッダーが付与され、`OPTIONS` プリフライトリクエストにも
`204` で応答するようになります。CLIやサーバーサイドのアプリからしか
使わない場合は既定 (`0`、無効) のままで問題ありません。

### Q: `PROXY_FORCE_MODEL` は何のためにありますか?

A: クライアントアプリが送ってくるリクエストの `model` フィールドを、
常にプロファイル (または `LLM_MODEL` 環境変数) で指定したモデル名に
強制的に上書きしたい場合に `PROXY_FORCE_MODEL=1` を指定します。
アプリ側が固定のモデル名 (例: `gpt-4o`) しか指定できない、あるいは
アプリ側の指定を無視してバックエンドが実際に提供しているモデル名
(例: `local`) に必ず合わせたい、といった場合に有効です。既定 (`0`) では
クライアントが指定した `model` がそのままバックエンドへ転送されます。

### Q: トンネルのURLが変わってしまいました。どうすればいいですか?

A: `cloudflared`/`ngrok` 等のトンネルは再起動すると発行されるURLが
変わることがあります。新しいURLを確認し、`LLM_BASE_URL` を新しいURL
(末尾 `/v1` を忘れずに) に更新してから `scripts/ask.sh`/`scripts/healthcheck.sh`
を実行してください。プロファイルを使っている場合は、プロファイルファイル内の
`LLM_BASE_URL` も更新が必要です。

### Q: `requirements.txt` はローカル端末側にも必要ですか?

A: 不要です。`requirements.txt` (`llama-cpp-python[server]`,
`huggingface_hub`, `requests`, `python-dotenv`) はColabランタイム側
(`scripts/setup_colab.sh` が `pip install` する) でのみ必要です。
ローカル端末側で使う `scripts/ask.sh`/`scripts/healthcheck.sh` は
`bash`+`curl` (+あれば`jq`/`python3`) のみで動作し、`scripts/openai_proxy.py`
も標準ライブラリのみで実装されているため、ローカル側に追加のpipインストールは
必要ありません。

---

より詳しいアーキテクチャは [`docs/architecture.md`](architecture.md)、
全体の使い方は [README.ja.md](../README.ja.md) を参照してください。
