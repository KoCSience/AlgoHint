# Grounded Web Research and evaluation

## 課題との対応

| 課題 | 実装 |
|---|---|
| 必須 | Judge、非解答型段階ヒント、5問小テスト、履歴、アクセス分離 |
| 発展A | 問題別knowledge baseとExa実行時Web検索 |
| 発展B | 有限状態Agentic Research、引用、実行trace、audit log |
| 発展C | ヒント段階、問題別履歴、Research同意、学習レポート |
| 発展D | 固定15ケース、引用・domain・非解答・完了・遅延・cache指標 |
| 発展E | [画像入力設計](image-input-design.md) |

## 問題別knowledge base

各`data/problems/<problem_id>/knowledge.json`には、schema version、review日、Exaへ送信
できる公開問題要約、概念、検索語、source title、HTTPS URL、domainを保存します。
knowledge baseは隠しテストや模範解答と別fileです。問題ID一致、URL、source domainを
起動・評価時に検証します。検索不能時も既存の5段階author hintが利用できます。

## データフロー

```text
learner explicit consent
  → GroundedResearchService
  → reviewed problem summary + concepts + allowed domains + Judge category
  → authenticated Gemma Server /v1/research
  → Exa Search / Highlights
  → local Gemma synthesis
  → citations + finite trace + usage
  → profile-scoped SQLite history
```

送信するのは公開問題ID・題名・要約・概念・許可domain・`WA/RE/TLE/CE/AC/GIVE_UP`
だけです。source code、質問、プロフィール、会話、学習履歴、実テスト入出力、隠し
テストはResearch request型にfield自体がありません。

通常のcloud hint同意とResearch同意は別です。Research同意は1回実行後に自動でoffへ
戻り、暗黙の再検索を防ぎます。

## UI

問題演習の「根拠付きWeb検索（Exa）」から次を確認できます。

- 外部送信する情報・送信しない情報
- 1回限りの同意
- `[S1]`形式の出典
- `requested → planned → searched → ... → completed` trace
- Search、Contents、cache hit、所要時間
- 今月・直近30日の使用額とSearch残数
- 同一プロフィール・問題の保存済みResearch履歴

上限や障害で検索できなくても、Judge、author hint、小テスト、学習履歴は継続します。

## 実行設定

Researchは専用のTransformers HTTP Gemma Serverで利用します。

```text
ALGOHINT_GEMMA_BACKEND=transformers_http
ALGOHINT_GEMMA_BASE_URL=http://127.0.0.1:18080/v1
ALGOHINT_GEMMA_API_KEY=<GPU hostと共有したGemma認証キー>
```

AlgoHint側へ`EXA_API_KEY`は置きません。GPU hostへの安全な配置と無料運用はGemma
Serverの`docs/research.md`を参照してください。SSH同期scriptはGemma認証キーだけを
client hostへ転送します。

## 評価

固定datasetは`data/evaluation/research-cases.json`です。5問題についてWA、TLE、ACの
3状態、計15ケースを持ちます。

```bash
uv run algohint --data-dir data evaluate
uv run algohint --data-dir data evaluate --json
uv run algohint --data-dir data evaluate --profile-id <PROFILE_ID>
```

通常の`evaluate`は外部通信せず、15ケース、全問題knowledge、source数と保存済み実測を
集計します。出力は固定ケースの`fixed_runs`と、`--profile-id`で選択した通常学習履歴の
`profile_runs`を分離します。両方についてgrounded completion、citation integrity、
許可domain、non-answer、fallback、平均Search回数、平均latency、cache hitを測定します。

### 固定ケースのライブ実測

未測定の固定ケースを実際のGemma Server／Exa経路へ流す場合だけ、費用確認を明示します。
既定は1ケースで、既に結果があるケースを自動的に飛ばします。

```bash
uv run algohint --data-dir data evaluate \
  --run-live \
  --confirm-live-search-cost \
  --max-cases 1 \
  --json
```

特定ケースだけを測る場合は`--case-id range-sum-wa`を使用します。複数指定できます。
同じケースを再測定する`--rerun`はExa creditを再消費し得るため、意図した比較時だけ
使用します。`--run-live`なしで費用関連optionを渡した場合と、確認flagがない場合は
provider作成前に停止します。

1ケースは最大3 Searchです。各roundのHighlights 2ページと1回のContents再試行を含む
保守的な単価上限は最大約0.033 USDです。実際の各外部要求はGemma Serverの月9 USD、
月1,000 Search、日30 Search、日60 Contentsページの台帳へ先に予約されます。

固定ケースの`expected_focus`は評価用正本であり、Research requestへ送信しません。
問題別の公開要約・概念・検索語・許可domainと、ケースのJudge分類だけを送ります。
途中でprovider障害が起きても、それまで完了したケースは失わず保存します。

実測結果は次へappendし、reportではケースごとの最新版だけを比較します。

```text
data/runtime/research_evaluation/runs.sqlite3
```

DBはmode `0600`、論理payload 64 MiB上限です。保存するのは最終ヒント、引用、有限trace、
件数、遅延、usageであり、Exa APIキー、query、取得highlight、学習者コードは保存しません。

学習レポートには、従来の正答率・提出回数・ヒント数に加え、ギブアップ数、ヒント利用後
の正解割合、Research回数、根拠取得率、平均応答時間を表示します。

実Exaの評価も通常利用と同じ月9ドル、月1,000 Search、日30 Searchへ含まれます。
自動CIは外部APIを呼ばず、mock responseでSearch payload、cost、cache、budget、
引用、traceを再現します。

## 受入基準

- 固定datasetが全5問題×3状態を覆う
- ライブ実測がケース別に保存され、固定ケースcoverageを表示できる
- knowledge sourceと問題IDのschema検証が100%
- 保存済みgrounded runの引用整合率100%
- 許可domain遵守率100%
- non-answer rate 100%
- 1 runのSearchが3回以下
- 予算超過時に外部I/Oが発生しない
- Exa credentialがAlgoHintのrequest、history、logへ入らない
