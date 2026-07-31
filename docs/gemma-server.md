# Gemma Server接続ガイド

Grounded ResearchのExa API keyはAlgoHint hostではなくGPU hostの
`${XDG_CONFIG_HOME:-$HOME/.config}/algohint-gemma-server/credentials`へ置きます。
AlgoHintへ同期するのは`ALGOHINT_GEMMA_API_KEY`だけです。支払方法、Top up、
Auto-rechargeを使用しない運用と月9ドルguardはstandalone serverの
`docs/research.md`を参照してください。

AlgoHintからGemma 4 12Bを利用するための、独立推論サーバーの初回配備、credentials、
起動、SSH tunnel、障害切り分けを説明します。サーバーのsource、Hydra設定、API、
controllerの正本は
[KoCSience/AlgoHint-Gemma-Server](https://github.com/KoCSience/AlgoHint-Gemma-Server)
です。AlgoHintリポジトリには推論server実装を同梱しません。

## このガイドの実行場所

| 表記          | 実体                       | 主な処理                                         |
| ------------- | -------------------------- | ------------------------------------------------ |
| AlgoHint host | AlgoHintを動かす現在のPC   | SSH、credential同期、tunnel、doctor、UI          |
| GPU host      | 設定ファイルで選んだ接続先 | Gemma Server、GPU、model cache、remote credential |
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

Gemma Serverは`/healthz`、通常生成APIに加えて`/v1/research/status`、
`/v1/research/usage`、`/v1/research`を提供します。生成APIはBearer認証と1件の
共通lockを使い、prompt、
learner code、model出力、credentialをlog/statusへ保存しません。完全な契約は
[standalone API guide](https://github.com/KoCSience/AlgoHint-Gemma-Server/blob/main/docs/api.md)
を参照してください。

## 1. SSH接続の確認

AlgoHintが使うSSH接続先は、AlgoHint hostの
`$HOME/.config/algohint/gemma-ssh-target`だけで管理します。ファイルはshellとして
読み込まれず、検証済みのalias 1行だけがSSHへ渡されます。ユーザー名、port、鍵のpathは
このファイルではなく`~/.ssh/config`へ設定してください。

**実行場所: AlgoHint host（AlgoHint repository root）**

```bash
unset ALGOHINT_SSH_TARGET
ssh_target_file="$HOME/.config/algohint/gemma-ssh-target"
install -d -m 700 "$HOME/.config/algohint"
(umask 077; "${EDITOR:-vi}" "$ssh_target_file")
chmod 600 "$ssh_target_file"
```

ファイルには`~/.ssh/config`で設定済みのaliasを1行だけ記述します。空行、複数行、
symlink、mode 600以外のfileは拒否されます。手動SSHを行う後続手順のため、検証後の
値を現在のterminalだけで使う非export変数へ読み込みます。terminalを開き直した場合は
この代入を再実行してください。

```bash
./scripts/check-gemma-ssh.sh
ssh_target="$(<"$ssh_target_file")"
```

成功時はSSHのbannerやMOTDに続き、AlgoHint host側で次の行が表示され、終了code 0を
返します。

```text
SSH connection OK: AlgoHint host -> GPU host (target: <SSH設定名>)
```

alias、host key、公開鍵認証を先に解決します。bootstrapはpassword、sudo、root権限を
要求しません。以前のガイドにあったremote `printf`が
`printf "...": command not found`となる場合、SSH sessionの開始後にremote shellが
成功表示用commandを期待どおり解釈できていません。後続installerが
`Pinned Gemma Server release installed ...`を、同期helperが`already synchronized`を
表示した場合、その2処理はそれぞれ正常終了しています。接続確認にはremoteで`true`だけを
実行し、成功文をlocal表示する上のhelperを使用してください。

## 2. 固定releaseの初回配備

**実行場所: AlgoHint host（AlgoHint repository root）**

```bash
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

成功時の最終行は`Pinned Gemma Server release installed on <SSH設定名>.`です。
同じreleaseを再実行したときの`Release is already current: <40桁SHA>`も正常です。

remote install rootを変える場合:

**実行場所: AlgoHint host（AlgoHint repository root）**

```bash
ALGOHINT_SSH_REMOTE_APP_ROOT='/srv/algohint-gemma-server' \
  ./scripts/install-gemma-server-ssh.sh
```

installerはcredentialsやmodel weightsを作成しません。manifestのcommitがGitHubで
未公開ならfetchで安全に失敗し、別branchや最新commitへfallbackしません。

## 3. Remote credentials

GPU hostで初回だけAPI keyを作成します。値をterminalへ表示しません。

**実行場所: AlgoHint host**

```bash
ssh "$ssh_target"
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
./scripts/sync-gemma-credentials-ssh.sh
```

初回は`Gemma client credentials synchronized: <path>`、同じkeyの再実行は
`Gemma client credentials are already synchronized: <path>`と表示されます。どちらも
終了code 0の成功です。

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
./scripts/sync-gemma-credentials-ssh.sh --replace
```

異なる既存fileは、`~/.config/algohint/_GARBAGE/`へmode 600のまま退避されます。新旧keyを
表示して比較せず、同期後にdoctorで接続を確認してください。

## 4. Preflightとmodel cache

GPU、dtype、必要GPU数、portをmodel download前に確認します。

**実行場所: AlgoHint host**

```bash
ssh -T "$ssh_target" \
  '"$HOME/programs/algohint-gemma-server/current/.venv/bin/algohint-gemma-preflight"'
```

modelを事前取得する場合は、GPU hostの資格情報をsourceした非表示のsessionで実行します。

**実行場所: AlgoHint host**

```bash
ssh "$ssh_target"
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
ssh "$ssh_target"
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
  ./scripts/run-ssh-stack.sh
```

scriptは次の順で実行します。

1. remote controllerが実行可能か検査する。
2. 既存serverがなければstartする。
3. remote host内でhealthがreadyになるまでbounded waitする。
4. `127.0.0.1:18000`からremote `127.0.0.1:18080`へtunnelを作る。
5. credentials読込後も接続先を上のloopback tunnelへ固定する。
6. 認証付き`/v1/models`でmodel IDとreadyを検査する。
7. doctor成功後だけAlgoHintを起動し、5秒間隔でhealthを監視する。
8. 終了時に自分が作ったtunnelとserverだけを停止する。

```text
remote controller
  → remote /healthz ready待機
  → SSH tunnel
  → managed endpoint固定
  → doctor (/v1/models)
  → AlgoHint + health monitor
```

monitorは3回連続でhealthを取得できなかった場合に端末へ1回だけ警告します。remote
serverを自動再起動したり生成POSTを自動再送したりはしません。起動前から存在したserverの
所有権を奪うことと、応答だけ失われた生成処理を重複実行することを避けるためです。
AlgoHint自体は停止せず、Gemma要求は安全にRuleBasedヒントへfallbackします。監視間隔は
`ALGOHINT_GEMMA_MONITOR_INTERVAL_SECONDS`で1〜60秒に変更でき、既定は5秒です。

Uvicornはmodel load完了後に`127.0.0.1:18080`をlistenします。そのため起動中に先に
tunnelへ接続すると、正常なload中でもSSHが`channel ... Connection refused`を表示します。
launcherは1本のSSH session内でremote healthを待つことでこの表示を避け、10秒ごとに
`starting`、`loading_processor`、`loading_model`などの安全な状態だけを表示します。
既定timeoutは初回model取得を考慮して900秒です。

remote Gemmaを維持する場合は`--keep-remote`を指定します。

### AlgoHintとGemmaの両方をDockerで起動

host SSH tunnelを維持したままAlgoHintもcontainer化できます。初回はmanifestで固定した
remote releaseを必要に応じて導入し、同じcommitのimageを構築します。

```bash
ALGOHINT_CREDENTIALS="$HOME/.config/algohint/gemma-remote-credentials" \
  ./scripts/run-ssh-docker-stack.sh --build-remote
```

`--build-remote`はremote `current/RELEASE`が固定SHAと異なる場合、既存installerを実行し、
SHAとcontrollerを再検査してからbuildします。以後は`--build-remote`を外します。この経路はremote
`current/scripts/docker-control.sh`の安定した`container: running|not-running`状態を
使って所有権を判定します。native tmux Gemmaとの同時起動はremote controller側で
拒否されます。SSH鍵はhostだけが使用し、containerにはAPI利用に必要なGemma keyだけを
環境変数として渡します。

```text
remote Docker controller (3 GPU, 127.0.0.1:18080)
  → host SSH tunnel (127.0.0.1:18000)
  → AlgoHint Docker doctor
  → AlgoHint Docker UI (127.0.0.1:7860)
```

詳細は[Docker運用ガイド](docker.md#remote-docker-gemmaとの一括起動)を参照してください。

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
  ./scripts/run-ssh-stack.sh --keep-remote doctor --provider gemma
```

doctorはprompt、問題文、codeを送らず、`/v1/models`でbackend、model ID、readyを
確認します。成功時は
`Gemma診断: OK provider=gemma model=google/gemma-4-12B-it`と表示されます。
明示的にdoctorを指定した場合、launcher内の起動前doctorは重複実行されません。

## Connection refusedの切り分け

次の組み合わせは、HTTP statusを受け取る前に接続先listenerへ到達できなかったことを
示します。API key不一致、model ID不一致、生成レスポンス検証とは別の障害です。

```text
reason_code=endpoint_unreachable
http_status=-
exception_type=ConnectError
```

まずAlgoHint hostで、秘密値を表示せずlistenerと設定fileの属性だけを確認します。

```bash
ss -ltn | grep -E ':(18000|18080)[[:space:]]'
stat -c 'owner_uid=%u mode=%a type=%F path=%n' \
  "$HOME/.config/algohint/gemma-ssh-target" \
  "$HOME/.config/algohint/gemma-remote-credentials"
```

Remote構成ではAlgoHint hostの`127.0.0.1:18000`がSSH tunnel、GPU hostの
`127.0.0.1:18080`がGemma Serverです。AlgoHint hostに18000のlistenerがなければ、
単独の`run-algohint.sh`ではなく次の順に復旧します。

```bash
./scripts/check-gemma-ssh.sh
./scripts/install-gemma-server-ssh.sh
./scripts/sync-gemma-credentials-ssh.sh
ALGOHINT_CREDENTIALS="$HOME/.config/algohint/gemma-remote-credentials" \
  ./scripts/run-ssh-stack.sh --keep-remote doctor --provider gemma
```

installerは固定releaseに対して冪等です。doctor成功後は同じcredentialsで
`./scripts/run-ssh-stack.sh`を起動します。doctorより前に失敗した場合は、GPU hostで
`server-control.sh status`と`logs`を確認します。credentialsやログ全体を表示せず、
controllerが示すclosed metadataからmodel load、GPU、portの失敗を切り分けてください。

Local構成では`$HOME/programs/algohint-gemma-server/current/scripts/server-control.sh`が
存在するhostで`run-local-stack.sh doctor --provider gemma`を使用します。Dockerから
hostのGemmaへ接続する場合、container内の`127.0.0.1`はhostを指さないため、
[Docker運用ガイド](docker.md)の接続先設定を使用してください。

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
| `endpoint_unreachable` / `Connection refused`                     | server／tunnelのlistener不在。上の専用手順で起動経路を再構築       |
| tunnel起動失敗                                                    | local 18000競合、SSH forwarding設定、remote 18080を確認            |
| 起動前doctor失敗                                                  | UIは未起動。reason codeに従い認証、model ID、ready、接続経路を修正 |
| 起動後のhealth喪失警告                                            | UIは継続中。stackを再起動してdoctor成功後にGemmaを再試行           |
| `gemma-ssh-target`検証失敗                                        | 通常file、現在ユーザー所有、mode 600、alias 1行だけか確認          |
| `ALGOHINT_SSH_TARGET is no longer supported`                      | 変数を`unset`し、`~/.config/algohint/gemma-ssh-target`へ移行       |
| 旧接続確認の`printf ...: command not found`                       | remote成功表示の解釈失敗。`check-gemma-ssh.sh`で再確認             |

## Update and rollback

manifestのSHA更新は、standalone側のCI、release checklist、GPU acceptanceが完了した
releaseだけを対象にし、AlgoHintのconsumer contract testと同じcommitでreviewします。
更新後にinstallerを再実行すると新releaseを作ります。rollbackはstandaloneの
[Deployment guide](https://github.com/KoCSience/AlgoHint-Gemma-Server/blob/main/docs/deployment.md)
に従い、停止後に`previous`の既存release再利用を明示します。
