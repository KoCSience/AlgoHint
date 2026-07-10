"""Pure Markdown formatting functions for the Gradio adapter."""

from algohint.application.dto import LearnerProblemView, LearningReport, SubmissionView
from algohint.domain.models import Hint


def format_problem(problem: LearnerProblemView) -> tuple[str, str]:
    """Render only learner-safe problem metadata and public samples."""

    header = f"## {problem.level}: {problem.title}\n\n目標: {problem.learning_goal}\n\nタグ: {', '.join(problem.tags)}"
    samples = "\n\n".join(
        f"### サンプル {index}\n入力:\n```text\n{input_text.rstrip()}\n```\n出力:\n```text\n{output_text.rstrip()}\n```"
        for index, (input_text, output_text) in enumerate(problem.samples, start=1)
    )
    body = (
        f"### 問題文\n{problem.statement}\n\n### 制約\n{problem.constraints}"
        f"\n\n### 入力形式\n```text\n{problem.input_format}\n```"
        f"\n\n### 出力形式\n{problem.output_format}\n\n{samples}"
    )
    return header, body


def format_submission(result: SubmissionView) -> str:
    """Render a result without ever formatting hidden testcase data."""

    text = f"## {result.status}\n\n{result.message}\n\n通過: {result.passed_count}/{result.total_count}"
    if result.sample_input is not None:
        text += f"\n\n### 失敗した公開サンプルの入力\n```text\n{result.sample_input.rstrip()}\n```"
    if result.actual_output is not None:
        text += f"\n\n実際の出力:\n```text\n{result.actual_output.rstrip()}\n```"
    if result.expected_output is not None:
        text += f"\n\n期待する出力:\n```text\n{result.expected_output.rstrip()}\n```"
    return text


def format_hint(hint: Hint) -> str:
    """Present a single next-step hint with its educational category."""

    return f"### ヒント {hint.level}（{hint.category}）\n\n{hint.text}"


def format_report(report: LearningReport) -> str:
    """Present simple, auditable learning metrics."""

    weak = ", ".join(f"{tag}: {count}" for tag, count in report.weak_tags) or "まだ十分な記録がありません"
    recommendation = report.recommended_problem_id or "すべての問題を完了しました"
    return (
        "## 学習レポート\n\n"
        f"- 取り組んだ問題: {report.attempted_count}\n"
        f"- 解けた問題: {report.solved_count}\n"
        f"- 正答率: {report.correctness_rate:.0%}\n"
        f"- 平均ヒント数: {report.average_hint_count:.2f}\n"
        f"- 平均提出回数: {report.average_attempt_count:.2f}\n"
        f"- 苦手タグ: {weak}\n"
        f"- 次の推奨問題: `{recommendation}`"
    )
