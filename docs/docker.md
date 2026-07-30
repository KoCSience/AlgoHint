# Docker運用ガイド

## 前提と運用範囲

Docker EngineとDocker Compose v2互換の`docker compose`サブコマンドを使用します。WSL2では、対象ディストリビューションに対するDocker DesktopのWSL integrationを有効にしてください。

この構成は、信頼できる個人が`127.0.0.1`から利用するためのものです。提出コードはアプリと同じコンテナ内で実行されるため、LANやインターネットへ公開しないでください。

Dockerを先に切り分け環境として使うのではなく、まずWSLホストでpytest、Gradio API E2E、
Playwright E2Eを成功させます。その後に同じソースをruntimeイメージへ組み込み、
ホストのChrome MCPまたはPlaywrightからDocker版UIを確認します。ブラウザとMCPは
WSLホスト側で動かし、runtimeイメージへNodeやChromeを追加しません。

## Docker Compose

利用するキーをホーム側から起動シェルへ読み込んでからComposeを実行すると、
`compose.yaml`の受け口がコンテナへ引き継ぎます。Composeファイル、イメージ、
名前付きボリュームにはキーを保存しません。変数名とホーム管理の例は
[開発ガイド](development.md#llm設定と秘密情報)を参照してください。

ビルドしてバックグラウンド起動します。

```bash
docker compose up --build --detach
docker compose ps
```

`app`が`healthy`になったら、<http://127.0.0.1:7860>を開きます。ログの確認と停止は次のとおりです。

```bash
docker compose logs --follow app
docker compose down
```

`down`では名前付きボリュームを削除しないため、次回起動時もプロフィールと学習履歴を読み込めます。

### WSLホスト検証後のruntime確認

古いイメージを誤って検証しないよう、ビルドと起動を分けます。

```bash
docker compose build app
ALGOHINT_ENV=development docker compose up --detach --no-build
docker compose ps
```

`healthy`になったら次を確認します。

- 公開先が`127.0.0.1:7860`だけである。
- コンテナユーザーがUID 10001で、root filesystemがread-onlyである。
- `/tmp`と`/opt/algohint/data/runtime`が書込み可能である。
- 問題選択、公開サンプルのAC、キー未設定時のRuleBasedヒントが動く。
- console error、HTTP 4xx/5xx、ログへの秘密情報露出がない。

画面確認はWSL側ブラウザから<http://127.0.0.1:7860>へ接続します。終了後はvolumeを
保持したまま停止し、保持を確認します。

```bash
docker compose logs --tail 200 app
docker compose down
docker volume inspect algohint-runtime
```

教師モードは通常モードを停止してから、同じ安全設定とボリュームを使って一時起動します。

```bash
docker compose down
docker compose run --rm --service-ports app \
  --host 0.0.0.0 \
  --port 7860 \
  --data-dir /opt/algohint/data \
  --teacher-mode
```

終了は`Ctrl+C`です。教師モードでは隠しテストと模範解答を表示するため、画面を共有しないでください。

## docker run

Composeを使わない場合も、同じ制約を明示して起動します。

```bash
docker build --target runtime --tag algohint:local .
docker volume create algohint-runtime
docker run --detach \
  --name algohint \
  --init \
  --restart unless-stopped \
  --publish 127.0.0.1:7860:7860 \
  --volume algohint-runtime:/opt/algohint/data/runtime \
  --read-only \
  --tmpfs /tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --pids-limit 128 \
  --memory 512m \
  --cpus 1 \
  --env OPENAI_API_KEY \
  algohint:local
docker ps --filter name=algohint
```

上の `--env OPENAI_API_KEY` はシェルに設定済みの値を渡す指定であり、値自体を
コマンドラインへ書きません。GeminiまたはGemmaを使う場合は、同様に
`GEMINI_API_KEY`、`ALGOHINT_GEMMA_BASE_URL`、必要なら
`ALGOHINT_GEMMA_API_KEY`を渡します。別ホストのTransformersサーバーを使う場合は
`ALGOHINT_GEMMA_BACKEND=transformers_http`と
`ALGOHINT_GEMMA_DEPLOYMENT=remote`も渡します。

Dockerコンテナ内の`127.0.0.1`はコンテナ自身を指すため、WSLホストの
`127.0.0.1:18000`へ作成したSSHトンネルをそのまま参照できません。Dockerで実Gemmaを
検証する場合は、トンネルの公開範囲と認証を別途設計してください。通常のDocker
スモークではRuleBasedを使い、実GemmaのE2EはWSLホスト起動のAlgoHintで実施します。
推論サーバーの実装とversion付き配備は
[AlgoHint Gemma Server](https://github.com/KoCSience/AlgoHint-Gemma-Server)、
AlgoHintとの接続は[Gemma Server接続ガイド](gemma-server.md)を参照してください。

停止と再開ではボリュームを保持します。

```bash
docker stop algohint
docker start algohint
```

コンテナを作り直す場合も、同じ`algohint-runtime`ボリュームを指定してください。

```bash
docker stop algohint
docker container rm algohint
```

## VS Code Dev Container

VS Codeでリポジトリを開き、`Dev Containers: Reopen in Container`を実行します。作成後は`uv sync --frozen`が自動実行され、仮想環境は`algohint-dev-venv`ボリュームへ保存されます。

Dev ContainersはLinux／WSL上でコンテナユーザーのUIDをホストユーザーに合わせます。Ruff、mypy、uvのキャッシュは`/tmp`へ分離し、bind mountしたソースの所有権を変えません。開発コンテナはCPU 1コア、メモリ1GB、合計メモリ＋Swap 1.5GB、PID 256以下に制限し、VS Codeを含むWSL全体の応答停止リスクを抑えます。

コンテナ内のターミナルで品質確認とアプリ起動を行います。

```bash
uv run pytest
uv run ruff check .
uv run mypy src
uv run algohint --host 0.0.0.0 --port 7860
```

VS Codeが転送したポート7860から画面を開きます。開発コンテナはソースをbind mountするため、runtimeイメージの読み取り専用構成とは異なります。

品質検査は上記の順番で逐次実行してください。メモリの小さいWSL環境では、pytest、Ruff、mypyを別コンテナで同時実行すると、依存読み込みとbytecode生成が重なり、VS Codeが応答しなくなることがあります。

### `.venv`ボリュームの権限エラー

Dev ContainersはLinux／WSL上で`algohint`ユーザーのUID/GIDをホストユーザーに合わせますが、既存の名前付きボリュームに記録された数値の所有者は自動変更されません。たとえばコンテナユーザーが1000、`algohint-dev-venv`が10001のままだと、`uv`は次のエラーで停止します。

この挙動と非rootユーザーでボリューム所有権を補正する方法は、VS Codeの[非rootユーザー設定ガイド](https://code.visualstudio.com/remote/advancedcontainers/add-nonroot-user)にも記載されています。

```text
error: failed to open file `/workspace/.venv/CACHEDIR.TAG`: Permission denied
```

コンテナ内で実効ユーザーとボリュームの所有者を確認できます。

```bash
id
stat -c '%u:%g %a %n' /workspace/.venv
```

通常はVS Codeのコマンドパレットから`Dev Containers: Rebuild Container`を実行してください。初回の`postCreateCommand`が所有権の不一致だけを補正してから`uv sync --frozen`を実行します。所有権が一致している場合は、WSLへの負荷を避けるため再帰的な補正を省略します。

Rebuild Containerでも復旧せず、インストール済みの開発依存を破棄してよい場合だけ、VS Codeで`Dev Containers: Reopen Folder Locally`を実行した後に次のボリュームを削除します。

```bash
docker volume rm algohint-dev-venv
```

これは開発用仮想環境だけを削除し、次回のRebuild Containerで再作成します。プロフィールと学習履歴を持つ`algohint-runtime`は削除しないでください。

## データの管理

永続化するデータは`/opt/algohint/data/runtime`だけです。教材はイメージに含まれ、コンテナ実行中には変更しません。

ボリュームの場所と利用状況は次で確認できます。

```bash
docker volume inspect algohint-runtime
docker system df --verbose
```

`docker compose down --volumes`または`docker volume rm algohint-runtime`は、プロフィールと全学習履歴を削除します。バックアップを確認したうえで、初期化する意図がある場合だけ実行してください。

## トラブルシューティング

- `permission denied`でDocker APIへ接続できない: Docker Desktopが起動済みか、WSL integrationが対象ディストリビューションで有効か確認します。
- `~/.docker/config.json`を変更した後にJSON構文警告が出る: JSONではコメントを使えません。`credsStore`を無効化する場合は行自体を削除し、`python3 -m json.tool ~/.docker/config.json >/dev/null`で構文を確認します。
- `error getting credentials`とWSLのvsockエラーが出る: Docker設定のJSON構文を直し、Docker Desktopを再起動してWSL側のターミナルを開き直します。
- ポート7860が使用中: 既存のAlgoHintコンテナを停止するか、Composeとdocker runのどちらか一方だけを起動します。
- `unhealthy`になる: `docker compose logs app`でGradioの起動エラーと、ボリュームの書き込み権限を確認します。
- モデルが「利用不可」になる: コンテナ内に必要な変数名が渡っているかを確認します。値そのものはログや問い合わせへ貼り付けないでください。
- 依存関係を更新した: `uv.lock`を更新・検証した後、`docker compose build --no-cache app`で再構築します。

## WSLが応答しなくなる場合

次の状態なら、WSLのメモリ上限とSwap不足が原因です。

```bash
free -h
uptime
dmesg --ctime | grep -Ei 'memory pressure|out of memory|killed process'
```

`available`が少なく、Swapがほぼ100%で、`memory pressure`が続く場合は、実行中のビルドを止めて`docker compose down`を実行します。その後、Windows PowerShellから次を実行してWSL VMとSwapを初期化します。

```powershell
wsl --shutdown
```

Windowsに8GB以上の物理メモリがある場合の基準値として、`%UserProfile%\.wslconfig`を次のように設定します。ほかのWSLディストリビューションにも共通で適用されるため、Windows側に必要なメモリを残して値を調整してください。

```ini
[wsl2]
memory=4GB
processors=2
swap=4GB

[experimental]
autoMemoryReclaim=gradual
```

保存後にもう一度`wsl --shutdown`を実行し、Docker Desktop、WSL、VS Codeの順で起動します。`free -h`で新しい上限を確認してから、developmentとruntimeのビルド、品質検査を一つずつ実行します。

各キーの意味と既定値は、Microsoftの[WSLでの詳細設定](https://learn.microsoft.com/ja-jp/windows/wsl/wsl-config)を参照してください。
