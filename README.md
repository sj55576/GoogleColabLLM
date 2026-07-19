# colab-local-llm-cli

**English** | [日本語](README.ja.md)

A lightweight collection of scripts that runs a GGUF-quantized LLM as an
OpenAI-compatible API on a Google Colab T4 runtime, and lets you query it from
a CLI on your local machine.

## Table of Contents

- [1. Overview](#1-overview)
- [2. Quickstart](#2-quickstart)
- [3. Architecture Diagram](#3-architecture-diagram)
- [4. Prerequisites](#4-prerequisites)
- [5. Setup / Starting a T4 Runtime](#5-setup--starting-a-t4-runtime)
- [6. Server Environment Variables](#6-server-environment-variables)
- [7. Connecting from Your Local Machine](#7-connecting-from-your-local-machine)
- [8. Switching Between Backends (Profiles)](#8-switching-between-backends-profiles)
- [9. OpenAI-Compatible Proxy for Other Apps (Gateway)](#9-openai-compatible-proxy-for-other-apps-gateway)
- [10. Changing the Model](#10-changing-the-model)
- [11. Troubleshooting](#11-troubleshooting)
- [12. Security Notes](#12-security-notes)
- [13. Repository Layout](#13-repository-layout)
- [14. License](#14-license)

## 1. Overview

This repository does the following:

- Starts a T4 runtime with the official Google Colab CLI and runs a
  GGUF-quantized model on the `llama-cpp-python` OpenAI-compatible server
  (`llama_cpp.server`).
- From your local machine, a simple `curl`-based CLI (`scripts/ask.sh`) sends
  `POST /v1/chat/completions`-style requests and prints the answer.
- Model download, setup, and health checks are all automated.

## 2. Quickstart

The shortest path to try it out. See the linked chapters for details on each step.

### (1) Colab side: start the server

```bash
colab --gpu T4 exec scripts/start_server.sh
```

If the Colab CLI is not available, the same operation can be done from a
regular Colab notebook cell. See [chapter 5](#5-setup--starting-a-t4-runtime).

### (2) Local side: health check, then ask

```bash
LLM_BASE_URL="http://localhost:8000/v1" ./scripts/healthcheck.sh
export LLM_BASE_URL="http://localhost:8000/v1"
./scripts/ask.sh "What is a quantized LLM?"
```

See [chapter 7](#7-connecting-from-your-local-machine) for connecting through a
tunnel, and [chapter 8](#8-switching-between-backends-profiles) for switching
to other backends.

### (3) Using it from other apps

```bash
./scripts/serve_proxy.sh   # relays to the Colab local server (http://localhost:8000/v1) by default
```

```python
from openai import OpenAI
client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="dummy")
```

See [chapter 9](#9-openai-compatible-proxy-for-other-apps-gateway) for details.

## 3. Architecture Diagram

```
Local machine                           Colab T4 runtime
+--------------------+                +-----------------------------------+
|                    |     port       |                                   |
| scripts/ask.sh     |   forward /    |  colab/start_llm_server.py        |
| (CLI client)       | <--tunnel-->   |   -> llama-cpp-python server      |
|                    | (http://:8000) |      (OpenAI-compatible API,:8000)|
+--------------------+                |   -> GGUF quantized model         |
                                      |      (models/)                    |
                                      +-----------------------------------+
```

For a detailed description of each component, the request flow, and the
configuration precedence rules, see [`docs/architecture.md`](docs/architecture.md).

## 4. Prerequisites

- A Google account (with access to Google Colab)
- The official Google Colab CLI, installed and authenticated
  - Official docs: https://developers.google.com/colab
  - Installation and authentication steps may change between versions, so
    always follow the latest official documentation
    (it may look something like `pip install google-colab-cli`).
- Python 3.10+ (on both the local machine and the Colab runtime)
- `curl` (used on the local machine for health checks and API calls)

## 5. Setup / Starting a T4 Runtime

The intended one-shot command that runs setup through server startup on a
T4 GPU runtime via the Colab CLI:

```bash
colab --gpu T4 exec scripts/start_server.sh
```

Example of placing the repository on the runtime (running git clone on the runtime):

```bash
colab --gpu T4 exec -- git clone https://github.com/<your>/colab-local-llm-cli.git
```

### Fallback: when the Colab CLI is unavailable

In environments where the Colab CLI cannot be used, the equivalent steps can
be run from regular Colab notebook cells.

```python
!git clone https://github.com/<your>/colab-local-llm-cli.git
%cd colab-local-llm-cli
!bash scripts/start_server.sh
```

### Using the dashboard (GUI)

Instead of the CLI, you can also do everything — from model selection to
server startup and testing — through a GUI in a Colab notebook.

[![Open In Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/sj55576/GCLLM/blob/main/colab/dashboard.ipynb)

Open the notebook and run the cells top to bottom to get a dashboard with the
following five tabs:

- **Model**: pick from presets, or specify a Hugging Face repository to download
- **Server settings**: set the port, N_CTX, and N_GPU_LAYERS (same meaning as
  the environment variables of the same names in chapter 6)
- **Run**: start / stop / restart the server and run health checks
- **Monitor**: check GPU usage and the server log (`logs/llm_server.log`)
- **Test chat**: send questions to the running server to verify it works

Internally, `ServerManager` in `colab/dashboard.py` assembles the same command
line as `colab/start_llm_server.py` and launches it as a subprocess, so the
behavior matches the CLI. See [`docs/architecture.md`](docs/architecture.md)
for details.

## 6. Server Environment Variables

`colab/start_llm_server.py` and related scripts can be tuned with the
following environment variables.

| Variable       | Default                                                  | Meaning                                            |
|----------------|----------------------------------------------------------|----------------------------------------------------|
| `MODEL_PATH`   | `models/qwen2.5-1.5b-instruct-q4_k_m.gguf` (repo-relative) | Path of the GGUF model file to load                |
| `LLM_HOST`     | `0.0.0.0`                                                | Host the server binds to                           |
| `LLM_PORT`     | `8000`                                                   | Port the server listens on                         |
| `N_GPU_LAYERS` | `-1`                                                     | Number of layers to offload to the GPU (`-1` = all)|
| `N_CTX`        | `4096`                                                   | Context length (in tokens)                         |
| `HF_REPO_ID`   | `Qwen/Qwen2.5-1.5B-Instruct-GGUF`                        | Hugging Face repository to download from           |
| `HF_FILENAME`  | `qwen2.5-1.5b-instruct-q4_k_m.gguf`                      | File name to download                              |
| `MODEL_DIR`    | `models`                                                 | Directory to store models (repo-relative allowed)  |
| `HF_TOKEN`     | (unset)                                                  | Hugging Face token for gated (auth-required) models|

## 7. Connecting from Your Local Machine

The server listens on `localhost:8000` inside the Colab runtime. To reach it
from your local machine, expose it outside the runtime in one of these ways:

- (a) The Colab CLI's port-forwarding feature (prefer this when available)
- (b) A tunnel service such as `cloudflared` or `ngrok` (optional)

Tunnel example (using `cloudflared`):

```bash
cloudflared tunnel --url http://localhost:8000
```

Using the URL it prints (e.g. `https://xxxx.trycloudflare.com`), connect from
your local machine like this:

```bash
export LLM_BASE_URL="http://localhost:8000/v1"   # when using a tunnel, replace with e.g. https://xxxx.trycloudflare.com/v1
export LLM_API_KEY="dummy"
export LLM_MODEL="local"
./scripts/ask.sh "What is a quantized LLM?"
```

Verifying connectivity (health check):

```bash
LLM_BASE_URL="http://localhost:8000/v1" ./scripts/healthcheck.sh
```

## 8. Switching Between Backends (Profiles)

Using configuration files (profiles) in the `profiles/` directory,
`scripts/ask.sh` / `scripts/healthcheck.sh` can easily switch not only to this
repository's own Colab T4 server, but to any OpenAI-compatible backend such as
OpenAI, Groq, OpenRouter, Ollama, LM Studio, or vLLM. If no profile is
specified, everything keeps working with environment variables alone
(`LLM_BASE_URL`, etc.) for backward compatibility.

### Bundled profile templates

| Profile name   | Base URL                                 | API key environment variable |
|----------------|------------------------------------------|------------------------------|
| `colab-local`  | `http://localhost:8000/v1`               | (not needed, fixed `dummy`)  |
| `openai`       | `https://api.openai.com/v1`              | `OPENAI_API_KEY`             |
| `groq`         | `https://api.groq.com/openai/v1`         | `GROQ_API_KEY`               |
| `openrouter`   | `https://openrouter.ai/api/v1`           | `OPENROUTER_API_KEY`         |
| `ollama`       | `http://localhost:11434/v1`              | (not needed, fixed `dummy`)  |
| `lmstudio`     | `http://localhost:1234/v1`               | (not needed, fixed `dummy`)  |
| `vllm`         | `http://localhost:8000/v1`               | (set as your setup requires) |

For vLLM and other OpenAI-compatible servers, just copy a bundled template and
change `LLM_BASE_URL` / `LLM_MODEL`.

### Setup example (OpenAI)

```bash
cp profiles/openai.env.example profiles/openai.env
export OPENAI_API_KEY="sk-..."   # keep the key itself only in your shell environment
./scripts/ask.sh -p openai "Hello"
```

`profiles/*.env` is excluded by `.gitignore`, so concrete profile files cannot
be committed by accident. See [`profiles/README.md`](profiles/README.md) for
details.

The `LLM_PROFILE` environment variable works the same way (the `-p`/`--profile`
flag takes precedence):

```bash
LLM_PROFILE=groq ./scripts/ask.sh "What is a quantized LLM?"
```

`scripts/healthcheck.sh` supports the same `-p`/`--profile` and `LLM_PROFILE`:

```bash
./scripts/healthcheck.sh -p ollama
```

### Model, system prompt, and generation parameters

```bash
# Override the model and system prompt
./scripts/ask.sh -m gpt-4o-mini -s "You are an assistant that answers concisely." "What is 1+1?"

# temperature / max_tokens via environment variables (not sent when unset)
LLM_TEMPERATURE=0.2 LLM_MAX_TOKENS=100 ./scripts/ask.sh "What is a quantized LLM?"

# Print an SSE streaming response incrementally
./scripts/ask.sh --stream "Introduce yourself briefly."
```

| Option / variable   | Description                                                        |
|---------------------|--------------------------------------------------------------------|
| `-p`, `--profile`   | Load `profiles/NAME.env` to switch backends                        |
| `-m`, `--model`     | Override the `model` field (always highest precedence)             |
| `-s`, `--system`    | Set the system prompt (always highest precedence, overrides `LLM_SYSTEM_PROMPT`) |
| `--stream`          | Send `stream: true` and print SSE `delta.content` as it arrives    |
| `LLM_PROFILE`       | Profile name used when `--profile` is not given                    |
| `LLM_SYSTEM_PROMPT` | Content of the system message                                      |
| `LLM_TEMPERATURE`   | `temperature` field (not sent when unset)                          |
| `LLM_MAX_TOKENS`    | `max_tokens` field (not sent when unset)                           |

**Notes on precedence:**

- Profile resolution: `-p`/`--profile` flag > `LLM_PROFILE` environment
  variable > none.
- When a profile is loaded, the values inside the profile file
  (`LLM_BASE_URL`/`LLM_MODEL`/`LLM_API_KEY`, etc.) take precedence over
  environment variables exported beforehand (the file is sourced over them).
- The `-m`/`-s` flags, however, always take precedence over profile values.

Frequently asked questions about creating and choosing profiles are collected
in [`docs/faq.md`](docs/faq.md).

## 9. OpenAI-Compatible Proxy for Other Apps (Gateway)

With `scripts/openai_proxy.py` (and its thin wrapper `scripts/serve_proxy.sh`),
you can run a local OpenAI-compatible endpoint and use this repository's
backends from any OpenAI-SDK-compatible app (chat UIs, editor extensions, your
own apps, etc.) — not just `scripts/ask.sh`. The proxy relays requests to the
backend selected by a profile and injects the real API key internally, so the
client app never needs the key. It is implemented with the standard library
only; no extra pip installs are required.

### Architecture diagram

```
Other apps (OpenAI SDK, etc.)      Local proxy                         Selected backend
+----------------------+        +---------------------------+        +---------------------------+
|                      |  HTTP  |                           |  HTTP  |                           |
| Any OpenAI SDK       | -----> | scripts/openai_proxy.py   | -----> | Colab / OpenAI / Groq /   |
| client app           |        | http://127.0.0.1:8765/v1  |        | Ollama ... (per profile)  |
|                      |        | (injects the API key)     |        |                           |
+----------------------+        +---------------------------+        +---------------------------+
```

### Starting the proxy

```bash
./scripts/serve_proxy.sh -p groq
PROXY_PORT=9000 ./scripts/serve_proxy.sh -p colab-local
```

### Client-side configuration examples

Python (OpenAI SDK):

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="dummy")
resp = client.chat.completions.create(
    model="local",
    messages=[{"role": "user", "content": "Hello"}],
)
print(resp.choices[0].message.content)
```

curl:

```bash
curl http://127.0.0.1:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "local", "messages": [{"role": "user", "content": "Hello"}]}'
```

A more detailed example ([`examples/proxy_example.sh`](examples/proxy_example.sh)):

```bash
./examples/proxy_example.sh          # only prints usage
RUN_LIVE=1 ./examples/proxy_example.sh -p colab-local   # actually starts it and verifies
```

### Streaming (SSE)

The proxy forwards upstream data as soon as it can be read with `read1()`, so
when the backend streams a response via SSE (Server-Sent Events), chunks are
relayed to the client in real time as-is.

curl:

```bash
curl -N http://127.0.0.1:8765/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model": "local", "stream": true, "messages": [{"role": "user", "content": "Hello"}]}'
```

Python (OpenAI SDK, `stream=True`):

```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="dummy")
stream = client.chat.completions.create(
    model="local",
    messages=[{"role": "user", "content": "Hello"}],
    stream=True,
)
for chunk in stream:
    delta = chunk.choices[0].delta.content
    if delta:
        print(delta, end="", flush=True)
```

### Options

| Environment variable | Default             | Description                                                     |
|----------------------|---------------------|-----------------------------------------------------------------|
| `PROXY_PORT`         | `8765`              | Port the proxy listens on (also settable via `--port`)          |
| `PROXY_HOST`         | `127.0.0.1`         | Host the proxy listens on (also settable via `--host`)          |
| `PROXY_API_KEY`      | (empty = no auth)   | API key required from client apps (checked via `Authorization: Bearer`) |
| `PROXY_FORCE_MODEL`  | `0`                 | When `1`, always overwrite the request's `model` with the profile's `LLM_MODEL` |
| `PROXY_ALLOW_CORS`   | `0`                 | When `1`, add CORS headers so browser-based apps can connect    |

### Security

- By default the proxy listens on `127.0.0.1` only, so only apps on the same
  machine can reach it.
- Changing `PROXY_HOST` to `0.0.0.0` or similar exposes it to the LAN. In that
  case, setting `PROXY_API_KEY` is strongly recommended (without it, anyone on
  the network can send requests using your backend API key).
- The backend's real API key (`LLM_API_KEY`) is used only inside the proxy and
  is never passed to client apps.

## 10. Changing the Model

Switching to another GGUF model only requires changing `HF_REPO_ID` /
`HF_FILENAME` (and `MODEL_PATH` if needed) and re-running
`scripts/download_model.py`.

```bash
export HF_REPO_ID="bartowski/Llama-3.2-1B-Instruct-GGUF"
export HF_FILENAME="Llama-3.2-1B-Instruct-Q4_K_M.gguf"
python3 scripts/download_model.py

export MODEL_PATH="models/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
python3 colab/start_llm_server.py
```

Larger models such as the Qwen2.5-3B family work the same way — just switch
`HF_REPO_ID`/`HF_FILENAME` (watch your VRAM budget).

## 11. Troubleshooting

For questions not covered here, also see [`docs/faq.md`](docs/faq.md).

### CI / tests

GitHub Actions runs `bash -n`, `python3 -m compileall`, `shellcheck`, Markdown
link validation, and functional tests against a fake OpenAI-compatible backend
on every PR. To run the main functional tests locally:

```bash
bash tests/run_tests.sh
```

### CUDA / GPU not visible

- Check that a GPU (T4) is selected under Colab's "Change runtime type".
- If `nvidia-smi` fails, the runtime is not connected to a GPU.
- If `llama-cpp-python` was built CPU-only, re-run `scripts/setup_colab.sh`
  with `INSTALL_CUDA_LLAMA=1` to reinstall the CUDA-enabled build.

```bash
INSTALL_CUDA_LLAMA=1 bash scripts/setup_colab.sh
```

### Model too large / OOM (out of memory)

- Use a smaller quantization (e.g. Q4_K_M → Q3_K_M) or a model with fewer parameters.
- Lower `N_CTX` (context length) to reduce memory usage.
- Reduce `N_GPU_LAYERS` to offload some layers to the CPU and save VRAM.

### Cannot connect to the port

- Check that the server is up with `scripts/healthcheck.sh`.
- Check that the server itself is running on the Colab runtime
  (look at the output of `scripts/start_server.sh`).
- When using a tunnel, check that the tunnel URL has not changed.
- Check that `LLM_BASE_URL` ends with `/v1`.

### Colab session disconnected

- Reconnect the runtime and re-run `scripts/start_server.sh`.
- If the runtime was reset, downloaded models may also be gone, in which case
  you may need to re-download them with `scripts/download_model.py`.

## 12. Security Notes

- Public URLs issued by tunnels (`cloudflared`/`ngrok`, etc.) can potentially
  be accessed by anyone who knows them. Consider authentication and short-lived
  URLs, and stop the tunnel promptly when you are done.
- Never commit API keys or Hugging Face tokens, even when written in `.env`
  (`.env` is already excluded via `.gitignore`).
- The default `LLM_API_KEY` value `dummy` is only a placeholder for
  OpenAI-compatible clients, not an actual authentication mechanism. Provide
  separate access control when using this in a public environment.
- Concrete profile files (`profiles/*.env`) are also excluded via
  `.gitignore`, but for cloud API keys (OpenAI/Groq/OpenRouter, etc.) we
  recommend the `LLM_API_KEY_ENV` approach, which avoids writing keys to files
  entirely (only the environment variable name goes into the profile; the key
  itself stays in your shell environment). See
  [`profiles/README.md`](profiles/README.md) for details.
- If you expose `scripts/openai_proxy.py` (the proxy/gateway), changing the
  default `PROXY_HOST=127.0.0.1` to `0.0.0.0` or similar makes it reachable
  from the LAN, so always set `PROXY_API_KEY`. Left unset while exposed to the
  LAN, anyone on the same network can send requests using your backend API key.

### About the Google Colab Terms of Service

- This tool starts an LLM server on Google Colab, and your use of Colab is
  subject to the
  [Google Colab Terms of Service](https://research.google.com/colaboratory/faq.html).
  In particular, on the free tier, long-running always-on workloads and
  continuously serving remote clients may fall under its restrictions.
- Please stay within the Colab Terms of Service — use it for interactive
  experimentation and development, and stop the runtime when you are done. If
  you want to run a server for long or sustained periods, consider a paid plan
  such as Colab Pro, or your own GPU machine or a cloud VM (the profile
  feature lets you switch to backends such as `vllm`/`ollama`).

## 13. Repository Layout

```
.
├── README.md                     # This file (English)
├── README.ja.md                  # Japanese version
├── requirements.txt              # Python dependencies
├── .gitignore                    # Files/directories excluded from Git
├── scripts/
│   ├── lib/
│   │   └── common.sh             # Shared library for profile loading, etc. (source-only)
│   ├── setup_colab.sh            # Dependency setup on the Colab runtime
│   ├── download_model.py         # Download GGUF models from the Hugging Face Hub
│   ├── start_server.sh           # Setup → model download → server start, in one shot
│   ├── healthcheck.sh            # Server connectivity check (supports -p/--profile)
│   ├── ask.sh                    # CLI script to send questions (supports -p/-m/-s)
│   ├── openai_proxy.py           # OpenAI-compatible proxy/gateway for other apps
│   └── serve_proxy.sh            # Thin wrapper that starts openai_proxy.py
├── colab/
│   ├── start_llm_server.py       # Startup wrapper for the llama-cpp-python server
│   ├── dashboard.py              # Dashboard core logic (ServerManager, etc.)
│   ├── dashboard_ui.py           # Dashboard GUI layer (ipywidgets)
│   └── dashboard.ipynb           # Notebook that opens the dashboard on Colab
├── profiles/
│   ├── README.md                 # Description of the profile feature
│   ├── colab-local.env.example   # Template for the Colab local server
│   ├── openai.env.example        # Template for OpenAI
│   ├── groq.env.example          # Template for Groq
│   ├── openrouter.env.example    # Template for OpenRouter
│   ├── ollama.env.example        # Template for Ollama
│   ├── lmstudio.env.example      # Template for LM Studio
│   └── vllm.env.example          # Template for vLLM
├── examples/
│   ├── README.md                 # List and usage of example scripts
│   ├── ask_example.sh            # Basic usage example of ask.sh
│   ├── ask_multi_backend.sh      # Profile-switching example of ask.sh
│   └── proxy_example.sh          # Usage example of openai_proxy.py (proxy)
├── docs/
│   ├── architecture.md           # Architecture, request flow, config precedence
│   └── faq.md                    # Frequently asked questions
├── tests/
│   ├── run_tests.sh              # Functional tests using the fake backend
│   ├── fake_openai_backend.py    # OpenAI-compatible backend for tests
│   ├── check_sse_timing.py       # SSE relay timing verification
│   ├── check_readme_links.py     # Markdown link/anchor validation
│   └── test_dashboard.py         # Unit tests for the dashboard (dashboard.py)
├── .github/
│   └── workflows/
│       └── ci.yml                # GitHub Actions CI
└── LICENSE                       # MIT License
```

## 14. License

This repository is released under the MIT License. See the
[`LICENSE`](LICENSE) file for details.
