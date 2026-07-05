#!/usr/bin/env bash
# ローカル端末からOpenAI互換のchat/completions APIに質問を送るCLI。
#
# 使い方:
#   ./scripts/ask.sh "質問文"
#
# 環境変数:
#   LLM_BASE_URL : APIのベースURL (既定: http://localhost:8000/v1)
#   LLM_API_KEY  : Authorizationヘッダーに使うAPIキー (既定: dummy)
#   LLM_MODEL    : modelフィールドに指定する値 (既定: local)
set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "使い方: $0 \"質問文\"" >&2
    exit 1
fi

QUESTION="$1"

LLM_BASE_URL="${LLM_BASE_URL:-http://localhost:8000/v1}"
LLM_BASE_URL="${LLM_BASE_URL%/}"
LLM_API_KEY="${LLM_API_KEY:-dummy}"
LLM_MODEL="${LLM_MODEL:-local}"

# --- リクエストボディの組み立て ---
# 質問文にダブルクォートや改行が含まれていても壊れないよう、
# 可能であればpython3でJSONエスケープを行う。python3が無い環境向けに
# 簡易的なsedによるエスケープをフォールバックとして用意する。
build_request_body() {
    local question="$1"
    local model="$2"

    if command -v python3 >/dev/null 2>&1; then
        python3 -c '
import json
import sys

question = sys.argv[1]
model = sys.argv[2]
body = {
    "model": model,
    "messages": [{"role": "user", "content": question}],
}
print(json.dumps(body))
' "$question" "$model"
    else
        # 簡易フォールバック: バックスラッシュとダブルクォートのみエスケープする。
        # (制御文字や改行までは完全にケアできないため、python3の使用を推奨)
        local escaped
        escaped="$(printf '%s' "$question" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')"
        printf '{"model": "%s", "messages": [{"role": "user", "content": "%s"}]}' "$model" "$escaped"
    fi
}

REQUEST_BODY="$(build_request_body "$QUESTION" "$LLM_MODEL")"

# --- APIへのリクエスト送信 ---
if ! RESPONSE="$(curl -fsS --max-time 300 \
    -X POST "$LLM_BASE_URL/chat/completions" \
    -H "Authorization: Bearer $LLM_API_KEY" \
    -H "Content-Type: application/json" \
    -d "$REQUEST_BODY")"; then
    echo "エラー: LLMサーバーへのリクエストに失敗しました。" >&2
    echo "以下を確認してください:" >&2
    echo "  - サーバーが起動しているか (scripts/healthcheck.sh で確認可能)" >&2
    echo "  - LLM_BASE_URL が正しいか (現在値: $LLM_BASE_URL)" >&2
    echo "  - トンネル/ポートフォワードが有効か" >&2
    exit 1
fi

# --- レスポンスから回答テキストを抽出 ---
if command -v jq >/dev/null 2>&1; then
    # -e により content が null (エラーレスポンス等) の場合は失敗として扱う
    if CONTENT="$(echo "$RESPONSE" | jq -e -r '.choices[0].message.content')"; then
        echo "$CONTENT"
    else
        echo "エラー: レスポンスから回答を取得できませんでした。" >&2
        echo "--- 生レスポンス ---" >&2
        echo "$RESPONSE" >&2
        exit 1
    fi
elif command -v python3 >/dev/null 2>&1; then
    printf '%s' "$RESPONSE" | python3 -c '
import json
import sys

raw = sys.stdin.read()
try:
    data = json.loads(raw)
    content = data["choices"][0]["message"]["content"]
    print(content)
except (KeyError, IndexError, json.JSONDecodeError) as exc:
    print(f"エラー: レスポンスの解析に失敗しました ({exc})", file=sys.stderr)
    error_info = locals().get("data")
    if isinstance(error_info, dict) and "error" in error_info:
        error_detail = error_info["error"]
        print(f"サーバーからのエラー内容: {error_detail}", file=sys.stderr)
    print("--- 生レスポンス ---", file=sys.stderr)
    print(raw, file=sys.stderr)
    sys.exit(1)
'
else
    echo "$RESPONSE"
fi
