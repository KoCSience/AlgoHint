# Gemma 4 12B Transformersサーバー

AlgoHintからGemma 4 12Bを使うための、専用推論サーバーの導入・運用手順です。
vLLM、TGI、Docker、root権限、公開ポートは必要ありません。`143-home`の
`saeki`ユーザーのホーム配下へ、uv、PyTorch、Hugging Face Transformersで構築します。

AlgoHint本体とモデル推論を別プロセスにするのは、約12Bパラメータのモデル依存と
GPU資源をUIから分離し、障害時にもRuleBasedヒントへ安全に退避できるようにするためです。
FastAPIがJSON APIを担当し、モデルにはJSON生成を要求しません。

## 検証対象

現在の固定構成は次のとおりです。

| 項目 | 値 |
|---|---|
| 接続先 | SSH設定名 `143-home` |
| 実行ユーザー | `saeki` |
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

## ホーム配下の構造

```text
/home/saeki/
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
cd /home/user/School/AlgoHint
release_id="$(git rev-parse --short=12 HEAD)"
git archive --format=tar.gz \
  --output="/tmp/algohint-gemma-server-${release_id}.tar.gz" \
  HEAD:services/gemma-transformers-server
scp "/tmp/algohint-gemma-server-${release_id}.tar.gz" 143-home:/tmp/
```

`143-home`へ接続し、saekiのホーム配下へ展開します。

```bash
ssh 143-home
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
saeki環境で確認済みのuvを絶対パスで使います。

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
scp 143-home:/home/saeki/.config/algohint-gemma-server/credentials \
  "$HOME/.config/algohint/gemma-143-home-credentials"
chmod 600 "$HOME/.config/algohint/gemma-143-home-credentials"
bash -n "$HOME/.config/algohint/gemma-143-home-credentials"
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
同意が必要な場合は、saekiユーザーのHugging Faceトークンを別途設定してください。

```bash
app_root="$HOME/programs/algohint-gemma-server"
HF_HOME="$app_root/cache/huggingface" \
"$app_root/.venv/bin/hf" download \
  google/gemma-4-12B-it \
  --revision 707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7
```

## 起動

SSH切断後も維持するため、saekiユーザーのtmuxで起動します。サーバーは
`127.0.0.1`だけで待ち受け、3枚のGPUへ自動分散します。

```bash
app_root="$HOME/programs/algohint-gemma-server"
tmux new-session -d -s algohint-gemma \
  "$app_root/current/scripts/run-server.sh 2>&1 | tee -a '$app_root/state/server.log'"
tmux ls
tail -f "$app_root/state/server.log"
```

ログに`Application startup complete`が出た後、認証付きのモデル診断を行います。

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

WSLの専用ターミナル1でSSHトンネルを維持します。

```bash
ssh -N -T \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L 127.0.0.1:18000:127.0.0.1:18080 \
  143-home
```

専用ターミナル2でGemma用credentialsだけを読み込み、AlgoHintを起動します。

```bash
cd /home/user/School/AlgoHint
set -a
. "$HOME/.config/algohint/gemma-143-home-credentials"
set +a

export ALGOHINT_ENV='development'
export ALGOHINT_GEMMA_BACKEND='transformers_http'
export ALGOHINT_GEMMA_DEPLOYMENT='remote'
export ALGOHINT_GEMMA_BASE_URL='http://127.0.0.1:18000/v1'
export ALGOHINT_GEMMA_MODEL='google/gemma-4-12B-it'
export ALGOHINT_GEMMA_TIMEOUT_SECONDS='180'

uv run algohint doctor --provider gemma
uv run algohint
```

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
tmux send-keys -t algohint-gemma C-c
```

プロセス停止をログと`tmux ls`で確認してから、同じ起動コマンドを再実行します。

## 停止

```bash
tmux send-keys -t algohint-gemma C-c
```

停止後もセッションだけが残った場合に限り、次を実行します。

```bash
tmux kill-session -t algohint-gemma
```

WSL側のSSHトンネルは専用ターミナルで`Ctrl-C`を押して終了します。

## トラブルシューティング

| 症状 | 確認と対処 |
|---|---|
| `uv`が見つからない | `$HOME/.local/bin/uv --version`を使い、PATH依存を避ける |
| Hugging Faceで401/403 | モデル利用規約、トークン、saekiユーザーの権限を確認する |
| CUDA out of memory | 他プロセス、3枚のGPU空き、14 GiB/GPU上限、offload領域を確認する |
| 起動が長時間継続する | 初回ダウンロード量、`server.log`、GPUメモリ使用量を確認する |
| AlgoHint doctorが接続拒否 | tmux、18080待受、SSHトンネル、18000競合を順に確認する |
| 401 | WSLとサーバーのcredentialsが同じ世代か確認し、安全に再コピーする |
| 429 | 単一生成ロックが使用中。現在要求の完了を待ち、重複送信しない |
| RuleBasedへ退避する | UIの安全化理由、AlgoHintログ、サーバーログの順で確認する |

ログへAPIキー、Authorizationヘッダー、プロンプト全文、提出コードを出力しないで
ください。詳細な設計と信頼境界は[LLMヒント設計](llm-hint-design.md)および
[安全な運用](security-and-operation.md)を参照してください。

参考:
[Gemmaモデル導入](https://ai.google.dev/gemma/docs/get_started)、
[Gemma 4 12B ITモデルカード](https://huggingface.co/google/gemma-4-12B-it)
