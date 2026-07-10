# AlgoHint Coach 完全版仕様書・設計書 v4

作成日: 2026-07-10  
対象: アルゴリズム、プログラミングテスト、競技プログラミング初級〜中級向け学習支援システム  
システム名: AlgoHint Coach  
想定実装言語: Python  
UI方針: MVPでは Gradio を採用し、将来的に Flet へ移行可能な構成にする  
AI方針: MVPでは Gemma 4 12B を既定モデル候補とし、Gemini API などに切り替え可能な LLM 抽象化層を設ける  
Judge方針: MVPでは内製 LocalJudge を必須とし、online-judge-tools/oj 連携は発展機能として扱う  

---

## 0. 本仕様書の位置づけ

本仕様書は、これまで作成した <File>algohint_coach_spec.md</File>、<File>algohint_learning_system_spec_v2_gradio_gemma.md</File>、<File>algohint_learning_system_spec_v3_judge_oj.md</File> を統合し、改めて要件、構成、学習フロー、Judgeフロー、教材利用方針、実装設計をまとめた完全版である。既存仕様では、AlgoHint Coach は就活プログラミングテストや競技プログラミング初級問題に取り組む学習者に、完成コードや直接解答ではなく、段階的ヒント、正誤判定、根拠付き解説、学習ログを提供する学習支援AIとして定義されていた。citeturn6search2turn6search3

また、v3仕様では、既存仕様に不足していた「問題」「ジャッジ」「隠し回答例」「サンプルケース取得」「オンラインジャッジ連携」を補うため、内製Judge、oj連携Judge、外部提出Judgeの3層方針が整理されていた。特に、MVPでは内製Judgeを必須とし、online-judge-tools/oj はサンプル取得とローカルテスト補助に限定する判断が示されていた。citeturn6search1

---

## 1. コンセプト

AlgoHint Coach は、就活プログラミングテストや競技プログラミング初級〜中級入口の問題に取り組む学習者に対して、完成コードや直接解答ではなく、段階的ヒント、実行による正誤判定、根拠付き解説、学習ログ、苦手分野の可視化を提供する学習支援AIである。

ユーザーは、アルゴ式のような体系的な流れで基礎から学び、AtCoder Beginners Selection のような競技プログラミング入門題材、Codility のような就活・技術選考寄りの問題構成、paiza アルゴリズム Python のようなPython向けアルゴリズム学習項目を参考にした自作問題へ取り組む。既存仕様でも、AtCoder Beginners Selection は競技プログラミング入門、Codility Lessons は技術選考・コーディングテスト風トピック設計、アルゴ式は日本語で体系的に学ぶカリキュラム設計、paiza はPython向けアルゴリズム学習項目として位置づけられていた。citeturn6search2turn6search3

本システムの学習体験は、以下の流れを基本とする。

1. 学習者が現在の到達度・学習目的に応じた問題を選ぶ。
2. 問題文、制約、入出力形式、サンプルを読む。
3. 学習者が自分で方針を考え、Pythonコードを書く。
4. システムが実際にコードを実行して、AC / WA / RE / TLE / CE / IE を判定する。
5. 不正解の場合、完成コードではなく「惜しい点」「見直す観点」「次に確認すべきテストケース」をヒントとして出す。
6. 正解後またはギブアップ後に、解法の考え方、計算量、実装上の注意、参考資料を示す。
7. 学習ログから、苦手タグ、平均ヒント数、平均提出回数、正答率を可視化する。

---

## 2. 対象範囲

### 2.1 主対象

- プログラミングテスト対策
- アルゴリズムとデータ構造の基礎
- Pythonによる標準入力・標準出力形式の問題演習
- 競技プログラミング初級から中級入口
- 可能なら AtCoder Beginner Contest の D、E 問題程度へ進むための基礎固め

### 2.2 学習トピック

| 分類        | トピック                            |
| --------- | ------------------------------- |
| Python基礎  | 標準入力、標準出力、条件分岐、ループ、リスト、辞書、集合、関数 |
| 問題理解      | 問題文読解、制約確認、サンプル手計算、出力形式確認       |
| 計算量       | O記法、全探索の限界、制約からの方針選択            |
| 基本アルゴリズム  | 全探索、線形探索、ソート、累積和、二分探索、スタック、キュー  |
| データ構造     | 配列、集合、辞書、木、グラフ、優先度付きキュー         |
| グラフ       | BFS、DFS、最短距離、グリッド探索             |
| 数学        | 素数、約数、最大公約数、最小公倍数、余り、組合せ基礎      |
| 応用入口      | 貪欲法、DP基礎、しゃくとり法、いもす法            |
| コーディングテスト | 境界条件、例外的入力、計算量改善、デバッグ方針         |

---

