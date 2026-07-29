# 開発ガイド

## 構成

- `src/algohint/domain/`: UI非依存のモデル、状態、ポート
- `src/algohint/application/`: 問題選択、提出、Tutor、解説、レポートのユースケース
- `src/algohint/infrastructure/`: JSON、LocalJudge、固定／外部LLMヒント
- `src/algohint/ui/`: Gradio画面と表示整形
- `data/`: 自作教材。実行時ログは `data/runtime/`

## 検証

ホストまたはDev Containerで、ロック済みの開発依存を使って実行します。

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
uv run mypy src
uv lock --check
```

リリース前はロック済みruntime依存を一時ファイルへ書き出して監査します。

```bash
uv export --frozen --no-dev --no-emit-project \
  --format requirements-txt \
  --output-file /tmp/algohint-runtime-requirements.txt
uvx pip-audit --requirement /tmp/algohint-runtime-requirements.txt
```

新しい問題を追加したら、`data/problems/<problem_id>/` に4ファイルを作成し、`data/curriculum.json` の順序へIDを追加します。問題データを読み込むテストと、正解・境界・誤答のJudgeテストも追加してください。

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

# Gemma 4 12Bを利用する場合
ALGOHINT_GEMMA_BASE_URL='http://127.0.0.1:8000/v1'

# Gemmaサーバーが認証を要求する場合だけ設定
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

| 用途                  | 環境変数                                      | 秘密               |
| --------------------- | --------------------------------------------- | ------------------ |
| OpenAI                | `OPENAI_API_KEY`                              | はい               |
| Gemini                | `GEMINI_API_KEY`                              | はい               |
| 認証付きGemmaサーバー | `ALGOHINT_GEMMA_API_KEY`                      | サーバー構成による |
| Gemma接続先           | `ALGOHINT_GEMMA_BASE_URL`                     | 通常はいいえ       |
| 起動時のモデル選択    | `ALGOHINT_LLM_PROVIDER=openai\|gemma\|gemini` | いいえ             |
| 開発プロフィール      | `ALGOHINT_ENV=development`                    | いいえ             |

既定モデルは `ALGOHINT_OPENAI_MODEL`、`ALGOHINT_GEMINI_MODEL`、
`ALGOHINT_GEMMA_MODEL` で上書きできます。モデル選択はプロフィールへ保存されますが、
キーとクラウド送信への同意は保存されません。

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
