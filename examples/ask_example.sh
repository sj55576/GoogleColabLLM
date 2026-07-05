#!/usr/bin/env bash
# scripts/ask.sh の実行例。
# 環境変数を上書きしたい場合は、実行前に export しておくか、
# このスクリプトを直接編集して使用してください。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export LLM_BASE_URL="${LLM_BASE_URL:-http://localhost:8000/v1}"
export LLM_API_KEY="${LLM_API_KEY:-dummy}"
export LLM_MODEL="${LLM_MODEL:-local}"

echo "=== 例1: 自己紹介を依頼する ==="
"$SCRIPT_DIR/../scripts/ask.sh" "日本語で自己紹介してください。"

echo
echo "=== 例2: 量子化LLMについて質問する ==="
"$SCRIPT_DIR/../scripts/ask.sh" "量子化LLMとは何か、初心者にもわかるように説明してください。"
