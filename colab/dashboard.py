#!/usr/bin/env python3
"""Colabダッシュボードのコアロジック層。

UI (colab/dashboard_ui.py の ipywidgets 層など) から呼び出されることを想定した、
依存の薄いモジュール。
サーバーの起動・停止・死活監視、モデルのダウンロード・一覧取得、
チャット送信、GPU使用状況の取得といった処理をまとめる。

このモジュールは import 時に標準ライブラリ以外へ依存しない
(CI では pip install を行わずに import できる必要があるため)。
huggingface_hub は download_model() 関数の内部で遅延importする。
HTTPリクエストは requests を使わず標準ライブラリの urllib.request を用いる。
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODELS_DIR = REPO_ROOT / "models"
DEFAULT_LOG_DIR = REPO_ROOT / "logs"
DEFAULT_BASE_URL = "http://127.0.0.1:8000/v1"

# モデルプリセット。T4 (VRAM 15GB) で動作するGGUFを厳選している。
MODEL_PRESETS: list[dict] = [
    {
        "label": "Qwen2.5 1.5B Instruct Q4_K_M",
        "repo_id": "Qwen/Qwen2.5-1.5B-Instruct-GGUF",
        "filename": "qwen2.5-1.5b-instruct-q4_k_m.gguf",
        "note": "サイズ目安: 約1GB。最も軽量でリポジトリの既定モデル。動作確認や低VRAM環境向け。",
    },
    {
        "label": "Qwen2.5 3B Instruct Q4_K_M",
        "repo_id": "Qwen/Qwen2.5-3B-Instruct-GGUF",
        "filename": "qwen2.5-3b-instruct-q4_k_m.gguf",
        "note": "サイズ目安: 約2GB。軽量さと応答品質のバランスが良い。",
    },
    {
        "label": "Qwen2.5 7B Instruct Q4_K_M",
        "repo_id": "Qwen/Qwen2.5-7B-Instruct-GGUF",
        "filename": "qwen2.5-7b-instruct-q4_k_m.gguf",
        "note": "サイズ目安: 約4.5GB。T4 (VRAM 15GB) で全レイヤーGPUオフロード可能な高品質モデル。",
    },
    {
        "label": "Llama 3.2 3B Instruct Q4_K_M",
        "repo_id": "bartowski/Llama-3.2-3B-Instruct-GGUF",
        "filename": "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        "note": "サイズ目安: 約2GB。HF上で利用条件への同意とHF_TOKENが必要な場合あり。",
    },
]


class DashboardError(Exception):
    """ダッシュボード利用者向けの日本語メッセージを持つ例外。"""


@dataclasses.dataclass
class ServerConfig:
    """llama_cpp.server の起動設定。"""

    model_path: Path
    host: str = "0.0.0.0"
    port: int = 8000
    n_gpu_layers: int = -1
    n_ctx: int = 4096


def build_server_command(config: ServerConfig, python_executable: str | None = None) -> list[str]:
    """colab/start_llm_server.py の build_command と同一の引数列を組み立てる。"""
    python_bin = python_executable or sys.executable
    return [
        python_bin,
        "-m",
        "llama_cpp.server",
        "--model",
        str(config.model_path),
        "--host",
        config.host,
        "--port",
        str(config.port),
        "--n_gpu_layers",
        str(config.n_gpu_layers),
        "--n_ctx",
        str(config.n_ctx),
    ]


class ServerManager:
    """llama_cpp.server サブプロセスのライフサイクル管理。1インスタンス=1サーバー。"""

    def __init__(self, repo_root: Path | None = None, log_dir: Path | None = None) -> None:
        self._repo_root = repo_root or REPO_ROOT
        self._log_dir = log_dir or DEFAULT_LOG_DIR
        self._process: subprocess.Popen | None = None
        self._config: ServerConfig | None = None
        self._log_fh = None
        self._log_path = self._log_dir / "llm_server.log"

    def start(self, config: ServerConfig, command: list[str] | None = None) -> None:
        """サーバーを起動する。既に起動中の場合はDashboardErrorを送出する。"""
        if self.is_running():
            raise DashboardError("サーバーは既に起動しています。先に停止してください。")

        # 前回のプロセスが自然終了していた場合、開いたままのログFH等を確実に片付ける。
        if self._process is not None:
            self.stop()

        if command is None:
            if not config.model_path.exists():
                raise DashboardError(
                    f"モデルファイルが見つかりません: {config.model_path}\n"
                    "先にモデルをダウンロードしてください。"
                )
            command = build_server_command(config)

        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_fh = self._log_path.open("a", encoding="utf-8")

        self._process = subprocess.Popen(
            command,
            stdout=self._log_fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            cwd=str(self._repo_root),
        )
        self._config = config

    def stop(self, timeout: float = 15.0) -> None:
        """サーバーを停止する。既に停止済みの場合は何もしない(冪等)。"""
        if self._process is None:
            return

        process = self._process
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            else:
                deadline = time.monotonic() + timeout
                while process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.1)

            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=timeout)

        if self._log_fh is not None:
            self._log_fh.close()
            self._log_fh = None

        self._process = None
        self._config = None

    def is_running(self) -> bool:
        """サーバーが現在起動中かどうかを返す。"""
        return self._process is not None and self._process.poll() is None

    def status(self) -> dict:
        """現在の状態を辞書形式で返す。"""
        running = self.is_running()
        config_dict = None
        if self._config is not None:
            config_dict = {
                "model_path": str(self._config.model_path),
                "host": self._config.host,
                "port": self._config.port,
                "n_gpu_layers": self._config.n_gpu_layers,
                "n_ctx": self._config.n_ctx,
            }
        return {
            "running": running,
            "pid": self._process.pid if running and self._process else None,
            "config": config_dict,
            "log_path": str(self._log_path),
        }

    def tail_log(self, lines: int = 60) -> str:
        """ログの末尾を返す。ログファイルが未作成なら案内文字列を返す。"""
        if not self._log_path.exists():
            return "ログファイルはまだ作成されていません(サーバーが起動されていない可能性があります)。"

        with self._log_path.open("r", encoding="utf-8", errors="replace") as handle:
            content = handle.readlines()
        return "".join(content[-lines:])

    def wait_healthy(self, base_url: str | None = None, timeout: float = 300.0, interval: float = 2.0) -> bool:
        """サーバーが応答可能になるまでポーリングする。"""
        if base_url is None:
            port = self._config.port if self._config is not None else 8000
            base_url = f"http://127.0.0.1:{port}/v1"

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._process is not None and self._process.poll() is not None:
                return False

            result = check_health(base_url=base_url, timeout=min(interval, 5.0))
            if result["ok"]:
                return True

            time.sleep(interval)

        return False


def check_health(base_url: str = DEFAULT_BASE_URL, timeout: float = 5.0) -> dict:
    """{base_url}/models へGETし、サーバーの死活状態を確認する。"""
    url = f"{base_url.rstrip('/')}/models"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            response.read()
            return {"ok": True, "detail": "サーバーは正常に応答しています。"}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "detail": f"サーバーがエラーを返しました (HTTP {exc.code})。"}
    except urllib.error.URLError as exc:
        return {"ok": False, "detail": f"サーバーへの接続に失敗しました: {exc.reason}"}
    except OSError as exc:
        return {"ok": False, "detail": f"サーバーへの接続に失敗しました: {exc}"}


def send_chat(
    base_url: str,
    prompt: str,
    system: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model: str = "local",
    timeout: float = 300.0,
) -> str:
    """{base_url}/chat/completions へ非ストリーミングでリクエストし、応答本文を返す。"""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    payload: dict = {
        "model": model,
        "messages": messages,
        "stream": False,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    url = f"{base_url.rstrip('/')}/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise DashboardError(f"サーバーがエラーを返しました (HTTP {exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise DashboardError(f"サーバーへの接続に失敗しました: {exc.reason}") from exc

    try:
        parsed = json.loads(body)
        return parsed["choices"][0]["message"]["content"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise DashboardError(f"サーバーの応答を解析できませんでした: {exc}") from exc


def gpu_info() -> dict:
    """nvidia-smi からGPUの使用状況を取得する。"""
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi is None:
        return {"available": False, "detail": "nvidia-smi が見つかりません(GPUなし環境の可能性があります)。"}

    command = [
        nvidia_smi,
        "--query-gpu=name,memory.used,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"available": False, "detail": f"nvidia-smi の実行に失敗しました: {exc}"}

    line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    parts = [p.strip() for p in line.split(",")]
    if len(parts) != 4:
        return {"available": False, "detail": f"nvidia-smi の出力を解析できませんでした: {line!r}"}

    try:
        name, memory_used, memory_total, utilization = parts
        return {
            "available": True,
            "name": name,
            "memory_used_mb": int(memory_used),
            "memory_total_mb": int(memory_total),
            "utilization_pct": int(utilization),
        }
    except ValueError as exc:
        return {"available": False, "detail": f"nvidia-smi の出力を解析できませんでした: {exc}"}


def list_local_models(models_dir: Path | None = None) -> list[Path]:
    """models_dir 配下の *.gguf をソートして返す。ディレクトリが無ければ空リスト。"""
    target_dir = models_dir or DEFAULT_MODELS_DIR
    if not target_dir.exists():
        return []
    return sorted(target_dir.glob("*.gguf"))


def download_model(repo_id: str, filename: str, model_dir: Path | None = None, token: str | None = None) -> Path:
    """Hugging Face Hubからモデルファイルをダウンロードする。"""
    target_dir = model_dir or DEFAULT_MODELS_DIR
    target_path = target_dir / filename

    if target_path.exists():
        return target_path

    try:
        from huggingface_hub import hf_hub_download
    except ImportError as exc:
        raise DashboardError(
            "huggingface_hub モジュールが見つかりません。\n"
            "先に scripts/setup_colab.sh を実行して依存パッケージをインストールしてください。"
        ) from exc

    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            local_dir=str(target_dir),
            token=token,
        )
    except Exception as exc:  # noqa: BLE001 - ユーザー向けに理由を要約して案内するため広く捕捉する
        raise DashboardError(
            "モデルのダウンロードに失敗しました。\n"
            f"詳細: {exc}\n"
            "考えられる原因: リポジトリID/ファイル名のスペルミス、ネットワーク接続の問題、"
            "gated (要認証) モデルのためHF_TOKENの設定が必要、のいずれかです。"
        ) from exc

    return Path(downloaded_path)
