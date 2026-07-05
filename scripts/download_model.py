#!/usr/bin/env python3
"""GGUF量子化モデルをHugging Face Hubからダウンロードするスクリプト。

環境変数:
    HF_REPO_ID  : ダウンロード元のリポジトリID (既定: Qwen/Qwen2.5-1.5B-Instruct-GGUF)
    HF_FILENAME : ダウンロードするファイル名 (既定: qwen2.5-1.5b-instruct-q4_k_m.gguf)
    MODEL_DIR   : 保存先ディレクトリ。リポジトリルートからの相対パス (既定: models)
    HF_TOKEN    : gated (要認証) モデルをダウンロードする場合のHugging Faceトークン
"""
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_HF_REPO_ID = "Qwen/Qwen2.5-1.5B-Instruct-GGUF"
DEFAULT_HF_FILENAME = "qwen2.5-1.5b-instruct-q4_k_m.gguf"
DEFAULT_MODEL_DIR = "models"


def get_config() -> dict:
    """環境変数から設定値を取得する(未設定の場合は既定値を使用)。"""
    model_dir = os.environ.get("MODEL_DIR", DEFAULT_MODEL_DIR)
    model_dir_path = Path(model_dir)
    if not model_dir_path.is_absolute():
        model_dir_path = REPO_ROOT / model_dir_path

    return {
        "repo_id": os.environ.get("HF_REPO_ID", DEFAULT_HF_REPO_ID),
        "filename": os.environ.get("HF_FILENAME", DEFAULT_HF_FILENAME),
        "model_dir": model_dir_path,
        "token": os.environ.get("HF_TOKEN") or None,
    }


def model_exists(model_dir: Path, filename: str) -> bool:
    """指定ファイルが既に保存先に存在するかを確認する。"""
    return (model_dir / filename).exists()


def download(config: dict) -> Path:
    """huggingface_hub.hf_hub_download を用いてモデルファイルをダウンロードする。"""
    from huggingface_hub import hf_hub_download

    config["model_dir"].mkdir(parents=True, exist_ok=True)

    downloaded_path = hf_hub_download(
        repo_id=config["repo_id"],
        filename=config["filename"],
        local_dir=str(config["model_dir"]),
        token=config["token"],
    )
    return Path(downloaded_path)


def main() -> None:
    config = get_config()
    target_path = config["model_dir"] / config["filename"]

    print("=== モデルダウンロード設定 ===")
    print(f"リポジトリID   : {config['repo_id']}")
    print(f"ファイル名     : {config['filename']}")
    print(f"保存先ディレクトリ: {config['model_dir']}")
    print(f"HFトークン     : {'設定済み' if config['token'] else '未設定'}")

    if model_exists(config["model_dir"], config["filename"]):
        print(f"既に存在するためスキップ: {target_path}")
        sys.exit(0)

    try:
        result_path = download(config)
    except Exception as exc:  # noqa: BLE001 - ユーザー向けに理由を要約して案内するため広く捕捉する
        print("エラー: モデルのダウンロードに失敗しました。")
        print(f"詳細: {exc}")
        print("考えられる原因:")
        print("  - HF_REPO_ID / HF_FILENAME のスペルミス")
        print("  - ネットワーク接続の問題")
        print("  - gated (要認証) モデルのため HF_TOKEN の設定が必要")
        sys.exit(1)

    print(f"ダウンロードが完了しました: {result_path}")


if __name__ == "__main__":
    main()