## 3. 教材・題材の位置づけ

| 参考元                         | 仕様上の役割             | 使用方針                                                                                                                                   |
| --------------------------- | ------------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| アルゴ式                        | 学習順序・体系化           | Python入門、ロジック実装、アルゴリズム初級・中級の流れを参考に、学習ロードマップを構成する                                                                                       |
| Codility Lessons            | 就活・技術選考型トピック       | Iterations、Arrays、Time Complexity、Prefix Sums、Sorting、Stacks and Queues、Binary Search、Greedy、Dynamic Programmingなどの分類を参考に、自作類題と解説観点を作る |
| AtCoder Beginners Selection | 競技プログラミング入門題材      | 公式問題文・解答コードは転載せず、入門問題セットの流れと難易度感を参考にする                                                                                                 |
| paiza アルゴリズム Python         | Python向けアルゴリズム学習項目 | 線形探索、計算量、ソート、素数、ユークリッド互除法、累積和、二分探索、スタック・キュー、木、BFS・DFSなどをタグ設計へ反映する                                                                      |

<External>AtCoder Beginners Selection</External> は、AtCoderに登録したが次に何をすればよいか分からない人に向けて作られた初心者向け問題集として説明されている。citeturn6search190  
<External>Codility Lesson 1 Iterations</External> には、BinaryGap という easy タスクがあり、整数の2進表現における最長の0列を見つける問題として説明されている。citeturn6search157  
<External>アルゴ式 トピック一覧</External> には、Python入門、Python基礎、ロジック実装初級・中級、アルゴリズム初級・中級・上級、整数論的アルゴリズムなどのトピックが掲載されている。citeturn6search178  
<External>paiza 新・アルゴリズムとデータ構造入門 Python編</External> では、線形探索、計算量の見積りとO記法、ソート、素数、ユークリッドの互除法、累積和、二分探索、スタック・キュー、木、BFS・DFSなどを学べると説明されている。citeturn6search160

### 3.1 著作権・利用方針

- 外部サイトの問題文・解答コードは転載しない。
- 問題テーマ、トピック分類、難易度傾斜、学習順序を参考にする。
- 実際にシステムに登録する問題文、テストケース、ヒント、解説、模範解答は自作する。
- 外部問題を扱う場合は、URLを参照情報として保持し、必要に応じて `online-judge-tools/oj` でサンプル取得のみ行う。

---

## 4. 要件定義

### 4.1 機能要件

| ID     | 要件                                                        | 優先度 | MVP |
| ------ | --------------------------------------------------------- | ---:| ---:|
| FR-001 | 問題DBを保持できる                                                | S   | ○   |
| FR-002 | 学習ロードマップに沿って問題を提示できる                                      | S   | ○   |
| FR-003 | 問題文、制約、入力形式、出力形式、サンプルを表示できる                               | S   | ○   |
| FR-004 | 学習者がPythonコードを提出できる                                       | S   | ○   |
| FR-005 | LocalJudgeでユーザーコードを実行し、AC / WA / RE / TLE / CE / IEを判定できる | S   | ○   |
| FR-006 | サンプルケースと隠しテストケースを分けて管理できる                                 | S   | ○   |
| FR-007 | 隠しテストの詳細を学習者に表示しない                                        | S   | ○   |
| FR-008 | 模範解答を隠し機能として保持できる                                         | S   | ○   |
| FR-009 | 正解後またはギブアップ後のみ解説を表示できる                                    | S   | ○   |
| FR-010 | 不正解時に完成コードではなく段階的ヒントを提示できる                                | S   | ○   |
| FR-011 | ヒントに答え漏洩がないか検査できる                                         | S   | ○   |
| FR-012 | 学習ログを保存できる                                                | A   | ○   |
| FR-013 | 正答率、平均ヒント数、平均提出回数、苦手タグを算出できる                              | A   | ○   |
| FR-014 | Gradioで問題演習、ヒント、コード提出、解説、学習ログを操作できる                       | S   | ○   |
| FR-015 | LLMプロバイダをGemma、Gemini API、Mock、RuleBasedで切り替えられる          | A   | △   |
| FR-016 | online-judge-tools/ojで外部問題サンプルを取得できる                      | B   | △   |
| FR-017 | oj testで外部問題サンプルをローカル実行できる                                | B   | △   |
| FR-018 | oj submitによる外部提出ができる                                      | C   | ×   |
| FR-019 | Flet移行を見据えて中核処理をUI非依存にする                                  | A   | ○   |
| FR-020 | 将来、D/E問題相当の応用問題へ拡張できる                                     | B   | △   |

### 4.2 非機能要件

