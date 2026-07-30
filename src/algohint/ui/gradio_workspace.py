"""Contextual Gradio workspace for execution, diagnostics, tutoring, and explanation."""

import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

import gradio as gr

from algohint.application.dto import LearnerDiagnostic
from algohint.application.completion_review_service import (
    CodeReviewUnavailableError,
    CompletionRequiredError,
    PersonalizedQuizUnavailableError,
    QuizRequiredError,
    ReviewConsentRequiredError,
)
from algohint.application.tutor_service import CloudConsentRequiredError
from algohint.application.research_service import ResearchConsentRequiredError
from algohint.domain.enums import (
    CompletionReason,
    HintProviderId,
    HintTrigger,
    JudgeStatus,
    PersonalizedQuizMode,
    ProviderFailureReason,
    SubmissionMode,
    TutorRole,
)
from algohint.domain.models import (
    ProviderAvailability,
    ResearchHistoryEntry,
    ResearchResult,
    ResearchUsage,
    TutorSession,
)
from algohint.infrastructure.gemma_research_provider import ResearchProviderError
from algohint.ui.formatters import (
    format_problem,
    format_code_review,
    format_code_review_history,
    format_quiz_history,
    format_quiz_result,
    format_report,
    format_review_quota,
    format_submission,
)
from algohint.ui.view_models import ApplicationServices

PROVIDER_CHOICES = [
    ("GPT-5.6", HintProviderId.OPENAI.value),
    ("Gemma 4 12B", HintProviderId.GEMMA.value),
    ("Gemini", HintProviderId.GEMINI.value),
]
PROVIDER_LABELS = {provider_id: label for label, provider_id in PROVIDER_CHOICES}
QUIZ_MODE_CHOICES = [
    ("AIが2〜5問を判断", PersonalizedQuizMode.ADAPTIVE_2_TO_5.value),
    ("3問固定", PersonalizedQuizMode.FIXED_3.value),
]
FALLBACK_NOTICES = {
    ProviderFailureReason.NOT_CONFIGURED.value: (
        "モデルの接続設定がありません。環境変数を確認してください。"
    ),
    ProviderFailureReason.INVALID_REQUEST.value: (
        "モデルへの要求形式が受理されませんでした。アプリとSDKの互換性を確認してください。"
    ),
    ProviderFailureReason.AUTHENTICATION_OR_PERMISSION.value: (
        "APIキー、権限、または課金設定を確認してください。"
    ),
    ProviderFailureReason.MODEL_NOT_FOUND.value: (
        "モデル名またはそのモデルへのアクセス権を確認してください。"
    ),
    ProviderFailureReason.RATE_OR_QUOTA_EXCEEDED.value: (
        "利用上限に達しています。時間を置くか、レート制限と割当量を確認してください。"
    ),
    ProviderFailureReason.TIMEOUT.value: (
        "モデルへの接続がタイムアウトしました。ネットワークを確認して再試行してください。"
    ),
    ProviderFailureReason.ENDPOINT_UNREACHABLE.value: (
        "Gemma ServerまたはSSH tunnelへ接続できません。"
        "管理用launcherからdoctor診断を実行してください。"
    ),
    ProviderFailureReason.PROVIDER_UNAVAILABLE.value: (
        "モデルが一時的に利用できません。時間を置いて再試行してください。"
    ),
    ProviderFailureReason.EMPTY_OR_BLOCKED_RESPONSE.value: (
        "モデルの応答が空、または安全設定によりブロックされました。"
    ),
    ProviderFailureReason.INVALID_STRUCTURED_RESPONSE.value: (
        "モデルの応答形式を検証できませんでした。"
    ),
    ProviderFailureReason.CLIENT_LIFECYCLE_ERROR.value: (
        "モデル接続の内部クライアントが早期終了しました。アプリを更新または再起動してください。"
    ),
    ProviderFailureReason.UNKNOWN_PROVIDER_ERROR.value: (
        "モデル呼び出しで分類できないエラーが発生しました。doctor診断を実行してください。"
    ),
    "unsafe_output": "答え漏洩の可能性がある応答を表示しませんでした。",
}
QUESTION_SHORTCUT_SCRIPT = """
() => {
  const bindShortcut = () => {
    const input = document.querySelector("#tutor-question textarea");
    if (!input || input.dataset.algohintShortcutBound === "true") return;
    input.dataset.algohintShortcutBound = "true";
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" || (!event.ctrlKey && !event.metaKey)) return;
      event.preventDefault();
      const button = document.querySelector(
        "button#ask-question, #ask-question button, #ask-question"
      );
      if (button instanceof HTMLElement) button.click();
    });
  };
  bindShortcut();
  new MutationObserver(bindShortcut).observe(document.body, {
    childList: true,
    subtree: true,
  });
}
""".strip()
OPEN_COMPLETION_TAB_SCRIPT = """
() => {
  let attempts = 0;
  const selectWhenEnabled = () => {
    attempts += 1;
    const completionTab = Array.from(document.querySelectorAll('[role="tab"]'))
      .find((tab) => tab.textContent?.includes('完了後の小テスト'));
    const disabled = completionTab?.getAttribute('aria-disabled') === 'true'
      || completionTab?.hasAttribute('disabled');
    if (completionTab instanceof HTMLElement && !disabled) {
      completionTab.click();
      return;
    }
    if (attempts < 30) window.setTimeout(selectWhenEnabled, 100);
  };
  selectWhenEnabled();
}
""".strip()


def _format_curriculum_item(item: dict[str, object]) -> str:
    """Defensively render validated JSON content for the roadmap."""

    problem_ids = item.get("problem_ids", [])
    ids = problem_ids if isinstance(problem_ids, list) else []
    return (
        f"### {item.get('level', '')}: {item.get('title', '')}\n"
        f"{item.get('description', '')}\n問題: "
        f"{', '.join(str(problem_id) for problem_id in ids)}"
    )


def _format_provider_status(provider_id: HintProviderId, availability: ProviderAvailability) -> str:
    """Describe readiness without exposing credentials or endpoint internals."""

    label = PROVIDER_LABELS[provider_id.value]
    if not availability.available:
        return f"🟡 **{label}**: {availability.reason} RuleBasedヒントを使用します。"
    destination = "外部サービスへ送信" if availability.sends_data_off_device else "ローカル接続"
    return f"🟢 **{label}**: 利用可能（{destination}）"


def _format_tutor_session(session: TutorSession) -> list[dict[str, str]]:
    """Render source-free persisted messages for Gradio Chatbot."""

    messages: list[dict[str, str]] = []
    for message in session.messages:
        content = message.text
        if message.role is TutorRole.ASSISTANT and message.provider and message.model_name:
            content += f"\n\n— {message.provider} / {message.model_name}"
        messages.append({"role": message.role.value, "content": content})
    return messages


def _format_fallback_notice(reason_code: str | None) -> str:
    """Map a safe reason code to an actionable message without raw provider data."""

    detail = (
        FALLBACK_NOTICES.get(reason_code) if reason_code is not None else None
    ) or "選択モデルを利用できませんでした。接続設定を確認してください。"
    return f"{detail} RuleBasedヒントを表示しました。"


def _format_research_usage(usage: ResearchUsage) -> str:
    """Render cost controls without suggesting that response estimates are invoices."""

    icon = "🟢" if usage.state == "available" else "🟡" if usage.state == "warning" else "🔴"
    return (
        f"{icon} **Exa内部予算**: 今月 ${usage.calendar_month_cost_usd} / "
        f"${usage.monthly_budget_usd}、直近30日 ${usage.rolling_30_day_cost_usd}、"
        f"Search {usage.calendar_month_searches}回（残り最大"
        f"{usage.remaining_searches}回）。状態: `{usage.state}`"
    )


def _safe_markdown_text(value: str) -> str:
    """Neutralize link delimiters in untrusted external source titles."""

    return value.replace("[", "［").replace("]", "］").replace("\n", " ").strip()


