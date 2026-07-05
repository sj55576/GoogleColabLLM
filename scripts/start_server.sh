#!/usr/bin/env bash
# Colab (T4) ランタイム上で「セットアップ→モデル取得→サーバー起動」を
# 一括で行うオーケストレーションスクリプト。
#
# 想定される実行例 (ローカル端末から Google Colab CLI 経由):
#   colab --gpu T4 exec scripts/start_server.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

echo "=== [1/3] 依存パッケージのセットアップを行います ==="
bash scripts/setup_colab.sh

echo "=== [2/3] モデルをダウンロードします (既にあればスキップされます) ==="
python3 scripts/download_model.py

echo "=== [3/3] LLMサーバーを起動します ==="
# execでプロセスを置き換えることで、シグナル(Ctrl+Cなど)がサーバーに正しく伝わるようにする。
exec python3 colab/start_llm_server.py
