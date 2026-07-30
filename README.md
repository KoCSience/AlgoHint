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

別ホストのGemmaを使う場合は、AlgoHintより先に互換性のある
[AlgoHint Gemma Server](https://github.com/KoCSience/AlgoHint-Gemma-Server)を
SSH接続先へ配備する必要があります。このAlgoHint commitが検証したGemma Serverの
public repositoryと40桁commit SHAは
[release manifest](config/gemma-server-release.conf)に固定しています。SSH設定名
（例: `gpu-learning-host`）を自分の接続先へ置き換え、接続と初回配備を行います。

```bash
ssh -T 'gpu-learning-host' \
  'printf "SSH connection OK: AlgoHint host -> GPU host\n"'
ALGOHINT_SSH_TARGET='gpu-learning-host' \
  ./scripts/install-gemma-server-ssh.sh
```

必要なGPU、credentials、モデル、`server-control.sh`の配置順は
[Gemma接続・移行ガイド](docs/gemma-server.md)を参照してください。controlが未配置なら
`run-ssh-stack.sh`はサーバーやトンネルを開始せず、期待パスと復旧先を表示して停止します。
接続後はremote credentials全体をコピーせず、次のhelperでGemma API keyだけを
AlgoHint hostへ同期します。

```bash
ALGOHINT_SSH_TARGET='gpu-learning-host' \
  ./scripts/sync-gemma-credentials-ssh.sh
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

別ホストのGemma、SSHトンネル、ローカルAlgoHintをまとめて起動する場合は、SSH設定名を
環境変数で渡します。下記の`gpu-learning-host`は自分のSSH設定名へ置き換えてください。
終了後も新規起動したリモートGemmaを維持する場合は`--keep-remote`を付けます。

```bash
ALGOHINT_CREDENTIALS="$HOME/.config/algohint/gemma-remote-credentials" \
ALGOHINT_SSH_TARGET='gpu-learning-host' \
  ./scripts/run-ssh-stack.sh
```

vLLMを使わず、別のLinuxホストへPyTorch／Transformers版Gemma 4 12Bサーバーを
接続する場合は、[Gemma Server接続ガイド](docs/gemma-server.md)を参照してください。
ホーム配下へ配置し、SSHトンネルで接続する構成を記載しています。

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

提出コードはアプリと同じ環境の子プロセスで実行されます。Docker利用時も提出専用コンテナへ分離されず、教材、隠しテスト、学習ログ、コンテナのネットワークを共有します。公開サーバーや不特定多数が使える共有リンクで運用しないでください。提出コードは学習ログへ保存されません。

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
