"""Contextual Gradio workspace for execution, diagnostics, tutoring, and explanation."""

import time
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterator
from typing import Any, cast

import gradio as gr

from algohint.application.dto import LearnerDiagnostic
from algohint.application.tutor_service import CloudConsentRequiredError
from algohint.domain.enums import (
    HintProviderId,
    HintTrigger,
    ProviderFailureReason,
    SubmissionMode,
    TutorRole,
)
from algohint.domain.models import ProviderAvailability, TutorSession
from algohint.ui.formatters import format_problem, format_report, format_submission
from algohint.ui.view_models import ApplicationServices

PROVIDER_CHOICES = [
    ("GPT-5.6", HintProviderId.OPENAI.value),
    ("Gemma 4 12B", HintProviderId.GEMMA.value),
    ("Gemini", HintProviderId.GEMINI.value),
]
PROVIDER_LABELS = {provider_id: label for label, provider_id in PROVIDER_CHOICES}
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
    default_provider = (
        default_profile.preferences.hint_provider
        if default_profile is not None
        else HintProviderId.OPENAI
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
                            "選択中のクラウドモデルへ送信することに同意します"
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

                    gr.Markdown("## 解説")
                    with gr.Row():
                        show_explanation_button = gr.Button("解説を表示")
                        give_up = gr.Button("ギブアップして解説を見る", variant="stop")
                    explanation_result = gr.Markdown("ACまたはギブアップ後に解説を表示できます。")

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
            if trigger is HintTrigger.QUESTION and cleaned_question is not None:
                # Keep the pending turn browser-only. Persistence remains an
                # assistant/user pair so interrupted generations leave no orphan.
                pending_messages = [
                    *pending_messages,
                    {"role": TutorRole.USER.value, "content": cleaned_question},
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

        def show_explanation(
            profile_id: str | None,
            problem_id: str | None,
            surrender: bool,
        ):
            if not profile_id or not problem_id:
                return "プロフィールと問題を選択してください。"
            if surrender:
                services.explanations.give_up(profile_id, problem_id)
            explanation = services.explanations.get_explanation(profile_id, problem_id)
            return explanation or "解説はACまたはギブアップ後に表示できます。"

        def show_report(profile_id: str | None):
            if not profile_id:
                return "プロフィールを選択してください。"
            return format_report(services.reports.report(profile_id))

        problem_selector.change(
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
        create_profile.click(
            created_profile,
            inputs=profile_name,
            outputs=[
                profile_selector,
                provider_selector,
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
        profile_selector.change(
            selected_profile,
            inputs=[profile_selector, problem_selector],
            outputs=[
                provider_selector,
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
        provider_selector.change(
            selected_provider,
            inputs=[profile_selector, provider_selector],
            outputs=[provider_status, cloud_consent],
            api_name="select_hint_provider",
        )
        sample_submit.click(
            lambda profile, problem, source: submit(
                profile, problem, source, SubmissionMode.SAMPLE
            ),
            inputs=[profile_selector, problem_selector, code],
            outputs=[submission_result, latest_diagnostic],
            api_name="run_samples",
        )
        full_submit.click(
            lambda profile, problem, source: submit(profile, problem, source, SubmissionMode.FULL),
            inputs=[profile_selector, problem_selector, code],
            outputs=[submission_result, latest_diagnostic],
            api_name="submit_solution",
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
        show_explanation_button.click(
            lambda profile, problem: show_explanation(profile, problem, False),
            inputs=[profile_selector, problem_selector],
            outputs=explanation_result,
            api_name="show_explanation",
        )
        give_up.click(
            lambda profile, problem: show_explanation(profile, problem, True),
            inputs=[profile_selector, problem_selector],
            outputs=explanation_result,
            api_name="give_up",
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
