#!/usr/bin/env python3
"""Colabノートブック上で使うダッシュボードのGUI層 (ipywidgets)。

`colab/dashboard.py` のコア関数・クラス (ServerManager, download_model,
send_chat, gpu_info など) をラップし、ノートブックのセルから

    import dashboard_ui
    dashboard_ui.show()

と呼ぶだけでLLMサーバーの操作 (モデル取得・起動/停止・監視・テスト送信) を
一通り行えるGUIを組み立てる。本モジュール自体はUIの組み立てとイベント処理のみを
担当し、実際の処理 (サーバー起動、ダウンロード、ヘルスチェック等) はすべて
`dashboard` モジュールに委譲する。

注意:
    - 本モジュールは Colab / Jupyter 環境で ipywidgets が使えることを前提にしている。
    - 時間のかかる処理 (モデルダウンロード・サーバー起動・チャット送信) は別スレッドで
      実行し、ノートブックのメインスレッド (カーネル) をブロックしないようにしている。
      ipywidgets のウィジェットは内部でcomm経由の非同期更新に対応しているため、
      バックグラウンドスレッドから value/disabled 等を更新しても問題ない。
"""
import sys
import threading
from pathlib import Path

# ipywidgets が無い環境向けに、分かりやすい日本語メッセージで案内する。
try:
    import ipywidgets as widgets
    from IPython.display import display
except ImportError as exc:  # pragma: no cover - 環境依存のため通常のテストでは踏まない
    raise ImportError(
        "ipywidgets が見つかりません。Colab / Jupyter 環境で "
        "ipywidgets をインストールしてください "
        "(例: `!pip install ipywidgets` を実行してからこのセルを再実行してください)。"
    ) from exc

# `colab.dashboard` としてのimportを優先し (パッケージ経由で実行された場合)、
# 失敗したら自ファイルの親ディレクトリをsys.pathへ追加したうえで
# 単体モジュールとして `dashboard` をimportする (Colabのセルから直接
# `import dashboard_ui` する使い方でも動くように)。
try:
    from colab.dashboard import DashboardError  # noqa: F401  (存在確認のみ)
    from colab import dashboard
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import dashboard  # type: ignore[import-not-found, no-redef]


# ダッシュボード全体で共有する ServerManager のシングルトン。
# (複数回 build_dashboard()/show() を呼んでも同じサーバープロセスを参照する)
_SERVER_MANAGER = dashboard.ServerManager()


# ---------------------------------------------------------------------------
# 共通ヘルパー
# ---------------------------------------------------------------------------

def _run_in_thread(func, *args, **kwargs) -> None:
    """時間のかかる処理を別スレッドで実行する (カーネルをブロックしないため)。"""
    thread = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
    thread.start()


def _report_exception(output: "widgets.Output", exc: Exception, context: str) -> None:
    """例外を日本語メッセージでOutputへ表示する (スタックトレースは生で出さない)。"""
    with output:
        if isinstance(exc, dashboard.DashboardError):
            print(f"エラー: {exc}")
        else:
            print(f"エラー: {context}中に想定外の問題が発生しました。")
            print(f"詳細: {exc!r}")


def _set_buttons_disabled(buttons, disabled: bool) -> None:
    for button in buttons:
        button.disabled = disabled


# ---------------------------------------------------------------------------
# 「モデル」タブ
# ---------------------------------------------------------------------------

