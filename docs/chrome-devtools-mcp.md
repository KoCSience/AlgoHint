# Chrome DevTools MCP導入ガイド

Chrome DevTools MCPは、Codexから隔離した実Chromeを操作し、AlgoHintの画面、
console、ブラウザとGradio間のnetworkを対話的に調査するために使います。
全開発者へブラウザ操作環境を強制しないため、プロジェクトの`.codex/config.toml`へは
自動登録せず、利用者単位で設定します。

## 前提

- Node.js LTSと`npm`／`npx`
- 現行ChromeまたはChrome for Testing
- Codex CLI、IDE拡張、デスクトップアプリのいずれか
- AlgoHintを`127.0.0.1`で起動できること

このプロジェクトで検証対象とする`chrome-devtools-mcp`は`1.2.0`です。
バージョンを固定し、導入日によって動作が変わることを避けます。

## 推奨するユーザー単位設定

CLIから登録します。

```bash
codex mcp add chrome-devtools -- \
  npx -y chrome-devtools-mcp@1.2.0 \
  --isolated \
  --headless \
  --no-usage-statistics \
  --no-performance-crux
```

または`~/.codex/config.toml`へ次を追加します。

```toml
[mcp_servers.chrome-devtools]
command = "npx"
args = [
  "-y",
  "chrome-devtools-mcp@1.2.0",
  "--isolated",
  "--headless",
  "--no-usage-statistics",
  "--no-performance-crux",
]
startup_timeout_sec = 20
tool_timeout_sec = 60
default_tools_approval_mode = "prompt"
enabled = true
```

`--isolated`は通常利用のChromeプロファイルとCookieを分離し、`--headless`は画面のない
環境でも起動できるようにします。usage statisticsとCrUX連携も無効化します。

CodexのMCP設定は既定で`~/.codex/config.toml`に保存され、CLI、IDE、デスクトップ間で
共有できます。プロジェクト設定も可能ですが、信頼済みプロジェクトだけで有効になる
設定であり、本プロジェクトでは個人のブラウザ環境を必須化しない方針です。

## 接続確認

```bash
codex mcp list
codex mcp get chrome-devtools
```

登録後はCodexを再起動し、`/mcp`で`chrome-devtools`が接続済みか確認します。
再起動前のセッションには新しいMCPツールが追加されないことがあります。

## AlgoHintの調査手順

1. credentialsを読み込んだシェルで`uv run algohint`を起動する。
2. MCPから`http://127.0.0.1:7860`を新しいページで開く。
3. ページ一覧とDOM snapshotを取得し、「AlgoHint Coach」を確認する。
4. プロフィール、問題、Gemini、同意を選択し、「わからない」を1回押す。
5. screenshotで`gemini / <model>`とヒントを確認する。
6. consoleに未処理例外がなく、Gradioのnetwork要求に4xx/5xxがないことを確認する。
7. サーバーログでGemini成功とフォールバックなしを確認する。

Chrome DevToolsが確認できるのは、ブラウザとGradioバックエンド間の通信です。
GradioバックエンドからGemini APIへの通信はブラウザを通らないため、network一覧には
表示されません。Gemini側の結果、reason code、client lifecycleは安全化した
サーバーログと`algohint doctor`で確認します。

## 安全要件

- AlgoHint専用の隔離ブラウザだけを使い、通常Chromeプロファイルを指定しない。
- 同じブラウザへメール、クラウド管理画面、決済画面、学校・職場システムを開かない。
- APIキーをUI、URL、質問欄へ入力しない。キーは起動プロセスの環境変数だけへ渡す。
- screenshot、DOM snapshot、console、network、traceを外部共有する前に内容を確認する。
- リモートデバッグポートを`0.0.0.0`やLANへ公開しない。

MCPサーバーにはブラウザで表示した内容と開発者ツール相当の情報が渡ります。
隔離は秘密漏洩リスクを下げますが、取得した情報を無害化するものではありません。

## 既存Chromeへ接続する代替構成

GUIや認証済みブラウザが必要な場合は、専用の一時プロファイルでChromeを起動し、
Chrome DevTools MCPをそのリモートデバッグエンドポイントへ接続できます。
ポート番号、接続用オプションは使用するMCPバージョンの公式READMEで確認してください。

リモートデバッグはChrome全体を操作できる強い権限です。待受先を
`127.0.0.1`へ限定し、SSHトンネルやコンテナのポート公開でも外部へ露出させないで
ください。通常プロフィールは使用しません。

## トラブルシューティング

| 症状 | 確認と対処 |
|---|---|
| MCP一覧へ出ない | `codex mcp list`と設定ファイルのTOML構文を確認する |
| ツールが反映されない | Codexを完全に再起動し、`/mcp`を確認する |
| `node`／`npx`がない | Node.js LTSを導入し、新しいシェルでPATHを確認する |
| Chrome executableがない | ChromeまたはChrome for Testingを導入し、MCPの対応オプションで場所を指定する |
| 起動timeout | 初回npm取得、プロキシ、Chrome起動時間を確認し、必要時だけtimeoutを延ばす |
| npm取得が拒否される | 組織プロキシ、npm registry、sandboxの外向き通信許可を確認する |
| WSL 1で`npm`／`npx`が`WSL 1 is not supported`になる | WSL 2へ更新するか、Windows側のNode.jsとCodexからMCPを起動する |
| WSLからWindows Chromeへ接続できない | WSL内Chromeを使うか、Windows側のローカル限定endpointと到達経路を確認する |
| profile lock | 既存Chromeを終了するか、新しい隔離プロフィールを使う |
| Gemini通信がnetworkにない | 正常。server-to-server通信なのでdoctorとサーバーログを確認する |

## 無効化・削除

一時的に止める場合は設定を次のように変更します。

```toml
[mcp_servers.chrome-devtools]
enabled = false
```

登録自体を削除する場合は次を実行します。

```bash
codex mcp remove chrome-devtools
```

削除後は、MCPが起動したChromeプロセスと隔離プロフィールが終了していることも確認します。

## バージョン更新

更新前に公式リリースノートとCLIオプション差分を確認し、設定中の
`chrome-devtools-mcp@1.2.0`を意図した版へ変更します。Codex再起動後、接続確認、
ページ一覧、snapshot、screenshot、console、network、「わからない」1回の順に
回帰確認します。通常Chromeプロファイルを使っていないことと、統計・CrUX無効化
オプションが引き続き有効であることも再確認します。

参考:
[Codex MCP公式マニュアル](https://learn.chatgpt.com/docs/extend/mcp.md)、
[Chrome DevTools MCP公式README](https://github.com/ChromeDevTools/chrome-devtools-mcp)