def _format_research_result(result: ResearchResult) -> str:
    """Render one grounded hint and its independently validated source list."""

    lines = ["## 根拠付きヒント", result.text]
    if result.citations:
        lines.append("### 出典")
        for citation in result.citations:
            title = _safe_markdown_text(citation.title)
            lines.append(
                f"- [{citation.citation_id}] [{title}]({citation.url}) "
                f"（{citation.domain}）"
            )
    lines.extend(
        (
            "### Agentic Research trace",
            "`" + " → ".join(result.trace) + "`",
            (
                f"Search {result.search_requests}回 / Contents {result.content_pages}ページ / "
                f"cache hit {result.cache_hits}回 / {result.elapsed_ms} ms"
            ),
        )
    )
    if result.fallback:
        lines.append("検索を完了できなかったため、静的ヒントへフォールバックしました。")
    return "\n\n".join(lines)


def _format_research_history(entries: tuple[ResearchHistoryEntry, ...]) -> str:
    """Show bounded, profile-scoped evidence without raw retrieved contents."""

    if not entries:
        return ""
    lines = ["### 保存済みResearch履歴"]
    for entry in entries[:5]:
        lines.append(
            f"- {entry.created_at.astimezone().strftime('%Y-%m-%d %H:%M')} / "
            f"{entry.judge_status} / run `{entry.result.run_id[:12]}` / "
            f"Search {entry.result.search_requests}回"
        )
    return "\n".join(lines)


