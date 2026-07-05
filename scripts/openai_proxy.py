#!/usr/bin/env python3
"""
他のアプリ (任意のOpenAI SDK対応クライアント) 向けの、ローカルOpenAI互換
ゲートウェイ/プロキシサーバー。

概要:
    このプロキシは `http://<host>:<port>/v1` でOpenAI互換のHTTPエンドポイントを
    立て、受信したリクエストを `profiles/<name>.env` (または環境変数) で選んだ
    実際のバックエンド (Colabローカルサーバー・OpenAI・Groq・Ollama等) へ
    そのまま中継します。バックエンドの実APIキーはプロキシ内部で注入するため、
    プロキシを利用するクライアントアプリ側はキーを一切知る必要がありません。

    標準ライブラリのみで実装されており (http.server / urllib.request 等)、
    pipインストールは不要です。

使い方:
    ./scripts/serve_proxy.sh -p groq
    ./scripts/openai_proxy.py --profile openai --port 9000

    起動後、他のアプリからは以下のように接続します (例: Python OpenAI SDK):
        from openai import OpenAI
        client = OpenAI(base_url="http://127.0.0.1:8765/v1", api_key="dummy")

コマンドライン引数:
    -p, --profile NAME   profiles/NAME.env を読み込んでバックエンドを切り替える
    --port PORT          プロキシが待ち受けるポート番号
    --host HOST          プロキシが待ち受けるホスト
    -h, --help           ヘルプ表示 (argparse既定)

環境変数 (コマンドライン引数の方が優先されます):
    LLM_PROFILE       : --profile を指定しなかった場合に使うプロファイル名
    PROXY_PORT        : プロキシの待ち受けポート (既定: 8765)
    PROXY_HOST        : プロキシの待ち受けホスト (既定: 127.0.0.1)
    PROXY_API_KEY     : クライアントアプリに要求するAPIキー (既定: 空 = 認証なし)
    PROXY_FORCE_MODEL : 1にすると、リクエストボディのmodelを常にLLM_MODELへ上書き (既定: 0)
    PROXY_ALLOW_CORS  : 1にするとCORSヘッダーを付与しOPTIONSに応答 (既定: 0)
    LLM_BASE_URL      : 中継先バックエンドのベースURL (既定: http://localhost:8000/v1)
    LLM_API_KEY       : バックエンドへ送るAPIキー (既定: dummy)
    LLM_MODEL         : PROXY_FORCE_MODEL=1のときmodelに強制する値 (既定: local)
    LLM_API_KEY_ENV   : 実際のキーを保持する環境変数名 (指定時はそちらを優先解決)

優先順位 (scripts/ask.sh と同じ考え方):
    1. プロファイル (profiles/<name>.env) の値
    2. 実行前にexportしていた環境変数
    (プロファイルを読み込んだ場合、プロファイル内の値が環境変数を上書きします)
    ただし --profile/--port/--host のコマンドライン引数は常に最優先です。
"""

import argparse
import hmac
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

# scripts/openai_proxy.py から見て1階層上がリポジトリルート
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args(argv=None):
    """コマンドライン引数をパースする。"""
    parser = argparse.ArgumentParser(
        description=(
            "他のアプリ向けのローカルOpenAI互換プロキシ/ゲートウェイを起動します。"
            "プロファイルで選んだバックエンドへリクエストを中継し、"
            "実際のAPIキーを内部で注入します。"
        )
    )
    parser.add_argument(
        "-p", "--profile",
        default=None,
        help="profiles/NAME.env を読み込んでバックエンドを切り替える",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="プロキシが待ち受けるポート番号 (既定: 環境変数PROXY_PORTまたは8765)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="プロキシが待ち受けるホスト (既定: 環境変数PROXY_HOSTまたは127.0.0.1)",
    )
    return parser.parse_args(argv)


