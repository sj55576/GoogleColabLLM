# profiles/ について

`scripts/ask.sh` / `scripts/healthcheck.sh` から `-p`/`--profile` (または
`LLM_PROFILE` 環境変数) で切り替えられる、バックエンドごとの接続設定です。

## 使い方

このディレクトリにある `*.env.example` を、拡張子 `.example` を外した
`*.env` としてコピーし、中身を編集してから使います。

```bash
cp profiles/openai.env.example profiles/openai.env
# 必要に応じて profiles/openai.env の LLM_MODEL などを編集
export OPENAI_API_KEY="sk-..."
./scripts/ask.sh -p openai "こんにちは"
```

実体である `*.env` ファイルは `.gitignore` で除外されており、
コミットされることはありません (`*.env.example` テンプレートのみコミット対象)。

## 同梱テンプレート

| ファイル                       | 対象バックエンド            |
|--------------------------------|-----------------------------|
| `colab-local.env.example`       | このリポジトリのColab T4サーバー (既定と同じ設定) |
| `openai.env.example`            | OpenAI公式API                |
| `groq.env.example`              | Groq                          |
| `openrouter.env.example`        | OpenRouter                    |
| `ollama.env.example`            | Ollama (ローカル)             |
| `lmstudio.env.example`          | LM Studio (ローカル)          |

## `LLM_API_KEY_ENV` によるキー保護

クラウド系のバックエンド (OpenAI/Groq/OpenRouter) のテンプレートでは、
APIキー本体を `LLM_API_KEY=...` として直接ファイルに書く代わりに、
`LLM_API_KEY_ENV=OPENAI_API_KEY` のように「キー本体を保持している
別の環境変数の名前」を指定する方式を使っています。

こうすることで、`profiles/*.env` ファイル自体にはキーの実体を
書かずに済みます。実行前にシェルで

```bash
export OPENAI_API_KEY="sk-..."
```

のようにexportしておけば、`scripts/lib/common.sh` の `load_profile` が
自動的に `LLM_API_KEY` へ解決します。`OPENAI_API_KEY` が未設定の場合は
分かりやすい日本語エラーで終了します。

ローカルで完結するバックエンド (Colab, Ollama, LM Studio) は認証が
実質不要なため、`LLM_API_KEY=dummy` を直接書いています。
