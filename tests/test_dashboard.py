#!/usr/bin/env python3
"""colab/dashboard.py のユニットテスト。

標準ライブラリの unittest のみを使用する。
`python3 tests/test_dashboard.py` で直接実行できる。
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "colab"))

import dashboard  # noqa: E402


def free_port() -> int:
    """空いているTCPポート番号を1つ取得する。"""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_health(base_url: str, attempts: int = 50, interval: float = 0.1) -> bool:
    """check_health が ok になるまでポーリングする。"""
    for _ in range(attempts):
        if dashboard.check_health(base_url=base_url, timeout=2.0)["ok"]:
            return True
        time.sleep(interval)
    return False


class BuildServerCommandTest(unittest.TestCase):
    def test_build_server_command_matches_expected_argument_list(self) -> None:
        config = dashboard.ServerConfig(
            model_path=Path("/models/example.gguf"),
            host="0.0.0.0",
            port=8123,
            n_gpu_layers=-1,
            n_ctx=4096,
        )
        command = dashboard.build_server_command(config, python_executable="/usr/bin/python3")
        self.assertEqual(
            command,
            [
                "/usr/bin/python3",
                "-m",
                "llama_cpp.server",
                "--model",
                "/models/example.gguf",
                "--host",
                "0.0.0.0",
                "--port",
                "8123",
                "--n_gpu_layers",
                "-1",
                "--n_ctx",
                "4096",
            ],
        )

    def test_build_server_command_defaults_to_sys_executable(self) -> None:
        config = dashboard.ServerConfig(model_path=Path("/models/example.gguf"))
        command = dashboard.build_server_command(config)
        self.assertEqual(command[0], sys.executable)


class ServerManagerLifecycleTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp_dir = tempfile.mkdtemp(prefix="dashboard-test-")
        self.log_dir = Path(self._tmp_dir) / "logs"
        self.manager = dashboard.ServerManager(repo_root=REPO_ROOT, log_dir=self.log_dir)

    def tearDown(self) -> None:
        self.manager.stop()
        shutil.rmtree(self._tmp_dir, ignore_errors=True)

    def _dummy_command(self) -> list[str]:
        return [
            sys.executable,
            "-c",
            "import time; print('x', flush=True); time.sleep(60)",
        ]

    def test_lifecycle_start_status_log_stop(self) -> None:
        config = dashboard.ServerConfig(model_path=Path("/nonexistent/model.gguf"))
        self.manager.start(config, command=self._dummy_command())

        self.assertTrue(self.manager.is_running())
        self.assertTrue(self.manager.status()["running"])
        self.assertIsInstance(self.manager.status()["pid"], int)

        log_content = ""
        for _ in range(50):
            log_content = self.manager.tail_log()
            if "x" in log_content:
                break
            time.sleep(0.1)
        self.assertIn("x", log_content)

        self.manager.stop()
        self.assertFalse(self.manager.is_running())
        self.assertFalse(self.manager.status()["running"])

        # 停止済みに対する再度のstopは冪等 (例外を投げない)
        self.manager.stop()
        self.assertFalse(self.manager.is_running())

    def test_double_start_raises_dashboard_error(self) -> None:
        config = dashboard.ServerConfig(model_path=Path("/nonexistent/model.gguf"))
        self.manager.start(config, command=self._dummy_command())
        with self.assertRaises(dashboard.DashboardError):
            self.manager.start(config, command=self._dummy_command())

    def test_restart_after_process_exited_on_its_own(self) -> None:
        config = dashboard.ServerConfig(model_path=Path("/nonexistent/model.gguf"))
        self.manager.start(config, command=[sys.executable, "-c", "pass"])

        # プロセスが自然終了するのを待つ
        for _ in range(50):
            if not self.manager.is_running():
                break
            time.sleep(0.1)
        self.assertFalse(self.manager.is_running())

        # 自然終了後は stop() を挟まなくても再startできる (内部状態が掃除される)
        self.manager.start(config, command=self._dummy_command())
        self.assertTrue(self.manager.is_running())

    def test_start_without_command_requires_existing_model_path(self) -> None:
        missing_model = Path(self._tmp_dir) / "missing-model.gguf"
        config = dashboard.ServerConfig(model_path=missing_model)
        with self.assertRaises(dashboard.DashboardError):
            self.manager.start(config)
        self.assertFalse(self.manager.is_running())


class FakeBackendTest(unittest.TestCase):
    """tests/fake_openai_backend.py を実プロセスとして起動して検証する。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp_dir = tempfile.mkdtemp(prefix="dashboard-fake-backend-")
        cls.port = free_port()
        cls.log_path = Path(cls._tmp_dir) / "backend.jsonl"
        cls.base_url = f"http://127.0.0.1:{cls.port}/v1"
        cls.process = subprocess.Popen(
            [
                sys.executable,
                str(REPO_ROOT / "tests" / "fake_openai_backend.py"),
                "--port",
                str(cls.port),
                "--log",
                str(cls.log_path),
            ],
        )
        if not wait_for_health(cls.base_url):
            cls.process.kill()
            cls.process.wait(timeout=10)
            raise RuntimeError("fake backend did not become healthy in time")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.process.kill()
        cls.process.wait(timeout=10)
        shutil.rmtree(cls._tmp_dir, ignore_errors=True)

    def test_check_health_ok_against_running_backend(self) -> None:
        result = dashboard.check_health(base_url=self.base_url)
        self.assertTrue(result["ok"])

    def test_send_chat_returns_message_content(self) -> None:
        content = dashboard.send_chat(self.base_url, "hello dashboard")
        self.assertEqual(content, "fake response: hello dashboard")

    def test_send_chat_with_system_and_options(self) -> None:
        content = dashboard.send_chat(
            self.base_url,
            "with options",
            system="be terse",
            temperature=0.1,
            max_tokens=16,
            model="dashboard-model",
        )
        self.assertEqual(content, "fake response: with options")


class CheckHealthUnreachableTest(unittest.TestCase):
    def test_check_health_returns_false_when_unreachable(self) -> None:
        port = free_port()
        result = dashboard.check_health(base_url=f"http://127.0.0.1:{port}/v1", timeout=1.0)
        self.assertFalse(result["ok"])
        self.assertIsInstance(result["detail"], str)
        self.assertTrue(result["detail"])


class GpuInfoTest(unittest.TestCase):
    def test_gpu_info_reports_unavailable_when_nvidia_smi_missing(self) -> None:
        original_path = os.environ.get("PATH")
        try:
            os.environ["PATH"] = ""
            info = dashboard.gpu_info()
        finally:
            if original_path is None:
                os.environ.pop("PATH", None)
            else:
                os.environ["PATH"] = original_path

        self.assertFalse(info["available"])
        self.assertIsInstance(info["detail"], str)
        self.assertTrue(info["detail"])


class ListLocalModelsTest(unittest.TestCase):
    def test_list_local_models_returns_only_gguf_files_sorted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dashboard-models-") as tmp_dir:
            models_dir = Path(tmp_dir)
            (models_dir / "b-model.gguf").write_bytes(b"")
            (models_dir / "a-model.gguf").write_bytes(b"")
            (models_dir / "notes.txt").write_bytes(b"")

            result = dashboard.list_local_models(models_dir)

            self.assertEqual(
                [p.name for p in result],
                ["a-model.gguf", "b-model.gguf"],
            )

    def test_list_local_models_returns_empty_list_for_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="dashboard-models-") as tmp_dir:
            missing_dir = Path(tmp_dir) / "does-not-exist"
            self.assertEqual(dashboard.list_local_models(missing_dir), [])


if __name__ == "__main__":
    unittest.main()
