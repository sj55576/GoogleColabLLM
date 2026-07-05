#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TMP_DIR="$(mktemp -d)"
PROFILE_FILE="$REPO_ROOT/profiles/ci-test.env"
PIDS=()

cleanup() {
    local pid
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    done
    rm -f "$PROFILE_FILE"
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

log() {
    printf '\n==> %s\n' "$1"
}

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
    mkdir -p "$TMP_DIR/bin"
    cat > "$TMP_DIR/bin/python3" <<'EOF'
#!/usr/bin/env sh
exec python "$@"
EOF
    chmod +x "$TMP_DIR/bin/python3"
    export PATH="$TMP_DIR/bin:$PATH"
else
    echo "python3 or python is required" >&2
    exit 1
fi

free_port() {
    "$PYTHON_BIN" - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

wait_for_url() {
    local url="$1"
    local attempts=0
    while [[ "$attempts" -lt 50 ]]; do
        if curl -fsS "$url" >/dev/null 2>&1; then
            return 0
        fi
        attempts=$((attempts + 1))
        sleep 0.1
    done
    echo "Timed out waiting for $url" >&2
    return 1
}

assert_backend_request() {
    local log_file="$1"
    local expected_auth="$2"
    local expected_model="$3"
    local expected_user="$4"
    local expected_system="${5:-}"
    local expected_stream="${6:-}"

    BACKEND_LOG="$log_file" \
    EXPECTED_AUTH="$expected_auth" \
    EXPECTED_MODEL="$expected_model" \
    EXPECTED_USER="$expected_user" \
    EXPECTED_SYSTEM="$expected_system" \
    EXPECTED_STREAM="$expected_stream" \
    "$PYTHON_BIN" - <<'PY'
import json
import os
import sys

log_path = os.environ["BACKEND_LOG"]
requests = []
with open(log_path, encoding="utf-8") as handle:
    for line in handle:
        entry = json.loads(line)
        if entry["method"] == "POST" and entry["path"] == "/v1/chat/completions":
            requests.append(entry)

if not requests:
    print("no chat/completions request was recorded", file=sys.stderr)
    sys.exit(1)

entry = requests[-1]
body = entry["json"]
expected_auth = os.environ["EXPECTED_AUTH"]
expected_model = os.environ["EXPECTED_MODEL"]
expected_user = os.environ["EXPECTED_USER"]
expected_system = os.environ["EXPECTED_SYSTEM"]
expected_stream = os.environ["EXPECTED_STREAM"]

assert entry["authorization"] == f"Bearer {expected_auth}", entry
assert body["model"] == expected_model, body
assert body["messages"][-1] == {"role": "user", "content": expected_user}, body
if expected_system:
    assert body["messages"][0] == {"role": "system", "content": expected_system}, body
if expected_stream:
    assert body["stream"] is True, body
if "direct" in expected_model:
    assert body["temperature"] == 0.25, body
    assert body["max_tokens"] == 7, body
PY
}

cd "$REPO_ROOT"

BACKEND_PORT="$(free_port)"
BACKEND_LOG="$TMP_DIR/backend.jsonl"
log "Starting fake backend on $BACKEND_PORT"
"$PYTHON_BIN" "$REPO_ROOT/tests/fake_openai_backend.py" \
    --port "$BACKEND_PORT" \
    --log "$BACKEND_LOG" &
PIDS+=("$!")
wait_for_url "http://127.0.0.1:$BACKEND_PORT/v1/models"

log "Testing ask.sh request body construction"
QUESTION=$'Hello "there"\nSecond line'
DIRECT_OUTPUT="$(
    LLM_BASE_URL="http://127.0.0.1:$BACKEND_PORT/v1" \
    LLM_API_KEY="direct-key" \
    LLM_MODEL="direct-model" \
    LLM_SYSTEM_PROMPT="system prompt" \
    LLM_TEMPERATURE="0.25" \
    LLM_MAX_TOKENS="7" \
    bash "$REPO_ROOT/scripts/ask.sh" "$QUESTION"
)"
[[ "$DIRECT_OUTPUT" == *"fake response: Hello \"there\""* ]]
assert_backend_request "$BACKEND_LOG" "direct-key" "direct-model" "$QUESTION" "system prompt"

log "Testing ask.sh streaming response parsing"
STREAM_OUTPUT="$(
    LLM_BASE_URL="http://127.0.0.1:$BACKEND_PORT/v1" \
    LLM_API_KEY="stream-key" \
    LLM_MODEL="stream-model" \
    bash "$REPO_ROOT/scripts/ask.sh" --stream "stream question"
)"
[[ "$STREAM_OUTPUT" == "alphabeta" ]]
assert_backend_request "$BACKEND_LOG" "stream-key" "stream-model" "stream question" "" "1"

log "Testing profile loading and LLM_API_KEY_ENV resolution"
cat > "$PROFILE_FILE" <<EOF
LLM_BASE_URL=http://127.0.0.1:$BACKEND_PORT/v1
LLM_API_KEY_ENV=TEST_BACKEND_KEY
LLM_MODEL=profile-model
EOF
PROFILE_OUTPUT="$(
    TEST_BACKEND_KEY="profile-secret" \
    bash "$REPO_ROOT/scripts/ask.sh" -p ci-test "profile question"
)"
[[ "$PROFILE_OUTPUT" == "fake response: profile question" ]]
assert_backend_request "$BACKEND_LOG" "profile-secret" "profile-model" "profile question"

PROXY_PORT="$(free_port)"
log "Starting proxy on $PROXY_PORT"
LLM_BASE_URL="http://127.0.0.1:$BACKEND_PORT/v1" \
LLM_API_KEY="backend-secret" \
PROXY_API_KEY="client-secret" \
PROXY_PORT="$PROXY_PORT" \
PROXY_HOST="127.0.0.1" \
"$PYTHON_BIN" "$REPO_ROOT/scripts/openai_proxy.py" \
    > "$TMP_DIR/proxy.out" \
    2> "$TMP_DIR/proxy.err" &
PIDS+=("$!")
wait_for_url "http://127.0.0.1:$PROXY_PORT/healthz"

log "Testing proxy client authentication"
NOAUTH_STATUS="$(
    curl -sS -o "$TMP_DIR/noauth.json" -w "%{http_code}" \
        -X POST "http://127.0.0.1:$PROXY_PORT/v1/chat/completions" \
        -H "Content-Type: application/json" \
        -d '{"model":"ignored","messages":[{"role":"user","content":"blocked"}]}'
)"
[[ "$NOAUTH_STATUS" == "401" ]]

log "Testing proxy backend key injection"
curl -fsS \
    -X POST "http://127.0.0.1:$PROXY_PORT/v1/chat/completions" \
    -H "Authorization: Bearer client-secret" \
    -H "Content-Type: application/json" \
    -d '{"model":"proxy-model","messages":[{"role":"user","content":"through proxy"}]}' \
    > "$TMP_DIR/proxy_response.json"
assert_backend_request "$BACKEND_LOG" "backend-secret" "proxy-model" "through proxy"

log "Testing proxy SSE relay timing"
"$PYTHON_BIN" "$REPO_ROOT/tests/check_sse_timing.py" \
    "http://127.0.0.1:$PROXY_PORT/v1/chat/completions" \
    "client-secret"

log "All functional tests passed"
