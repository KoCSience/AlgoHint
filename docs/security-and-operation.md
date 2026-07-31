# 安全な運用

## Grounded Research

Exa API keyはAlgoHint processへ渡さず、GPU hostのGemma Serverだけが保持します。
Research requestはreview済みの公開問題要約・概念・許可domain・一般化Judge状態に限定し、
source code、質問、profile、履歴、隠しtestを型から除外します。専用同意は1回の呼出し後に
解除されます。検索停止時は既存のJudge、author hint、小テストへfallbackします。

保存するResearch履歴は最終hint、citation、有限trace、件数、費用状態だけで、生の
Highlightsとcredentialを含みません。詳細は
[Grounded Web Researchと評価](research-and-evaluation.md)を参照してください。

固定ケースのライブ評価も同じ公開情報contractとServer予算台帳を使用します。
`expected_focus`は評価oracleとしてclient側に留め、検索・生成requestへ含めません。
ライブ実行には`--run-live --confirm-live-search-cost`の両方が必要で、結果DBには
query、highlight、API keyを保存しません。

LocalJudgeは `shell=False`、一時ディレクトリ、`python -I`、タイムアウト、出力上限、POSIX環境でのCPU・メモリ上限を用います。これは学習時の事故を減らすための対策であり、悪意あるコードを完全に隔離するサンドボックスではありません。

Docker構成では、非rootユーザー、読み取り専用ルートファイルシステム、capability削除、権限昇格防止、PID・CPU・メモリ・一時領域の上限を追加します。ポートは`127.0.0.1`だけへ公開し、永続書き込み先を学習ログ用ボリュームに限定します。これらはホストへの影響と偶発的な資源枯渇を軽減する多層防御です。

ただし、提出コードはアプリと同じコンテナ、ユーザー、ファイルの読み取り権限、ネットワークを共有します。教材中の隠しテストや模範解答を読み取ること、学習ログへアクセスすること、コンテナから外向き通信を試みることをDocker構成だけでは防止しません。

remote Docker stackのnative Linux host network経路では、提出コードからhostのloopback listenerへも
到達できます。Docker Desktopのbridge経路も`host.docker.internal`からhost serviceへ
到達できます。SSH鍵をcontainerへmountしないことでremote hostへの直接認証は避けますが、
host tunnelと他のlocal serviceは強い分離境界ではありません。信頼できる個人利用に限定し、
不要なhost listenerを停止してください。credentialsはowner限定・非symlink fileとして
launcherが検査し、Compose YAMLや`.env`へ値を保存しません。

そのため、アプリは単一PCまたは信頼できる個人のColabセッションでだけ使ってください。`--share` は明示的に指定した場合だけ有効ですが、不特定多数への公開には使えません。公開運用が必要になった場合は、提出ごとの実行環境、ネットワーク遮断、読み取り可能データの最小化、認証・認可、資源監視、監査ログを別途設計します。

集計用の学習ログはプロフィール名、提出回数、ヒント数、判定、完了状態だけを保存します。
プロフィール設定にはモデルIDと、次回表示用の `last_problem_id` を保存します。
`last_problem_id` は進捗や認可ではなく、削除済み問題なら自己修復される任意の
ナビゲーションポインタです。提出コードは後述の専用SQLiteへ保存し、APIキーは
いずれの履歴にも保存しません。
`data/runtime/` はGit管理しません。

隠しテストは通常UIに表示しませんが、ローカルリポジトリまたはアプリコンテナを操作できる利用者から物理的に隠せるものではありません。

## LLM利用時の信頼境界

GPT-5.6とGeminiはクラウドサービスです。UIでセッション単位の同意を有効にしたときだけ、
公開問題、現在コード、質問、安全化済み診断、問題別の会話履歴を選択中のサービスへ
送ります。プロフィール名、隠しテスト、模範解答、生のstderr、APIキーは送りません。
モデル変更とプロフィール変更のたびに同意を解除し、保存済み設定を将来の送信許可には
使いません。

