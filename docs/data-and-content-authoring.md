# 教材作成ガイド

問題はすべて自作します。外部サイトの問題文、テストケース、解答コードを転載しません。

各問題ディレクトリには次を置きます。

- `problem.json`: 問題文、タグ、5段階以上のヒント、解説
- `samples.json`: 学習者へ表示するテストケース
- `hidden_tests.json`: Judge専用テストケース
- `model_solution.py`: 教師モード専用の参照実装
- `review.json`: 完了後に出す、作成者確認済みの選択式小テスト5問

ヒントは、問題理解、計算量、方針、実装注意、デバッグ観点の順で少しずつ具体化します。完成コード、コードブロック、提出可能な疑似コード、「答えは」のような断定を含めません。

各問題に少なくとも2件の公開サンプルと、最小値・最大値・境界・重複・存在しないケースなどを含む隠しテストを追加してください。

## 復習小テスト

`review.json` は生成AIで実行時に作らず、教材と一緒にレビュー・版管理します。毎回同じ
内容を決定的に採点でき、正解を学習者向けレスポンスへ採点前に混ぜないためです。

必ず次の5トピックを一問ずつ含めます。

| `topic` | 確認する内容 |
|---|---|
| `algorithm` | 中心となるアルゴリズムや操作 |
| `problem_framing` | 入出力、状態、目標を整理する方法 |
| `complexity` | 時間・空間計算量と制約との関係 |
| `edge_cases` | 境界値、最小ケース、失敗しやすい条件 |
| `implementation` | 言語上の実装注意、可読性、保守性 |

最小構造は次のとおりです。実際には `questions` に5問を置きます。

```json
{
  "version": 1,
  "questions": [
    {
      "question_id": "algorithm-main-step",
      "topic": "algorithm",
      "prompt": "この問題の中心処理はどれですか？",
      "options": [
        {"option_id": "correct-step", "text": "必要な処理"},
        {"option_id": "distractor-a", "text": "もっともらしい誤り"},
        {"option_id": "distractor-b", "text": "別の誤り"}
      ],
      "correct_option_id": "correct-step",
      "explanation": "正解の理由と、問題を捉える観点を説明します。"
    }
  ]
}
```

作成時は次を守ります。

- `version` は1以上とし、設問や正解の意味を変えたら増やす。
- `question_id` と `option_id` は問題内で安定させ、小文字英数字・`_`・`-`だけを使う。
- 各問の選択肢は3〜4件、IDは重複不可、`correct_option_id` は必ず選択肢内に置く。
- 単純な暗記だけでなく、「なぜその方針か」「制約から何を判断するか」を問う。
- 誤答選択肢は曖昧さや複数正解を避け、学習上ありがちな誤解を表す。
- `explanation` は正解の断定だけでなく、次の問題にも使える検討手順を書く。
- 問題文、模範解答、隠しテストと矛盾しないことを人が確認する。

履歴は採点時点の設問・選択肢・正解・解説をスナップショット保存します。そのため、
古いIDを再利用して別の意味へ変えないでください。教材を更新しても過去履歴は書き換えません。

## 追加時の検証

問題追加・変更時は、少なくとも次を確認します。

```bash
uv run pytest -q tests/test_problem_repository.py tests/test_local_judge.py
uv run pytest -q tests/test_completion_review.py
uv run ruff check data src tests
```

読み込み時には、5問ちょうどであること、5トピックが一度ずつ揃うこと、ID重複がないこと、
正解IDが存在することをPydantic境界で検証します。正答コード、境界入力、代表的な誤答も
Judgeテストへ追加してください。