| ID      | 分類     | 要件                                | 優先度 |
| ------- | ------ | --------------------------------- | ---:|
| NFR-001 | 使用性    | Gradioでブラウザから直感的に操作できる            | S   |
| NFR-002 | 正確性    | 正誤判定はLLMではなくテストケース実行を主とする         | S   |
| NFR-003 | 安全性    | ユーザーコード実行にはtimeoutを設定する           | S   |
| NFR-004 | 安全性    | MVPではローカルまたはColab上の学習用途に限定する      | S   |
| NFR-005 | 保守性    | 問題、ヒント、Judge、解説、ログ、LLMを分離する       | S   |
| NFR-006 | 拡張性    | UI層を差し替えられる構造にする                  | A   |
| NFR-007 | 拡張性    | LLMClientでモデルやAPIを切り替えられる         | A   |
| NFR-008 | 再現性    | 問題DB、テストケース、ログをJSON/Markdownで保存する | A   |
| NFR-009 | 著作権配慮  | 外部問題文・解答コードを転載しない                 | S   |
| NFR-010 | 秘密情報保護 | APIキーは環境変数またはColab Secretsで扱う     | S   |

---

## 5. 全体構成

```text
AlgoHint Coach
├── UI Layer
│   ├── GradioApp（MVP）
│   └── FletApp（将来）
│
├── Application Layer
│   ├── ProblemSelectionUseCase
│   ├── SubmitCodeUseCase
│   ├── RequestHintUseCase
│   ├── ShowExplanationUseCase
│   └── ShowLearningReportUseCase
│
├── Domain Layer
│   ├── Problem
│   ├── TestCase
│   ├── ModelSolution
│   ├── JudgePolicy
│   ├── JudgeResult
│   ├── ProblemSession
│   └── LearningLog
│
├── Service Layer
│   ├── ProblemRepository
│   ├── CurriculumPlanner
│   ├── HintEngine
│   ├── SafetyChecker
│   ├── LocalJudgeRunner
│   ├── OJToolJudgeRunner
│   ├── ExplanationEngine
│   ├── LearningTracker
│   └── EvaluationEngine
│
└── Infrastructure Layer
    ├── JSONStorage
    ├── SubprocessRunner
    ├── LLMClient
    ├── GemmaLocalClient
    ├── GeminiApiClient
    ├── MockLLMClient
    └── RuleBasedHintClient
```

既存v2仕様では、GradioをUI層に閉じ込め、中核処理を `core/` や `application/` に置き、GradioやFletに依存させない方針が示されていた。citeturn6search3 これは本仕様でも採用する。

---

## 6. 学習フロー

### 6.1 標準フロー

```text
1. 学習者がロードマップまたはタグから問題を選ぶ
2. システムが問題文、制約、入力形式、出力形式、サンプルを表示する
3. 学習者が方針を考える
4. 必要に応じてヒント1を要求する
5. 学習者がPythonコードを書く
6. コードを提出する
7. LocalJudgeがサンプルケース・隠しテストケースで実行する
8. 判定結果を表示する
9. WA / RE / TLE の場合は、失敗種別に応じたヒントを提示する
10. ACの場合は解説を表示可能にする
11. 学習ログを更新する
12. 苦手タグと次の推奨問題を表示する
```

### 6.2 不正解時のヒントフロー

| 判定  | ヒント方針                                          |
| --- | ---------------------------------------------- |
| WA  | サンプル失敗なら入出力の差分を示す。隠しテスト失敗なら境界条件・制約・添字・例外ケースを示す |
| RE  | エラー種別、入力読み取り、型変換、空配列、添字範囲を確認させる                |
| TLE | 計算量、二重ループ、探索範囲、前処理、データ構造選択を確認させる               |
| CE  | 構文、インデント、括弧、未定義変数を確認させる                        |
| IE  | Judge側エラーとして、システムメッセージを表示する                    |

### 6.3 正解後・ギブアップ後のフロー

- 解説を表示する。
- 解法の発想を説明する。
- 計算量を説明する。
- 実装上の注意を示す。
- 参考トピックを表示する。
- 模範解答コードは、通常は表示しないか、teacher_mode / after_solved 設定に従う。

---

## 7. カリキュラム設計

### 7.1 学習ロードマップ

| Level | 目的        | 主な題材            | 参考元                                    |
| ----- | --------- | --------------- | -------------------------------------- |
| L0    | Python入出力 | 標準入力、出力、型変換     | アルゴ式、paiza                             |
| L1    | ロジック実装    | 条件分岐、ループ、配列     | アルゴ式、AtCoder Beginners Selection       |
| L2    | 基本探索      | 線形探索、最大最小、個数、位置 | paiza、Codility Arrays                  |
| L3    | 計算量       | O記法、全探索限界、改善方針  | paiza、Codility Time Complexity         |
| L4    | 前処理       | 累積和、区間和、いもす法    | paiza、Codility Prefix Sums             |
| L5    | 探索高速化     | 二分探索、単調性、境界     | paiza、Codility Binary Search           |
| L6    | データ構造     | スタック、キュー、辞書、集合  | paiza、Codility Stacks and Queues       |
| L7    | グラフ基礎     | BFS、DFS、グリッド探索  | paiza、AtCoder ABC C/D入口                |
| L8    | 応用入口      | 貪欲法、DP基礎、しゃくとり法 | Codility Greedy / DP、AtCoder ABC D/E入口 |

