"""Gradio UI adapter; all decisions remain in application services."""

import gradio as gr

from algohint.ui.formatters import format_hint, format_problem, format_report, format_submission
from algohint.ui.view_models import ApplicationServices


def _format_curriculum_item(item: dict[str, object]) -> str:
    """Defensively render validated JSON content for the roadmap."""

    problem_ids = item.get("problem_ids", [])
    ids = problem_ids if isinstance(problem_ids, list) else []
    return (
        f"### {item.get('level', '')}: {item.get('title', '')}\n"
        f"{item.get('description', '')}\n問題: {', '.join(str(problem_id) for problem_id in ids)}"
    )


def build_app(services: ApplicationServices, teacher_mode: bool, shared_mode: bool) -> gr.Blocks:
    """Build the MVP UI without exposing private judge data in learner callbacks."""

    profiles = services.profiles.list_profiles()
    profile_choices = [(profile.display_name, profile.profile_id) for profile in profiles]
    problems = services.problems.list_problems()
    problem_choices = [(f"{problem.level} | {problem.title}", problem.problem_id) for problem in problems]
    safety_note = "⚠️ 共有リンクでは任意コードが実行されます。信頼できる個人利用に限定してください。" if shared_mode else "ローカル個人学習用です。任意コード実行のため公開サーバーでは利用しないでください。"

    with gr.Blocks(title="AlgoHint Coach") as app:
        gr.Markdown("# AlgoHint Coach\n\n自分で考えるための段階的ヒント付きアルゴリズム練習")
        gr.Markdown(safety_note)
        if teacher_mode:
            gr.Markdown("教師モードが有効です。秘匿データは教師が管理する環境でだけ確認してください。")

        with gr.Row():
            profile_selector = gr.Dropdown(
                choices=profile_choices, label="プロフィール", value=profile_choices[0][1] if profiles else None
            )
            profile_name = gr.Textbox(label="新しいプロフィール名", max_length=40)
            create_profile = gr.Button("プロフィールを作成")

        with gr.Tab("学習ロードマップ"):
            roadmap = "\n\n".join(_format_curriculum_item(item) for item in services.problems.curriculum())
            gr.Markdown(roadmap)

        with gr.Tab("問題演習"):
            problem_selector = gr.Dropdown(choices=problem_choices, label="問題を選択")
            problem_header = gr.Markdown("問題を選択してください。")
            problem_body = gr.Markdown("")
            code = gr.Code(label="Pythonコード", language="python", value="")
            with gr.Row():
                sample_submit = gr.Button("公開サンプルで実行")
                full_submit = gr.Button("全テストで提出", variant="primary")
            submission_result = gr.Markdown("")

        with gr.Tab("ヒント"):
            request_hint = gr.Button("次のヒントを表示")
            hint_result = gr.Markdown("ヒントは一段階ずつ表示されます。")

        with gr.Tab("解説"):
            give_up = gr.Button("ギブアップして解説を見る", variant="stop")
            explanation_result = gr.Markdown("ACまたはギブアップ後に解説を表示できます。")

        with gr.Tab("学習レポート"):
            refresh_report = gr.Button("レポートを更新")
            report_result = gr.Markdown("プロフィールを選択してレポートを更新してください。")

        if teacher_mode:
            with gr.Tab("教師用"):
                teacher_result = gr.Markdown("問題を選択すると模範解答と隠しテストを表示します。")

        def selected_problem(problem_id: str | None):
            if not problem_id:
                return "問題を選択してください。", ""
            return format_problem(services.problems.get_learner_problem(problem_id))

        def created_profile(display_name: str):
            if not display_name.strip():
                return gr.Dropdown(), "プロフィール名を入力してください。"
            profile = services.profiles.create_profile(display_name)
            choices = [(item.display_name, item.profile_id) for item in services.profiles.list_profiles()]
            return gr.Dropdown(choices=choices, value=profile.profile_id), f"{profile.display_name} を選択しました。"

        def submit(profile_id: str | None, problem_id: str | None, source: str, samples_only: bool):
            if not profile_id or not problem_id:
                return "プロフィールと問題を選択してください。"
            if not source.strip():
                return "提出するPythonコードを入力してください。"
            return format_submission(services.submissions.submit(profile_id, problem_id, source, samples_only))

        def next_hint(profile_id: str | None, problem_id: str | None):
            if not profile_id or not problem_id:
                return "プロフィールと問題を選択してください。"
            return format_hint(services.hints.request(profile_id, problem_id))

        def show_explanation(profile_id: str | None, problem_id: str | None, surrender: bool):
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

        problem_selector.change(selected_problem, inputs=problem_selector, outputs=[problem_header, problem_body])
        create_profile.click(created_profile, inputs=profile_name, outputs=[profile_selector, report_result])
        sample_submit.click(
            lambda profile, problem, source: submit(profile, problem, source, True),
            inputs=[profile_selector, problem_selector, code],
            outputs=submission_result,
        )
        full_submit.click(
            lambda profile, problem, source: submit(profile, problem, source, False),
            inputs=[profile_selector, problem_selector, code],
            outputs=submission_result,
        )
        request_hint.click(next_hint, inputs=[profile_selector, problem_selector], outputs=hint_result)
        give_up.click(
            lambda profile, problem: show_explanation(profile, problem, True),
            inputs=[profile_selector, problem_selector],
            outputs=explanation_result,
        )
        refresh_report.click(show_report, inputs=profile_selector, outputs=report_result)

        if teacher_mode:
            def show_teacher(problem_id: str | None):
                if not problem_id:
                    return "問題を選択してください。"
                hidden = services.teacher_repository.get_tests(problem_id, include_hidden=True)
                hidden_only = [item for item in hidden if item.visibility.value == "hidden"]
                tests = "\n".join(
                    f"- `{item.case_id}`: 入力 `{item.input_text.rstrip()}` → `{item.expected_output.rstrip()}`"
                    for item in hidden_only
                )
                solution = services.teacher_repository.get_model_solution(problem_id)
                return f"## 隠しテスト\n{tests}\n\n## 模範解答\n```python\n{solution}\n```"

            problem_selector.change(show_teacher, inputs=problem_selector, outputs=teacher_result)

    return app
