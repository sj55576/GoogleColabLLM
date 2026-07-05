#!/usr/bin/env bash
# LLMサーバーが正常に応答するかを確認するヘルスチェックスクリプト。
#
# 使い方:
#   ./scripts/healthcheck.sh
#   LLM_BASE_URL="https://xxxx.trycloudflare.com/v1" ./scripts/healthcheck.sh
#   ./scripts/healthcheck.sh -p ollama
#   LLM_PROFILE=ollama ./scripts/healthcheck.sh
#
# オプション:
#   -p, --profile NAME   profiles/NAME.env を読み込んでLLM_BASE_URLを切り替える
#   -h, --help           ヘルプ表示
#
# プロファイルの優先順位: --profile > LLM_PROFILE > 指定なし(従来通り)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

usage() {
    cat <<EOF
使い方: $0 [オプション]

オプション:
  -p, --profile NAME   profiles/NAME.env を読み込んでLLM_BASE_URLを切り替える
  -h, --help           ヘルプ表示
EOF
}

PROFILE_NAME=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -p|--profile)
            if [[ $# -lt 2 ]]; then
                echo "エラー: $1 には値の指定が必要です。" >&2
                exit 1
            fi
            PROFILE_NAME="$2"
            shift 2
            ;;
        --profile=*)
            PROFILE_NAME="${1#--profile=}"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "エラー: 不明な引数です: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if [[ -z "$PROFILE_NAME" ]]; then
    PROFILE_NAME="${LLM_PROFILE:-}"
fi

if [[ -n "$PROFILE_NAME" ]]; then
    if ! load_profile "$PROFILE_NAME"; then
        exit 1
    fi
fi

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