### 7.2 問題セット構成

| セット          | 目的             | 問題数目安 | source_style     |
| ------------ | -------------- | -----:| ---------------- |
| Starter      | 標準入力・条件分岐・ループ  | 5     | algo-method-like |
| AtCoder入門    | 競プロ形式に慣れる      | 10    | atcoder-like     |
| Codility型    | 技術選考形式に慣れる     | 10    | codility-like    |
| Pythonアルゴリズム | Pythonで定番手法を学ぶ | 10    | paiza-like       |
| ABC D/E入口    | 中級入口の考え方を学ぶ    | 5〜10  | atcoder-abc-like |

---

## 8. データモデル

### 8.1 Problem

```python
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Problem:
    problem_id: str
    title: str
    difficulty: str
    level: str
    tags: list[str]
    source_style: str
    learning_goal: str
    statement: str
    constraints: str
    input_format: str
    output_format: str
    samples: list["TestCase"]
    hidden_tests: list["TestCase]
    generated_tests: list["TestCase"]
    hints: list["Hint"]
    explanation_id: str
    model_solution_id: str
    sources: list[str]
    external_judge_url: str | None = None
    judge_policy_id: str = "default_python_local"
```

### 8.2 TestCase

```python
@dataclass(frozen=True)
class TestCase:
    case_id: str
    input_text: str
    expected_output: str
    visibility: str  # sample, hidden, generated, downloaded
    score_weight: int = 1
```

### 8.3 Hint

```python
@dataclass(frozen=True)
class Hint:
    hint_id: str
    level: int
    category: str  # understanding, complexity, approach, implementation, debug
    text: str
    leak_checked: bool = False
```

### 8.4 ModelSolution

```python
@dataclass(frozen=True)
class ModelSolution:
    solution_id: str
    problem_id: str
    language: str
    code: str
    explanation: str
    visibility: str  # hidden, teacher_only, after_solved
```

### 8.5 JudgeResult

```python
@dataclass(frozen=True)
class JudgeResult:
    status: str  # AC, WA, RE, TLE, CE, IE
    passed_count: int
    total_count: int
    failed_case_id: str | None
    failed_case_visibility: str | None
    stdout: str | None
    stderr: str | None
    expected_output: str | None
    elapsed_ms: int | None
    message_for_learner: str
    debug_message: str | None
```

---

## 9. Judge設計

### 9.1 Judge方式

| 方式              | 内容                                     | MVP | 判断       |
| --------------- | -------------------------------------- | ---:| -------- |
| LocalJudge      | 自作問題DBのサンプル・隠しテストでコードを実行する             | ○   | MVP必須    |
| OJ Sample Judge | `oj download` と `oj test` で外部問題サンプルを扱う | △   | 発展機能     |
| OJ Submit Judge | `oj submit` で外部ジャッジへ提出する               | ×   | MVPでは不採用 |
| Docker Judge    | コンテナ隔離で実行する                            | △   | 実運用向け発展  |

<External>online-judge-tools/oj</External> は、サンプルケースのダウンロード、追加テストケース生成、コードテスト、提出を自動化するコマンドとして説明されている。citeturn6search172 <External>online-judge-tools</External> のPyPIページでは、`oj download [--system] URL`、`oj login URL`、`oj submit [URL] FILE`、`oj test [-c COMMAND] [TEST...]`、`oj generate-input`、`oj generate-output` が利用例として示されている。citeturn6search176

### 9.2 LocalJudge処理フロー

```text
1. ユーザーコードを一時ディレクトリへ保存
2. 問題IDからテストケースを取得
3. 実行対象ケースを選択
   - サンプルのみ
   - 全テスト
4. 各ケースに対して Python プロセスを起動
5. stdin に input_text を渡す
6. stdout を expected_output と比較
7. 結果に応じて AC / WA / RE / TLE / CE / IE を返す
8. 学習者向け表示と教師向け表示を分離
9. 学習ログを更新
10. LLMヒント生成へ JudgeResult を渡す
```

### 9.3 判定種別

