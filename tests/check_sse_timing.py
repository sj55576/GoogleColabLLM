#!/usr/bin/env python3
"""Verify that the local proxy relays SSE chunks without buffering the response."""

from __future__ import annotations

import http.client
import json
import sys
import time
from urllib.parse import urlsplit


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: check_sse_timing.py URL CLIENT_API_KEY", file=sys.stderr)
        sys.exit(2)

    target = urlsplit(sys.argv[1])
    client_api_key = sys.argv[2]
    body = json.dumps(
        {
            "model": "proxy-model",
            "stream": True,
            "messages": [{"role": "user", "content": "stream please"}],
        }
    )
    headers = {
        "Authorization": f"Bearer {client_api_key}",
        "Content-Type": "application/json",
    }

    conn = http.client.HTTPConnection(target.hostname, target.port, timeout=5)
    started = time.monotonic()
    conn.request("POST", target.path, body=body, headers=headers)
    response = conn.getresponse()
    if response.status != 200:
        print(f"expected 200, got {response.status}: {response.read()!r}", file=sys.stderr)
        sys.exit(1)

    arrivals: list[tuple[float, bytes]] = []
    while True:
        line = response.readline()
        if not line:
            break
        if not line.startswith(b"data: "):
            continue
        now = time.monotonic()
        if line.strip() == b"data: [DONE]":
            break
        arrivals.append((now, line.strip()))
        if len(arrivals) >= 2:
            break

    conn.close()

    if len(arrivals) < 2:
        print(f"expected at least 2 SSE chunks, got {len(arrivals)}", file=sys.stderr)
        sys.exit(1)

    first_delay = arrivals[0][0] - started
    chunk_gap = arrivals[1][0] - arrivals[0][0]
    if first_delay > 1.0:
        print(f"first SSE chunk arrived too late: {first_delay:.3f}s", file=sys.stderr)
        sys.exit(1)
    if chunk_gap < 0.15:
        print(f"SSE chunks appear buffered; gap was {chunk_gap:.3f}s", file=sys.stderr)
        sys.exit(1)

    print(f"SSE timing OK: first={first_delay:.3f}s gap={chunk_gap:.3f}s")


if __name__ == "__main__":
    main()
