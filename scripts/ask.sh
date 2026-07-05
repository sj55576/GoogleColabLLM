#!/usr/bin/env bash
# ローカル端末からOpenAI互換のchat/completions APIに質問を送るCLI。
#
# 使い方:
#   ./scripts/ask.sh [オプション] "質問文"
#
# オプション:
#   -p, --profile NAME   profiles/NAME.env を読み込んでバックエンドを切り替える
#   -m, --model MODEL    modelフィールドを上書き
#   -s, --system TEXT    systemプロンプトを指定
#   -h, --help           ヘルプ表示
#
# 環境変数:
#   LLM_PROFILE       : --profile を指定しなかった場合に使うプロファイル名
#   LLM_BASE_URL      : APIのベースURL (既定: http://localhost:8000/v1)
#   LLM_API_KEY       : Authorizationヘッダーに使うAPIキー (既定: dummy)
#   LLM_MODEL         : modelフィールドに指定する値 (既定: local)
#   LLM_SYSTEM_PROMPT : systemメッセージの内容 (-s で上書き可能)
#   LLM_TEMPERATURE   : temperatureフィールド (未設定なら送信しない)
#   LLM_MAX_TOKENS    : max_tokensフィールド (未設定なら送信しない)
#
# プロファイル (profiles/*.env) を使う場合の優先順位:
#   1. --profile / -p フラグ
#   2. LLM_PROFILE 環境変数
#   3. どちらも無ければ従来通り環境変数 (LLM_BASE_URL 等) のみで動作
#
# 注意: プロファイルを読み込んだ場合、プロファイルファイル内の値が
#       実行前にexportしていた環境変数より優先されます
#       (source時に上書きされるため)。
#       ただし -m / -s フラグは常に最優先です。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/common.sh
source "$SCRIPT_DIR/lib/common.sh"

