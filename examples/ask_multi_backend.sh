#!/usr/bin/env bash
# scripts/ask.sh の複数バックエンド切り替え (プロファイル機能) の実行例。
#
# プロファイルを何も設定していなくても最後まで実行できるよう、
# 未設定のプロファイルはスキップするようにしています。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ASK="$SCRIPT_DIR/../scripts/ask.sh"

echo "=== 例1: プロファイルを指定しない (従来通り、Colabローカルサーバー) ==="
export LLM_BASE_URL="${LLM_BASE_URL:-http://localhost:8000/v1}"
export LLM_API_KEY="${LLM_API_KEY:-dummy}"
export LLM_MODEL="${LLM_MODEL:-local}"
"$ASK" "日本語で自己紹介してください。"

echo
echo "=== 例2: -p でプロファイルを切り替える (Ollama) ==="
if [[ -f "$REPO_ROOT/profiles/ollama.env" ]]; then
    "$ASK" -p ollama "量子化LLMとは何か、初心者にもわかるように説明してください。"
else
    echo "スキップ: profiles/ollama.env が未設定です。" >&2
    echo "  cp profiles/ollama.env.example profiles/ollama.env で作成できます。" >&2
fi

echo
echo "=== 例3: LLM_PROFILE 環境変数でプロファイルを切り替える (OpenAI) ==="
if [[ -f "$REPO_ROOT/profiles/openai.env" ]]; then
    LLM_PROFILE=openai "$ASK" "こんにちは"
else
    echo "スキップ: profiles/openai.env が未設定です。" >&2
    echo "  cp profiles/openai.env.example profiles/openai.env で作成し、" >&2
    echo "  export OPENAI_API_KEY=\"sk-...\" してから再実行してください。" >&2
fi

echo
echo "=== 例4: -m / -s フラグと LLM_TEMPERATURE でモデル・system・生成パラメータを指定 ==="
LLM_TEMPERATURE=0.2 "$ASK" -m local -s "あなたは簡潔に回答するアシスタントです。" "1+1は？"
