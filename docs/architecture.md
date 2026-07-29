# アーキテクチャ

```text
Gradio UI
  -> application services
    -> domain ports
      -> JSON repositories / LocalJudge / hint providers
```

`domain/` はPydanticモデル、判定状態、出力比較、抽象ポートを持ち、Gradio・ファイルシステム・サブプロセスに依存しません。`application/` は学習フローを組み立て、学習者向けDTOへ私的なJudge情報を渡さない境界です。`infrastructure/` はJSON保存、ユーザーコード実行、固定ヒントを実装します。`ui/` はGradioイベントと表示整形だけを担当します。

適応型ヒントの追加後も依存方向は変えません。`TutorService` は公開問題情報、
安全化済みJudge診断、現在コード、質問、会話履歴からプロバイダ非依存の要求を作ります。
OpenAI、Gemma、Gemini固有のSDKとHTTP処理は `infrastructure/` に閉じ込めます。
詳しい信頼境界は[適応型ヒントとLLM設計](llm-hint-design.md)を参照してください。

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
