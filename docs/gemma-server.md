# Gemma Server接続ガイド

AlgoHintからGemma 4 12Bを利用するための、独立推論サーバーの初回配備、credentials、
起動、SSH tunnel、障害切り分けを説明します。サーバーのsource、Hydra設定、API、
controllerの正本は
[KoCSience/AlgoHint-Gemma-Server](https://github.com/KoCSience/AlgoHint-Gemma-Server)
です。AlgoHintリポジトリには推論server実装を同梱しません。

## このガイドの実行場所

| 表記          | 実体                       | 主な処理                                         |
| ------------- | -------------------------- | ------------------------------------------------ |
| AlgoHint host | AlgoHintを動かす現在のPC   | SSH、credential同期、tunnel、doctor、UI          |
| GPU host      | このガイドでは`143-home`   | Gemma Server、GPU、model cache、remote credential |
| GitHub        | 公開repository             | 固定SHAの配布元                                  |

各command blockの前に実行場所を示します。`$HOME`はcommandを実行しているhostのhome
directoryです。AlgoHint hostの`$HOME`とGPU hostの`$HOME`は別のpathを指します。

## 固定する境界

AlgoHintは[release manifest](../config/gemma-server-release.conf)で、公開repositoryと
40桁commit SHAを固定します。branchや`HEAD`を配備しないのは、同じAlgoHint commit
から起動するserver codeと依存が後から変わらないようにするためです。

| 項目             | 既定値                                                   |
| ---------------- | -------------------------------------------------------- |
| source           | `https://github.com/KoCSience/AlgoHint-Gemma-Server.git` |
| model            | `google/gemma-4-12B-it`                                  |
| model revision   | `707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7`               |
| GPU              | CUDA GPU 3台                                             |
| remote listener  | `127.0.0.1:18080`                                        |
| local SSH tunnel | `127.0.0.1:18000`                                        |
| install root     | `$HOME/programs/algohint-gemma-server`                   |

Gemma Serverは`/healthz`、`/v1/models`、`/v1/hints`、`/v1/reviews`、
`/v1/quizzes`だけを提供します。生成APIはBearer認証と1件の共通lockを使い、prompt、
learner code、model出力、credentialをlog/statusへ保存しません。完全な契約は
[standalone API guide](https://github.com/KoCSience/AlgoHint-Gemma-Server/blob/main/docs/api.md)
を参照してください。

## 1. SSH接続の確認

`143-home`は例です。利用者の`~/.ssh/config`にあるaliasへ置き換えます。

**実行場所: AlgoHint host（AlgoHint repository root）**

```bash
export ALGOHINT_SSH_TARGET='143-home'
ssh -T "$ALGOHINT_SSH_TARGET" \
  'printf "SSH connection OK: AlgoHint host -> GPU host\n"'
```

alias、host key、公開鍵認証を先に解決します。bootstrapはpassword、sudo、root権限を
要求しません。以前記載していた`ssh -T "$ALGOHINT_SSH_TARGET" 'true'`は、成功時に
何も表示せず終了code 0を返す確認方法でした。上のcommandは同じ接続確認に成功表示を
加えたものです。

## 2. 固定releaseの初回配備

**実行場所: AlgoHint host（AlgoHint repository root）**

```bash
ALGOHINT_SSH_TARGET='143-home' \
  ./scripts/install-gemma-server-ssh.sh
```

処理の流れ:

```text
AlgoHintのmanifestを検証
  → remote homeを安全に解決
  → GPU hostのcacheへpublic repoをbare clone/fetch
  → 固定SHAをtemporary worktreeへcheckout
  → そのcommit自身のdeploy-release.shを実行
  → tracked sourceだけをreleases/<SHA>へ展開
  → release専用.venvへlocked inference依存を導入
  → 停止状態を確認してcurrent symlinkをatomic replace
```

remote install rootを変える場合:

**実行場所: AlgoHint host（AlgoHint repository root）**

```bash
ALGOHINT_SSH_TARGET='143-home' \
ALGOHINT_SSH_REMOTE_APP_ROOT='/srv/algohint-gemma-server' \
  ./scripts/install-gemma-server-ssh.sh
```

installerはcredentialsやmodel weightsを作成しません。manifestのcommitがGitHubで
未公開ならfetchで安全に失敗し、別branchや最新commitへfallbackしません。

## 3. Remote credentials

GPU hostで初回だけAPI keyを作成します。値をterminalへ表示しません。

**実行場所: AlgoHint host**

```bash
ssh "$ALGOHINT_SSH_TARGET"
```

SSH login後はpromptと`$HOME`がGPU hostのものに変わります。

**実行場所: GPU host（上のSSH session内）**

```bash
credentials_dir="${XDG_CONFIG_HOME:-$HOME/.config}/algohint-gemma-server"
credentials_path="$credentials_dir/credentials"
umask 077
mkdir -p "$credentials_dir"
```

次のコマンドは、一度に貼り付けるようにしてください。

**実行場所: GPU host**

```bash
if [ ! -e "$credentials_path" ]; then
  token="$(openssl rand -hex 32)"
  printf "ALGOHINT_GEMMA_API_KEY='%s'\n" "$token" > "$credentials_path"
  unset token
fi
```

**実行場所: GPU host**

```bash
chmod 600 "$credentials_path"
```

Hugging Face認証が必要なら、同じfileへ`HF_TOKEN`を安全なeditorで追加します。
CodexやIssueへ内容の表示、`cat`、`printenv`を依頼しないでください。

`exit`でAlgoHint hostへ戻り、専用helperでAPI keyだけを同期します。remote
credentials全体を`scp`しないため、`HF_TOKEN`やserver専用設定はAlgoHint hostへ
複製されません。

**実行場所: GPU host**

```bash
exit
```

**実行場所: AlgoHint host（AlgoHint repository root）**

```bash
ALGOHINT_SSH_TARGET='143-home' \
  ./scripts/sync-gemma-credentials-ssh.sh
```

内容を表示せず、local fileの属性だけを確認します。

**実行場所: AlgoHint host**

```bash
local_credentials="$HOME/.config/algohint/gemma-remote-credentials"
stat -c 'owner_uid=%u mode=%a type=%F path=%n' "$local_credentials"
```

期待値は現在ユーザー所有、mode 600の通常fileです。このfileには
`ALGOHINT_GEMMA_API_KEY`だけが入り、起動時に`ALGOHINT_CREDENTIALS`で明示します。
他providerのkeyを自動的に統合しません。

### API keyのrotation

GPU host側でAPI keyを安全なeditorまたは非表示のshell処理により更新し、Gemma Serverを
再起動した後、AlgoHint hostで明示的に置き換えます。

**実行場所: AlgoHint host（AlgoHint repository root）**

```bash
ALGOHINT_SSH_TARGET='143-home' \
  ./scripts/sync-gemma-credentials-ssh.sh --replace
```

異なる既存fileは、`~/.config/algohint/_GARBAGE/`へmode 600のまま退避されます。新旧keyを
表示して比較せず、同期後にdoctorで接続を確認してください。

## 4. Preflightとmodel cache

GPU、dtype、必要GPU数、portをmodel download前に確認します。

**実行場所: AlgoHint host**

```bash
ssh -T "$ALGOHINT_SSH_TARGET" \
  '"$HOME/programs/algohint-gemma-server/current/.venv/bin/algohint-gemma-preflight"'
```

modelを事前取得する場合は、GPU hostの資格情報をsourceした非表示のsessionで実行します。

**実行場所: AlgoHint host**

```bash
ssh "$ALGOHINT_SSH_TARGET"
```

**実行場所: GPU host（上のSSH session内）**

```bash
set -a
. "${XDG_CONFIG_HOME:-$HOME/.config}/algohint-gemma-server/credentials"
set +a
app_root="$HOME/programs/algohint-gemma-server"
HF_HOME="${XDG_CACHE_HOME:-$HOME/.cache}/algohint-gemma-server/huggingface" \
  "$app_root/current/.venv/bin/hf" download \
  google/gemma-4-12B-it \
  --revision 707f0a3b8a3c7ad586ed01e27eafbad8a27dd0f7
```

## 5. Controller起動と状態確認

まずGPU hostへloginします。

**実行場所: AlgoHint host**

```bash
ssh "$ALGOHINT_SSH_TARGET"
```

**実行場所: GPU host（上のSSH session内）**

```bash
app_root="$HOME/programs/algohint-gemma-server"
"$app_root/current/scripts/server-control.sh" start
"$app_root/current/scripts/server-control.sh" status
"$app_root/current/scripts/server-control.sh" attach
```

`status.json`は`starting`、processor/model load、ready、用途別生成、直近失敗、
stopping/stoppedをclosed metadataだけで記録します。controllerはPIDの所有者、
Python module、作業directoryを検証した場合だけsignalを送ります。

**実行場所: GPU host**

```bash
"$app_root/current/scripts/server-control.sh" logs
"$app_root/current/scripts/server-control.sh" logs --follow
"$app_root/current/scripts/server-control.sh" stop
```

詳細はstandaloneの
[Operations](https://github.com/KoCSience/AlgoHint-Gemma-Server/blob/main/docs/operations.md)
と
[Troubleshooting](https://github.com/KoCSience/AlgoHint-Gemma-Server/blob/main/docs/troubleshooting.md)
を参照してください。

## 6. AlgoHintとSSH tunnelを起動

GPU hostのSSH sessionを開いている場合は`exit`でAlgoHint hostへ戻ってから実行します。

**実行場所: AlgoHint host（AlgoHint repository root）**

```bash
ALGOHINT_CREDENTIALS="$HOME/.config/algohint/gemma-remote-credentials" \
ALGOHINT_SSH_TARGET='143-home' \
  ./scripts/run-ssh-stack.sh
```

scriptは次の順で実行します。

1. remote controllerが実行可能か検査する。
2. 既存serverがなければstartする。
3. `127.0.0.1:18000`からremote `127.0.0.1:18080`へtunnelを作る。
4. healthがreadyになるまでbounded waitする。
5. `transformers_http`、`remote`を明示してAlgoHintを起動する。
6. 終了時に自分が作ったtunnelとserverだけを停止する。

remote Gemmaを維持する場合は`--keep-remote`を指定します。

同一hostでAlgoHintとstandalone serverを動かす場合:

**実行場所: AlgoHintとGemma Serverを同居させたhost**

```bash
ALGOHINT_CREDENTIALS="$HOME/.config/algohint/gemma-remote-credentials" \
  ./scripts/run-local-stack.sh
```

`run-local-stack.sh`も`$HOME/programs/algohint-gemma-server/current`を使い、AlgoHint内の
旧serviceへfallbackしません。

## 7. 接続診断

同じcredentialsでSSH tunnelを一時起動し、model discoveryだけを確認します。

**実行場所: AlgoHint host（AlgoHint repository root）**

```bash
ALGOHINT_CREDENTIALS="$HOME/.config/algohint/gemma-remote-credentials" \
ALGOHINT_SSH_TARGET='143-home' \
  ./scripts/run-ssh-stack.sh --keep-remote doctor --provider gemma
```

doctorはprompt、問題文、codeを送らず、`/v1/models`でbackend、model ID、readyを
確認します。成功時は
`Gemma診断: OK provider=gemma model=google/gemma-4-12B-it`と表示されます。

## Error map

| 症状                                                              | 原因と対応                                                         |
| ----------------------------------------------------------------- | ------------------------------------------------------------------ |
| `server-control.sh: そのようなファイルやディレクトリはありません` | standalone release未配備または`current`未作成。手順2を実行         |
| installerのfetch失敗                                              | manifest SHAが未公開、network、GitHub到達性。別SHAへfallbackしない |
| source cache origin不一致                                         | 既存cacheが別repo。内容を確認し、自動上書きしない                  |
| 非対話SSHで`uv`が見つからない                                    | `uv`をPATHまたはGPU hostの`$HOME/.local/bin/uv`へ導入              |
| preflightのCUDA/GPU失敗                                           | driver、PyTorch、`CUDA_VISIBLE_DEVICES`、GPU割当を確認             |
| credentials権限失敗                                               | owner、通常file、mode 600を確認。内容は表示しない                  |
| `loading_model`が継続                                             | cache、disk I/O、VRAM、safe log metadataを確認                     |
| `401`                                                             | keyを表示せず同期helperの`--replace`とdoctorを順に実行              |
| `429`                                                             | 別生成中。clientのbounded retryを待つ                              |
| tunnel起動失敗                                                    | local 18000競合、SSH forwarding設定、remote 18080を確認            |

## Update and rollback

manifestのSHA更新は、standalone側のCI、release checklist、GPU acceptanceが完了した
releaseだけを対象にし、AlgoHintのconsumer contract testと同じcommitでreviewします。
更新後にinstallerを再実行すると新releaseを作ります。rollbackはstandaloneの
[Deployment guide](https://github.com/KoCSience/AlgoHint-Gemma-Server/blob/main/docs/deployment.md)
に従い、停止後に`previous`の既存release再利用を明示します。
