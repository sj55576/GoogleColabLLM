#!/usr/bin/env bash
# このファイルはsourceして使う (直接実行しない)。
#
# scripts/ask.sh や scripts/healthcheck.sh から共通利用する、
# プロファイル (profiles/*.env) 読み込み用のライブラリ。
#
# 呼び出し側で `set -euo pipefail` 済みであることを前提とし、
# このファイル自体では set しない (source先の設定を尊重するため)。

# ライブラリ自身のパスから REPO_ROOT (リポジトリのルート) を計算する。
# scripts/lib/common.sh から見て2階層上がリポジトリルート。
_COMMON_SH_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMMON_SH_REPO_ROOT="$(cd "$_COMMON_SH_LIB_DIR/../.." && pwd)"

# load_profile <name>
#   profiles/<name>.env を読み込み、中の KEY=value 行を環境変数としてexportする。
#   LLM_API_KEY_ENV が設定されていれば、それが指す環境変数からAPIキーを
#   LLM_API_KEY に解決する。
#
# 戻り値:
#   0: 成功
#   1: プロファイルファイルが存在しない / APIキー用の環境変数が未設定
load_profile() {
    local name="$1"
    local profile_file="$COMMON_SH_REPO_ROOT/profiles/${name}.env"

    if [[ ! -f "$profile_file" ]]; then
        echo "エラー: プロファイル '$name' が見つかりません ($profile_file)。" >&2
        echo "" >&2
        echo "利用可能なプロファイル (実体 *.env):" >&2
        local found=0
        local f
        for f in "$COMMON_SH_REPO_ROOT"/profiles/*.env; do
            if [[ -f "$f" ]]; then
                echo "  - $(basename "$f" .env)" >&2
                found=1
            fi
        done
        if [[ "$found" -eq 0 ]]; then
            echo "  (なし)" >&2
        fi
        echo "" >&2
        echo "まだ設定していない場合は、profiles/*.env.example を profiles/<名前>.env に" >&2
        echo "コピーしてから編集してください。例:" >&2
        echo "  cp profiles/${name}.env.example profiles/${name}.env" >&2
        return 1
    fi

    # KEY=value 行をそのままexportするため、set -a / set +a で囲んでsourceする。
    set -a
    # shellcheck disable=SC1090
    source "$profile_file"
    set +a

    # LLM_API_KEY_ENV (実際のキーを保持する別の環境変数名) が指定されていれば解決する。
    if [[ -n "${LLM_API_KEY_ENV:-}" ]]; then
        local resolved_key="${!LLM_API_KEY_ENV:-}"
        if [[ -z "$resolved_key" ]]; then
            echo "エラー: 環境変数 $LLM_API_KEY_ENV が設定されていません。" >&2
            echo "プロファイル '$name' はAPIキーを $LLM_API_KEY_ENV から取得する設定になっています。" >&2
            echo "実行前に以下のようにexportしてください:" >&2
            echo "  export $LLM_API_KEY_ENV=\"sk-...\"" >&2
            return 1
        fi
        LLM_API_KEY="$resolved_key"
        export LLM_API_KEY
    fi

    return 0
}