def build_app(services: ApplicationServices, teacher_mode: bool, shared_mode: bool) -> gr.Blocks:
    """Build one contextual learning workspace without exposing private judge data."""

    default_profile = services.profiles.default_profile()
    profiles = services.profiles.list_profiles()
    profile_choices = [(profile.display_name, profile.profile_id) for profile in profiles]
    problems = services.problems.list_problems()
    problem_choices = [
        (f"{problem.level} | {problem.title}", problem.problem_id) for problem in problems
    ]
    default_selection = services.selections.restore(
        default_profile.profile_id if default_profile is not None else None
    )
    initial_problem_id = default_selection.problem_id
    if initial_problem_id is None:
        initial_problem_header = "利用できる問題がありません。"
        initial_problem_body = "教材データを確認してください。"
        initial_tutor_messages: list[dict[str, str]] = []
        initial_tutor_status = "問題を選択できません。"
    else:
        initial_problem_header, initial_problem_body = format_problem(
            services.problems.get_learner_problem(initial_problem_id)
        )
        if default_profile is None:
            initial_tutor_messages = []
            initial_tutor_status = "プロフィールを作成すると問題別の履歴を保存できます。"
        else:
            initial_session = services.tutor.load_session(
                default_profile.profile_id,
                initial_problem_id,
            )
            initial_tutor_messages = _format_tutor_session(initial_session)
            initial_tutor_status = (
                "保存済みの問題別履歴を読み込みました。"
                if initial_session.messages
                else "まだヒント履歴はありません。"
            )
        if default_selection.persistence_warning:
            initial_tutor_status += f"\n\n{default_selection.persistence_warning}"
    initial_review = (
        services.reviews.view(default_profile.profile_id, initial_problem_id)
        if default_profile is not None and initial_problem_id is not None
        else None
    )
    initial_quiz_questions = initial_review.questions if initial_review is not None else ()
    initial_quiz_history = (
        services.reviews.quiz_history(
            default_profile.profile_id,
            initial_problem_id,
        )
        if initial_review is not None
        and default_profile is not None
        and initial_problem_id is not None
        else None
    )
    initial_personalized_quiz = (
        services.reviews.view_personalized_quiz(
            default_profile.profile_id,
            initial_problem_id,
        )
        if initial_review is not None
        and initial_review.authored_quiz_completed
        and default_profile is not None
        and initial_problem_id is not None
        else None
    )
    default_provider = (
        default_profile.preferences.hint_provider
        if default_profile is not None
        else HintProviderId.OPENAI
    )
    default_quiz_mode = (
        default_profile.preferences.personalized_quiz_mode
        if default_profile is not None
        else PersonalizedQuizMode.ADAPTIVE_2_TO_5
    )
    safety_note = (
        "⚠️ 共有リンクでは任意コードが実行されます。信頼できる個人利用に限定してください。"
        if shared_mode
        else "ローカル個人学習用です。任意コード実行のため公開サーバーでは利用しないでください。"
    )

    with gr.Blocks(title="AlgoHint Coach") as app:
        gr.Markdown("# AlgoHint Coach\n\n自分で考えるための段階的ヒント付きアルゴリズム練習")
        gr.Markdown(safety_note)
        if teacher_mode:
            gr.Markdown(
                "教師モードが有効です。秘匿データは教師が管理する環境でだけ確認してください。"
            )
        if default_profile is not None and default_profile.is_development:
            gr.Markdown("🧪 開発モード: 「開発テスト」プロフィールを使用しています。")

        with gr.Row():
            profile_selector = gr.Dropdown(
                choices=profile_choices,
                label="プロフィール",
                value=default_profile.profile_id if default_profile is not None else None,
                scale=2,
                elem_id="profile-selector",
            )
            provider_selector = gr.Dropdown(
                choices=PROVIDER_CHOICES,
                label="ヒントモデル",
                value=default_provider.value,
                scale=1,
                elem_id="provider-selector",
            )
            quiz_mode_selector = gr.Dropdown(
                choices=QUIZ_MODE_CHOICES,
                label="AI小テスト問題数",
                value=default_quiz_mode.value,
                scale=1,
                elem_id="quiz-mode-selector",
            )
        provider_status = gr.Markdown(
            _format_provider_status(
                default_provider,
                services.tutor.provider_availability(default_provider),
            ),
            elem_id="provider-status",
        )
        with gr.Accordion("プロフィール管理", open=False):
            with gr.Row():
                profile_name = gr.Textbox(label="新しいプロフィール名", max_length=40, scale=3)
                create_profile = gr.Button("プロフィールを作成", scale=1)

        with gr.Tab("学習ロードマップ"):
            roadmap = "\n\n".join(
                _format_curriculum_item(item) for item in services.problems.curriculum()
            )
            gr.Markdown(roadmap)

        with gr.Tab("問題演習"):
            problem_selector = gr.Dropdown(
                choices=problem_choices,
                label="問題を選択",
                value=initial_problem_id,
                elem_id="problem-selector",
            )
            latest_diagnostic = gr.State(value=None)
            accepted_source = gr.State(value="")
            personalized_quiz_trigger = gr.State(value=False)
            with gr.Row(equal_height=False):
                with gr.Column(scale=6, min_width=360):
                    problem_header = gr.Markdown(initial_problem_header)
                    problem_body = gr.Markdown(initial_problem_body)
                with gr.Column(scale=5, min_width=340):
                    code = gr.Code(
                        label="Pythonコード",
                        language="python",
                        value="",
                        elem_id="code-editor",
                    )
                    with gr.Row():
                        sample_submit = gr.Button(
                            "公開サンプルで実行",
                            elem_id="sample-submit",
                        )
                        full_submit = gr.Button(
                            "全テストで提出",
                            variant="primary",
                            elem_id="full-submit",
                        )
                    submission_result = gr.Markdown("", elem_id="submission-result")

                    gr.Markdown("## ヒントコーチ")
                    tutor_chat = gr.Chatbot(
                        label="問題ごとの質問・ヒント履歴",
                        value=cast(Any, initial_tutor_messages),
                        height=320,
                        sanitize_html=True,
                        allow_file_downloads=False,
                        buttons=[],
                        elem_id="tutor-chat",
                    )
                    tutor_status = gr.Markdown(
                        initial_tutor_status,
                        elem_id="tutor-status",
                    )
                    cloud_consent = gr.Checkbox(
                        label=(
                            "公開問題、現在コード、質問、安全化した診断、会話履歴を"
                            "選択中のクラウド／リモートモデルへ送信し、生成したAI小テスト・"
                            "レビューをローカル履歴へ保存することに同意します"
                        ),
                        value=False,
                        elem_id="cloud-consent",
                    )
                    question = gr.Textbox(
                        label="質問",
                        placeholder="例: このループで何を数えるべきですか？",
                        info="Enterで改行、Ctrl+Enter（MacはCmd+Enter）で送信します。",
                        lines=3,
                        max_lines=8,
                        max_length=1_000,
                        elem_id="tutor-question",
                    )
                    with gr.Row():
                        ask_question = gr.Button(
                            "質問する",
                            variant="primary",
                            elem_id="ask-question",
                        )
                        stuck = gr.Button(
                            "わからない（次のヒント）",
                            elem_id="stuck-hint",
                        )
                        result_hint = gr.Button(
                            "実行結果からヒント",
                            elem_id="result-hint",
                        )
                    clear_history = gr.Button(
                        "この問題のヒント履歴をクリア",
                        elem_id="clear-tutor-history",
                    )

                    with gr.Accordion("根拠付きWeb検索（Exa）", open=False):
                        gr.Markdown(
                            "公開問題の題名・レビュー済み要約・概念タグ・一般化した"
                            "Judge状態だけをGemma Serverへ送ります。コード、質問、"
                            "プロフィール、履歴、隠しテストは送信しません。"
                        )
                        research_consent = gr.Checkbox(
                            label=(
                                "この1回について、上記の公開情報を使ったExa検索に"
                                "同意します"
                            ),
                            value=False,
                            elem_id="research-consent",
                        )
                        with gr.Row():
                            request_research_button = gr.Button(
                                "根拠付きヒントを検索",
                                variant="secondary",
                                interactive=services.research is not None,
                                elem_id="request-grounded-research",
                            )
                            refresh_research_usage_button = gr.Button(
                                "検索予算を確認",
                                interactive=services.research is not None,
                                elem_id="refresh-research-usage",
                            )
                        research_usage = gr.Markdown(
                            (
                                "Gemma Serverへ接続して検索予算を確認できます。"
                                if services.research is not None
                                else "Transformers HTTP版Gemma Serverが未設定のため利用できません。"
                            ),
                            elem_id="research-usage",
                        )
                        research_result = gr.Markdown(
                            "",
                            elem_id="research-result",
                        )

                    gr.Markdown(
                        "完了後の小テストは、全テストACまたはギブアップで解禁されます。",
                        elem_id="completion-unlock-notice",
                    )
                    give_up = gr.Button("ギブアップして小テストへ進む", variant="stop")

        with gr.Tab(
            "完了後の小テスト",
            interactive=initial_review is not None,
            id="completion-review",
            elem_id="completion-review-tab",
        ) as completion_tab:
            completion_banner = gr.Markdown(
                (
                    "固定5問に回答してください。"
                    if initial_review is not None
                    else "全テストACまたはギブアップ後に利用できます。"
                ),
                elem_id="completion-banner",
            )
            completion_status = gr.Markdown(
                (
                    "固定5問の採点後に、解説とAIコード改善レビューを確認できます。"
                    if initial_review is not None
                    and not initial_review.authored_quiz_completed
                    else "固定小テストは採点済みです。"
                    if initial_review is not None
                    else ""
                )
            )
            gr.Markdown("## 固定5問")
            quiz_radios: list[gr.Radio] = []
            for index in range(5):
                initial_question = (
                    initial_quiz_questions[index]
                    if index < len(initial_quiz_questions)
                    else None
                )
                quiz_radios.append(
                    gr.Radio(
                        choices=[
                            (option.text, option.option_id)
                            for option in initial_question.options
                        ]
                        if initial_question is not None
                        else [],
                        label=(
                            f"問{index + 1}: {initial_question.prompt}"
                            if initial_question is not None
                            else f"問{index + 1}"
                        ),
                        value=None,
                        visible=initial_question is not None,
                        elem_id=f"review-quiz-{index + 1}",
                    )
                )
            submit_quiz = gr.Button(
                "固定小テストを採点",
                variant="primary",
                visible=initial_review is not None,
                elem_id="submit-review-quiz",
            )
            quiz_result = gr.Markdown("", elem_id="review-quiz-result")
            review_quota = gr.Markdown(
                format_review_quota(initial_quiz_history)
                if initial_quiz_history is not None
                else "",
                elem_id="review-history-quota",
            )
            quiz_history = gr.Markdown(
                format_quiz_history(initial_quiz_history)
                if initial_quiz_history is not None
                else "",
                elem_id="review-quiz-history",
            )
            quiz_history_page = gr.State(value=0)
            with gr.Row():
                previous_quiz_history = gr.Button(
                    "新しい履歴へ",
                    visible=False,
                    elem_id="previous-review-history",
                )
                next_quiz_history = gr.Button(
                    "古い履歴へ",
                    visible=(
                        initial_quiz_history is not None
                        and initial_quiz_history.total_count
                        > initial_quiz_history.page_size
                    ),
                    elem_id="next-review-history",
                )

            gr.Markdown("## AIによるコード別小テスト")
            personalized_quiz_status = gr.Markdown(
                (
                    "AI生成内容のため誤りを含む可能性があります。"
                    if initial_personalized_quiz is not None
                    else "全テストAC後にコードを確認して自動生成します。"
                ),
                elem_id="personalized-quiz-status",
            )
            personalized_quiz_set_id = gr.State(
                value=(
                    initial_personalized_quiz.quiz_set_id
                    if initial_personalized_quiz is not None
                    else ""
                )
            )
            personalized_radios: list[gr.Radio] = []
            for index in range(5):
                initial_question = (
                    initial_personalized_quiz.questions[index]
                    if initial_personalized_quiz is not None
                    and index < len(initial_personalized_quiz.questions)
                    else None
                )
                personalized_radios.append(
                    gr.Radio(
                        choices=[
                            (option.text, option.option_id)
                            for option in initial_question.options
                        ]
                        if initial_question is not None
                        else [],
                        label=(
                            f"AI問{index + 1}: {initial_question.prompt}"
                            if initial_question is not None
                            else f"AI問{index + 1}"
                        ),
                        visible=initial_question is not None,
                        elem_id=f"personalized-quiz-{index + 1}",
                    )
                )
            grade_personalized_quiz = gr.Button(
                "AI小テストを採点",
                visible=initial_personalized_quiz is not None,
                elem_id="grade-personalized-quiz",
            )
            regenerate_personalized_quiz = gr.Button(
                "AI小テストを再生成",
                visible=False,
                elem_id="regenerate-personalized-quiz",
            )
            personalized_quiz_result = gr.Markdown(
                "",
                elem_id="personalized-quiz-result",
            )

            gr.Markdown("## 解説")
            show_explanation_button = gr.Button(
                "解説を表示",
                interactive=(
                    initial_review is not None
                    and initial_review.authored_quiz_completed
                ),
                elem_id="show-explanation",
            )
            explanation_result = gr.Markdown("", elem_id="explanation-result")

            gr.Markdown("## AIによるコード改善レビュー")
            code_review_status = gr.Markdown(
                (
                    "ボタンを押すまでレビューは表示しません。"
                    if initial_review is not None
                    and initial_review.authored_quiz_completed
                    else "固定小テスト実施中はレビューを確認できません。"
                ),
                elem_id="code-review-status",
            )
            with gr.Row():
                show_saved_code_reviews = gr.Button(
                    "保存済みAIレビューを表示",
                    interactive=(
                        initial_review is not None
                        and initial_review.authored_quiz_completed
                    ),
                    elem_id="show-saved-code-reviews",
                )
                retry_code_review = gr.Button(
                    "現在コードを新規AIレビュー",
                    interactive=(
                        initial_review is not None
                        and initial_review.authored_quiz_completed
                    ),
                    elem_id="retry-code-review",
                )
            current_code_review = gr.Markdown("", elem_id="current-code-review")
            code_review_history = gr.Markdown("", elem_id="code-review-history")
            code_review_history_page = gr.State(value=0)
            with gr.Row():
                previous_code_review_history = gr.Button(
                    "新しいレビューへ",
                    visible=False,
                    elem_id="previous-code-review-history",
                )
                next_code_review_history = gr.Button(
                    "古いレビューへ",
                    visible=False,
                    elem_id="next-code-review-history",
                )

        with gr.Tab("学習レポート"):
            refresh_report = gr.Button("レポートを更新")
            report_result = gr.Markdown("プロフィールを選択してレポートを更新してください。")

        if teacher_mode:
            with gr.Tab("教師用"):
                teacher_result = gr.Markdown("問題を選択すると模範解答と隠しテストを表示します。")

        def selected_problem(profile_id: str | None, problem_id: str | None):
            if not problem_id:
                return "問題を選択してください。", "", [], "", None, ""
            selection = services.selections.select(profile_id, problem_id)
            header, body = format_problem(services.problems.get_learner_problem(problem_id))
            if not profile_id:
                return (
                    header,
                    body,
                    [],
                    "プロフィールを選択してください。",
                    None,
                    "",
                )
            session = services.tutor.load_session(profile_id, problem_id)
            status = (
                "保存済みの問題別履歴を読み込みました。"
                if session.messages
                else "まだヒント履歴はありません。"
            )
            if selection.persistence_warning:
                status += f"\n\n{selection.persistence_warning}"
            return (
                header,
                body,
                _format_tutor_session(session),
                status,
                None,
                "",
            )

        def created_profile(display_name: str):
            if not display_name.strip():
                return (
                    gr.Dropdown(),
                    gr.Dropdown(),
                    gr.Dropdown(),
                    "プロフィール名を入力してください。",
                    "プロフィール名を入力してください。",
                    False,
                    gr.Dropdown(),
                    "問題を選択してください。",
                    "",
                    [],
                    "プロフィール名を入力してください。",
                    None,
                    "",
                )
            profile = services.profiles.create_profile(display_name)
            selection = services.selections.restore(profile.profile_id)
            choices = [
                (item.display_name, item.profile_id) for item in services.profiles.list_profiles()
            ]
            provider = profile.preferences.hint_provider
            if selection.problem_id is None:
                header, body = "利用できる問題がありません。", "教材データを確認してください。"
                messages: list[dict[str, str]] = []
                tutor_message = "問題を選択できません。"
            else:
                header, body = format_problem(
                    services.problems.get_learner_problem(selection.problem_id)
                )
                messages = _format_tutor_session(
                    services.tutor.load_session(profile.profile_id, selection.problem_id)
                )
                tutor_message = "まだヒント履歴はありません。"
            return (
                gr.Dropdown(choices=choices, value=profile.profile_id),
                gr.Dropdown(value=provider.value),
                gr.Dropdown(value=profile.preferences.personalized_quiz_mode.value),
                _format_provider_status(provider, services.tutor.provider_availability(provider)),
                f"{profile.display_name} を選択しました。",
                False,
                gr.Dropdown(value=selection.problem_id),
                header,
                body,
                messages,
                tutor_message,
                None,
                "",
            )

        def selected_profile(profile_id: str | None, problem_id: str | None):
            if not profile_id:
                return (
                    gr.Dropdown(value=HintProviderId.OPENAI.value),
                    gr.Dropdown(value=PersonalizedQuizMode.ADAPTIVE_2_TO_5.value),
                    "プロフィールを選択してください。",
                    gr.Dropdown(value=problem_id),
                    "問題を選択してください。",
                    "",
                    [],
                    "プロフィールを選択してください。",
                    False,
                    None,
                    "",
                )
            profile = services.profiles.get_profile(profile_id)
            provider = profile.preferences.hint_provider
            selection = services.selections.restore(profile_id)
            if selection.problem_id is None:
                header, body = "利用できる問題がありません。", "教材データを確認してください。"
                messages: list[dict[str, str]] = []
                tutor_message = "問題を選択できません。"
            else:
                header, body = format_problem(
                    services.problems.get_learner_problem(selection.problem_id)
                )
                session = services.tutor.load_session(profile_id, selection.problem_id)
                messages = _format_tutor_session(session)
                tutor_message = (
                    "保存済みの問題別履歴を読み込みました。"
                    if session.messages
                    else "まだヒント履歴はありません。"
                )
                if selection.persistence_warning:
                    tutor_message += f"\n\n{selection.persistence_warning}"
            return (
                gr.Dropdown(value=provider.value),
                gr.Dropdown(value=profile.preferences.personalized_quiz_mode.value),
                _format_provider_status(provider, services.tutor.provider_availability(provider)),
                gr.Dropdown(value=selection.problem_id),
                header,
                body,
                messages,
                tutor_message,
                False,
                None,
                "",
            )

        def selected_provider(profile_id: str | None, provider_name: str):
            if not profile_id:
                return "プロフィールを選択してください。", False
            provider = HintProviderId(provider_name)
            services.profiles.set_hint_provider(profile_id, provider)
            return (
                _format_provider_status(provider, services.tutor.provider_availability(provider)),
                False,
            )

        def selected_quiz_mode(profile_id: str | None, mode_name: str):
            if not profile_id:
                return gr.Dropdown(value=PersonalizedQuizMode.ADAPTIVE_2_TO_5.value)
            mode = PersonalizedQuizMode(mode_name)
            services.profiles.set_personalized_quiz_mode(profile_id, mode)
            return gr.Dropdown(value=mode.value)

        def submit(
            profile_id: str | None,
            problem_id: str | None,
            source: str,
            mode: SubmissionMode,
        ):
            if not profile_id or not problem_id:
                return "プロフィールと問題を選択してください。", None
            if not source.strip():
                return "提出するPythonコードを入力してください。", None
            result = services.submissions.submit(profile_id, problem_id, source, mode)
            return format_submission(result), result.diagnostic

        def submit_full(
            profile_id: str | None,
            problem_id: str | None,
            source: str,
        ):
            """Return an AI-quiz trigger only for the first accepted FULL source."""

            if not profile_id or not problem_id:
                return "プロフィールと問題を選択してください。", None, False, ""
            if not source.strip():
                return "提出するPythonコードを入力してください。", None, False, ""
            result = services.submissions.submit(
                profile_id,
                problem_id,
                source,
                SubmissionMode.FULL,
            )
            return (
                format_submission(result),
                result.diagnostic,
                result.newly_completed,
                source if result.status is JudgeStatus.AC else "",
            )

        def request_tutor_hint(
            profile_id: str | None,
            problem_id: str | None,
            source: str,
            question_text: str,
            consent: bool,
            diagnostic: LearnerDiagnostic | None,
            trigger: HintTrigger,
        ) -> Iterator[tuple[list[dict[str, str]], str, str]]:
            if not profile_id or not problem_id:
                yield [], "プロフィールと問題を選択してください。", question_text
                return
            try:
                cleaned_question, _, _ = services.tutor.validate_request(
                    profile_id,
                    trigger=trigger,
                    question=question_text if trigger is HintTrigger.QUESTION else None,
                    cloud_consent=consent,
                )
            except (CloudConsentRequiredError, ValueError) as error:
                session = services.tutor.load_session(profile_id, problem_id)
                yield _format_tutor_session(session), str(error), question_text
                return

            current = services.tutor.load_session(profile_id, problem_id)
            pending_messages = _format_tutor_session(current)
            # Keep every pending trigger browser-only. Persistence remains an
            # assistant/user pair so interrupted generations leave no orphan.
            pending_messages = [
                *pending_messages,
                {
                    "role": TutorRole.USER.value,
                    "content": services.tutor.user_message_text(
                        trigger,
                        cleaned_question,
                    ),
                },
            ]
            started = time.monotonic()
            cleared_question = "" if trigger is HintTrigger.QUESTION else question_text
            yield (
                pending_messages,
                "回答を生成中…（経過時間: 0 s）",
                cleared_question,
            )
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                services.tutor.request_hint,
                profile_id,
                problem_id,
                trigger=trigger,
                source_code=source,
                question=question_text if trigger is HintTrigger.QUESTION else None,
                diagnostic=diagnostic,
                cloud_consent=consent,
            )
            try:
                elapsed_seconds = 0
                while not future.done():
                    time.sleep(1)
                    current_elapsed = int(time.monotonic() - started)
                    if current_elapsed > elapsed_seconds and not future.done():
                        elapsed_seconds = current_elapsed
                        yield (
                            pending_messages,
                            f"回答を生成中…（経過時間: {elapsed_seconds} s）",
                            cleared_question,
                        )
                reply = future.result()
            except (CloudConsentRequiredError, ValueError) as error:
                session = services.tutor.load_session(profile_id, problem_id)
                yield _format_tutor_session(session), str(error), question_text
                return
            finally:
                executor.shutdown(wait=True)
            notices: list[str] = []
            if reply.hint.used_fallback:
                notices.append(_format_fallback_notice(reply.hint.fallback_reason))
            if reply.source_omitted:
                notices.append("コードが16KiBを超えたため、コード本文はモデルへ送りませんでした。")
            elapsed = time.monotonic() - started
            notices.append(f"回答を表示しました。（所要時間: {elapsed:.1f} s）")
            yield (
                _format_tutor_session(reply.session),
                "\n\n".join(notices),
                cleared_question,
            )

        def request_question(
            profile_id: str | None,
            problem_id: str | None,
            source: str,
            question_text: str,
            consent: bool,
            diagnostic: LearnerDiagnostic | None,
        ) -> Iterator[tuple[list[dict[str, str]], str, str]]:
            """Bind the explicit question trigger without obscuring callback types."""

            yield from request_tutor_hint(
                profile_id,
                problem_id,
                source,
                question_text,
                consent,
                diagnostic,
                HintTrigger.QUESTION,
            )

        def request_stuck_hint(
            profile_id: str | None,
            problem_id: str | None,
            source: str,
            question_text: str,
            consent: bool,
            diagnostic: LearnerDiagnostic | None,
        ) -> Iterator[tuple[list[dict[str, str]], str, str]]:
            """Bind the learner-initiated stuck trigger."""

            yield from request_tutor_hint(
                profile_id,
                problem_id,
                source,
                question_text,
                consent,
                diagnostic,
                HintTrigger.STUCK,
            )

        def request_result_hint(
            profile_id: str | None,
            problem_id: str | None,
            source: str,
            question_text: str,
            consent: bool,
            diagnostic: LearnerDiagnostic | None,
        ) -> Iterator[tuple[list[dict[str, str]], str, str]]:
            """Bind the latest safe Judge diagnostic to a tutoring request."""

            yield from request_tutor_hint(
                profile_id,
                problem_id,
                source,
                question_text,
                consent,
                diagnostic,
                HintTrigger.JUDGE_RESULT,
            )

        def clear_tutor_history(profile_id: str | None, problem_id: str | None):
            if not profile_id or not problem_id:
                return [], "プロフィールと問題を選択してください。"
            services.tutor.clear_session(profile_id, problem_id)
            return [], "この問題の質問・ヒント履歴をクリアしました。"

        def refresh_research_usage():
            """Fetch budget state explicitly without triggering Exa retrieval."""

            if services.research is None:
                return "Research機能は設定されていません。"
            try:
                return _format_research_usage(services.research.usage())
            except ResearchProviderError as error:
                return f"検索予算を確認できませんでした（{error.reason}）。"

        def request_grounded_research(
            profile_id: str | None,
            problem_id: str | None,
            consent: bool,
        ):
            """Run one explicit public-context research action and reset consent."""

            if services.research is None:
                return "", "Research機能は設定されていません。", False
            if not profile_id or not problem_id:
                return "", "プロフィールと問題を選択してください。", False
            try:
                result = services.research.research(
                    profile_id,
                    problem_id,
                    consent=consent,
                )
                history = services.research.history(profile_id, problem_id, limit=5)
            except (ResearchConsentRequiredError, ResearchProviderError, ValueError) as error:
                reason = error.reason if isinstance(error, ResearchProviderError) else str(error)
                return "", f"根拠付き検索を実行できませんでした（{reason}）。", False
            rendered = _format_research_result(result)
            saved = _format_research_history(history)
            if saved:
                rendered += "\n\n" + saved
            return rendered, _format_research_usage(result.usage), False

        def show_explanation(
            profile_id: str | None,
            problem_id: str | None,
            surrender: bool,
        ):
            if not profile_id or not problem_id:
                return "プロフィールと問題を選択してください。"
            if surrender:
                services.completions.give_up(profile_id, problem_id)
            try:
                return services.reviews.get_explanation(profile_id, problem_id)
            except (CompletionRequiredError, QuizRequiredError) as error:
                return str(error)

        def give_up_and_explain(
            profile_id: str | None,
            problem_id: str | None,
        ):
            """Record give-up without revealing explanation or starting an AI review."""

            if not profile_id or not problem_id:
                return "プロフィールと問題を選択してください。", ""
            services.completions.give_up(profile_id, problem_id)
            return (
                "ギブアップを記録しました。固定小テストに進みましょう。",
                "",
            )

        def show_report(profile_id: str | None):
            if not profile_id:
                return "プロフィールを選択してください。"
            return format_report(services.reports.report(profile_id))

        def load_completion(profile_id: str | None, problem_id: str | None):
            """Synchronize the completion tab without revealing gated material."""

            view = (
                services.reviews.view(profile_id, problem_id)
                if profile_id and problem_id
                else None
            )
            if view is None:
                return (
                    gr.Tab(interactive=False),
                    "全テストACまたはギブアップ後に利用できます。",
                    "",
                    *[
                        gr.Radio(choices=[], value=None, visible=False)
                        for _ in range(5)
                    ],
                    gr.Button(visible=False),
                    "",
                    gr.Button(interactive=False),
                    gr.Button(interactive=False),
                    gr.Button(interactive=False),
                )
            updates = [
                gr.Radio(
                    choices=[(option.text, option.option_id) for option in question.options],
                    label=f"問{index}: {question.prompt}",
                    value=None,
                    visible=True,
                )
                for index, question in enumerate(view.questions, start=1)
            ]
            return (
                gr.Tab(interactive=True),
                (
                    "🎉 AC、おめでとうございます！固定小テストを始めましょう。"
                    if view.completion_reason is CompletionReason.FULL_AC
                    else "ギブアップを記録しました。固定小テストに進みましょう。"
                ),
                (
                    "固定小テストは採点済みです。"
                    if view.authored_quiz_completed
                    else (
                        "固定5問の採点後に、解説とAIコード改善レビューを"
                        "確認できます。"
                    )
                ),
                *updates,
                gr.Button(visible=True),
                "",
                gr.Button(interactive=view.authored_quiz_completed),
                gr.Button(interactive=view.authored_quiz_completed),
                gr.Button(interactive=view.authored_quiz_completed),
            )

        def grade_quiz(
            profile_id: str | None,
            problem_id: str | None,
            *answers: str | None,
        ):
            if not profile_id or not problem_id:
                return (
                    "プロフィールと問題を選択してください。",
                    "",
                    "",
                    0,
                    gr.Button(visible=False),
                    gr.Button(visible=False),
                    "",
                    gr.Button(interactive=False),
                    gr.Button(interactive=False),
                    gr.Button(interactive=False),
                )
            try:
                result = services.reviews.grade(
                    profile_id,
                    problem_id,
                    tuple(answers),
                )
            except (CompletionRequiredError, ValueError) as error:
                return (
                    str(error),
                    "",
                    "",
                    0,
                    gr.Button(visible=False),
                    gr.Button(visible=False),
                    "固定5問すべてに回答してください。",
                    gr.Button(interactive=False),
                    gr.Button(interactive=False),
                    gr.Button(interactive=False),
                )
            history_page = services.reviews.quiz_history(profile_id, problem_id)
            return (
                format_quiz_result(result),
                format_quiz_history(history_page),
                format_review_quota(history_page),
                0,
                gr.Button(visible=False),
                gr.Button(
                    visible=history_page.total_count > history_page.page_size
                ),
                "固定小テストを採点しました。解説とAIレビューを利用できます。",
                gr.Button(interactive=True),
                gr.Button(interactive=True),
                gr.Button(interactive=True),
            )

        def change_quiz_history_page(
            profile_id: str | None,
            problem_id: str | None,
            current_page: int,
            delta: int,
        ):
            if not profile_id or not problem_id:
                return "", "", 0, gr.Button(visible=False), gr.Button(visible=False)
            requested_page = max(0, current_page + delta)
            page = services.reviews.quiz_history(
                profile_id,
                problem_id,
                page=requested_page,
            )
            max_page = max(0, (page.total_count - 1) // page.page_size)
            if requested_page > max_page:
                page = services.reviews.quiz_history(
                    profile_id,
                    problem_id,
                    page=max_page,
                )
            has_newer = page.page > 0
            has_older = (page.page + 1) * page.page_size < page.total_count
            return (
                format_quiz_history(page),
                format_review_quota(page),
                page.page,
                gr.Button(visible=has_newer),
                gr.Button(visible=has_older),
            )

        def load_quiz_history(
            profile_id: str | None,
            problem_id: str | None,
        ):
            view = (
                services.reviews.view(profile_id, problem_id)
                if profile_id and problem_id
                else None
            )
            if view is None or not profile_id or not problem_id:
                return "", "", 0, gr.Button(visible=False), gr.Button(visible=False)
            page = services.reviews.quiz_history(profile_id, problem_id)
            return (
                format_quiz_history(page),
                format_review_quota(page),
                0,
                gr.Button(visible=False),
                gr.Button(visible=page.total_count > page.page_size),
            )

        def load_personalized_quiz(
            profile_id: str | None,
            problem_id: str | None,
            source: str,
        ):
            """Release generated questions only after the fixed quiz gate."""

            hidden = [
                gr.Radio(choices=[], value=None, visible=False)
                for _ in range(5)
            ]
            if not profile_id or not problem_id:
                return (
                    "プロフィールと問題を選択してください。",
                    "",
                    *hidden,
                    gr.Button(visible=False),
                    gr.Button(visible=False),
                )
            try:
                quiz = services.reviews.view_personalized_quiz(
                    profile_id,
                    problem_id,
                )
            except (CompletionRequiredError, QuizRequiredError) as error:
                return (
                    str(error),
                    "",
                    *hidden,
                    gr.Button(visible=False),
                    gr.Button(visible=bool(source)),
                )
            if quiz is None:
                return (
                    "AI小テストはまだありません。AC済みコードから再生成できます。",
                    "",
                    *hidden,
                    gr.Button(visible=False),
                    gr.Button(visible=bool(source)),
                )
            updates = [
                gr.Radio(
                    choices=[
                        (option.text, option.option_id)
                        for option in question.options
                    ],
                    label=f"AI問{index}: {question.prompt}",
                    value=None,
                    visible=True,
                )
                for index, question in enumerate(quiz.questions, start=1)
            ]
            updates.extend(
                gr.Radio(choices=[], value=None, visible=False)
                for _ in range(5 - len(updates))
            )
            return (
                (
                    f"{quiz.provider} / {quiz.model_name} が生成した"
                    f"{len(quiz.questions)}問です。AI生成内容のため誤りを"
                    "含む可能性があります。"
                ),
                quiz.quiz_set_id,
                *updates,
                gr.Button(visible=True),
                gr.Button(visible=bool(source)),
            )

        def generate_personalized_quiz_ui(
            profile_id: str | None,
            problem_id: str | None,
            source: str,
            consent: bool,
            should_generate: bool,
        ) -> Iterator[tuple[Any, bool, Any]]:
            """Generate in a separate event after the AC result is already visible."""

            if not should_generate:
                yield gr.skip(), False, gr.skip()
                return
            if not profile_id or not problem_id:
                yield "プロフィールと問題を選択してください。", False, gr.Button(
                    visible=False
                )
                return
            started = time.monotonic()
            yield "AI小テストを準備中…（経過時間: 0 s）", False, gr.Button(
                visible=False
            )
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                services.reviews.generate_personalized_quiz,
                profile_id,
                problem_id,
                source,
                cloud_consent=consent,
            )
            try:
                elapsed_seconds = 0
                while not future.done():
                    time.sleep(1)
                    current_elapsed = int(time.monotonic() - started)
                    if current_elapsed > elapsed_seconds and not future.done():
                        elapsed_seconds = current_elapsed
                        yield (
                            (
                                "AI小テストを準備中…"
                                f"（経過時間: {elapsed_seconds} s）"
                            ),
                            False,
                            gr.Button(visible=False),
                        )
                receipt = future.result()
            except (
                CompletionRequiredError,
                PersonalizedQuizUnavailableError,
                ReviewConsentRequiredError,
                ValueError,
            ) as error:
                yield (
                    f"{error} 固定5問はそのまま回答できます。",
                    False,
                    gr.Button(visible=bool(source)),
                )
                return
            finally:
                executor.shutdown(wait=True)
            elapsed = time.monotonic() - started
            yield (
                (
                    f"AI小テスト{receipt.question_count}問を準備しました。"
                    "固定5問の採点後に表示します。"
                    f"（所要時間: {elapsed:.1f} s）"
                ),
                False,
                gr.Button(visible=bool(source)),
            )

        def grade_personalized_quiz_ui(
            profile_id: str | None,
            problem_id: str | None,
            quiz_set_id: str,
            *answers: str | None,
        ) -> str:
            if not profile_id or not problem_id or not quiz_set_id:
                return "AI小テストを読み込んでください。"
            quiz = services.reviews.view_personalized_quiz(profile_id, problem_id)
            if quiz is None:
                return "AI小テストを読み込んでください。"
            try:
                result = services.reviews.grade_personalized_quiz(
                    profile_id,
                    problem_id,
                    quiz_set_id,
                    tuple(answers[: len(quiz.questions)]),
                )
            except (CompletionRequiredError, QuizRequiredError, ValueError) as error:
                return str(error)
            return (
                format_quiz_result(result)
                + "\n\nAI生成内容のため誤りを含む可能性があります。"
            )

        def retry_personalized_quiz_ui(
            profile_id: str | None,
            problem_id: str | None,
            source: str,
            consent: bool,
        ) -> Iterator[tuple[Any, bool, Any]]:
            yield from generate_personalized_quiz_ui(
                profile_id,
                problem_id,
                source,
                consent,
                True,
            )

        def load_code_review_state(
            profile_id: str | None,
            problem_id: str | None,
        ):
            view = (
                services.reviews.view(profile_id, problem_id)
                if profile_id and problem_id
                else None
            )
            if view is None or not profile_id or not problem_id:
                return (
                    "",
                    "全テストACまたはギブアップ後に利用できます。",
                    gr.Button(interactive=False),
                    "",
                    0,
                    gr.Button(visible=False),
                    gr.Button(visible=False),
                )
            if not view.authored_quiz_completed:
                return (
                    "",
                    "固定小テスト実施中は、AIコード改善レビューを確認できません。",
                    gr.Button(interactive=False),
                    "",
                    0,
                    gr.Button(visible=False),
                    gr.Button(visible=False),
                )
            history = services.reviews.code_review_history(profile_id, problem_id)
            latest = (
                format_code_review(history.entries[0]) if history.entries else ""
            )
            return (
                latest,
                "保存済みAIレビューを表示しました。",
                gr.Button(interactive=True),
                format_code_review_history(history),
                0,
                gr.Button(visible=False),
                gr.Button(visible=history.total_count > history.page_size),
            )

        def browse_code_review_history(
            profile_id: str | None,
            problem_id: str | None,
            current_page: int,
            delta: int,
        ):
            """Move through bounded review pages without changing the current review."""

            if not profile_id or not problem_id:
                return "", 0, gr.Button(visible=False), gr.Button(visible=False)
            requested_page = max(0, current_page + delta)
            page = services.reviews.code_review_history(
                profile_id,
                problem_id,
                page=requested_page,
            )
            max_page = max(0, (page.total_count - 1) // page.page_size)
            if requested_page > max_page:
                page = services.reviews.code_review_history(
                    profile_id,
                    problem_id,
                    page=max_page,
                )
            has_newer = page.page > 0
            has_older = (page.page + 1) * page.page_size < page.total_count
            return (
                format_code_review_history(page),
                page.page,
                gr.Button(visible=has_newer),
                gr.Button(visible=has_older),
            )

        def generate_code_review_ui(
            profile_id: str | None,
            problem_id: str | None,
            source: str,
            consent: bool,
        ) -> Iterator[tuple[Any, str, Any, Any, int, Any, Any]]:
            """Stream measured elapsed time while the completion review runs."""

            if not profile_id or not problem_id:
                yield (
                    "",
                    "プロフィールと問題を選択してください。",
                    "",
                    "",
                    0,
                    gr.Button(visible=False),
                    gr.Button(visible=False),
                )
                return
            started = time.monotonic()
            yield (
                gr.skip(),
                "コードレビューを生成中…（経過時間: 0 s）",
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
                gr.skip(),
            )
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                services.reviews.generate_code_review,
                profile_id,
                problem_id,
                source,
                cloud_consent=consent,
            )
            try:
                elapsed_seconds = 0
                while not future.done():
                    time.sleep(1)
                    current_elapsed = int(time.monotonic() - started)
                    if current_elapsed > elapsed_seconds and not future.done():
                        elapsed_seconds = current_elapsed
                        yield (
                            gr.skip(),
                            (
                                "コードレビューを生成中…"
                                f"（経過時間: {elapsed_seconds} s）"
                            ),
                            gr.skip(),
                            gr.skip(),
                            gr.skip(),
                            gr.skip(),
                            gr.skip(),
                        )
                receipt = future.result()
            except (
                CodeReviewUnavailableError,
                CompletionRequiredError,
                QuizRequiredError,
                ReviewConsentRequiredError,
                ValueError,
            ) as error:
                try:
                    history = services.reviews.code_review_history(
                        profile_id,
                        problem_id,
                    )
                except CompletionRequiredError:
                    history = None
                yield (
                    (
                        format_code_review(history.entries[0])
                        if history is not None and history.entries
                        else ""
                    ),
                    f"{error} 設定またはコードを確認して再試行できます。",
                    format_code_review_history(history) if history is not None else "",
                    format_review_quota(history) if history is not None else gr.skip(),
                    0,
                    gr.Button(visible=False),
                    gr.Button(
                        visible=(
                            history is not None
                            and history.total_count > history.page_size
                        )
                    ),
                )
                return
            finally:
                executor.shutdown(wait=True)
            history = services.reviews.code_review_history(profile_id, problem_id)
            elapsed = time.monotonic() - started
            yield (
                format_code_review(receipt.entry),
                f"コードレビューを表示しました。（所要時間: {elapsed:.1f} s）",
                format_code_review_history(history),
                format_review_quota(history),
                0,
                gr.Button(visible=False),
                gr.Button(visible=history.total_count > history.page_size),
            )

        def retry_code_review_ui(
            profile_id: str | None,
            problem_id: str | None,
            source: str,
            consent: bool,
        ) -> Iterator[tuple[Any, str, Any, Any, int, Any, Any]]:
            yield from generate_code_review_ui(
                profile_id,
                problem_id,
                source,
                consent,
            )

        completion_outputs = [
            completion_tab,
            completion_banner,
            completion_status,
            *quiz_radios,
            submit_quiz,
            quiz_result,
            show_explanation_button,
            show_saved_code_reviews,
            retry_code_review,
        ]
        personalized_outputs = [
            personalized_quiz_status,
            personalized_quiz_set_id,
            *personalized_radios,
            grade_personalized_quiz,
            regenerate_personalized_quiz,
        ]

        problem_selection_event = problem_selector.change(
            selected_problem,
            inputs=[profile_selector, problem_selector],
            outputs=[
                problem_header,
                problem_body,
                tutor_chat,
                tutor_status,
                latest_diagnostic,
                submission_result,
            ],
            api_name="select_problem",
        )
        problem_selection_event.then(
            load_completion,
            inputs=[profile_selector, problem_selector],
            outputs=completion_outputs,
            api_visibility="private",
        )
        problem_selection_event.then(
            load_quiz_history,
            inputs=[profile_selector, problem_selector],
            outputs=[
                quiz_history,
                review_quota,
                quiz_history_page,
                previous_quiz_history,
                next_quiz_history,
            ],
            api_visibility="private",
        )
        problem_selection_event.then(
            lambda: ("", False, "", "", ""),
            outputs=[
                accepted_source,
                personalized_quiz_trigger,
                explanation_result,
                current_code_review,
                code_review_history,
            ],
            api_visibility="private",
        ).then(
            load_personalized_quiz,
            inputs=[profile_selector, problem_selector, accepted_source],
            outputs=personalized_outputs,
            api_visibility="private",
        )
        problem_selection_event.then(
            lambda: (False, "", "問題ごとの検索予算は「検索予算を確認」で確認できます。"),
            outputs=[research_consent, research_result, research_usage],
            api_visibility="private",
        )
        create_profile.click(
            created_profile,
            inputs=profile_name,
            outputs=[
                profile_selector,
                provider_selector,
                quiz_mode_selector,
                provider_status,
                report_result,
                cloud_consent,
                problem_selector,
                problem_header,
                problem_body,
                tutor_chat,
                tutor_status,
                latest_diagnostic,
                submission_result,
            ],
            api_name="create_profile",
        )
        profile_selection_event = profile_selector.change(
            selected_profile,
            inputs=[profile_selector, problem_selector],
            outputs=[
                provider_selector,
                quiz_mode_selector,
                provider_status,
                problem_selector,
                problem_header,
                problem_body,
                tutor_chat,
                tutor_status,
                cloud_consent,
                latest_diagnostic,
                submission_result,
            ],
            api_name="select_profile",
        )
        profile_selection_event.then(
            load_completion,
            inputs=[profile_selector, problem_selector],
            outputs=completion_outputs,
            api_visibility="private",
        )
        profile_selection_event.then(
            load_quiz_history,
            inputs=[profile_selector, problem_selector],
            outputs=[
                quiz_history,
                review_quota,
                quiz_history_page,
                previous_quiz_history,
                next_quiz_history,
            ],
            api_visibility="private",
        )
        profile_selection_event.then(
            lambda: ("", False, "", "", ""),
            outputs=[
                accepted_source,
                personalized_quiz_trigger,
                explanation_result,
                current_code_review,
                code_review_history,
            ],
            api_visibility="private",
        ).then(
            load_personalized_quiz,
            inputs=[profile_selector, problem_selector, accepted_source],
            outputs=personalized_outputs,
            api_visibility="private",
        )
        profile_selection_event.then(
            lambda: (False, "", "検索前に専用の同意欄を確認してください。"),
            outputs=[research_consent, research_result, research_usage],
            api_visibility="private",
        )
        provider_selector.change(
            selected_provider,
            inputs=[profile_selector, provider_selector],
            outputs=[provider_status, cloud_consent],
            api_name="select_hint_provider",
        )
        quiz_mode_selector.change(
            selected_quiz_mode,
            inputs=[profile_selector, quiz_mode_selector],
            outputs=quiz_mode_selector,
            api_name="select_personalized_quiz_mode",
        )
        sample_submit.click(
            lambda profile, problem, source: submit(
                profile, problem, source, SubmissionMode.SAMPLE
            ),
            inputs=[profile_selector, problem_selector, code],
            outputs=[submission_result, latest_diagnostic],
            api_name="run_samples",
        )
        full_submission_event = full_submit.click(
            submit_full,
            inputs=[profile_selector, problem_selector, code],
            outputs=[
                submission_result,
                latest_diagnostic,
                personalized_quiz_trigger,
                accepted_source,
            ],
            api_name="submit_solution",
        )
        completion_loaded_event = full_submission_event.then(
            load_completion,
            inputs=[profile_selector, problem_selector],
            outputs=completion_outputs,
            api_visibility="private",
        )
        completion_loaded_event.then(
            None,
            js=OPEN_COMPLETION_TAB_SCRIPT,
            api_visibility="private",
        )
        completion_loaded_event.then(
            load_quiz_history,
            inputs=[profile_selector, problem_selector],
            outputs=[
                quiz_history,
                review_quota,
                quiz_history_page,
                previous_quiz_history,
                next_quiz_history,
            ],
            api_visibility="private",
        )
        completion_loaded_event.then(
            generate_personalized_quiz_ui,
            inputs=[
                profile_selector,
                problem_selector,
                accepted_source,
                cloud_consent,
                personalized_quiz_trigger,
            ],
            outputs=[
                personalized_quiz_status,
                personalized_quiz_trigger,
                regenerate_personalized_quiz,
            ],
            api_visibility="private",
            show_progress="hidden",
            concurrency_limit=1,
            concurrency_id="personalized-quiz-generation",
        )
        tutor_inputs = [
            profile_selector,
            problem_selector,
            code,
            question,
            cloud_consent,
            latest_diagnostic,
        ]
        ask_question.click(
            request_question,
            inputs=tutor_inputs,
            outputs=[tutor_chat, tutor_status, question],
            api_name="ask_tutor",
            trigger_mode="once",
            concurrency_limit=1,
            concurrency_id="tutor-generation",
            show_progress="hidden",
        )
        stuck.click(
            request_stuck_hint,
            inputs=tutor_inputs,
            outputs=[tutor_chat, tutor_status, question],
            api_name="request_stuck_hint",
            trigger_mode="once",
            concurrency_limit=1,
            concurrency_id="tutor-generation",
            show_progress="hidden",
        )
        result_hint.click(
            request_result_hint,
            inputs=tutor_inputs,
            outputs=[tutor_chat, tutor_status, question],
            api_name="request_result_hint",
            trigger_mode="once",
            concurrency_limit=1,
            concurrency_id="tutor-generation",
            show_progress="hidden",
        )
        clear_history.click(
            clear_tutor_history,
            inputs=[profile_selector, problem_selector],
            outputs=[tutor_chat, tutor_status],
            api_name="clear_tutor_history",
        )
        request_research_button.click(
            request_grounded_research,
            inputs=[profile_selector, problem_selector, research_consent],
            outputs=[research_result, research_usage, research_consent],
            api_name="request_grounded_research",
            trigger_mode="once",
            concurrency_limit=1,
            concurrency_id="grounded-research",
            show_progress="full",
        )
        refresh_research_usage_button.click(
            refresh_research_usage,
            outputs=research_usage,
            api_name="research_usage",
        )
        show_explanation_button.click(
            lambda profile, problem: show_explanation(profile, problem, False),
            inputs=[profile_selector, problem_selector],
            outputs=explanation_result,
            api_name="show_explanation",
        )
        give_up_event = give_up.click(
            give_up_and_explain,
            inputs=[profile_selector, problem_selector],
            outputs=[submission_result, accepted_source],
            api_name="give_up",
        )
        give_up_completion_event = give_up_event.then(
            load_completion,
            inputs=[profile_selector, problem_selector],
            outputs=completion_outputs,
            api_visibility="private",
        )
        give_up_completion_event.then(
            None,
            js=OPEN_COMPLETION_TAB_SCRIPT,
            api_visibility="private",
        )
        give_up_completion_event.then(
            load_quiz_history,
            inputs=[profile_selector, problem_selector],
            outputs=[
                quiz_history,
                review_quota,
                quiz_history_page,
                previous_quiz_history,
                next_quiz_history,
            ],
            api_visibility="private",
        )
        fixed_quiz_event = submit_quiz.click(
            grade_quiz,
            inputs=[profile_selector, problem_selector, *quiz_radios],
            outputs=[
                quiz_result,
                quiz_history,
                review_quota,
                quiz_history_page,
                previous_quiz_history,
                next_quiz_history,
                completion_status,
                show_explanation_button,
                show_saved_code_reviews,
                retry_code_review,
            ],
            api_name="grade_review_quiz",
            # Correctness is still validated by CompletionReviewService. Skipping
            # component preprocessing also lets the named API accept option IDs
            # after choices were populated by a prior completion event.
            preprocess=False,
        )
        fixed_quiz_event.then(
            load_personalized_quiz,
            inputs=[profile_selector, problem_selector, accepted_source],
            outputs=personalized_outputs,
            api_visibility="private",
        )
        personalized_regeneration_event = regenerate_personalized_quiz.click(
            retry_personalized_quiz_ui,
            inputs=[
                profile_selector,
                problem_selector,
                accepted_source,
                cloud_consent,
            ],
            outputs=[
                personalized_quiz_status,
                personalized_quiz_trigger,
                regenerate_personalized_quiz,
            ],
            api_name="regenerate_personalized_quiz",
            show_progress="hidden",
            concurrency_limit=1,
            concurrency_id="personalized-quiz-generation",
        )
        personalized_regeneration_event.then(
            load_personalized_quiz,
            inputs=[profile_selector, problem_selector, accepted_source],
            outputs=personalized_outputs,
            api_visibility="private",
        )
        grade_personalized_quiz.click(
            grade_personalized_quiz_ui,
            inputs=[
                profile_selector,
                problem_selector,
                personalized_quiz_set_id,
                *personalized_radios,
            ],
            outputs=personalized_quiz_result,
            api_name="grade_personalized_quiz",
            preprocess=False,
        )
        previous_quiz_history.click(
            lambda profile, problem, page: change_quiz_history_page(
                profile,
                problem,
                page,
                -1,
            ),
            inputs=[profile_selector, problem_selector, quiz_history_page],
            outputs=[
                quiz_history,
                review_quota,
                quiz_history_page,
                previous_quiz_history,
                next_quiz_history,
            ],
            api_visibility="private",
        )
        next_quiz_history.click(
            lambda profile, problem, page: change_quiz_history_page(
                profile,
                problem,
                page,
                1,
            ),
            inputs=[profile_selector, problem_selector, quiz_history_page],
            outputs=[
                quiz_history,
                review_quota,
                quiz_history_page,
                previous_quiz_history,
                next_quiz_history,
            ],
            api_visibility="private",
        )
        previous_code_review_history.click(
            lambda profile, problem, page: browse_code_review_history(
                profile,
                problem,
                page,
                -1,
            ),
            inputs=[
                profile_selector,
                problem_selector,
                code_review_history_page,
            ],
            outputs=[
                code_review_history,
                code_review_history_page,
                previous_code_review_history,
                next_code_review_history,
            ],
            api_visibility="private",
        )
        next_code_review_history.click(
            lambda profile, problem, page: browse_code_review_history(
                profile,
                problem,
                page,
                1,
            ),
            inputs=[
                profile_selector,
                problem_selector,
                code_review_history_page,
            ],
            outputs=[
                code_review_history,
                code_review_history_page,
                previous_code_review_history,
                next_code_review_history,
            ],
            api_visibility="private",
        )
        show_saved_code_reviews.click(
            load_code_review_state,
            inputs=[profile_selector, problem_selector],
            outputs=[
                current_code_review,
                code_review_status,
                retry_code_review,
                code_review_history,
                code_review_history_page,
                previous_code_review_history,
                next_code_review_history,
            ],
            api_name="show_saved_code_reviews",
        )
        retry_code_review.click(
            retry_code_review_ui,
            inputs=[
                profile_selector,
                problem_selector,
                code,
                cloud_consent,
            ],
            outputs=[
                current_code_review,
                code_review_status,
                code_review_history,
                review_quota,
                code_review_history_page,
                previous_code_review_history,
                next_code_review_history,
            ],
            api_name="retry_code_review",
            show_progress="hidden",
            concurrency_limit=1,
            concurrency_id="review-generation",
        )
        refresh_report.click(
            show_report,
            inputs=profile_selector,
            outputs=report_result,
            api_name="refresh_report",
        )

        if teacher_mode:

            def show_teacher(problem_id: str | None):
                if not problem_id:
                    return "問題を選択してください。"
                hidden = services.teacher_repository.get_tests(problem_id, include_hidden=True)
                hidden_only = [item for item in hidden if item.visibility.value == "hidden"]
                tests = "\n".join(
                    f"- `{item.case_id}`: 入力 `{item.input_text.rstrip()}`"
                    f" → `{item.expected_output.rstrip()}`"
                    for item in hidden_only
                )
                solution = services.teacher_repository.get_model_solution(problem_id)
                return f"## 隠しテスト\n{tests}\n\n## 模範解答\n```python\n{solution}\n```"

            problem_selector.change(show_teacher, inputs=problem_selector, outputs=teacher_result)

        app.load(fn=None, js=QUESTION_SHORTCUT_SCRIPT, queue=False)

    return app.queue(default_concurrency_limit=1)
