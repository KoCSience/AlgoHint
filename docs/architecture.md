# アーキテクチャ

```text
Gradio UI
  -> application services
    -> domain ports
      -> JSON repositories / SQLite review history / LocalJudge / learning providers
```

`domain/` はPydanticモデル、判定状態、出力比較、抽象ポートを持ち、Gradio・
ファイルシステム・サブプロセスに依存しません。`application/` は学習フローを組み立て、
学習者向けDTOへ私的なJudge情報を渡さない境界です。`infrastructure/` はJSON／SQLite保存、
ユーザーコード実行、固定ヒント、外部モデルアダプタを実装します。`ui/` はGradioイベントと
表示整形だけを担当します。

適応型ヒントの追加後も依存方向は変えません。`TutorService` は公開問題情報、
安全化済みJudge診断、現在コード、質問、会話履歴からプロバイダ非依存の要求を作ります。
OpenAI、Gemma、Gemini固有のSDKとHTTP処理は `infrastructure/` に閉じ込めます。
詳しい信頼境界は[適応型ヒントとLLM設計](llm-hint-design.md)を参照してください。

Exa Grounded Researchは`ResearchProvider`からprivate Gemma Serverへ委譲し、API key、
予算、検索I/Oをclientから分離します。問題別knowledge、profile別history、UI同意、
評価は既存Judge・hint flowと独立させ、検索停止時にも必須課題を継続します。詳細は
[Grounded Web Researchと評価](research-and-evaluation.md)を参照してください。

完了後の復習は `CompletionReviewService` が担当します。固定小テストとコード別AI小テストの
公開・採点、完了条件の再確認、解説とAIレビューの公開、安全検査、履歴保存を一つの
ユースケース境界に集めます。UIや各プロバイダが独自に完了を判断したり、正解情報を
組み立てたりしません。

## 状態の分類

状態の用途を分けることが、起動時の選択不整合と復習内容の早期公開を防ぐ中心設計です。

| 状態 | 保存先 | 意味 | 使用してよい判断 |
|---|---|---|---|
| `last_problem_id` | `profiles.json` の `ProfilePreferences` | 次回戻る問題への任意ポインタ | 初期表示とナビゲーション |
| `hint_provider` | `profiles.json` の `ProfilePreferences` | 次回選択するモデル | プロバイダ選択 |
| `ProblemProgress` | `learning_logs/<profile>.json` | 提出・ヒント・AC・ギブアップの学習事実 | 完了、レポート、復習解禁 |
| クラウド同意 | Gradioのブラウザセッション状態 | 今回の外部送信許可 | そのセッションの外部API呼び出し |
| Tutor履歴 | `tutor_sessions/` | 完結した質問・回答の組 | 会話文脈の復元 |
| 復習履歴 | `review_history/<profile>.sqlite3` | 小テスト結果、AI問題、生成済みレビュー | 復習の再表示 |
| Research履歴 | `research_history/<profile>.sqlite3` | 引用、trace、費用状態、最終ヒント | 根拠と実測評価 |
| 固定Research実測 | `research_evaluation/runs.sqlite3` | 公開固定caseの最終応答と実行指標 | case別最新版の比較 |
| 固定小テスト解除 | 同SQLiteの`review_unlocks` | 固定5問を一度採点した事実 | 解説・AIレビューの公開 |

### `last_problem_id` が「利便性の状態」である理由

`last_problem_id` はブックマークに近いポインタであり、次の性質を持ちます。

- 問題を開いただけで更新されるため、学習した証拠にならない。
- 問題の削除・改名で古くなり得るため、存在を保証しない。
- 複数タブでは最後の書き込みが前の値を上書きし得る。
- ディスク書き込みに失敗しても、Judgeや問題閲覧を止める必要がない。
- コード、診断、提出結果、完了日時を含まず、それらを暗黙にも示さない。

したがって、`last_problem_id` から `solved` や `gave_up` を推測してはいけません。
復習の表示、AIレビュー、レポート集計は、常に `ProblemProgress` を再読込して判断します。
モデル設定を更新するときも `ProfilePreferences` 全体を置き換えず、
`last_problem_id` を保持したコピーを保存します。

### 起動・プロフィール変更・問題選択の流れ

```text
カリキュラムを順序付きで読込
  -> 最初のL0（なければ先頭）を決定
  -> プロフィールのlast_problem_idを読込
    -> 現存する: そのIDをセレクターと問題本文へ同時反映
    -> 未設定: 既定IDを同時反映し、次回用に保存
    -> 不正・削除済み: 既定IDへフォールバックして保存値を自己修復
    -> 問題なし: 未選択表示
```