def _build_model_tab() -> "tuple[widgets.Widget, widgets.Dropdown]":
    preset_labels = [preset["label"] for preset in dashboard.MODEL_PRESETS] + ["カスタム"]

    preset_dropdown = widgets.Dropdown(
        options=preset_labels,
        value=preset_labels[0],
        description="プリセット:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="480px"),
    )
    repo_id_text = widgets.Text(
        description="repo_id:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="480px"),
    )
    filename_text = widgets.Text(
        description="filename:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="480px"),
    )
    note_html = widgets.HTML(value="")
    hf_token_text = widgets.Password(
        description="HF_TOKEN:",
        placeholder="gated モデルのみ必要 (空欄可)",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="480px"),
    )

    def _apply_preset(label: str) -> None:
        if label == "カスタム":
            repo_id_text.disabled = False
            filename_text.disabled = False
            note_html.value = "<i>repo_id / filename を自由に入力してください。</i>"
            return
        preset = next((p for p in dashboard.MODEL_PRESETS if p["label"] == label), None)
        if preset is None:
            return
        repo_id_text.value = preset["repo_id"]
        filename_text.value = preset["filename"]
        repo_id_text.disabled = True
        filename_text.disabled = True
        note_html.value = f"<i>{preset.get('note', '')}</i>"

    def _on_preset_change(change) -> None:
        if change["name"] == "value":
            _apply_preset(change["new"])

    preset_dropdown.observe(_on_preset_change, names="value")
    _apply_preset(preset_dropdown.value)

    download_button = widgets.Button(
        description="モデルをダウンロード",
        button_style="primary",
        icon="download",
    )
    download_output = widgets.Output(layout=widgets.Layout(border="1px solid #ddd", padding="4px"))

    local_models_dropdown = widgets.Dropdown(
        options=[],
        description="ダウンロード済みモデル:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="560px"),
    )
    refresh_models_button = widgets.Button(description="一覧を更新", icon="refresh")

    def _refresh_local_models(_button=None) -> None:
        try:
            models = dashboard.list_local_models()
        except Exception as exc:  # noqa: BLE001 - Output側に日本語で要約表示するため広く捕捉
            _report_exception(download_output, exc, "モデル一覧の取得")
            return
        options = [str(path) for path in models]
        local_models_dropdown.options = options
        if options:
            local_models_dropdown.value = options[0]

    refresh_models_button.on_click(_refresh_local_models)
    _refresh_local_models()

    def _do_download() -> None:
        _set_buttons_disabled([download_button], True)
        original_description = download_button.description
        download_button.description = "ダウンロード中…"
        try:
            repo_id = repo_id_text.value.strip()
            filename = filename_text.value.strip()
            token = hf_token_text.value.strip() or None
            with download_output:
                download_output.clear_output()
                print(f"ダウンロード開始: {repo_id} / {filename}")
            result_path = dashboard.download_model(repo_id, filename, token=token)
            with download_output:
                print(f"完了しました: {result_path}")
            _refresh_local_models()
        except Exception as exc:  # noqa: BLE001 - ボタンハンドラの例外はすべてOutputへ表示する
            _report_exception(download_output, exc, "モデルのダウンロード")
        finally:
            download_button.description = original_description
            _set_buttons_disabled([download_button], False)

    def _on_download_click(_button) -> None:
        _run_in_thread(_do_download)

    download_button.on_click(_on_download_click)

    return widgets.VBox(
        [
            widgets.HTML("<h4>モデルの選択</h4>"),
            preset_dropdown,
            repo_id_text,
            filename_text,
            note_html,
            hf_token_text,
            download_button,
            download_output,
            widgets.HTML("<hr><h4>ダウンロード済みモデル (サーバー起動時に使用)</h4>"),
            widgets.HBox([local_models_dropdown, refresh_models_button]),
        ]
    ), local_models_dropdown


# ---------------------------------------------------------------------------
# 「サーバー設定」タブ
# ---------------------------------------------------------------------------

