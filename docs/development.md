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
読み込ませます。たとえば秘密ファイルを
`$HOME/.config/algohint/credentials` に用意した場合は、次のように起動します。

```bash
chmod 600 "$HOME/.config/algohint/credentials"
set -a
. "$HOME/.config/algohint/credentials"
set +a
uv run algohint
```

秘密ファイルには利用するプロバイダの変数だけを定義します。値をコマンド履歴、
Git管理ファイル、ログ、スクリーンショットへ残さないでください。

| 用途 | 環境変数 | 秘密 |
|---|---|---|
| OpenAI | `OPENAI_API_KEY` | はい |
| Gemini | `GEMINI_API_KEY` | はい |
| 認証付きGemmaサーバー | `ALGOHINT_GEMMA_API_KEY` | サーバー構成による |
| Gemma接続先 | `ALGOHINT_GEMMA_BASE_URL` | 通常はいいえ |
| 起動時のモデル選択 | `ALGOHINT_LLM_PROVIDER=openai\|gemma\|gemini` | いいえ |
| 開発プロフィール | `ALGOHINT_ENV=development` | いいえ |

既定モデルは `ALGOHINT_OPENAI_MODEL`、`ALGOHINT_GEMINI_MODEL`、
`ALGOHINT_GEMMA_MODEL` で上書きできます。モデル選択はプロフィールへ保存されますが、
キーとクラウド送信への同意は保存されません。

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
