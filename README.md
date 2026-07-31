# AlgoHint Coach

AlgoHint Coach は、完成コードを先に示さず、段階的ヒントと実行判定で考える力を支援するローカル向けアルゴリズム学習アプリです。

## MVPの機能

- L0〜L3を対象にした自作5問と、公開・隠しテスト
- Pythonの LocalJudge（AC / WA / RE / TLE / CE / IE）
- 安全化したコンパイル・実行・時間超過診断と、公開サンプル／全テストの実行分離
- GPT-5.6、Gemma 4 12B、Geminiを切り替えられる会話型ヒント
- 質問・「わからない」・実行結果を回答前に会話へ出す非解答型ヒント
- 問題選択と本文が同期し、プロフィールごとの最後の有効な問題へ戻る演習画面
- Ctrl+Enter／Cmd+Enter送信、質問の即時表示、実測経過時間を備えた質問UI
- 全テストAC・ギブアップ後に専用タブで始める、作成済み固定5問
- 固定5問の初回採点後にボタンで表示する解説とAIコード改善レビュー
- 全テストAC済みコードから2〜5問（または3問固定）を作る任意のAI小テスト
- プロフィール別SQLiteへ保存する、容量制御・ページング付き復習履歴
- プロフィール・問題別の自動保存ドラフトと、同一コードをまとめた実行履歴
- ローカルプロフィール別の学習ログと苦手タグレポート
- Exa通常Search・引用・予算表示を備えた、明示同意式の根拠付きWebヒント
- 15固定caseの明示確認付きライブ実測と保存済み実行を使うResearch品質評価
- 通常画面から分離した教師モード

