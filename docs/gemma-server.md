# Gemma 4 12B Transformersサーバー

AlgoHintからGemma 4 12Bを使うための、専用推論サーバーの導入・運用手順です。
vLLM、TGI、Docker、root権限、公開ポートは必要ありません。任意のLinuxアカウントの
ホーム配下へ、uv、PyTorch、Hugging Face Transformersで構築します。

AlgoHint本体とモデル推論を別プロセスにするのは、約12Bパラメータのモデル依存と
GPU資源をUIから分離し、障害時にもRuleBasedヒントへ安全に退避できるようにするためです。
FastAPIがJSON APIを担当し、モデルにはJSON生成を要求しません。

## 検証対象

現在の固定構成は次のとおりです。

| 項目 | 値 |
|---|---|
| 接続先 | `ALGOHINT_SSH_TARGET`で指定するSSH設定名 |
| 実行ユーザー | SSH接続先のログインユーザー |
| Python | 3.10以上 |
| uv | `0.11.25`以上 |
| GPU | NVIDIA RTX A4000 16 GiB × 3 |
| モデル | `google/gemma-4-12B-it` |
| revision | `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7` |
| 待受 | `127.0.0.1:18080` |
| WSL側トンネル | `127.0.0.1:18000` |

モデルIDとrevisionはHugging Faceの公式Gemma 4 12B instruction-tunedチェックポイントに固定します。
movingな`main`を直接使わず、再起動時に重みや設定が無断で変わることを防ぎます。

## API境界

サーバーは次の最小APIだけを公開します。OpenAPI、Swagger UI、任意の生成パラメータは
公開しません。

| パス | 認証 | 用途 | 応答本文上限 |
|---|---|---|---|
| `/healthz` | 不要 | 生存・モデル準備状態 | 固定 |
| `/v1/models` | Bearer必須 | `algohint doctor` のモデル確認 | 固定 |
| `/v1/hints` | Bearer必須 | 段階的ヒント生成 | 1,200文字 |
| `/v1/reviews` | Bearer必須 | 完了後コードレビューのJSON生成 | 4,000文字 |
| `/v1/quizzes` | Bearer必須 | ACコード別小テストのJSON生成 | 8,000文字 |

3つの生成APIは、モデルID、システム指示、JSON化済み学習者コンテキスト
だけを受け取ります。本文全体はサーバー設定のサイズ上限、各フィールドはPydanticの長さ
上限で拒否します。全エンドポイントは同じ単一生成ロックを共有し、同時要求には429を返します。

ログはrequest ID、モデル、所要時間、安全な例外クラスだけを記録します。Authorization、
システム指示、学習者コンテキスト、提出コード、モデル生出力は記録しません。
レビューとAI小テストのJSONはAlgoHint本体でも共通スキーマと安全ポリシーを
再検証してから表示・保存します。

運用状態は`$ALGOHINT_GEMMA_STATUS_FILE`へ原子的に保存します。状態名は`starting`、
`loading_processor`、`loading_model`、`ready`、`generating_hint`、
`generating_review`、`generating_quiz`、`ready_with_last_error`、`stopping`、
`stopped`、`failed`のいずれかです。更新日時、PID、モデルID、revision、安全な要求種別、
経過時間、例外クラス以外は保存しません。プロンプト、コード、生成本文、認証値は状態JSONへ
渡せないインターフェースにしています。

## ホーム配下の構造

```text
$HOME/
├── .config/algohint-gemma-server/
│   └── credentials               # 600、Git管理外
└── programs/algohint-gemma-server/
    ├── current -> releases/<commit>
    ├── releases/<commit>/         # Gitコミット単位のサーバーコード
    ├── .venv/                     # 共通のuv環境
    ├── cache/
    │   ├── huggingface/
    │   └── uv/
    ├── runtime/offload/           # GPUから退避する重み
    └── state/                     # ログなどの運用状態
```

