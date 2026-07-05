#!/usr/bin/env bash
# scripts/openai_proxy.py (他のアプリ向けOpenAI互換プロキシ) の使い方を示す例。
#
# 既定 (RUN_LIVE未設定) では、実際にプロキシを起動せず、実行例のみを表示します
# (CI/ネットワーク不要な環境でも安全に実行できます)。
#
# RUN_LIVE=1 を指定すると、実際にプロキシをバックグラウンドで起動し、
# ヘルスチェックと簡単な質問リクエストまで動作確認してから停止します
# (この場合、profiles/colab-local.env 等でバックエンドが起動している必要があります)。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

show_usage_examples() {
    cat <<'EOF'
=== scripts/openai_proxy.py の使い方例 ===

1. プロキシの起動 (プロファイルでバックエンドを選択):

   ./scripts/serve_proxy.sh -p groq
   PROXY_PORT=9000 ./scripts/serve_proxy.sh -p colab-local

2. Python (OpenAI SDK) からの利用例:

   from openai import OpenAI

   client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="dummy")
   resp = client.chat.completions.create(
       model="local",
       messages=[{"role": "user", "content": "こんにちは"}],
   )
   print(resp.choices[0].message.content)

3. curlでの利用例:

   curl http://127.0.0.1:8765/v1/chat/completions \
     -H "Content-Type: application/json" \
     -d '{"model": "local", "messages": [{"role": "user", "content": "こんにちは"}]}'

4. ヘルスチェック:

   curl http://127.0.0.1:8765/healthz

RUN_LIVE=1 を指定してこのスクリプトを実行すると、実際にプロキシを起動して
動作確認まで行います (要: 起動済みバックエンド、例えば profiles/colab-local.env)。

   RUN_LIVE=1 ./examples/proxy_example.sh
EOF
}

run_live_demo() {
    local proxy_pid=""

    cleanup() {
        if [[ -n "$proxy_pid" ]] && kill -0 "$proxy_pid" 2>/dev/null; then
            kill "$proxy_pid" 2>/dev/null || true
            wait "$proxy_pid" 2>/dev/null || true
        fi
    }
    trap cleanup EXIT

    local proxy_port="${PROXY_PORT:-8765}"
    local proxy_host="${PROXY_HOST:-127.0.0.1}"

    echo "=== プロキシをバックグラウンドで起動します (http://$proxy_host:$proxy_port) ==="
    "$SCRIPT_DIR/../scripts/serve_proxy.sh" "$@" &
    proxy_pid=$!

    echo "起動待機中..."
    local attempts=0
    while [[ "$attempts" -lt 30 ]]; do
        if curl -fsS "http://$proxy_host:$proxy_port/healthz" >/dev/null 2>&1; then
            break
        fi
        attempts=$((attempts + 1))
        sleep 0.5
    done

    echo "=== ヘルスチェック ==="
    curl -fsS "http://$proxy_host:$proxy_port/healthz"
    echo

    echo "=== ask.sh からプロキシ経由で質問を送信 ==="
    LLM_BASE_URL="http://$proxy_host:$proxy_port/v1" \
        LLM_API_KEY="dummy" \
        "$SCRIPT_DIR/../scripts/ask.sh" "日本語で自己紹介してください。"
}

if [[ "${RUN_LIVE:-0}" == "1" ]]; then
    run_live_demo "$@"
else
    show_usage_examples
fi