def _build_server_config_tab():
    port_int = widgets.IntText(
        value=8000,
        description="ポート:",
        style={"description_width": "initial"},
    )
    port_help = widgets.HTML(
        "<small>サーバーが待ち受けるポート番号 (環境変数 <code>LLM_PORT</code> 相当、既定: 8000)</small>"
    )

    n_ctx_dropdown = widgets.Dropdown(
        options=[2048, 4096, 8192, 16384],
        value=4096,
        description="N_CTX:",
        style={"description_width": "initial"},
    )
    n_ctx_help = widgets.HTML(
        "<small>コンテキスト長 (トークン数、環境変数 <code>N_CTX</code> 相当)。"
        "大きいほど長い会話を扱えるが、必要なメモリも増える。</small>"
    )

    n_gpu_layers_slider = widgets.IntSlider(
        value=-1,
        min=-1,
        max=48,
        step=1,
        description="N_GPU_LAYERS:",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="480px"),
    )
    n_gpu_layers_help = widgets.HTML(
        "<small>GPUにオフロードするレイヤー数 (環境変数 <code>N_GPU_LAYERS</code> 相当)。"
        "<b>-1 = 全レイヤーをGPUへ</b> (T4であれば通常はこのままでよい)。</small>"
    )

    box = widgets.VBox(
        [
            widgets.HTML("<h4>サーバー設定</h4>"),
            port_int,
            port_help,
            n_ctx_dropdown,
            n_ctx_help,
            n_gpu_layers_slider,
            n_gpu_layers_help,
        ]
    )
    return box, port_int, n_ctx_dropdown, n_gpu_layers_slider


# ---------------------------------------------------------------------------
# 「実行」タブ
# ---------------------------------------------------------------------------

_STATUS_RUNNING = '<span style="color:green;">●</span> 稼働中'
_STATUS_STOPPED = '<span style="color:gray;">●</span> 停止中'
_STATUS_STARTING = '<span style="color:#c9a227;">●</span> 起動中…'


def _build_run_tab(local_models_dropdown, port_int, n_ctx_dropdown, n_gpu_layers_slider):
    status_badge = widgets.HTML(value=_STATUS_STOPPED)
    run_output = widgets.Output(layout=widgets.Layout(border="1px solid #ddd", padding="4px"))

    start_button = widgets.Button(description="サーバー起動", button_style="success", icon="play")
    stop_button = widgets.Button(description="停止", button_style="danger", icon="stop")
    restart_button = widgets.Button(description="再起動", icon="refresh")
    refresh_status_button = widgets.Button(description="状態を更新", icon="sync")
    health_button = widgets.Button(description="ヘルスチェック", icon="heartbeat")

    all_buttons = [start_button, stop_button, restart_button, refresh_status_button, health_button]

    def _build_config() -> "dashboard.ServerConfig":
        if not local_models_dropdown.options:
            raise dashboard.DashboardError(
                "ダウンロード済みモデルがありません。先に「モデル」タブでモデルを取得してください。"
            )
        model_path = Path(local_models_dropdown.value)
        return dashboard.ServerConfig(
            model_path=model_path,
            port=int(port_int.value),
            n_ctx=int(n_ctx_dropdown.value),
            n_gpu_layers=int(n_gpu_layers_slider.value),
        )

    def _refresh_status(_button=None) -> None:
        try:
            running = _SERVER_MANAGER.is_running()
        except Exception as exc:  # noqa: BLE001
            _report_exception(run_output, exc, "状態の取得")
            return
        if running:
            status_badge.value = _STATUS_RUNNING
        else:
            status_badge.value = _STATUS_STOPPED

    def _do_start() -> None:
        _set_buttons_disabled(all_buttons, True)
        start_button.description = "起動中…"
        status_badge.value = _STATUS_STARTING
        try:
            config = _build_config()
            with run_output:
                run_output.clear_output()
                print(f"サーバーを起動しています: {config.model_path} (port={config.port})")
            _SERVER_MANAGER.start(config)
            healthy = _SERVER_MANAGER.wait_healthy()
            with run_output:
                if healthy:
                    print("サーバーの起動が完了し、ヘルスチェックに成功しました。")
                else:
                    print("サーバーは起動しましたが、ヘルスチェックがタイムアウトしました。")
                    print("「ログを更新」で詳細を確認してください。")
        except Exception as exc:  # noqa: BLE001
            _report_exception(run_output, exc, "サーバーの起動")
        finally:
            start_button.description = "サーバー起動"
            _set_buttons_disabled(all_buttons, False)
            _refresh_status()

    def _do_stop() -> None:
        _set_buttons_disabled(all_buttons, True)
        stop_button.description = "停止中…"
        try:
            with run_output:
                run_output.clear_output()
                print("サーバーを停止しています…")
            _SERVER_MANAGER.stop()
            with run_output:
                print("サーバーを停止しました。")
        except Exception as exc:  # noqa: BLE001
            _report_exception(run_output, exc, "サーバーの停止")
        finally:
            stop_button.description = "停止"
            _set_buttons_disabled(all_buttons, False)
            _refresh_status()

    def _do_restart() -> None:
        _set_buttons_disabled(all_buttons, True)
        restart_button.description = "再起動中…"
        status_badge.value = _STATUS_STARTING
        try:
            config = _build_config()
            with run_output:
                run_output.clear_output()
                print("サーバーを再起動しています…")
            _SERVER_MANAGER.stop()
            _SERVER_MANAGER.start(config)
            healthy = _SERVER_MANAGER.wait_healthy()
            with run_output:
                if healthy:
                    print("再起動が完了し、ヘルスチェックに成功しました。")
                else:
                    print("再起動しましたが、ヘルスチェックがタイムアウトしました。")
        except Exception as exc:  # noqa: BLE001
            _report_exception(run_output, exc, "サーバーの再起動")
        finally:
            restart_button.description = "再起動"
            _set_buttons_disabled(all_buttons, False)
            _refresh_status()

    def _do_health_check() -> None:
        _set_buttons_disabled(all_buttons, True)
        try:
            with run_output:
                run_output.clear_output()
                print("ヘルスチェックを実行しています…")
            result = dashboard.check_health(
                base_url=f"http://127.0.0.1:{int(port_int.value)}/v1"
            )
            with run_output:
                run_output.clear_output()
                print("OK" if result.get("ok") else "NG")
                print(f"詳細: {result.get('detail')}")
        except Exception as exc:  # noqa: BLE001
            _report_exception(run_output, exc, "ヘルスチェック")
        finally:
            _set_buttons_disabled(all_buttons, False)

    start_button.on_click(lambda _b: _run_in_thread(_do_start))
    stop_button.on_click(lambda _b: _run_in_thread(_do_stop))
    restart_button.on_click(lambda _b: _run_in_thread(_do_restart))
    refresh_status_button.on_click(_refresh_status)
    health_button.on_click(lambda _b: _run_in_thread(_do_health_check))

    _refresh_status()

    return widgets.VBox(
        [
            widgets.HTML("<h4>サーバーの実行</h4>"),
            widgets.HBox([widgets.HTML("<b>状態:</b>"), status_badge]),
            widgets.HBox([start_button, stop_button, restart_button, refresh_status_button, health_button]),
            run_output,
        ]
    )