`releases`と`current`を分けるのは、コード更新に失敗しても旧リリースへsymlinkを
戻せるようにするためです。モデルキャッシュと仮想環境はリリース間で共有します。

## 初回配置

WSL側のAlgoHintリポジトリで、現在コミットのサーバーだけをアーカイブします。

```bash
project_root="$(git rev-parse --show-toplevel)"
cd "$project_root"
release_id="$(git rev-parse --short=12 HEAD)"
git archive --format=tar.gz \
  --output="/tmp/algohint-gemma-server-${release_id}.tar.gz" \
  HEAD:services/gemma-transformers-server
target="${ALGOHINT_SSH_TARGET:?SSH設定名を指定してください}"
scp "/tmp/algohint-gemma-server-${release_id}.tar.gz" "$target:/tmp/"
```

SSH接続先のログインユーザーのホーム配下へ展開します。

```bash
ssh "$ALGOHINT_SSH_TARGET"
app_root="$HOME/programs/algohint-gemma-server"
release_id='<WSL側で表示した12桁のコミットID>'

install -d -m 700 \
  "$app_root/releases/$release_id" \
  "$app_root/cache/huggingface" \
  "$app_root/cache/uv" \
  "$app_root/runtime/offload" \
  "$app_root/state" \
  "$HOME/.config/algohint-gemma-server"

tar -xzf "/tmp/algohint-gemma-server-${release_id}.tar.gz" \
  -C "$app_root/releases/$release_id"
ln -sfn "$app_root/releases/$release_id" "$app_root/current"
```

依存をロックファイルどおりに同期します。login shellのPATHに依存しないよう、
接続先アカウントのuvを絶対パスで指定します。

```bash
app_root="$HOME/programs/algohint-gemma-server"
uv_bin="$HOME/.local/bin/uv"

UV_PROJECT_ENVIRONMENT="$app_root/.venv" \
UV_CACHE_DIR="$app_root/cache/uv" \
"$uv_bin" sync --frozen --project "$app_root/current"
```

## credentials

推論APIはループバック限定でもBearer認証を必須にします。初回だけ、値を端末へ
表示せずランダムキーを作成します。

```bash
credentials="$HOME/.config/algohint-gemma-server/credentials"
if [ ! -e "$credentials" ]; then
  umask 077
  token="$("$HOME/programs/algohint-gemma-server/.venv/bin/python" \
    -c 'import secrets; print(secrets.token_urlsafe(48))')"
  {
    printf "ALGOHINT_GEMMA_API_KEY='%s'\n" "$token"
    printf "ALGOHINT_GEMMA_MODEL_REVISION='%s'\n" \
      '707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7'
  } >"$credentials"
  unset token
fi
chmod 600 "$credentials"
bash -n "$credentials"
```

AlgoHintを動かすWSLへ同じキーを安全にコピーします。内容を画面表示したり、
リポジトリへ置いたりしません。

```bash
install -d -m 700 "$HOME/.config/algohint"
target="${ALGOHINT_SSH_TARGET:?SSH設定名を指定してください}"
scp "$target:.config/algohint-gemma-server/credentials" \
  "$HOME/.config/algohint/gemma-remote-credentials"
chmod 600 "$HOME/.config/algohint/gemma-remote-credentials"
bash -n "$HOME/.config/algohint/gemma-remote-credentials"
```

このファイルは利用者が管理します。Codexへ調査を依頼する場合も、値の表示、
`cat`、`printenv`、ログへの出力は行わないでください。

## 事前検査とモデル取得

GPU、メモリ、ディスク、CUDA、キー、書き込み先を、モデルロード前に確認します。

```bash
app_root="$HOME/programs/algohint-gemma-server"
set -a
. "$HOME/.config/algohint-gemma-server/credentials"
set +a

ALGOHINT_GEMMA_CACHE_DIR="$app_root/cache/huggingface" \
ALGOHINT_GEMMA_OFFLOAD_DIR="$app_root/runtime/offload" \
"$app_root/.venv/bin/python" "$app_root/current/scripts/preflight.py"
```

