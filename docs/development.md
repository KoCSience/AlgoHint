# 開発ガイド

## 構成

- `src/algohint/domain/`: UI非依存のモデル、状態、ポート
- `src/algohint/application/`: 問題選択、提出、Tutor、完了後復習、レポートのユースケース
- `src/algohint/infrastructure/`: JSON／SQLite、LocalJudge、固定／外部LLM学習支援
- `src/algohint/ui/`: Gradio画面と表示整形
- `data/`: 自作教材。実行時ログは `data/runtime/`

プロフィール設定の `last_problem_id` は画面復元専用であり、進捗モデルへ移さないでください。
復習解禁は `CompletionReviewService` が `ProblemProgress` を再確認します。状態分類と
依存方向は[アーキテクチャ](architecture.md#状態の分類)を参照してください。

## 検証

ホストまたはDev Containerで、ロック済みの開発依存を使って実行します。

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
uv run mypy src
uv lock --check
```

Gemma専用サーバーの正本は
[KoCSience/AlgoHint-Gemma-Server](https://github.com/KoCSience/AlgoHint-Gemma-Server)
です。AlgoHint側ではHTTP consumer、固定release manifest、起動scriptだけを保守し、
server実装を重複させません。server変更は独立repoで検証し、そのfull commit SHAを
AlgoHintのmanifestへ更新してconsumer contract testを実行します。

```bash
git clone https://github.com/KoCSience/AlgoHint-Gemma-Server.git \
  ../AlgoHint-Gemma-Server
uv run --project ../AlgoHint-Gemma-Server --locked pytest
uv run pytest -q \
  tests/test_transformers_http_hint_provider.py \
  tests/test_gemma_server_install.py \
  tests/test_remote_ready_wait.py \
  tests/test_startup_scripts.py \
  tests/test_ssh_docker_stack.py
```

ヒント機能を変更した場合は、通常テストに加えてGradio API E2Eと、明示的に有効化する
Playwright E2Eを実行します。Chrome DevTools MCPを含む検出範囲、導入、実行順序、
失敗成果物は[E2Eデバッグガイド](e2e-debugging.md)を参照してください。

根拠付き検索を変更した場合は、公開情報だけのprovider契約、同意拒否、履歴の
データ最小化、固定15ケース評価に加え、ブラウザ上で同意が1回ごとに解除されることを
確認します。

```bash
uv run pytest -q \
  tests/test_research_integration.py \
  tests/test_research_evaluation.py \
  tests/test_gradio_api_e2e.py
ALGOHINT_RUN_BROWSER_E2E=1 uv run pytest -q tests/test_browser_e2e.py
uv run algohint --data-dir data evaluate --json
```

自動テストはライブ評価providerを注入し、確認flag、未測定ケースの選択、再実行、専用DB、
入れ子の実測指標を外部通信なしで検証します。実Exa確認はBillingとServer preflightの
確認後に1ケースだけ実施し、CIでは実行しません。

WSL 2でChrome MCPを利用する場合は、`node`だけでなく`npm`と`npx`もLinux版へ
統一します。Windows PATHとの混在、mise Node 24、Chrome for Testing、Codex設定は
[Chrome DevTools MCP導入ガイド](chrome-devtools-mcp.md#wsl-2のnode環境)を参照してください。

リリース前はロック済みruntime依存を一時ファイルへ書き出して監査します。

```bash
uv export --frozen --no-dev --no-emit-project \
  --format requirements-txt \
  --output-file /tmp/algohint-runtime-requirements.txt
uvx pip-audit --requirement /tmp/algohint-runtime-requirements.txt
```

新しい問題を追加したら、`data/problems/<problem_id>/` に `problem.json`、
`samples.json`、`hidden_tests.json`、`model_solution.py`、`review.json`、
`knowledge.json`の6ファイルを作成し、
`data/curriculum.json` の順序へIDを追加します。問題データを読み込むテスト、固定5問の
検証、正解・境界・誤答のJudgeテスト、レビュー済み知識源のURL・許可domain検証も
追加してください。詳細は
[教材作成ガイド](data-and-content-authoring.md)を参照してください。

## LLM設定と秘密情報

アプリはdotenvファイルやホーム配下のファイルを直接読みません。キーはホーム配下の
権限を制限したファイルなどで利用者が管理し、起動前にシェルの環境変数として
読み込ませます。以下の手順では、POSIXシェルで読み込める変数代入形式の
`$HOME/.config/algohint/credentials` を使用します。拡張子は付けません。

### credentialsの作成と記述例

保存先ディレクトリとファイルは、同じOSユーザーだけが読み書きできる権限にします。

```bash
mkdir -p "$HOME/.config/algohint"
chmod 700 "$HOME/.config/algohint"
"${EDITOR:-vi}" "$HOME/.config/algohint/credentials"
chmod 600 "$HOME/.config/algohint/credentials"
```

ファイルには、利用するプロバイダの変数だけを記述します。次の値は説明用の
プレースホルダーであり、そのままでは接続できません。

```sh
# AlgoHint Coach credentials
# このファイルをGit管理、ログ、スクリーンショットへ含めないこと。

# GPT-5.6を利用する場合
OPENAI_API_KEY='<OpenAIで発行したAPIキー>'

# Geminiを利用する場合
GEMINI_API_KEY='<Gemini用のAPIキー>'

# Gemma 4 12BをTransformers専用サーバーで利用する場合
ALGOHINT_GEMMA_BACKEND='transformers_http'
ALGOHINT_GEMMA_DEPLOYMENT='remote'
ALGOHINT_GEMMA_BASE_URL='http://127.0.0.1:18000/v1'

# Transformers専用サーバーでは必須
ALGOHINT_GEMMA_API_KEY='<Gemmaサーバー用のAPIキー>'

# 任意設定: 起動時の既定プロバイダ
ALGOHINT_LLM_PROVIDER='openai'

# 任意設定: ホスト起動でも開発テストプロフィールを使う
ALGOHINT_ENV='development'
```

モデルIDを既定値から変更する場合だけ、次の変数も追加できます。

```sh
ALGOHINT_OPENAI_MODEL='gpt-5.6-sol'
ALGOHINT_GEMINI_MODEL='gemini-3.6-flash'
ALGOHINT_GEMMA_MODEL='google/gemma-4-12B-it'
```

記述時は次の規則を守ります。

- `変数名='値'` とし、`=` の前後に空白を入れない。
- 値は原則としてシングルクォートで囲み、空白、`$`、`!`などのシェル解釈を防ぐ。
- APIキーにシングルクォートが含まれる場合は手作業でエスケープせず、発行元の仕様を
  確認する。
- `$(...)`、バッククォート、別ファイルの読み込み、外部コマンドを記述しない。
- 第三者から受け取ったcredentialsファイルをそのまま読み込まない。

たとえば、`=` の周囲に空白がある次の形式はシェル変数の代入になりません。

```sh
# 正しい
OPENAI_API_KEY='<APIキー>'

# 誤り
OPENAI_API_KEY = '<APIキー>'
```

### 起動シェルへの読み込み

通常はリポジトリ位置を自動解決する起動スクリプトを使います。credentialsの場所は
`ALGOHINT_CREDENTIALS`で変更できます。

```bash
./scripts/run-algohint.sh
```

スクリプトを使わず手動で起動する場合は、次のように明示的に読み込みます。

次のように読み込んでから、同じシェルでAlgoHintを起動します。

```bash
set -a
. "$HOME/.config/algohint/credentials"
set +a
uv run algohint
```

`set -a` は、credentials内で代入した変数を子プロセスへ自動的に公開します。
このためファイル内へ `export` を繰り返し書く必要はありません。アプリはファイルを
開かず、起動時のプロセス環境だけを参照します。読み込み後に別用途のコマンドを実行する
場合は、キーがその子プロセスにも渡る点に注意してください。

### Gemini接続診断

GeminiがRuleBasedヒントへ退避する場合は、同じシェルで次を実行します。

```bash
uv run algohint doctor --provider gemini
```

doctorは設定中のモデル情報を取得し、APIキーの存在、認証・権限、モデル到達性、
ネットワークを確認します。問題文、提出コード、質問、会話履歴は送信しません。
成功時は終了コード`0`、失敗時は`1`を返し、APIキーやGoogleの生レスポンスを
表示しません。

```text
Gemini診断: OK provider=gemini model=gemini-3.6-flash backend=developer_api
```

AlgoHintは`GEMINI_API_KEY`を利用するGemini Developer APIへ接続を固定します。
`GOOGLE_GENAI_USE_VERTEXAI`や`GOOGLE_GENAI_USE_ENTERPRISE`が親プロセスに存在しても、
Vertex AI／Enterpriseのアクセストークン認証へ切り替えません。Vertex AI対応が必要に
なった場合は、認証・課金・リージョンの境界が異なるため別アダプタとして追加します。

失敗時は、次の安全化された`reason_code`に従って対処します。

| reason_code | 主な意味 | 対処 |
|---|---|---|
| `not_configured` | キーがプロセスへ渡っていない | credentialsを同じシェルで読み込み直す |
| `invalid_request` | SDKとAPIの要求形式が不整合 | 依存ロックとモデル設定を確認する |
| `authentication_or_permission` | キー不正、権限不足、課金・地域条件 | Google AI Studioのキー、プロジェクト、課金を確認する |
| `model_not_found` | モデル名またはアクセス権が不正 | `ALGOHINT_GEMINI_MODEL`と利用可能モデルを確認する |
| `rate_or_quota_exceeded` | レートまたは割当量超過 | 時間を置き、利用上限と課金枠を確認する |
| `timeout` | 通信または応答のタイムアウト | ネットワークを確認して再実行する |
| `provider_unavailable` | Gemini側の一時障害 | 時間を置き、サービス状態を確認する |
| `empty_or_blocked_response` | 空応答または安全設定によるブロック | 質問内容を見直し、再試行する |
| `invalid_structured_response` | 応答JSONが共通スキーマ不適合 | SDK・モデル互換性を確認する |
| `client_lifecycle_error` | SDKクライアントが通信完了前に閉じられた | 依存ロックを確認し、再現時はバグとして報告する |
| `unknown_provider_error` | 上記以外 | development詳細診断でSDK例外を確認する |

productionログにはprovider、model、reason_code、検証済みprovider detail code、
HTTPステータス、再試行可能性、例外クラスだけを記録します。APIキー、プロンプト、
コード、生レスポンスは記録しません。
429と5xxの再試行はGoogle SDKへ任せ、AlgoHintから重複して再試行しません。

開発中に原因を詳しく確認する場合は、次を実行します。

```bash
ALGOHINT_ENV=development uv run algohint doctor --provider gemini --verbose
```

`--verbose`はdevelopmentでだけ有効です。モデル情報取得で発生したSDK例外メッセージ、
例外チェーン、スタックトレースを端末へ表示します。通常のヒント生成でも
`ALGOHINT_ENV=development`なら、同じ詳細を`gemini_provider_exception`ログへ記録します。
実際の`GEMINI_API_KEY`、`Authorization`、Bearerトークン、`x-goog-api-key`は必ず
`[REDACTED]`へ置換します。

詳細にはGoogle SDKが返した応答エラーが含まれることがあるため、共有前に内容を確認して
ください。AlgoHintから問題文、提出コード、プロンプトを追加でログ出力することは
ありません。developmentログをproduction環境で有効にしないでください。

Geminiアダプタは、生成応答の`text`取得またはdoctorのモデル情報取得が完了するまで
親SDKクライアントを強参照し、その後に1回だけ明示的にcloseします。close自体の失敗は
正常なヒントや主要例外を上書きしません。`client_lifecycle_error`または
`Cannot send a request, as the client has been closed`が再発した場合は、
[E2Eデバッグガイド](e2e-debugging.md)の偽プロバイダ回帰、doctor、実API 1要求の順で
切り分けてください。

### Gemma接続診断

vLLMが導入できないLinuxホストでは、PyTorch／Hugging Face Transformers版の専用
FastAPIサーバーを利用できます。利用者のホーム配下への配置、認証キー作成、
固定revisionのモデル取得、SSHトンネル、起動・停止・ロールバックは
[Gemma Server接続ガイド](gemma-server.md)を参照してください。

SSHトンネルとGemmaサーバーを個別起動して直接doctorを実行することもできますが、通常は
server、tunnel、health、認証付きmodel discoveryを同じ接続先で検証するmanaged
launcherを使用します。

```bash
ALGOHINT_CREDENTIALS="$HOME/.config/algohint/gemma-remote-credentials" \
  ./scripts/run-ssh-stack.sh --keep-remote doctor --provider gemma
```

同一ホストでは`./scripts/run-local-stack.sh`、別ホストでは
`$HOME/.config/algohint/gemma-ssh-target`へSSH aliasを設定してから
`./scripts/run-ssh-stack.sh`を使うと、Gemma、トンネル、AlgoHintを順に起動できます。
設定fileの作成と検証は[Gemma Server接続ガイド](gemma-server.md#1-ssh接続の確認)を
参照してください。各スクリプトは自分が新規起動したGemmaだけを終了時に停止します。
managed launcherはcredentials読込後も検証済みloopback接続先を再適用するため、
credentials fileに残った古いbackend、deployment、base URLで接続先が変わりません。

AlgoHintもDockerで動かす経路は`compose.ssh.yaml`と
`scripts/run-ssh-docker-stack.sh`が担当します。変更時は、Compose展開後のloopback
listenerとhost network、資格情報権限、固定releaseの導入・再検査、remote
`container: running|not-running`契約、既存remoteの非所有、doctor失敗時cleanupを
`test_ssh_docker_stack.py`で検証します。

通常doctorは`/v1/models`だけを呼び、問題文、提出コード、質問、履歴を送りません。
成功時は設定したbackend、deployment、modelを表示します。`transformers_http`を
選択した場合、`ALGOHINT_GEMMA_API_KEY`は必須です。`remote`を明示すると、
SSHトンネルのURLが`127.0.0.1`でもUIで外部送信同意を要求します。

実生成経路まで確認する場合は、Gemmaだけに明示的なprobeを指定します。

```bash
uv run algohint doctor --provider gemma --generation-probe
```

probeはbodyを送らず、Gemma Serverが所有する固定textだけを最大64 token生成します。
`502`/`503`のresponseは`extra=forbid`のclosed schemaで検証し、既知codeだけを
`provider_detail_code`として表示します。不正JSON、未知code、余分なfield、HTMLは
本文を破棄して`unknown_generation_failure`へ閉じます。

| 用途                  | 環境変数                                      | 秘密               |
| --------------------- | --------------------------------------------- | ------------------ |
| OpenAI                | `OPENAI_API_KEY`                              | はい               |
| Gemini                | `GEMINI_API_KEY`                              | はい               |
| 認証付きGemmaサーバー | `ALGOHINT_GEMMA_API_KEY`                      | サーバー構成による |
| Gemma接続先           | `ALGOHINT_GEMMA_BASE_URL`                     | 通常はいいえ       |
| Gemma実装方式         | `ALGOHINT_GEMMA_BACKEND`                      | いいえ             |
| Gemma配置場所         | `ALGOHINT_GEMMA_DEPLOYMENT`                   | いいえ             |
| Gemma health監視間隔  | `ALGOHINT_GEMMA_MONITOR_INTERVAL_SECONDS`     | いいえ             |
| 起動時のモデル選択    | `ALGOHINT_LLM_PROVIDER=openai\|gemma\|gemini` | いいえ             |
| 開発プロフィール      | `ALGOHINT_ENV=development`                    | いいえ             |

既定モデルは `ALGOHINT_OPENAI_MODEL`、`ALGOHINT_GEMINI_MODEL`、
`ALGOHINT_GEMMA_MODEL` で上書きできます。モデル選択はプロフィールへ保存されますが、
キーとクラウド送信への同意は保存されません。

`endpoint_unreachable`はHTTP応答前の接続失敗を表します。`provider_unavailable`は
ready=false、HTTP 502/503、または接続後のtransport障害に使用します。Gemma Serverの
closed detail codeがある場合はGPU memory、CUDA、device placement、parserを追加で
区別します。この区別により、前者はserver/tunnelの起動確認、後者はgeneration probeと
server状態確認へ誘導します。生成POSTは自動再送せず、失敗した操作だけをRuleBasedへ
fallbackします。

### この形式の理由

このファイルの目的は、少数の文字列を起動プロセスへ渡すことです。たとえばYAMLやTOMLは構造化されたアプリ設定には適していますが、そのままでは環境変数になりません。採用すると、ファイルの探索、パーサー、キー名の変換、型変換、構文エラー処理をアプリまたは専用起動スクリプトへ追加する必要があります。また、アプリ自身が秘密ファイルを開く責務を持つことになり、現在の「秘密値はプロセス環境からだけ受け取る」境界が複雑になります。

シェル変数代入形式なら、追加ライブラリや独自変換なしでホスト、Docker Compose、Dev Containerへ同じ環境変数名を渡せます。一方、この形式は単なるデータではなくシェルによって評価されます。そのため、権限を`600`に限定し、コマンドを記述せず、自分で作成したファイルだけを読み込むことを前提とします。

Dev Containerはホスト側の上記キーとGemma接続先をコンテナ環境へ受け渡し、
`ALGOHINT_ENV=development` により予約済みの「開発テスト」プロフィールを既定にします。
ホスト側で未設定の変数は空のままで、外部接続は行われません。

## コンテナ開発

`.devcontainer/devcontainer.json`はDockerfileの`development`ターゲットを使います。ソースは`/workspace`へマウントし、依存環境だけを名前付きボリュームに分離するため、ホストのPythonや`.venv`には依存しません。

runtimeイメージまたはCompose構成を変更した場合は、通常のPython検証に加えて次を実行します。

```bash
docker compose config --quiet
docker build --target runtime --tag algohint:local .
docker build --target development --tag algohint:development .
docker compose up --detach
docker compose ps
```

WSLのメモリが限られる場合は、ビルドや品質検査を並列実行しません。Dev ContainerにはCPU・メモリ・PID上限を設定し、開発時のキャッシュはbind mountしたリポジトリ外へ分離しています。

詳細な起動・停止・永続化手順は[Docker運用ガイド](docker.md)を参照してください。
