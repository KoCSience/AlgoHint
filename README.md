# AlgoHint Coach

AlgoHint Coach は、完成コードを先に示さず、段階的ヒントと実行判定で考える力を支援するローカル向けアルゴリズム学習アプリです。

## MVPの機能

- L0〜L3を対象にした自作5問と、公開・隠しテスト
- Pythonの LocalJudge（AC / WA / RE / TLE / CE / IE）
- 非解答型の段階的ヒントと、AC・ギブアップ後だけ表示する解説
- ローカルプロフィール別の学習ログと苦手タグレポート
- 通常画面から分離した教師モード

## 起動

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

提出コードはローカルプロセスで実行されます。時間・メモリ・出力の制限は設けますが、Dockerのような完全隔離ではありません。公開サーバーや不特定多数が使える共有リンクで運用しないでください。提出コードは学習ログへ保存されません。

詳細は [ドキュメント](docs/development.md) を参照してください。

## 開発時の検証

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```