| 判定  | 意味                                    |
| --- | ------------------------------------- |
| AC  | 全テストケースで期待出力と一致                       |
| WA  | 実行は成功したが出力が期待値と異なる                    |
| RE  | 実行時エラーが発生                             |
| TLE | 制限時間超過                                |
| CE  | 構文エラーなど、Pythonでは実行前または実行開始直後に検出されるエラー |
| IE  | Judge内部エラー                            |

既存仕様では、AC、WA、RE、TLEの判定種別と、行末空白・末尾改行を無視する比較ルールが整理されていた。citeturn6search2 v3仕様では、これにCEとIEを加え、サンプルケース、隠しテストケース、模範解答、JudgePolicyを管理する設計へ拡張されていた。citeturn6search1

### 9.4 出力比較ルール

| compare_mode    | 内容                   |
| --------------- | -------------------- |
| trim            | 末尾空白と末尾改行を無視する。MVP標準 |
| exact           | 完全一致                 |
| float           | 浮動小数誤差を許容する          |
| unordered_lines | 行順を問わない              |

### 9.5 安全性

- MVPでは `subprocess.run` を使う。
- 必ず `timeout` を指定する。
- 一時ディレクトリで実行する。
- 実行後は一時ファイルを削除する。
- ネットワーク遮断やCPU・メモリ制限はMVPでは完全には保証せず、実運用時はDocker化する。

---

## 10. ヒント設計

### 10.1 ヒント段階

| 段階     | 分類        | 内容                          |
| ------ | --------- | --------------------------- |
| Hint 1 | 問題理解      | 何を求める問題か、入力と出力を言葉で整理する      |
| Hint 2 | 制約・計算量    | Nや値域から、全探索で間に合うか考える         |
| Hint 3 | 解法方針      | 使うべき考え方を抽象的に示す              |
| Hint 4 | 実装注意      | 添字、初期値、ループ範囲、データ構造を確認する     |
| Hint 5 | デバッグ観点    | サンプル以外の最小ケース、最大ケース、境界ケースを試す |
| Hint 6 | Judge結果連動 | WA/RE/TLEの原因候補を直接コード修正なしで示す |

既存仕様では、ヒントは問題理解、制約・計算量、解法方針、実装注意、デバッグ観点の順で段階化され、完成コードや直接解答を含めない方針が定義されていた。citeturn6search2

### 10.2 答え漏洩禁止ルール

ヒントには以下を含めない。

- 完成コード
- `def solve()` を含むコードブロック
- そのまま提出できる疑似コード
- 最終出力の直接提示
- 「答えは〜です」「正解は〜です」という断定
- 模範解答に近い実装手順の全文

### 10.3 不正解時ヒント生成の入力

LLMまたはRuleBasedHintClientには、以下を渡す。

- 問題ID
- タグ
- 学習目標
- 制約
- 判定種別
- 失敗ケースがサンプルか隠しか
- サンプル失敗時の入力・出力・期待出力
- ユーザーのヒント使用回数
- ユーザーの過去の誤答傾向

---

## 11. LLM設計

### 11.1 LLMの役割

LLMは正誤判定を行わない。LLMの役割は、Judge結果と問題情報をもとに、学習者が次に考えるべき観点を提示することである。既存仕様でも、正誤判定はLLMではなくテストケース実行を主とする方針が示されていた。citeturn6search2turn6search3

### 11.2 LLMClient

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass(frozen=True)
class LLMRequest:
    system_prompt: str
    user_prompt: str
    context: dict
    temperature: float = 0.2
    max_tokens: int = 1024

@dataclass(frozen=True)
class LLMResponse:
    text: str
    model_name: str
    provider: str
    raw: dict | None = None

class LLMClient(ABC):
    @abstractmethod
    def generate(self, request: LLMRequest) -> LLMResponse:
        raise NotImplementedError
