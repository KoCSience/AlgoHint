# E2Eデバッグ

AlgoHint Coachは、速さと検出範囲が異なる三層のE2Eでヒント機能を確認します。
通常の回帰では偽Geminiを使い、実APIへ問題文やコードを送る確認は最後の1要求だけに
限定します。

## 三層の役割

| 層 | 確認できること | 確認できないこと |
|---|---|---|
| Gradio Python Client | 名前付きAPI、キュー、コールバック、戻り値、サーバー側状態 | DOM、実クリック、ブラウザconsole |
| Playwright | DOM、ボタン配線、実クリック、console、HTTP応答、画面上の状態連携 | サーバーからLLMへの通信内容 |
| Chrome DevTools MCP | 実Chromeを使った対話調査、console、ブラウザ側network、画面 | サーバーからGeminiへの直接通信 |

推奨する実行順序は次のとおりです。

1. 単体・結合テストと静的解析
2. Gradio API E2E
3. Playwright E2E
4. `algohint doctor`
5. Chrome DevTools MCPと実Geminiによる1回のヒント要求

前半三層は一時データディレクトリ、偽Gemini、一時ローカルポートを使います。
実credentialsや外部通信を必要とせず、利用枠も消費しません。

## 単体・結合テスト

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
uv run mypy src
uv lock --check
```

通常の`pytest`ではブラウザE2Eをskipするため、Chromium未導入環境でも実行できます。

## Gradio API E2E

```bash
uv run pytest tests/test_gradio_api_e2e.py -vv
```

テストはローカルでGradioを起動し、次の名前付きAPIを確認します。

- `/select_problem`
- `/select_hint_provider`
- `/ask_tutor`
- `/request_stuck_hint`
- `/run_samples`
- `/request_result_hint`
- `/clear_tutor_history`

期待結果は、未同意時にクラウドプロバイダを呼ばないこと、同意後に質問・
「わからない」・実行結果の三経路からヒントを得られること、provider/model表示、
問題別履歴、履歴消去が成立することです。

`gr.State`に保持する最新診断はGradioの公開APIスキーマへ露出しません。このため、
API E2Eでは判定からヒント要求までのコールバックを確認し、画面内での診断状態の
受け渡しは次のPlaywright E2Eで確認します。

## Playwright E2E

### 導入

Python依存はロックファイルから同期し、ブラウザ本体は別途導入します。

```bash
uv sync --frozen
uv run playwright install chromium
```

Linuxの共有ライブラリが不足するときだけ、管理者権限を確認したうえで次を使います。
このコマンドはOSパッケージも変更します。

```bash
uv run playwright install --with-deps chromium
```

### 実行

```bash
ALGOHINT_RUN_BROWSER_E2E=1 uv run pytest tests/test_browser_e2e.py -vv \
  --browser chromium \
  --tracing=retain-on-failure \
  --screenshot=only-on-failure \
  --output=/tmp/algohint-e2e
```

このテストは開発プロフィール、問題選択、Gemini選択、送信同意、質問、
「わからない」、RE実行結果からのヒント、履歴消去を実ブラウザで操作します。
RE診断がヒント要求へ渡ることに加え、console error、HTTP 4xx/5xx、
想定外の通信失敗がないことも確認します。

Gradioはキュー処理の完了後に`/gradio_api/queue/data`のイベントストリームを閉じて
再接続します。Chromiumはこれを`requestfailed`として通知する場合がありますが、
コールバック成功とHTTPエラーなしを別に確認しているため、このURLだけは正常な
接続ライフサイクルとして除外します。

画面を見ながら実行する場合は`--headed`を追加します。

```bash
ALGOHINT_RUN_BROWSER_E2E=1 uv run pytest tests/test_browser_e2e.py -vv \
  --browser chromium --headed
```

Playwright Inspectorで1操作ずつ確認する場合は`PWDEBUG=1`を付けます。

```bash
PWDEBUG=1 ALGOHINT_RUN_BROWSER_E2E=1 \
  uv run pytest tests/test_browser_e2e.py -vv --browser chromium