# ---------------------------------------------------------------------------
# 「モニタ」タブ
# ---------------------------------------------------------------------------

def _build_monitor_tab():
    gpu_output = widgets.Output(layout=widgets.Layout(border="1px solid #ddd", padding="4px"))
    log_output = widgets.Output(layout=widgets.Layout(border="1px solid #ddd", padding="4px"))

    gpu_button = widgets.Button(description="GPU情報を更新", icon="tachometer")
    log_button = widgets.Button(description="ログを更新", icon="file-text")

    def _do_gpu_refresh(_button=None) -> None:
        try:
            info = dashboard.gpu_info()
        except Exception as exc:  # noqa: BLE001
            _report_exception(gpu_output, exc, "GPU情報の取得")
            return
        with gpu_output:
            gpu_output.clear_output()
            if info.get("available"):
                used = info.get("memory_used_mb")
                total = info.get("memory_total_mb")
                util = info.get("utilization_pct")
                print(f"GPU名        : {info.get('name')}")
                print(f"メモリ使用量 : {used} MB / {total} MB")
                print(f"使用率       : {util} %")
            else:
                print("GPUは利用できません。")
                print(f"詳細: {info.get('detail')}")

    def _do_log_refresh(_button=None) -> None:
        try:
            log_text = _SERVER_MANAGER.tail_log(80)
        except Exception as exc:  # noqa: BLE001
            _report_exception(log_output, exc, "ログの取得")
            return
        with log_output:
            log_output.clear_output()
            print(log_text if log_text.strip() else "(ログはまだありません)")

    gpu_button.on_click(_do_gpu_refresh)
    log_button.on_click(_do_log_refresh)

    return widgets.VBox(
        [
            widgets.HTML("<h4>GPU情報</h4>"),
            gpu_button,
            gpu_output,
            widgets.HTML("<hr><h4>サーバーログ (末尾80行)</h4>"),
            log_button,
            log_output,
        ]
    )