```

### 11.3 LLM実装候補

| 実装                  | 役割                | MVP |
| ------------------- | ----------------- | ---:|
| GemmaLocalClient    | Gemma 4 12Bローカル推論 | △   |
| GeminiApiClient     | Gemini API呼び出し    | △   |
| MockLLMClient       | テスト用固定応答          | ○   |
| RuleBasedHintClient | ルールベースヒント         | ○   |

<External>Gemma 4 model overview</External> では、Gemmaは質問応答、要約、推論などの生成タスクに使えるopen weightsのモデルファミリーであり、Gemma 4には12Bモデルが含まれると説明されている。citeturn6search184  <External>Google Gen AI SDK documentation</External> では、Google Gen AI Python SDK はGoogleの生成モデルをPythonアプリケーションへ統合するインターフェースで、Gemini Developer APIとVertex AI APIsをサポートすると説明されている。citeturn6search166

### 11.4 MVPでの判断

MVPでは、Judge、問題DB、Gradio UI、学習ログを優先する。Gemma 4 12BやGemini APIは設計上は切り替え可能にするが、実装が重い場合は MockLLMClient と RuleBasedHintClient で課題要件を満たす。

---

## 12. UI設計

### 12.1 Gradio採用方針

MVPではGradioを採用する。<External>Gradio Blocks Docs</External> では、Blocks は Interface より柔軟なGradioの低レベルAPIであり、レイアウト、イベント、データフローをより細かく制御でき、タブで関連デモをまとめる方法も提供されると説明されている。citeturn6search195  <External>Gradio API Documentation</External> では、Gradio は機械学習デモやWebアプリをPythonで素早く構築・共有できる中核ライブラを提供すると説明されている。citeturn6search196

### 12.2 画面構成

```text
1. ホーム
2. 学習ロードマップ
3. 問題演習
4. ヒント
5. コード提出・Judge
6. 結果分析
7. 解説
8. 学習ログ
9. 設定
10. 教師用・隠し回答例（teacher_modeのみ）
11. 外部OJ連携（発展）
```

### 12.3 主要画面

| 画面          | 主な機能                                               |
| ----------- | -------------------------------------------------- |
| 学習ロードマップ    | アルゴ式風の体系的な順序で学習単元を表示                               |
| 問題演習        | 問題文、制約、入力形式、出力形式、サンプルを表示                           |
| ヒント         | 段階的ヒント、Judge結果連動ヒントを表示                             |
| コード提出・Judge | Pythonコード入力、サンプル実行、全テスト実行、判定表示                     |
| 結果分析        | WA/RE/TLEの原因候補、通過ケース数、次の確認観点を表示                    |
| 解説          | AC後またはギブアップ後に解説を表示                                 |
| 学習ログ        | 正答率、平均ヒント数、平均提出回数、苦手タグを表示                          |
| 教師用・隠し回答例   | 模範解答、隠しテスト、Judgeログを表示。通常は非表示                       |
| 外部OJ連携      | `oj download` と `oj test` を扱う。`oj submit` はMVPでは無効 |

---

## 13. ディレクトリ構成

```text
algohint-coach/
├── README.md
├── pyproject.toml
├── requirements.txt
├── data/
│   ├── problems/
│   │   ├── starter.json
│   │   ├── atcoder_like.json
│   │   ├── codility_like.json
│   │   └── paiza_like.json
│   ├── testcases/
│   │   ├── samples/
│   │   ├── hidden/
│   │   └── generated/
│   ├── model_solutions/
│   ├── explanations/
│   ├── knowledge_base.json
│   └── research_logs.json
├── src/
│   └── algohint_coach/
│       ├── core/
│       │   ├── models.py
│       │   ├── requests.py
│       │   ├── responses.py
│       │   ├── safety.py
│       │   └── formatters.py
│       ├── domain/
│       │   ├── problem.py
│       │   ├── testcase.py
│       │   ├── judge.py
│       │   ├── hint.py
│       │   └── session.py
│       ├── application/
│       │   ├── select_problem_usecase.py
│       │   ├── submit_code_usecase.py
│       │   ├── request_hint_usecase.py
│       │   ├── show_explanation_usecase.py
│       │   └── show_learning_report_usecase.py
│       ├── infrastructure/
│       │   ├── problem_repository.py
│       │   ├── answer_repository.py
│       │   ├── log_repository.py
│       │   ├── subprocess_runner.py
│       │   ├── local_judge_runner.py
│       │   ├── oj_tool_judge_runner.py
│       │   ├── llm_client.py
│       │   ├── gemma_local_client.py
│       │   ├── gemini_api_client.py
│       │   ├── mock_llm_client.py
│       │   └── rule_based_hint_client.py
│       └── ui/
│           ├── gradio_app.py
│           └── flet_app.py
├── tests/
│   ├── test_problem_repository.py
│   ├── test_local_judge_runner.py
│   ├── test_hint_engine.py
│   ├── test_safety_checker.py
│   └── test_learning_tracker.py
├── examples/
│   └── dialogue_examples.md
└── docs/
    ├── specification.md
    └── report.md