モデルは固定revisionを明示してダウンロードします。Hugging Face側でモデル利用規約への
同意が必要な場合は、接続先ユーザーのHugging Faceトークンを別途設定してください。

```bash
app_root="$HOME/programs/algohint-gemma-server"
HF_HOME="$app_root/cache/huggingface" \
"$app_root/.venv/bin/hf" download \
  google/gemma-4-12B-it \
  --revision 707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7
```

## 起動・状態確認

SSH切断後も維持するため、制御スクリプトが`algohint-gemma` tmuxセッションを作ります。
接続時の既定画面はmonitor windowで、上ペインが2秒ごとの状態・PID・healthz・GPU概要、
下ペインが`server.log`の追従表示です。server windowにはUvicornの実プロセスと同じ
コンソール出力が表示されます。サーバーが異常終了してもmonitor windowは残るため、
最終状態とログを確認できます。

```bash
app_root="$HOME/programs/algohint-gemma-server"
"$app_root/current/scripts/server-control.sh" start
"$app_root/current/scripts/server-control.sh" status
"$app_root/current/scripts/server-control.sh" attach
```

tmuxから離れるときは`Ctrl-b d`を使います。別端末から直近ログだけを見る場合と、
追従する場合は次を使います。

```bash
"$app_root/current/scripts/server-control.sh" logs
"$app_root/current/scripts/server-control.sh" logs --follow
```

`status`はtmuxセッション、検証済みUvicorn PID、状態JSON、`/healthz`を照合し、
食い違いを警告します。`nvidia-smi`がない環境ではGPU欄だけを利用不可と表示し、
monitor自体は継続します。

ログは起動時に既定10 MiBを超えると5世代までローテーションします。必要なら秘密を
含まない整数環境変数で変更できます。

```bash
export ALGOHINT_GEMMA_LOG_MAX_BYTES=20971520
export ALGOHINT_GEMMA_LOG_GENERATIONS=8
```

processor読込、モデル重み読込、GPU配置、ready、要求開始・完了・失敗、shutdownは
INFOログまたは状態JSONで確認できます。ログに`Application startup complete`が出た後、
認証付きのモデル診断を行います。

```bash
app_root="$HOME/programs/algohint-gemma-server"
set -a
. "$HOME/.config/algohint-gemma-server/credentials"
set +a

"$app_root/.venv/bin/python" -c '
import os
import httpx
response = httpx.get(
    "http://127.0.0.1:18080/v1/models",
    headers={"Authorization": f"Bearer {os.environ[\"ALGOHINT_GEMMA_API_KEY\"]}"},
    timeout=10,
)
response.raise_for_status()
print("Gemma server doctor: OK")
'
```

キー値やレスポンス本文は出力しません。

## WSLから接続

ローカルのAlgoHint credentialsを
`$HOME/.config/algohint/credentials`（または`$ALGOHINT_CREDENTIALS`）へ用意し、
Gemma用キーと接続設定を含めます。一括起動スクリプトはリモートGemma、
SSHトンネル、ローカルAlgoHintを順に起動します。

```bash
project_root="$(git rev-parse --show-toplevel)"
cd "$project_root"
export ALGOHINT_SSH_TARGET='gpu-learning-host'
export ALGOHINT_SSH_LOCAL_PORT='18000'
export ALGOHINT_SSH_REMOTE_PORT='18080'
export ALGOHINT_SSH_STARTUP_TIMEOUT='300'
export ALGOHINT_CREDENTIALS="$HOME/.config/algohint/gemma-remote-credentials"
./scripts/run-ssh-stack.sh
```