```

失敗時のtrace、スクリーンショット、動画などは`/tmp/algohint-e2e/`へ出力します。
プラグインと失敗時点により一部だけ生成されますが、構成例は次のとおりです。

```text
/tmp/algohint-e2e/
└── test_hint_coach_in_rendered_browser-.../
    ├── trace.zip
    ├── test-failed-1.png
    └── video.webm
```

traceが生成された場合は次で開けます。

```bash
uv run playwright show-trace /tmp/algohint-e2e/<テスト成果物>/trace.zip
```

成果物には画面や入力内容が含まれます。実credentialsを使うテストでは、共有前に
APIキー、認証ヘッダー、個人情報がないことを確認し、確認後はディレクトリを削除して
ください。プロジェクトの削除方針に合わせ、まず一時ゴミ箱へ移す場合は次を使います。

```bash
mkdir -p /tmp/_GARBAGE
mv /tmp/algohint-e2e /tmp/_GARBAGE/algohint-e2e
```

同名の退避先がある場合は上書きせず、別名を指定してください。`/tmp`自体の最終消去は
利用中OSの一時ファイル管理へ任せます。

## doctorと実Gemini

credentialsを読み込んだ同じシェルで、まずモデル情報だけを取得します。

```bash
uv run algohint doctor --provider gemini
```

成功後、隔離したChromeでクラウド送信へ同意し、「わからない」を1回だけ実行します。
画面に`gemini / <model>`とヒントが表示され、RuleBasedへのフォールバック通知がないことを
確認します。サーバーログでは`client_lifecycle_error`、
`Cannot send a request, as the client has been closed`、未処理例外がないことを確認します。

実API確認を1要求に限定するのは、利用枠の消費、送信データ、外部状態による不安定性を
最小化するためです。網羅的な異常系と画面回帰は偽プロバイダで確認します。
Chrome DevTools MCPの導入と操作は
[Chrome DevTools MCPガイド](chrome-devtools-mcp.md)を参照してください。

## 実行環境別の代替

- WSLからGUIが使えない場合はheadless Playwrightを使います。Chrome MCPはWSL内の
  Chrome for Testingを使うか、ローカル限定のリモートデバッグ接続を構成します。
- Dev Containerではブラウザ依存をコンテナへ導入します。導入できない場合は
  Gradio API E2Eまでをコンテナ内で実行し、Playwrightをホスト側から接続します。
- Docker runtimeイメージへテスト用ブラウザを追加しません。起動中の
  `127.0.0.1:7860`へホストのPlaywrightまたはChrome MCPから接続します。

## トラブルシューティング

| 症状 | 確認と対処 |
|---|---|
| Chromium executableがない | `uv run playwright install chromium`を実行する |
| Linux共有ライブラリがない | 管理者承認後に`playwright install --with-deps chromium`を使う |
| Gradio起動待ちがtimeout | 既存プロセス、CPU負荷、ループバック接続、ログを確認する |
| ポート競合 | テストは一時ポートを使う。固定7860の手動起動プロセスを確認する |
| locator不一致 | `elem_id`の変更とPlaywright traceのDOM snapshotを確認する |
| queue timeout | サーバーログの未処理例外と`/gradio_api/queue/*`のHTTP応答を確認する |
| consoleに接続エラー | テスト終了時だけならサーバー停止順序、操作中ならnetwork失敗を確認する |

## バージョン更新

`pytest-playwright`／`playwright`を更新したら`uv.lock`も更新し、Chromiumを再導入します。
その後、通常テスト、Gradio API E2E、headless Playwright、失敗traceの生成・閲覧を
再確認します。Chrome DevTools MCPを更新する場合の手順は専用ガイドに記載しています。

参考:
[Gradio Python Client](https://www.gradio.app/main/docs/python-client/introduction)、
[Playwright Python](https://playwright.dev/python/docs/intro)、
[Playwright trace](https://playwright.dev/python/docs/api/class-tracing)