```

---

## 14. MVP仕様

### 14.1 MVPで必ず実装するもの

- Gradio UI
- 学習ロードマップ表示
- 自作問題DB 5問以上
- 各問題のサンプルケース
- 各問題の隠しテストケース
- 模範解答の隠し保存
- LocalJudgeによるPythonコード実行
- AC / WA / RE / TLE / CE / IE 判定
- 段階的ヒント
- Judge結果に応じたヒント
- 正解後またはギブアップ後の解説表示
- 学習ログ
- 評価指標
- 答え漏洩チェック

### 14.2 MVPでは後回しにするもの

- 本格的なDocker Sandbox
- 外部サイトへの `oj submit`
- ユーザー認証
- 複数ユーザー管理
- ベクトルDB
- 本格RAG
- 手書きメモ画像解析
- Flet UI

### 14.3 MVP成功条件

- 少なくとも5問の自作問題がある。
- 各問題にサンプルケースと隠しテストがある。
- Pythonコードを提出して判定できる。
- 不正解時に完成コードを出さず、惜しい点や考える観点を提示できる。
- 正解前に模範解答が表示されない。
- 正解後またはギブアップ後に解説を表示できる。
- 学習ログが更新される。
- Gradio上で一連の演習フローが動く。

---

## 15. テスト計画

### 15.1 単体テスト

| ID     | 対象                | 内容                      |
| ------ | ----------------- | ----------------------- |
| UT-001 | ProblemRepository | 問題一覧を取得できる              |
| UT-002 | ProblemRepository | 問題IDで問題を取得できる           |
| UT-003 | LocalJudgeRunner  | 正解コードをACと判定できる          |
| UT-004 | LocalJudgeRunner  | 誤答コードをWAと判定できる          |
| UT-005 | LocalJudgeRunner  | 実行時エラーをREと判定できる         |
| UT-006 | LocalJudgeRunner  | 無限ループをTLEと判定できる         |
| UT-007 | LocalJudgeRunner  | 構文エラーをCE相当として扱える        |
| UT-008 | SafetyChecker     | 完成コード漏洩を検出できる           |
| UT-009 | HintEngine        | ヒント段階を進められる             |
| UT-010 | LearningTracker   | 正答率、平均ヒント数、平均提出回数を算出できる |

### 15.2 結合テスト

| ID     | シナリオ           | 期待結果                 |
| ------ | -------------- | -------------------- |
| IT-001 | 問題選択→コード提出→AC  | 解説表示可能になり、学習ログが更新される |
| IT-002 | 問題選択→コード提出→WA  | 修正コードではなくヒントが出る      |
| IT-003 | 問題選択→RE        | 入力処理や例外原因の観点が示される    |
| IT-004 | 問題選択→TLE       | 計算量改善の観点が示される        |
| IT-005 | ギブアップ→解説       | 解説が表示される             |
| IT-006 | teacher_mode   | 模範解答タブが表示される         |
| IT-007 | teacher_modeなし | 模範解答タブが表示されない        |

---

## 16. 評価指標

| 指標                        | 定義                         | 目的         |
| ------------------------- | -------------------------- | ---------- |
| correctness_rate          | 正解問題数 / 取り組んだ問題数           | 学習成果       |
| average_hint_count        | ヒント使用回数 / 取り組んだ問題数         | 自力到達度      |
| average_attempt_count     | 提出回数 / 取り組んだ問題数            | 実装安定性      |
| weak_topic_count          | タグ別不正解数                    | 苦手分野把握     |
| answer_leak_rate          | 漏洩判定ヒント数 / 全ヒント数           | ヒント安全性     |
| judge_accuracy            | 既知正解・既知誤答に対する判定一致率         | Judge品質    |
| grounded_explanation_rate | 根拠付き解説数 / 全解説数             | ハルシネーション抑制 |
| fallback_rate             | LLM fallback発生数 / LLM呼び出し数 | LLM運用安定性   |

既存仕様でも、正答率、平均ヒント数、平均提出回数、苦手タグ、答え漏洩率、根拠付き解説率、judge_accuracy、hint_progression_scoreが評価指標として定義されていた。citeturn6search2turn6search3

---

## 17. リスクと対策

| リスク            | 影響           | 対策                                   |
| -------------- | ------------ | ------------------------------------ |
| 外部問題文転載        | 著作権上の問題      | 自作問題にする。外部問題はURLとタグだけ参照              |
| LLMが答えを出す      | 学習支援として不適切   | SafetyChecker、プロンプト制御、ルールベースfallback |
| LLMが誤判定する      | 学習者に誤った結果を返す | 判定はJudgeが行う                          |
| 任意コード実行        | セキュリティリスク    | timeout、一時ディレクトリ、ローカル限定、将来Docker化    |
| 隠しテスト漏洩        | 問題の意味が薄れる    | learner_view / teacher_view を分離      |
| 模範解答漏洩         | 学習効果低下       | teacher_modeとafter_solved制御          |
| Gemma 4 12Bが重い | MVPが動かない     | Mock / RuleBased / Gemini API切り替え    |
| Gemini APIキー漏洩 | セキュリティ事故     | 環境変数・Colab Secretsを使う                |
| oj submitの誤提出  | 外部サイトへの影響    | MVPでは無効化                             |

---

## 18. 実装フェーズ

### Phase 0: 仕様確定

- 本仕様書を確定する。
- MVP範囲を固定する。
- 自作問題の初期5問を決める。

### Phase 1: データモデルと問題DB

- `Problem`, `TestCase`, `Hint`, `ModelSolution`, `JudgePolicy`, `JudgeResult` を実装する。
- `data/problems/*.json` を作る。
- サンプルケースと隠しテストケースを分ける。

### Phase 2: LocalJudge

- `SubprocessRunner` を作る。
- `LocalJudgeRunner` を作る。
- AC / WA / RE / TLE / CE / IE を返す。
- learner_view と teacher_view を分ける。

### Phase 3: ヒント・解説

- `HintEngine` を作る。
- `SafetyChecker` を作る。
- JudgeResultに応じたヒント生成を作る。
- 解説表示制御を作る。

### Phase 4: Gradio UI

- `gr.Blocks` でタブ構成を作る。
- 問題演習、ヒント、コード提出、解説、学習ログ、設定を接続する。
- `ui/gradio_app.py` だけがGradioに依存するようにする。

### Phase 5: 学習ログと評価

- `LearningTracker` を作る。
- 学習ログをJSON保存する。
- 評価指標を表示する。

### Phase 6: LLM抽象化

- `LLMClient` を作る。
- `MockLLMClient` と `RuleBasedHintClient` を先に実装する。
- 余裕があれば `GemmaLocalClient`、`GeminiApiClient` を接続する。

### Phase 7: 発展

- `OJToolJudgeRunner` を追加する。
- `oj download` と `oj test` の結果をJudgeResultへ変換する。
- Flet UIを試作する。
- 手書きメモ解析を検討する。

---

## 19. 最終判断

本システムは、単なるチャット型AIではなく、**問題DB、Judge、段階的ヒント、解説、学習ログを統合したアルゴリズム学習支援システム**として設計するべきである。

特に重要な判断は次の通りである。

1. MVPでは **LocalJudgeを必須** とする。
2. 問題は外部サイトの転載ではなく、アルゴ式、Codility、AtCoder Beginners Selection、paizaの流れやトピックを参考にした **自作問題** とする。
3. ヒントは、問題理解、制約・計算量、解法方針、実装注意、デバッグ観点の順で段階化する。
4. 不正解時には、回答の惜しいところを示すが、完成コードは出さない。
5. 模範解答は必要だが、隠し機能として扱う。
6. GradioでMVPを作り、中核処理はUI非依存にする。
7. Gemma 4 12BやGemini APIは切り替え可能にするが、MVPの成立にはMock/RuleBasedでもよい。
8. online-judge-tools/oj は有用だが、MVPでは補助機能に留める。

---

## 20. 参考資料

- <File>algohint_coach_spec.md</File>: 初期の完全仕様書。コンセプト、対象分野、参考教材、機能要件、JudgeEngine、評価指標などを定義。citeturn6search2
- <File>algohint_learning_system_spec_v2_gradio_gemma.md</File>: Gradio UI、Gemma 4 12B、Gemini API切り替え、UI非依存アーキテクチャを定義。citeturn6search3
- <File>algohint_learning_system_spec_v3_judge_oj.md</File>: Judge機能、問題管理、隠し回答例、online-judge-tools連携を追加。citeturn6search1
- <External>AtCoder Beginners Selection</External>: 初心者向け問題集として説明されている。citeturn6search190
- <External>Codility Lesson 1 Iterations</External>: IterationsのLessonにBinaryGapが含まれる。citeturn6search157
- <External>アルゴ式 トピック一覧</External>: Python入門、ロジック実装、アルゴリズム初級・中級などのトピックを掲載。citeturn6search178
- <External>paiza 新・アルゴリズムとデータ構造入門 Python編</External>: Python向けの定番アルゴリズム・データ構造項目を掲載。citeturn6search160
- <External>online-judge-tools/oj</External>: サンプル取得、テスト、提出などを自動化するツール。citeturn6search172
- <External>Gradio Blocks Docs</External>: Blocksは柔軟なWebアプリ・デモ作成用API。citeturn6search195
- <External>Gemma 4 model overview</External>: Gemma 4と12Bモデルの概要。citeturn6search184
- <External>Google Gen AI SDK documentation</External>: Gemini Developer APIとVertex AI APIsをサポートするPython SDK。citeturn6search166

---

## 今来三行

AlgoHint Coachは、アルゴ式のような体系的な流れで基礎から学び、AtCoder、Codility、paizaの要素を参考にした自作問題を解く学習支援AIである。  
MVPではGradio、LocalJudge、サンプル・隠しテスト、段階的ヒント、模範解答の隠し管理、学習ログを必須にする。  
正誤判定はLLMではなく実行結果で行い、LLMは惜しい点や次に考える観点を提示する補助役に限定する。  
