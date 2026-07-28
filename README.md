# AlgoHint Coach

AlgoHint Coach は、完成コードを先に示さず、段階的ヒントと実行判定で考える力を支援するローカル向けアルゴリズム学習アプリです。

## MVPの機能

- L0〜L3を対象にした自作5問と、公開・隠しテスト
- Pythonの LocalJudge（AC / WA / RE / TLE / CE / IE）
- 非解答型の段階的ヒントと、AC・ギブアップ後だけ表示する解説
- ローカルプロフィール別の学習ログと苦手タグレポート
- 通常画面から分離した教師モード

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
uv run algohint
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
```

### 環境構築について

uvが入っていない場合はuvをインストール：[Installation | uv](https://docs.astral.sh/uv/getting-started/installation/#standalone-installer)

```shell
uv sync
```
