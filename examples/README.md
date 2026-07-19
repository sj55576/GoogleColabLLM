# examples/ について

`scripts/ask.sh`・`scripts/openai_proxy.py` の使い方を示す実行例スクリプト集です。
いずれも設定なし (プロファイル未作成・バックエンド未起動) でも安全に実行できるよう、
未設定の場合はエラーで止まらずスキップ/表示のみを行うようになっています。

## 一覧

| スクリプト | 目的 | 前提条件 | 実行方法 |
|---|---|---|---|
| [`ask_example.sh`](ask_example.sh) | `scripts/ask.sh` の基本的な使い方 (自己紹介・簡単な質問) を示す | `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL` を事前にexportしていなければ既定値 (`http://localhost:8000/v1`/`dummy`/`local`) を使用。実際に回答を得るにはバックエンド (Colabサーバー等) が起動している必要がある | `./examples/ask_example.sh` |
| [`ask_multi_backend.sh`](ask_multi_backend.sh) | `-p`/`--profile` や `LLM_PROFILE` によるバックエンド切り替え、`-m`/`-s`/`LLM_TEMPERATURE` の指定例を示す | プロファイル (`profiles/ollama.env`, `profiles/openai.env` 等) が無い場合は該当例をスキップして続行する | `./examples/ask_multi_backend.sh` |
| [`proxy_example.sh`](proxy_example.sh) | `scripts/openai_proxy.py` (プロキシ) の起動方法・Python (OpenAI SDK) /curlからの利用例・ヘルスチェックを示す | 既定では実際に起動せず使い方の表示のみ。実際にプロキシを起動して動作確認するには `RUN_LIVE=1` を指定し、バックエンド (例: `profiles/colab-local.env`) が起動している必要がある | `./examples/proxy_example.sh` (表示のみ) / `RUN_LIVE=1 ./examples/proxy_example.sh -p colab-local` (実際に起動して確認) |

## 補足

- `RUN_LIVE=1` は `proxy_example.sh` にのみ意味を持つ環境変数です。
  指定するとプロキシをバックグラウンドで起動し、`/healthz` へのヘルスチェックと
  `scripts/ask.sh` からの簡単な質問リクエストまで動作確認したのち、
  プロキシを自動的に停止します。
- どのスクリプトも `set -euo pipefail` で書かれていますが、プロファイル未設定など
  想定内の未設定状態は「スキップ」として扱われ、スクリプト全体の異常終了には
  つながりません。

詳しくはREADMEの[8. 複数バックエンドの切り替え (プロファイル)](../README.ja.md#8-複数バックエンドの切り替え-プロファイル)・
[9. 他のアプリ向けOpenAI互換プロキシ (ゲートウェイ)](../README.ja.md#9-他のアプリ向けopenai互換プロキシ-ゲートウェイ)も参照してください。
