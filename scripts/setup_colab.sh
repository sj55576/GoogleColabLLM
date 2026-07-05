#!/usr/bin/env bash
# Colab (T4) ランタイム上でLLMサーバーを動かすためのセットアップスクリプト。
# - GPUの可視性チェック
# - 必要なPythonパッケージのインストール
# - (任意) CUDA対応llama-cpp-pythonの再インストール
# - モデル格納用ディレクトリの作成
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== [1/4] セットアップを開始します ==="

echo "=== [2/4] GPUの可視性を確認します (nvidia-smi) ==="
if ! nvidia-smi; then
    echo "警告: nvidia-smi の実行に失敗しました。GPUが認識されていない可能性があります。"
    echo "      ColabのランタイムタイプがGPU(T4)になっているか確認してください。"
fi

echo "=== [3/4] Pythonパッケージをインストールします ==="
python3 -m pip install -q -r "$REPO_ROOT/requirements.txt"

# 注意: llama-cpp-pythonの標準ビルドはCPUのみの場合があります。
# CUDAによるGPUアクセラレーションを有効にするには、
# CMAKE_ARGS="-DGGML_CUDA=on" を指定して再ビルド・再インストールする必要があります。
# 時間がかかるため、環境変数 INSTALL_CUDA_LLAMA=1 が設定された場合のみ実行します。
if [[ "${INSTALL_CUDA_LLAMA:-0}" == "1" ]]; then
    echo "=== INSTALL_CUDA_LLAMA=1 が指定されたため、CUDA対応版を再インストールします ==="
    CMAKE_ARGS="-DGGML_CUDA=on" python3 -m pip install -q --force-reinstall --no-cache-dir "llama-cpp-python[server]"
fi

echo "=== [4/4] モデル格納用ディレクトリを作成します ==="
mkdir -p "$REPO_ROOT/models"

echo "=== セットアップが完了しました ==="
