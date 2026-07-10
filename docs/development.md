# 開発ガイド

## 構成

- `src/algohint/domain/`: UI非依存のモデル、状態、ポート
- `src/algohint/application/`: 問題選択、提出、ヒント、解説、レポートのユースケース
- `src/algohint/infrastructure/`: JSON、LocalJudge、固定ヒント
- `src/algohint/ui/`: Gradio画面と表示整形
- `data/`: 自作教材。実行時ログは `data/runtime/`

## 検証

```bash
uv run pytest
uv run ruff check .
uv run mypy src
```

新しい問題を追加したら、`data/problems/<problem_id>/` に4ファイルを作成し、`data/curriculum.json` の順序へIDを追加します。問題データを読み込むテストと、正解・境界・誤答のJudgeテストも追加してください。