リモート配置先が既定の`$HOME/programs/algohint-gemma-server`と異なる場合は
`ALGOHINT_SSH_REMOTE_APP_ROOT`で指定します。終了時はスクリプトが新規起動したリモート
Gemmaだけを停止します。維持する場合は`./scripts/run-ssh-stack.sh --keep-remote`を
使います。

起動スクリプトは依存インストールやモデルダウンロードを行いません。AlgoHintは
`uv sync --frozen`、Gemmaは前述の独立環境同期と固定revisionの`hf download`を事前に
完了してください。不足時は起動に失敗し、必要な準備箇所を表示します。

`remote`を明示するため、SSHトンネルのURLがループバックでもUIは外部送信の同意を
要求します。ブラウザでGemmaを選択し、同意後に「わからない」を1回実行して、
`gemma / google/gemma-4-12B-it`と生成ヒントが表示されることを確認します。続けて
全テストAC後のコード改善レビューを一回だけ実行し、同じprovider/modelの構造化レビューが
表示されること、サーバーログへコードやJSON本文が出ていないことを確認します。

## 更新とロールバック

更新は新しいコミットを別の`releases/<commit>`へ展開し、テスト後に`current`を
切り替えます。旧ディレクトリやキャッシュは自動削除しません。

```bash
app_root="$HOME/programs/algohint-gemma-server"
ln -sfn "$app_root/releases/<新commit>" "$app_root/current"
```

問題があれば旧リリースへ戻し、サーバーを再起動します。

```bash
app_root="$HOME/programs/algohint-gemma-server"
ln -sfn "$app_root/releases/<旧commit>" "$app_root/current"
"$app_root/current/scripts/server-control.sh" stop
"$app_root/current/scripts/server-control.sh" start
```

プロセス停止を`status`で確認してから再起動します。

## 停止

```bash
app_root="$HOME/programs/algohint-gemma-server"
"$app_root/current/scripts/server-control.sh" stop
```

`stop`はPIDファイルの値が実際に対象Uvicornのコマンド行と一致する場合だけシグナルを送り、
曖昧な`pkill`は使いません。その後、対象のtmuxセッションだけを終了します。
WSL側のSSHトンネルは専用ターミナルで`Ctrl-C`を押して終了します。

## トラブルシューティング

| 症状 | 確認と対処 |
|---|---|
| `uv`が見つからない | `$HOME/.local/bin/uv --version`を使い、PATH依存を避ける |
| Hugging Faceで401/403 | モデル利用規約、トークン、接続先ユーザーの権限を確認する |
| CUDA out of memory | 他プロセス、3枚のGPU空き、14 GiB/GPU上限、offload領域を確認する |
| 起動が長時間継続する | `server-control.sh attach`で読込状態、ログ、GPUメモリ使用量を確認する |
| AlgoHint doctorが接続拒否 | `server-control.sh status`、18080待受、SSHトンネル、18000競合を順に確認する |
| tmux接続時にサーバーが見えない | monitor windowを選び、上の状態と下の追従ログを確認する |
| `ready_with_last_error` | `request_kind`と`exception_type`、直近ログを確認して同じボタンから再試行する |
| `failed` | server windowの終了状態と最終ログを確認し、原因解消後にstop/startする |
| 401 | WSLとサーバーのcredentialsが同じ世代か確認し、安全に再コピーする |
| 429 | 単一生成ロックが使用中。現在要求の完了を待ち、重複送信しない |
| RuleBasedへ退避する | UIの安全化理由、AlgoHintログ、サーバーログの順で確認する |

ログへAPIキー、Authorizationヘッダー、プロンプト全文、提出コードを出力しないで
ください。詳細な設計と信頼境界は[LLMヒント設計](llm-hint-design.md)および
[安全な運用](security-and-operation.md)を参照してください。

参考:
[Gemmaモデル導入](https://ai.google.dev/gemma/docs/get_started)、
[Gemma 4 12B ITモデルカード](https://huggingface.co/google/gemma-4-12B-it)