def load_profile(name):
    """
    profiles/<name>.env を読み込み、KEY=value の辞書として返す。

    scripts/lib/common.sh の load_profile と同じ意味論を持つ:
    - 空行・#コメントはスキップ
    - 最初の '=' で分割
    - 値を囲むシングル/ダブルクォートは取り除く
    - 未知のキーもそのまま保持する

    ファイルが存在しない場合は、利用可能なプロファイル一覧を含む日本語エラーを
    表示して終了する。
    """
    profile_file = os.path.join(REPO_ROOT, "profiles", f"{name}.env")

    if not os.path.isfile(profile_file):
        print(f"エラー: プロファイル '{name}' が見つかりません ({profile_file})。", file=sys.stderr)
        print("", file=sys.stderr)
        print("利用可能なプロファイル (実体 *.env):", file=sys.stderr)
        profiles_dir = os.path.join(REPO_ROOT, "profiles")
        found = []
        if os.path.isdir(profiles_dir):
            for fname in sorted(os.listdir(profiles_dir)):
                if fname.endswith(".env"):
                    found.append(fname[: -len(".env")])
        if found:
            for pname in found:
                print(f"  - {pname}", file=sys.stderr)
        else:
            print("  (なし)", file=sys.stderr)
        print("", file=sys.stderr)
        print("まだ設定していない場合は、profiles/*.env.example を profiles/<名前>.env に", file=sys.stderr)
        print("コピーしてから編集してください。例:", file=sys.stderr)
        print(f"  cp profiles/{name}.env.example profiles/{name}.env", file=sys.stderr)
        sys.exit(1)

    values = {}
    with open(profile_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            values[key] = value

    return values


def build_config(args):
    """
    コマンドライン引数・環境変数・プロファイルの値をまとめ、プロキシの動作設定を
    表す辞書 (config) を組み立てる。

    優先順位: プロファイルの値 > 事前にexportされた環境変数。
    ただし --profile/--port/--host のコマンドライン引数は最優先。
    """
    profile_name = args.profile if args.profile is not None else os.environ.get("LLM_PROFILE", "")

    # まずは環境変数をベースにする (プロファイル未指定時のフォールバック)
    env = dict(os.environ)

    if profile_name:
        profile_values = load_profile(profile_name)
        # プロファイルの値が環境変数を上書きする (ask.sh と同じ優先順位)
        env.update(profile_values)

    if profile_name and "LLM_API_KEY_ENV" in env and env["LLM_API_KEY_ENV"]:
        key_env_name = env["LLM_API_KEY_ENV"]
        resolved_key = os.environ.get(key_env_name, "")
        if not resolved_key:
            print(f"エラー: 環境変数 {key_env_name} が設定されていません。", file=sys.stderr)
            print(f"プロファイル '{profile_name}' はAPIキーを {key_env_name} から取得する設定になっています。", file=sys.stderr)
            print("実行前に以下のようにexportしてください:", file=sys.stderr)
            print(f'  export {key_env_name}="sk-..."', file=sys.stderr)
            sys.exit(1)
        env["LLM_API_KEY"] = resolved_key

    def env_bool(name, default="0"):
        return env.get(name, default).strip() == "1"

    config = {
        "profile_name": profile_name,
        "backend_base_url": env.get("LLM_BASE_URL", "http://localhost:8000/v1").rstrip("/"),
        "backend_api_key": env.get("LLM_API_KEY", "dummy"),
        "backend_model": env.get("LLM_MODEL", "local"),
        "force_model": env_bool("PROXY_FORCE_MODEL"),
        "allow_cors": env_bool("PROXY_ALLOW_CORS"),
        "proxy_api_key": env.get("PROXY_API_KEY", ""),
        "host": args.host if args.host is not None else env.get("PROXY_HOST", "127.0.0.1"),
        "port": args.port if args.port is not None else int(env.get("PROXY_PORT", "8765")),
    }
    return config


def _openai_error_body(message, error_type="invalid_request_error"):
    """OpenAI形式のエラーレスポンスボディ(bytes)を組み立てる。"""
    payload = {"error": {"message": message, "type": error_type}}
    return json.dumps(payload).encode("utf-8")


def make_handler(config):
    """
    設定(config)を閉じ込めた BaseHTTPRequestHandler サブクラスを生成する
    (クラスファクトリ)。
    """

    class ProxyHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"
        server_version = "OpenAIProxy/1.0"

        # --- ログ ---
        def log_message(self, format, *args):
            # ヘッダーやボディは絶対に出力しない (APIキー漏洩防止)。
            try:
                status = args[1] if len(args) > 1 else "?"
            except Exception:
                status = "?"
            sys.stderr.write(
                f"[proxy] {self.command} {self.path} -> {status}\n"
            )

        # --- CORS共通処理 ---
        def _add_cors_headers(self):
            if config["allow_cors"]:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, PATCH, DELETE, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")

        def _send_json_error(self, status, message, error_type="invalid_request_error"):
            body = _openai_error_body(message, error_type)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._add_cors_headers()
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _check_auth(self):
            """PROXY_API_KEY が設定されている場合、クライアントの認証を確認する。"""
            required = config["proxy_api_key"]
            if not required:
                return True
            auth_header = self.headers.get("Authorization", "")
            expected = f"Bearer {required}"
            # タイミング攻撃を避けるため定数時間比較を使う
            if not hmac.compare_digest(auth_header, expected):
                self._send_json_error(
                    401,
                    "認証に失敗しました。Authorization: Bearer <PROXY_API_KEY> ヘッダーを指定してください。",
                    "authentication_error",
                )
                return False
            return True

        # --- ルーティング ---
        def do_GET(self):
            self._route()

        def do_POST(self):
            self._route()

        def do_PUT(self):
            self._route()

        def do_PATCH(self):
            self._route()

        def do_DELETE(self):
            self._route()

        def do_OPTIONS(self):
            if config["allow_cors"]:
                self.send_response(204)
                self._add_cors_headers()
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self._send_json_error(404, "Not Found")

        def _route(self):
            if self.path == "/healthz" or self.path.startswith("/healthz?"):
                self._handle_healthz()
                return

            if self.path.startswith("/v1/"):
                if not self._check_auth():
                    return
                self._handle_proxy()
                return

            self._send_json_error(
                404,
                f"不明なエンドポイントです: {self.path} (/v1/... または /healthz を利用してください)",
            )

        def _handle_healthz(self):
            body = json.dumps(
                {
                    "status": "ok",
                    "backend": config["backend_base_url"],
                    "force_model": config["force_model"],
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._add_cors_headers()
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def _read_body(self):
            length_header = self.headers.get("Content-Length")
            if not length_header:
                return b""
            try:
                length = int(length_header)
            except ValueError:
                return b""
            if length <= 0:
                return b""
            return self.rfile.read(length)

        def _build_target_url(self):
            """
            LLM_BASE_URL と、受信した /v1/... パスから中継先URLを組み立てる。

            base = LLM_BASE_URL.rstrip('/')
            base が /v1 で終わっていればそれを取り除く
            target = base + 受信した完全なパス (/v1/... から始まる)

            例:
                LLM_BASE_URL=http://localhost:8000/v1
                incoming path=/v1/chat/completions
                -> base(strip後)=http://localhost:8000
                -> target=http://localhost:8000/v1/chat/completions

                LLM_BASE_URL=https://api.groq.com/openai/v1
                incoming path=/v1/chat/completions
                -> base(strip後)=https://api.groq.com/openai
                -> target=https://api.groq.com/openai/v1/chat/completions
            """
            base = config["backend_base_url"]
            if base.endswith("/v1"):
                base = base[: -len("/v1")]
            return base + self.path

        def _handle_proxy(self):
            target_url = self._build_target_url()
            body = self._read_body()

            if (
                self.command in ("POST", "PUT", "PATCH")
                and config["force_model"]
                and body
            ):
                try:
                    parsed = json.loads(body)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    parsed = None
                if isinstance(parsed, dict):
                    parsed["model"] = config["backend_model"]
                    body = json.dumps(parsed).encode("utf-8")

            headers = {
                "Content-Type": self.headers.get("Content-Type", "application/json"),
                "Authorization": f"Bearer {config['backend_api_key']}",
            }
            accept = self.headers.get("Accept")
            if accept:
                headers["Accept"] = accept

            req = urllib.request.Request(
                target_url,
                data=body if body else None,
                headers=headers,
                method=self.command,
            )

            try:
                with urllib.request.urlopen(req, timeout=600) as resp:
                    self._relay_response(resp)
            except urllib.error.HTTPError as exc:
                # バックエンドが返したエラー(OpenAI形式であることが多い)をそのまま中継する。
                error_body = exc.read()
                self.send_response(exc.code)
                content_type = exc.headers.get("Content-Type", "application/json") if exc.headers else "application/json"
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(error_body)))
                self._add_cors_headers()
                self.end_headers()
                try:
                    self.wfile.write(error_body)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as exc:
                target_host = urlsplit(target_url).netloc
                message = (
                    f"バックエンド ({target_host}) に接続できませんでした。"
                    "LLM_BASE_URL・トンネル・バックエンドサーバーの起動状態を確認してください。"
                    f" (詳細: {exc})"
                )
                self._send_json_error(502, message, "api_connection_error")

        def _relay_response(self, resp):
            """アップストリームの応答を、ストリーミングも含めてそのままクライアントへ中継する。"""
            status = resp.status if hasattr(resp, "status") else resp.getcode()
            self.send_response(status)
            content_type = resp.headers.get("Content-Type", "application/json")
            self.send_header("Content-Type", content_type)
            for extra_header in ("Cache-Control", "x-request-id"):
                value = resp.headers.get(extra_header)
                if value:
                    self.send_header(extra_header, value)
            self._add_cors_headers()
            self.end_headers()

            try:
                while True:
                    # read() は8192バイト溜まるまでブロックし得るため、
                    # SSEをリアルタイム中継できるよう read1() で
                    # 「今読める分だけ」を即座に取得して転送する。
                    chunk = resp.read1(8192)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    return ProxyHandler


def _print_banner(config):
    """起動時のバナー(日本語)を表示する。"""
    profile_display = config["profile_name"] if config["profile_name"] else "なし(環境変数)"
    print("=" * 60)
    print("OpenAI互換プロキシ (ゲートウェイ) を起動します")
    print(f"  プロファイル       : {profile_display}")
    print(f"  中継先バックエンド : {config['backend_base_url']}")
    print(f"  待ち受け          : http://{config['host']}:{config['port']}/v1")
    print(f"  PROXY_FORCE_MODEL : {'有効 (' + config['backend_model'] + 'へ強制)' if config['force_model'] else '無効'}")
    print(f"  クライアント認証   : {'有効' if config['proxy_api_key'] else '無効 (誰でもアクセス可能)'}")
    print(f"  CORS              : {'有効' if config['allow_cors'] else '無効'}")
    print("-" * 60)
    example_key = config["proxy_api_key"] if config["proxy_api_key"] else "任意の値 (例: dummy)"
    print("他のアプリからは以下を指定してください:")
    print(f"  base_url = http://{config['host']}:{config['port']}/v1")
    print(f"  api_key  = {example_key}")
    print("-" * 60)
    if config["host"] not in ("127.0.0.1", "localhost"):
        print("警告: 127.0.0.1/localhost 以外にバインドしているため、LAN公開になります。")
        print("       PROXY_API_KEY の設定を強く推奨します。")
        print("-" * 60)
    print("Ctrl+C で終了します。")
    print("=" * 60)


def main():
    args = parse_args()
    config = build_config(args)
    _print_banner(config)

    handler_cls = make_handler(config)
    server = ThreadingHTTPServer((config["host"], config["port"]), handler_cls)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nプロキシを終了します。")
        server.server_close()
        sys.exit(0)


if __name__ == "__main__":
    main()