# ---------------------------------------------------------------------------
# 「テストチャット」タブ
# ---------------------------------------------------------------------------

def _build_chat_tab(port_int):
    system_text = widgets.Text(
        description="system:",
        placeholder="(任意) システムプロンプト",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="600px"),
    )
    prompt_textarea = widgets.Textarea(
        description="質問:",
        placeholder="ここに質問を入力してください",
        style={"description_width": "initial"},
        layout=widgets.Layout(width="600px", height="100px"),
    )
    temperature_slider = widgets.FloatSlider(
        value=0.7,
        min=0.0,
        max=2.0,
        step=0.05,
        description="temperature:",
        style={"description_width": "initial"},
    )
    max_tokens_int = widgets.IntText(
        value=512,
        description="max_tokens:",
        style={"description_width": "initial"},
    )
    send_button = widgets.Button(description="送信", button_style="primary", icon="paper-plane")
    chat_output = widgets.Output(layout=widgets.Layout(border="1px solid #ddd", padding="4px"))

    def _do_send() -> None:
        _set_buttons_disabled([send_button], True)
        original_description = send_button.description
        send_button.description = "送信中…"
        try:
            base_url = f"http://127.0.0.1:{int(port_int.value)}/v1"
            with chat_output:
                chat_output.clear_output()
                print("送信中…")
            reply = dashboard.send_chat(
                base_url=base_url,
                prompt=prompt_textarea.value,
                system=system_text.value or None,
                temperature=float(temperature_slider.value),
                max_tokens=int(max_tokens_int.value),
            )
            with chat_output:
                chat_output.clear_output()
                print(reply)
        except Exception as exc:  # noqa: BLE001
            _report_exception(chat_output, exc, "チャット送信")
        finally:
            send_button.description = original_description
            _set_buttons_disabled([send_button], False)

    send_button.on_click(lambda _b: _run_in_thread(_do_send))

    return widgets.VBox(
        [
            widgets.HTML("<h4>テストチャット</h4>"),
            system_text,
            prompt_textarea,
            temperature_slider,
            max_tokens_int,
            send_button,
            chat_output,
        ]
    )


# ---------------------------------------------------------------------------
# 組み立て・公開API
# ---------------------------------------------------------------------------

def build_dashboard() -> "widgets.Widget":
    """ダッシュボード全体のウィジェットを組み立てて返す (表示はしない)。"""
    model_tab, local_models_dropdown = _build_model_tab()
    server_config_tab, port_int, n_ctx_dropdown, n_gpu_layers_slider = _build_server_config_tab()
    run_tab = _build_run_tab(local_models_dropdown, port_int, n_ctx_dropdown, n_gpu_layers_slider)
    monitor_tab = _build_monitor_tab()
    chat_tab = _build_chat_tab(port_int)

    tab = widgets.Tab(children=[model_tab, server_config_tab, run_tab, monitor_tab, chat_tab])
    tab.set_title(0, "モデル")
    tab.set_title(1, "サーバー設定")
    tab.set_title(2, "実行")
    tab.set_title(3, "モニタ")
    tab.set_title(4, "テストチャット")

    return widgets.VBox([widgets.HTML("<h3>GCLLM ダッシュボード</h3>"), tab])


def show() -> None:
    """ダッシュボードを組み立ててノートブックのセルに表示する。"""
    display(build_dashboard())


if __name__ == "__main__":
    # ノートブック以外 (通常のPythonインタプリタ) から誤って実行された場合の案内。
    print("このモジュールはColab/Jupyterのノートブックセルから `dashboard_ui.show()` として"
          "使うことを想定しています。")
