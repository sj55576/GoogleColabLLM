#!/usr/bin/env python3
"""Small OpenAI-compatible fake backend used by tests."""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log", required=True)
    return parser.parse_args()


def make_handler(log_path: Path):
    class FakeOpenAIHandler(BaseHTTPRequestHandler):
        server_version = "FakeOpenAI/1.0"

        def log_message(self, format, *args):  # noqa: A002 - matches stdlib hook
            return

        def _write_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> bytes:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return b""
            return self.rfile.read(length)

        def _record(self, body: bytes) -> dict:
            text = body.decode("utf-8", errors="replace")
            try:
                parsed = json.loads(text) if text else None
            except json.JSONDecodeError:
                parsed = None

            entry = {
                "method": self.command,
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
                "content_type": self.headers.get("Content-Type", ""),
                "body": text,
                "json": parsed,
                "time": time.time(),
            }
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return entry

        def do_GET(self) -> None:
            self._record(b"")
            if self.path == "/v1/models":
                self._write_json(200, {"data": [{"id": "fake-model", "object": "model"}]})
                return
            self._write_json(404, {"error": {"message": "not found"}})

        def do_POST(self) -> None:
            body = self._read_body()
            entry = self._record(body)
            if self.path != "/v1/chat/completions":
                self._write_json(404, {"error": {"message": "not found"}})
                return

            payload = entry["json"] if isinstance(entry["json"], dict) else {}
            if payload.get("stream") is True:
                self._write_stream()
                return

            messages = payload.get("messages", [])
            last_user = ""
            if messages and isinstance(messages[-1], dict):
                last_user = str(messages[-1].get("content", ""))
            self._write_json(
                200,
                {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": f"fake response: {last_user}",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                },
            )

        def _write_stream(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            chunks = [
                {"choices": [{"delta": {"content": "alpha"}}]},
                {"choices": [{"delta": {"content": "beta"}}]},
            ]
            for chunk in chunks:
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode("utf-8"))
                self.wfile.flush()
                time.sleep(0.25)
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

    return FakeOpenAIHandler


def main() -> None:
    args = parse_args()
    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")
    server = ThreadingHTTPServer((args.host, args.port), make_handler(log_path))
    server.serve_forever()


if __name__ == "__main__":
    main()