Gemmaは別管理のvLLM／llama.cpp互換サーバー、または専用Transformers HTTPサーバーへ
接続します。別ホストへSSHトンネルで接続する場合はURLがループバックに見えるため、
`ALGOHINT_GEMMA_DEPLOYMENT=remote`を明示してクラウドと同じ送信同意を要求します。
推論サーバーはリモート側の`127.0.0.1`だけで待ち受け、Bearer認証を必須にします。
サーバー実装と設定の正本は
[AlgoHint Gemma Server](https://github.com/KoCSience/AlgoHint-Gemma-Server)です。
AlgoHint側は固定commitのmanifest、鍵の受渡し、SSHトンネルだけを所有します。詳細は
[Gemma Server接続ガイド](gemma-server.md)を参照してください。

質問と表示済みヒントは `data/runtime/tutor_sessions/` に最大20往復保存します。
この会話履歴には現在コードと診断本文を保存しません。「この問題のヒント履歴をクリア」
で問題単位に削除できます。生成失敗、キー不足、不正出力、答え漏洩の疑いがある場合は、別の
クラウドへ自動転送せずローカルのRuleBasedヒントへ退避します。

キーはホーム側で管理し、アプリにはプロセス環境変数としてだけ渡します。アプリは
秘密ファイルを読み込まず、キーの値をUI、例外、ログ、プロフィール、会話履歴へ
出力しません。Judgeの子プロセス環境も最小化するため、提出コードの通常の
`os.environ`にはキーを継承しません。

productionのGemini障害ログには、provider、model、安全化したreason code、
HTTPステータス、再試行可能性、例外クラスだけを記録します。APIキー、リクエスト、
提出コード、Googleの生レスポンスと例外メッセージは記録しません。
`algohint doctor`もモデル情報の取得だけを行い、問題文、コード、質問、会話履歴を
送信しません。

`ALGOHINT_ENV=development`ではデバッグのため、Gemini SDKの例外メッセージ、例外チェーン、
スタックトレースを端末ログへ出力できます。`doctor --verbose`も同じ情報を表示します。
実際のAPIキー、Authorization、Bearerトークン、`x-goog-api-key`は出力前に伏字化します。
ただしSDKの応答エラーなど内部情報は含まれ得るため、developmentログを公開環境で有効に
したり、確認せず外部へ共有したりしないでください。

ただし提出コードはアプリと同じOSユーザー／コンテナで動くため、これは強固な秘密分離
ではありません。また、コンテナ環境変数はDocker管理権限を持つ利用者が確認できます。
LLMキーを渡した状態で信頼できないコードを実行しないでください。この制約を解消するには、
Judgeをキーのない別ユーザー／別コンテナへ分離する必要があります。

### 完了後レビューと履歴

コード改善レビューは、全テストACまたはギブアップを学習ログで再確認した後だけ要求します。
クラウドまたはリモートGemmaには、現在コード、公開問題情報、公開済み解説、完了理由を
送ります。固定小テストの正解、模範解答、隠しテスト、生のJudge情報は要求モデルに
存在せず、プロンプトにも入りません。外部送信同意はヒントと共通のセッション状態であり、
プロフィールやモデルを変えると解除します。

プロバイダ応答は厳密なJSONスキーマで検証し、完成コード・答え漏洩の安全検査に加えて、
提出コード中の長い行をそのまま再掲していないかを確認します。不合格応答や生の
プロバイダ例外は保存・表示しません。障害時は安全化した案内だけを表示し、別プロバイダへ
自動転送しません。

`data/runtime/review_history/` には、プロフィールごとのSQLiteデータベースを置きます。
保存対象は小テスト採点スナップショットと安全検査済みのコードレビュー文です。
提出ソース、プロンプト、認証情報は保存しません。通常画面へ表示するレビュー文はMarkdown
として解釈させる前にHTML特殊文字をエスケープし、教材・モデル由来文字列のHTML注入を
防ぎます。

容量はプロフィールごとに、保存するUTF-8 JSONエンベロープの論理サイズ1 GiBまでです。
80%から警告し、書込み後に上限を超えた場合は、同一SQLiteトランザクション内で全履歴種別の
最古から削除します。他プロフィールの履歴は削除しません。これは物理DBファイル容量の
即時縮小を保証する仕組みではありません。バックアップ時は `profiles.json`、
`learning_logs/`、`tutor_sessions/`、`review_history/` を同じ世代として扱ってください。

SQLiteはプロフィールIDをファイル名に使う前に既存プロフィールとして検証し、
ID自体も許可文字へ制限しています。SQL値はプレースホルダーで渡し、問題ID・履歴種別を
文字列連結しません。WAL利用中の手動コピーは不整合になり得るため、アプリを停止してから
runtime全体をコピーしてください。

### コードドラフトと実行履歴

`data/runtime/code_history/`にはプロフィールごとのSQLiteを置きます。問題別ドラフトと、
公開サンプル／全テストで実行した異なるコード本文を保存します。同一コードはSHA-256と
本文一致を確認して一件にまとめ、各モードの最新日時、判定、通過数、実行時間、公開
サンプル差分、安全化済み診断だけを保持します。隠し入力、生のstderr、Judge内部情報、
APIキーは保存しません。

コードはUTF-8で1 MiBまでの平文です。ディレクトリをmode 700、DBをmode 600にしますが、
OSまたはDocker管理権限を持つ利用者から暗号学的に隠すものではありません。runtimeの
コピーやバックアップにもコードが含まれるため、外部共有しないでください。

削除は確認後にコードsnapshotと関連結果へ`secure_delete`を適用し、WALをtruncate
checkpointします。稼働DBからの残留を抑える処理であり、既存バックアップやストレージ
snapshotは削除しません。バックアップ時は従来の保存先に`code_history/`も加え、
アプリ停止中にruntime全体を同じ世代としてコピーしてください。

## ブラウザMCP利用時の信頼境界

Chrome DevTools MCPは、操作対象ブラウザの画面、DOM、console、Cookieを含み得る
ブラウザ状態、ブラウザとGradio間のnetwork情報へアクセスします。AlgoHint専用の
`--isolated`ブラウザを使い、通常Chromeプロフィール、メール、クラウド管理画面、
学校・職場システムを同じブラウザへ開かないでください。usage statisticsとCrUX連携も
無効化します。

APIキーはブラウザへ入力せず、AlgoHint起動プロセスの環境変数だけに渡します。
Chrome MCPからはGradioバックエンドとGemini間のserver-to-server通信を直接確認できない
ため、Gemini側は安全化されたサーバーログとdoctorで確認します。リモートデバッグポートを
使う場合は`127.0.0.1`だけで待ち受け、LAN、共有ホスト、公開コンテナポートへ露出させては
いけません。

screenshot、snapshot、console、network、Playwright traceには学習内容や入力コードが
含まれ得ます。外部共有前に内容を確認し、実API検証後の成果物は不要になった時点で
削除してください。導入、接続、無効化は
[Chrome DevTools MCP導入ガイド](chrome-devtools-mcp.md)を参照してください。
