#!/usr/bin/env python3
"""llama-cpp-pythonのOpenAI互換サーバーを起動するラッパースクリプト。

Google Colab (T4など) のランタイム上で実行し、GGUF量子化モデルを
OpenAI互換のREST API (/v1/chat/completions 等) として公開する。

環境変数:
    MODEL_PATH    : GGUFモデルファイルへのパス
                    (既定: <repo_root>/models/qwen2.5-1.5b-instruct-q4_k_m.gguf)
    LLM_PORT      : サーバーが待ち受けるポート番号 (既定: 8000)
    N_GPU_LAYERS  : GPUにオフロードするレイヤー数。-1で全レイヤー (既定: -1)
    N_CTX         : コンテキスト長 (既定: 4096)
    LLM_HOST      : バインドするホスト (既定: 0.0.0.0)
"""
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL_PATH = REPO_ROOT / "models" / "qwen2.5-1.5b-instruct-q4_k_m.gguf"


def get_config() -> dict:
    """環境変数から設定値を取得する(未設定の場合は既定値を使用)。"""
    return {
        "model_path": Path(os.environ.get("MODEL_PATH", str(DEFAULT_MODEL_PATH))),
        "host": os.environ.get("LLM_HOST", "0.0.0.0"),
        "port_raw": os.environ.get("LLM_PORT", "8000"),
        "n_gpu_layers": os.environ.get("N_GPU_LAYERS", "-1"),
        "n_ctx": os.environ.get("N_CTX", "4096"),
    }


def validate(config: dict) -> dict:
    """設定値を検証し、後続処理で使いやすい形に正規化して返す。"""
    if importlib.util.find_spec("llama_cpp") is None:
        print("エラー: llama_cpp モジュールが見つかりません。")
        print("       先に scripts/setup_colab.sh を実行してください。")
        sys.exit(1)

    if not config["model_path"].exists():
        print(f"エラー: モデルファイルが見つかりません: {config['model_path']}")
        print("       先に scripts/download_model.py を実行してモデルを取得してください。")
        sys.exit(1)

    try:
        port = int(config["port_raw"])
    except ValueError:
        print(f"エラー: LLM_PORT は整数である必要があります (指定値: {config['port_raw']!r})")
        sys.exit(1)

    try:
        n_gpu_layers = int(config["n_gpu_layers"])
    except ValueError:
        print(f"エラー: N_GPU_LAYERS は整数である必要があります (指定値: {config['n_gpu_layers']!r})")
        sys.exit(1)

    try:
        n_ctx = int(config["n_ctx"])
    except ValueError:
        print(f"エラー: N_CTX は整数である必要があります (指定値: {config['n_ctx']!r})")
        sys.exit(1)

    return {
        "model_path": config["model_path"],
        "host": config["host"],
        "port": port,
        "n_gpu_layers": n_gpu_layers,
        "n_ctx": n_ctx,
    }


def build_command(config: dict) -> list:
    """llama_cpp.server を起動するためのコマンドラインを組み立てる。"""
    return [
        sys.executable,
        "-m",
        "llama_cpp.server",
        "--model",
        str(config["model_path"]),
        "--host",
        config["host"],
        "--port",
        str(config["port"]),
        "--n_gpu_layers",
        str(config["n_gpu_layers"]),
        "--n_ctx",
        str(config["n_ctx"]),
    ]


def print_banner(config: dict) -> None:
    """起動前に設定内容を要約して表示する。"""
    print("=== LLMサーバー設定 ===")
    print(f"モデルパス   : {config['model_path']}")
    print(f"ホスト       : {config['host']}")
    print(f"ポート       : {config['port']}")
    print(f"N_GPU_LAYERS : {config['n_gpu_layers']}")
    print(f"N_CTX        : {config['n_ctx']}")
    print("========================")


def main() -> None:
    raw_config = get_config()
    config = validate(raw_config)
    print_banner(config)

    command = build_command(config)
    print(f"実行コマンド: {' '.join(command)}")

    try:
        result = subprocess.run(command)
    except KeyboardInterrupt:
        print("\n中断を検知しました。サーバーを終了します。")
        sys.exit(0)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