`last_problem_id` は進捗ではなく、次回同じ問題へ戻るためだけの利便性状態です。
削除済み問題なら既定L0へ自己修復し、解説や復習の解禁は必ず学習ログの全テストAC／
ギブアップで判断します。詳しい状態分類と処理フローは
[アーキテクチャ](docs/architecture.md#状態の分類)、教材の小テスト形式は
[教材作成ガイド](docs/data-and-content-authoring.md#復習小テスト)を参照してください。
Web検索の構造、評価指標、送信情報は
[Grounded Web Researchと評価](docs/research-and-evaluation.md)、画像入力の発展設計は
[画像入力の実装可能性設計](docs/image-input-design.md)を参照してください。

## 初回設定

[uvの公式手順](https://docs.astral.sh/uv/getting-started/installation/#standalone-installer)
に従ってuvを導入し、リポジトリのロック済み依存を同期します。

```bash
uv --version
uv sync --frozen
./scripts/run-algohint.sh
```

<http://127.0.0.1:7860>を開いてください。LLMのキーがなくてもアプリは起動し、
固定のRuleBasedヒントを利用できます。GPT-5.6、Gemini、Gemmaを使う場合だけ、
[開発ガイドの秘密情報管理](docs/development.md#llm設定と秘密情報)に従って、必要な
credentialsをホーム配下へ作成します。`.env`やリポジトリ内へキーを保存しないでください。
別ホストのGemmaを使う場合は、この単独launcherではなく、serverとSSH tunnelを検証する
`run-ssh-stack.sh`から起動してください。

別ホストのGemmaを使う場合は、AlgoHintより先に互換性のある
[AlgoHint Gemma Server](https://github.com/KoCSience/AlgoHint-Gemma-Server)を
SSH接続先へ配備し、起動する必要があります。このAlgoHint commitが検証したGemma Serverの
public repositoryと40桁commit SHAは
[release manifest](config/gemma-server-release.conf)に固定しています。接続先は
`$HOME/.config/algohint/gemma-ssh-target`だけで管理します。初回にディレクトリと
ファイルを現在ユーザーだけが読み書きできる権限で作成します。

```bash
unset ALGOHINT_SSH_TARGET
ssh_target_file="$HOME/.config/algohint/gemma-ssh-target"
install -d -m 700 "$HOME/.config/algohint"
(umask 077; "${EDITOR:-vi}" "$ssh_target_file")
chmod 600 "$ssh_target_file"
```

ファイルには`~/.ssh/config`で設定済みのaliasを1行だけ記述します。ユーザー名やportは
このファイルへ書かず、SSH config側で管理します。

```text
143-home
```

接続確認と初回配備を順に実行します。接続確認の成功文はremote shellではなく
AlgoHint hostで表示するため、remote shellによる`printf`の解釈差に依存しません。

```bash
./scripts/check-gemma-ssh.sh
./scripts/install-gemma-server-ssh.sh
```

成功時は末尾に次のように表示されます。installerを再実行したときの
`Release is already current: <40桁SHA>`も正常です。

```text
SSH connection OK: AlgoHint host -> GPU host (target: 143-home)
Pinned Gemma Server release installed on 143-home.
```

必要なGPU、モデル、`server-control.sh`の配置順は
[Gemma接続・移行ガイド](docs/gemma-server.md)を参照してください。GPU hostの
`${XDG_CONFIG_HOME:-$HOME/.config}/algohint-gemma-server/credentials`へGemma API keyと
必要なHF tokenを作る手順は
[Remote credentials](docs/gemma-server.md#3-remote-credentials)にあります。controlが
未配置なら`run-ssh-stack.sh`はサーバーやトンネルを開始せず、期待パスと復旧先を
表示して停止します。

接続後はremote credentials全体をコピーせず、次のhelperでGemma API keyだけを
AlgoHint hostの`$HOME/.config/algohint/gemma-remote-credentials`へ同期します。

```bash
./scripts/sync-gemma-credentials-ssh.sh
```

初回同期と同じkeyでの再実行では、次のいずれかが表示され、どちらも成功です。

```text
Gemma client credentials synchronized: /home/<user>/.config/algohint/gemma-remote-credentials
Gemma client credentials are already synchronized: /home/<user>/.config/algohint/gemma-remote-credentials
```

## Dockerで起動

Docker Composeを使うと、学習ログ用ボリュームとローカル限定のポート公開を含めて起動できます。

```bash
docker compose up --build --detach
docker compose ps
```

ヘルスチェックが`healthy`になったら、<http://127.0.0.1:7860>を開いてください。停止してもプロフィールと学習ログは`algohint-runtime`ボリュームに残ります。

```bash
docker compose down
```

`docker run`を使う手順、教師モード、Dev Container、データ管理は[Docker運用ガイド](docs/docker.md)を参照してください。

remote GPU hostのDocker版Gemma、host所有のSSH tunnel、Docker版AlgoHintをまとめる
場合は、初回だけremote imageも構築します。SSH鍵はAlgoHint containerへmountしません。

```bash
ALGOHINT_CREDENTIALS="$HOME/.config/algohint/gemma-remote-credentials" \
  ./scripts/run-ssh-docker-stack.sh --build-remote
```

2回目以降は`--build-remote`を外します。local imageの再構築も省略する場合だけ
`--no-build-local`を指定します。構造・前提・所有processのcleanupは
[Docker運用ガイド](docs/docker.md#remote-docker-gemmaとの一括起動)を参照してください。

## ホストで起動

```bash
./scripts/run-algohint.sh
```

キーはリポジトリへ置かず、ホーム配下で管理して起動シェルの環境変数へ読み込ませます。
アプリが受け取る変数と安全な管理例は
[開発ガイド](docs/development.md#llm設定と秘密情報)を参照してください。キーがない場合も
アプリは起動し、固定のRuleBasedヒントへ安全に退避します。

同一ホストへstandalone Gemma Serverをversion付き配備済みの場合は、次を使います。
AlgoHintリポジトリ内のserverへfallbackしません。終了時はこのスクリプトが新しく起動した
Gemmaだけを停止し、継続する場合は`--keep-gemma`を付けます。

```bash
./scripts/run-local-stack.sh
```

別ホストのGemma、SSHトンネル、ローカルAlgoHintをまとめて起動する場合も、上で作成した
`gemma-ssh-target`を自動的に使います。終了後も新規起動したリモートGemmaを維持する場合は
`--keep-remote`を付けます。

```bash
ALGOHINT_CREDENTIALS="$HOME/.config/algohint/gemma-remote-credentials" \
  ./scripts/run-ssh-stack.sh
```

AlgoHintもcontainerで動かす場合は`run-ssh-docker-stack.sh`を使います。これはremoteの
native `server-control.sh`ではなくDocker controllerを選び、既存remote containerの
所有権を奪いません。

このlauncherはhealth確認後に認証付きdoctorを実行し、model IDとready状態が一致した場合
だけAlgoHintを起動します。起動後にserverまたはtunnelのhealthが失われても、アプリは
RuleBasedヒントを利用できる状態で継続し、端末へ復旧案内を1回表示します。
Gemmaはmodel load完了後にlistenerを開くため、launcherはremote側でreadyを確認してから
SSH tunnelを作ります。初回のmodel取得を含め最大900秒待ち、10秒ごとに秘密を含まない
`loading_model`などの進捗を表示します。

vLLMを使わず、別のLinuxホストへPyTorch／Transformers版Gemma 4 12Bサーバーを
接続する場合は、[Gemma Server接続ガイド](docs/gemma-server.md)を参照してください。
ホーム配下へ配置し、SSHトンネルで接続する構成を記載しています。

Gemma接続だけを確認する場合:

```bash
ALGOHINT_CREDENTIALS="$HOME/.config/algohint/gemma-remote-credentials" \
  ./scripts/run-ssh-stack.sh --keep-remote doctor --provider gemma
```

`reason_code=endpoint_unreachable`または`ConnectError: [Errno 111] Connection refused`
の場合は、認証やモデル応答より前にserverまたはtunnelのlistenerへ到達できていません。
[Connection refusedの切り分け](docs/gemma-server.md#connection-refusedの切り分け)を
参照してください。

Geminiの接続、キー、権限、モデル到達性だけを確認する場合は、学習者の問題文や
コードを送らない診断コマンドを使用できます。

```bash
./scripts/run-algohint.sh doctor --provider gemini
```

開発中にSDKの例外メッセージとスタックトレースまで確認する場合は、認証情報を
伏字化する詳細診断を使用します。

```bash
ALGOHINT_ENV=development uv run algohint doctor --provider gemini --verbose
```

教師用の隠しテストと模範解答を確認する場合だけ、次を使います。

```bash
uv run algohint --teacher-mode
```

Colabなどで共有リンクが必要なときは、信頼できる個人利用に限って明示的に指定してください。

```bash
uv run algohint --share
```

## 安全上の注意

提出コードはアプリと同じ環境の子プロセスで実行されます。Docker利用時も提出専用コンテナへ分離されず、教材、隠しテスト、学習ログ、コンテナのネットワークを共有します。公開サーバーや不特定多数が使える共有リンクで運用しないでください。提出コードは集計用学習ログとは分離したプロフィール別SQLiteへ保存されるため、runtimeとバックアップを機密データとして管理してください。

詳細は[安全な運用](docs/security-and-operation.md)を参照してください。

## 開発時の検証

```bash
uv run pytest
uv run ruff check .
uv run mypy src
uv lock --check
```

ヒント機能はGradio API、Playwright、Chrome DevTools MCPの三層で確認します。
ブラウザ導入、実行コマンド、実Geminiを1要求だけ使う最終確認は
[E2Eデバッグガイド](docs/e2e-debugging.md)、Codexへ隔離Chromeを接続する手順は
[Chrome DevTools MCP導入ガイド](docs/chrome-devtools-mcp.md)を参照してください。
