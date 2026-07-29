# 受入確認

- [ ] 通常起動では教師タブが表示されない。
- [ ] プロフィールを作成し、問題と公開サンプルを閲覧できる。
- [ ] 正解コードはACとなり、解説が表示される。
- [ ] 隠しケースだけで失敗するコードでは、隠し入力・出力・IDが表示されない。
- [ ] RE、TLE、CEで修正コードではない見直し観点が表示される。
- [ ] 公開サンプル実行ではサンプル診断を表示し、全テスト提出では隠しケースの入力・期待出力・IDを表示しない。
- [ ] 開発起動では「開発テスト」プロフィールが自動作成・選択され、通常起動では表示されない。
- [ ] プロフィールごとにGPT-5.6、Gemma 4 12B、Geminiの選択が保存される。
- [ ] キー未設定またはプロバイダ障害でも起動とJudgeは成功し、RuleBasedヒントへ退避する。
- [ ] Gemini障害時に認証、モデル、利用上限、タイムアウト、応答形式の安全化した原因と対処が表示される。
- [ ] Gemini生成とdoctorは処理完了まで親SDKクライアントを保持し、正常・API例外・応答検証失敗の後に1回だけcloseする。
- [ ] close失敗は正常なヒントまたは主要例外を上書きせず、早期closeは`client_lifecycle_error`としてRuleBasedへ退避する。
- [ ] 連続2回のGeminiヒント要求が成功し、`Cannot send a request, as the client has been closed`が発生しない。
- [ ] `algohint doctor --provider gemini`が問題文やコードを送らず、成功時`0`、失敗時`1`を返す。
- [ ] productionのdoctor、UI、ログにAPIキー、プロンプト、コード、生レスポンスが表示されない。
- [ ] developmentの`doctor --verbose`とGeminiエラーログに例外トレースが表示され、APIキーと認証ヘッダーは`[REDACTED]`になる。
- [ ] Vertex／Enterprise向け環境変数が存在しても、Gemini接続はAPIキー方式のDeveloper APIを利用する。
- [ ] クラウド送信へ同意する前はGPT-5.6／Geminiを呼び出さず、同意後だけ質問・「わからない」・実行結果ヒントを要求できる。
- [ ] プロフィールまたはモデルを変更するとクラウド送信への同意が解除される。
- [ ] 質問と表示ヒントは問題単位で復元され、現在コード、診断本文、キーは保存されない。
- [ ] 「この問題のヒント履歴をクリア」で対象問題の会話だけを削除できる。
- [ ] ヒントに完成コードや答え漏洩の疑いがある場合はRuleBasedヒントへ退避する。
- [ ] ギブアップ後に解説が表示され、模範コードは通常画面に表示されない。
- [ ] レポートがプロフィール別に分離される。
- [ ] 教師モードでは隠しテストと模範解答を確認できる。

## ヒントE2E

- [ ] `uname -r`とWindows側`wsl --list --verbose`でWSL 2を確認できる。
- [ ] `node`、`npm`、`npx`の先頭候補がmiseのLinux shimsで、Node `v24.18.0`とplatform `linux`を返す。
- [ ] 通常Codex sandbox内の`npm --version`と`npx --version`がWindows interopなしで成功する。
- [ ] Chrome MCP `1.6.0`がWSL内Chrome for Testing、隔離、headless、統計・CrUX無効、header伏字で登録される。
- [ ] Codex再起動後、`/mcp`でChrome MCPが接続済みになる。
- [ ] 通常の`uv run pytest`はChromium未導入環境でも成功し、ブラウザE2Eだけをskipする。
- [ ] Gradio API E2Eで問題・Gemini選択、未同意拒否、質問、「わからない」、実行結果ヒント、履歴消去が成功する。
- [ ] Playwright E2Eで同じ操作を実クリックでき、RE診断が実行結果ヒントへ渡る。
- [ ] Playwright実行中にconsole error、HTTP 4xx/5xx、想定外の通信失敗がない。
- [ ] Playwright失敗時のtraceとスクリーンショットを`/tmp/algohint-e2e/`へ保存し、秘密情報を含まないことを確認できる。
- [ ] doctor成功後、Chrome DevTools MCPの隔離Chromeから実Geminiへ「わからない」を1回だけ要求する。
- [ ] 実Geminiのヒントとprovider/modelが画面に表示され、RuleBasedフォールバックがない。
- [ ] Chrome MCPで画面、console、ブラウザからGradioへのnetworkを確認し、Gemini側はサーバーログと突き合わせる。
- [ ] APIキー、認証ヘッダー、credentials内容がログ、trace、screenshotへ出ない。
- [ ] READMEからE2EとChrome MCPの前提、導入、確認、障害対応、無効化・削除手順へ到達できる。

## Docker

- [ ] runtimeとdevelopmentの両ターゲットをビルドできる。
- [ ] Compose設定が検証に合格し、公開ポートが`127.0.0.1:7860`に限定される。
- [ ] 起動シェルに設定したLLM変数がComposeの受け口からコンテナへ渡り、Composeファイルとイメージには秘密値が含まれない。
- [ ] コンテナがUID 10001の非rootユーザーで起動し、ヘルスチェックが`healthy`になる。
- [ ] ルートファイルシステムへ書き込めず、`/tmp`と`data/runtime`へは書き込める。
- [ ] WSL側ChromeからDocker版UIを操作し、AC Judge、RuleBasedヒント、console／HTTP正常を確認できる。
- [ ] コンテナ内でもAC、WA、CE、RE、TLEの判定が成功する。
- [ ] コンテナを削除・再作成しても、同じボリュームからプロフィールと学習履歴を復元できる。
- [ ] 通常モード停止後、明示的な教師モード起動でのみ教師タブが表示される。
- [ ] Dev Container作成後、pytest、Ruff、mypyとGradio起動を実行できる。
- [ ] Dev ContainerのCPU、メモリ、Swap、PID上限が有効で、品質検査を逐次実行してもWSLのSwapを枯渇させない。
- [ ] UID 1000のDev Containerで、所有者10001の`.venv`ボリュームが初回`postCreateCommand`により1000へ補正される。
- [ ] 補正後に`CACHEDIR.TAG`を作成でき、`uv sync --frozen`が成功する。
- [ ] 同じボリュームで再作成した場合は所有権補正を省略し、依存環境を再利用できる。
- [ ] 想定外の`UV_PROJECT_ENVIRONMENT`は依存同期や権限変更を行わずエラー終了する。
