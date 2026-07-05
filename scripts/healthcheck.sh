#!/usr/bin/env bash
# LLMサーバーが正常に応答するかを確認するヘルスチェックスクリプト。
#
# 使い方:
#   ./scripts/healthcheck.sh
#   LLM_BASE_URL="https://xxxx.trycloudflare.com/v1" ./scripts/healthcheck.sh
set -euo pipefail

LLM_BASE_URL="${LLM_BASE_URL:-http://localhost:8000/v1}"
# 末尾のスラッシュを念のため取り除く
LLM_BASE_URL="${LLM_BASE_URL%/}"

echo "=== ヘルスチェック対象: $LLM_BASE_URL/models ==="

if response="$(curl -fsS --max-time 10 "$LLM_BASE_URL/models")"; then
    echo "OK: サーバーは正常に応答しています。"
    echo "--- レスポンス ---"
    echo "$response"
    exit 0
else
    echo "NG: サーバーへの接続に失敗しました。"
    echo "以下を確認してください:"
    echo "  - Colabランタイム側でサーバーが起動しているか (scripts/start_server.sh)"
    echo "  - ポート番号が正しいか (既定: 8000)"
    echo "  - ポートフォワードやトンネル(cloudflared/ngrok)が有効になっているか"
    echo "  - LLM_BASE_URL に /v1 が付いているか (現在値: $LLM_BASE_URL)"
    exit 1
fi