usage() {
    cat <<EOF
使い方: $0 [オプション] "質問文"

オプション:
  -p, --profile NAME   profiles/NAME.env を読み込んでバックエンドを切り替える
  -m, --model MODEL    modelフィールドを上書き
  -s, --system TEXT    systemプロンプトを指定
  -h, --help           ヘルプ表示

環境変数:
  LLM_PROFILE       : --profile を指定しなかった場合に使うプロファイル名
  LLM_BASE_URL      : APIのベースURL (既定: http://localhost:8000/v1)
  LLM_API_KEY       : Authorizationヘッダーに使うAPIキー (既定: dummy)
  LLM_MODEL         : modelフィールドに指定する値 (既定: local)
  LLM_SYSTEM_PROMPT : systemメッセージの内容 (-s で上書き可能)
  LLM_TEMPERATURE   : temperatureフィールド (未設定なら送信しない)
  LLM_MAX_TOKENS    : max_tokensフィールド (未設定なら送信しない)

利用可能なプロファイル (profiles/*.env):
EOF
    local found=0
    local f
    if [[ -d "$COMMON_SH_REPO_ROOT/profiles" ]]; then
        for f in "$COMMON_SH_REPO_ROOT"/profiles/*.env; do
            if [[ -f "$f" ]]; then
                echo "  - $(basename "$f" .env)"
                found=1
            fi
        done
    fi
    if [[ "$found" -eq 0 ]]; then
        echo "  (なし。profiles/*.env.example を profiles/<名前>.env にコピーして作成してください)"
    fi
}

PROFILE_NAME=""
MODEL_FLAG=""
SYSTEM_FLAG=""
QUESTION=""

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
        -m|--model)
            if [[ $# -lt 2 ]]; then
                echo "エラー: $1 には値の指定が必要です。" >&2
                exit 1
            fi
            MODEL_FLAG="$2"
            shift 2
            ;;
        --model=*)
            MODEL_FLAG="${1#--model=}"
            shift
            ;;
        -s|--system)
            if [[ $# -lt 2 ]]; then
                echo "エラー: $1 には値の指定が必要です。" >&2
                exit 1
            fi
            SYSTEM_FLAG="$2"
            shift 2
            ;;
        --system=*)
            SYSTEM_FLAG="${1#--system=}"
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            if [[ $# -gt 0 ]]; then
                QUESTION="$1"
                shift
            fi
            break
            ;;
        -*)
            echo "エラー: 不明なオプションです: $1" >&2
            usage >&2
            exit 1
            ;;
        *)
            QUESTION="$1"
            shift
            ;;
    esac
done

if [[ -z "$QUESTION" ]]; then
    usage >&2
    exit 1
fi

# --- プロファイルの決定 (優先順位: --profile > LLM_PROFILE > なし) ---
if [[ -z "$PROFILE_NAME" ]]; then
    PROFILE_NAME="${LLM_PROFILE:-}"
fi

if [[ -n "$PROFILE_NAME" ]]; then
    if ! load_profile "$PROFILE_NAME"; then
        exit 1
    fi
fi

# --- 既定値の適用 (プロファイル/事前exportされた環境変数が無ければこれを使う) ---
LLM_BASE_URL="${LLM_BASE_URL:-http://localhost:8000/v1}"
LLM_BASE_URL="${LLM_BASE_URL%/}"
LLM_API_KEY="${LLM_API_KEY:-dummy}"
LLM_MODEL="${LLM_MODEL:-local}"
LLM_SYSTEM_PROMPT="${LLM_SYSTEM_PROMPT:-}"
LLM_TEMPERATURE="${LLM_TEMPERATURE:-}"
LLM_MAX_TOKENS="${LLM_MAX_TOKENS:-}"

# --- -m / -s フラグは常に最優先 ---
if [[ -n "$MODEL_FLAG" ]]; then
    LLM_MODEL="$MODEL_FLAG"
fi
if [[ -n "$SYSTEM_FLAG" ]]; then
    LLM_SYSTEM_PROMPT="$SYSTEM_FLAG"
fi

# --- リクエストボディの組み立て ---
# 質問文にダブルクォートや改行が含まれていても壊れないよう、
# 可能であればpython3でJSONエスケープを行う。python3が無い環境向けに
# 簡易的なsedによるエスケープをフォールバックとして用意する。
# system/temperature/max_tokensはpythonコードへの直接埋め込み(文字列補間)を避け、
# 環境変数経由 (os.environ.get) で渡す。
build_request_body() {
    local question="$1"
    local model="$2"

    if command -v python3 >/dev/null 2>&1; then
        LLM_QUESTION="$question" \
        LLM_MODEL_FOR_BODY="$model" \
        LLM_SYSTEM_PROMPT="$LLM_SYSTEM_PROMPT" \
        LLM_TEMPERATURE="$LLM_TEMPERATURE" \
        LLM_MAX_TOKENS="$LLM_MAX_TOKENS" \
        python3 -c '
import json
import os
import sys

question = os.environ.get("LLM_QUESTION", "")
model = os.environ.get("LLM_MODEL_FOR_BODY", "")
system_prompt = os.environ.get("LLM_SYSTEM_PROMPT", "")
temperature_raw = os.environ.get("LLM_TEMPERATURE", "")
max_tokens_raw = os.environ.get("LLM_MAX_TOKENS", "")

messages = []
if system_prompt:
    messages.append({"role": "system", "content": system_prompt})
messages.append({"role": "user", "content": question})

body = {
    "model": model,
    "messages": messages,
}

if temperature_raw:
    try:
        body["temperature"] = float(temperature_raw)
    except ValueError:
        print(
            f"エラー: LLM_TEMPERATURE の値が数値として不正です: {temperature_raw!r}",
            file=sys.stderr,
        )
        sys.exit(1)

if max_tokens_raw:
    try:
        body["max_tokens"] = int(max_tokens_raw)
    except ValueError:
        print(
            f"エラー: LLM_MAX_TOKENS の値が整数として不正です: {max_tokens_raw!r}",
            file=sys.stderr,
        )
        sys.exit(1)

print(json.dumps(body))
'
    else
        # 簡易フォールバック: バックスラッシュとダブルクォートのみエスケープする。
        # (制御文字や改行までは完全にケアできないため、python3の使用を推奨)
        if [[ -n "$LLM_SYSTEM_PROMPT" || -n "$LLM_TEMPERATURE" || -n "$LLM_MAX_TOKENS" ]]; then
            echo "警告: system/temperature/max_tokens の指定にはpython3が必要です。python3が見つからないため、これらの指定は無視されます。" >&2
        fi
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
