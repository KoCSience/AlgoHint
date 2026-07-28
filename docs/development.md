# 開発ガイド

## 構成

- `src/algohint/domain/`: UI非依存のモデル、状態、ポート
- `src/algohint/application/`: 問題選択、提出、ヒント、解説、レポートのユースケース
- `src/algohint/infrastructure/`: JSON、LocalJudge、固定ヒント
- `src/algohint/ui/`: Gradio画面と表示整形
- `data/`: 自作教材。実行時ログは `data/runtime/`

## 検証

ホストまたはDev Containerで、ロック済みの開発依存を使って実行します。

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
uv run mypy src
```

新しい問題を追加したら、`data/problems/<problem_id>/` に4ファイルを作成し、`data/curriculum.json` の順序へIDを追加します。問題データを読み込むテストと、正解・境界・誤答のJudgeテストも追加してください。

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