明示選択時は、先に問題リポジトリでIDを検証し、その後に表示と次回用ポインタを更新します。
保存だけが `OSError` で失敗した場合は現在表示を維持し、非致命的な警告を返します。
問題一覧を一回走査するため、復元の時間計算量は問題数を `P` として `O(P)`、追加空間も
有効ID集合の `O(P)` です。

## 質問生成の流れ

```text
質問する / Ctrl+Enter / Cmd+Enter
  -> 入力長・プロフィール・同意を同期検証
  -> 検証済み質問をブラウザの会話へ即時追加
  -> 入力欄をクリアし、単調時計で経過秒を表示
  -> 単一ワーカーでTutorServiceを呼び出す
    -> 成功: 質問と回答を一組で永続化し、所要時間を表示
    -> 失敗: 永続履歴を再読込し、質問を入力欄へ戻す
```

即時表示する質問はブラウザ内だけの暫定表示です。生成前に質問だけを永続化すると、
中断・タイムアウト後に回答のない履歴が残るため、永続化はサービス内で質問・回答の
一組が揃ってから行います。表示する秒数は `time.monotonic()` から求めた経過時間であり、
推定残り時間ではありません。

## 完了後レビューの流れ

```text
全テストAC / 初回ギブアップ
  -> ProblemProgressを更新
  -> CompletionReviewServiceが完了条件を再確認
    -> 正解情報を除いた固定5問を公開
    -> 固定5問をすべて採点
      -> 履歴とreview_unlocksを同一トランザクションで保存
      -> 固定解説とAIレビュー操作を公開
    -> 現在コードからCodeReviewRequestを構築
      -> 外部送信ならセッション同意を再確認
      -> 選択中LearningProviderへ一回だけ要求
      -> 厳密JSONスキーマを検証
      -> 答え漏洩・コード再掲を検査
      -> 生成済みレビューだけをSQLiteへ保存
```

公開サンプルACはこの流れを開始しません。小テスト採点では、送信された5個の選択肢IDを
教材側の正解IDと照合し、採点後の詳細スナップショットを保存します。固定小テストは
5問だけなので採点は `O(1)`、履歴表示は固定20件なので1ページのメモリ使用量も有界です。

`review_unlocks` は容量整理される履歴レコードから分離します。一度成立した公開条件が
履歴の削除によって失われないようにするためです。既存DBは保存済み固定小テスト履歴の
最古日時から解除状態を補完します。

SQLiteはプロフィールごとに一ファイルとし、WAL、`BEGIN IMMEDIATE`、5秒のbusy timeout、
`synchronous=FULL`を使います。保存時はUTF-8 JSONエンベロープの論理サイズを加算し、
1 GiBを超える間だけ全種別の最古レコードを削除します。これはDBファイルの物理サイズ
そのものではなく、予測可能なアプリ管理上限です。

## Docker実行時の構造

```text
ブラウザ
  -> 127.0.0.1:7860
    -> AlgoHintコンテナ（非root、read-only root filesystem）
      -> /opt/algohint/data/problems（イメージ内、読み取り専用）
      -> /opt/algohint/data/runtime（名前付きボリューム、永続化）
      -> /tmp/algohint-judge-*（tmpfs、提出ごとに破棄）
```

コンテナ化によってホストとの境界は追加されますが、アプリと提出コードの内部構造は変えません。提出コードは`LocalJudgeRunner`から同じコンテナ内の制限付き子プロセスとして起動されます。別コンテナ化しない理由はローカル個人利用というMVPの範囲と実装の単純さを維持するためであり、信頼できない利用者向けの隔離には使用できません。

提出時は、UIが `SubmissionService` へプロフィールID・問題ID・ソースを渡します。サービスは隠しケースを含むJudge結果を受け、ログを更新し、公開サンプルで失敗した場合だけ入出力差分を含むDTOへ変換します。隠しテストの詳細はUIへ渡しません。

CEと公開サンプルのREでは、学習者自身のコード位置と安全化した例外情報を表示します。
隠しケースの例外メッセージは入力値を含み得るため、例外型と提出コードの位置だけを
公開します。IEの内部例外はUIへ渡さず、診断IDだけを返します。

教師モードのタブは起動時の `--teacher-mode` 指定時だけ生成されます。通常のUI状態とコールバックには模範解答・隠しテストを保存しません。
