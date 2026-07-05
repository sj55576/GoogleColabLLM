#!/usr/bin/env bash
# 他のアプリ向けOpenAI互換プロキシ (scripts/openai_proxy.py) を起動する薄いラッパー。
#
# 使い方:
#   ./scripts/serve_proxy.sh -p groq
#   PROXY_PORT=9000 ./scripts/serve_proxy.sh -p colab-local
#
# オプション・環境変数の詳細は scripts/openai_proxy.py --help を参照してください。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec python3 "$SCRIPT_DIR/openai_proxy.py" "$@"
