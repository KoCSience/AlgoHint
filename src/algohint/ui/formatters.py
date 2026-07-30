"""Pure Markdown formatting functions for the Gradio adapter."""

from html import escape

from algohint.application.dto import (
    CodeReviewHistoryPage,
    LearnerProblemView,
    LearningReport,
    PersonalizedQuizResult,
    QuizHistoryPage,
    QuizResult,
    SubmissionView,
)
from algohint.domain.models import CodeReviewEntry, Hint


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
    if result.elapsed_ms is not None:
        text += f"\n\n実行時間: {result.elapsed_ms} ms"
    if result.diagnostic is not None:
        diagnostic = result.diagnostic
        text += f"\n\n### 診断\n\n{escape(diagnostic.summary)}"
        if diagnostic.source_line is not None:
            location = f"提出コード {diagnostic.source_line}行目"
            if diagnostic.source_column is not None:
                location += f" {diagnostic.source_column}列目"
            text += f"\n\n{location}"
        if diagnostic.details is not None:
            text += f"\n\n<pre>{escape(diagnostic.details)}</pre>"
        if diagnostic.redacted:
            text += "\n\n隠しテストの入力や値に関わる詳細は表示していません。"
        if diagnostic.diagnostic_id is not None:
            text += f"\n\n診断ID: `{diagnostic.diagnostic_id}`"
    if result.sample_input is not None:
        text += (
            f"\n\n### 失敗した公開サンプルの入力\n<pre>{escape(result.sample_input.rstrip())}</pre>"
        )
    if result.actual_output is not None:
        text += f"\n\n実際の出力:\n<pre>{escape(result.actual_output.rstrip())}</pre>"
    if result.expected_output is not None:
        text += f"\n\n期待する出力:\n<pre>{escape(result.expected_output.rstrip())}</pre>"
    return text


def format_hint(hint: Hint) -> str:
    """Present a single next-step hint with its educational category."""

    return f"### ヒント {hint.level}（{hint.category}）\n\n{hint.text}"


def format_report(report: LearningReport) -> str:
    """Present simple, auditable learning metrics."""

    weak = (
        ", ".join(f"{tag}: {count}" for tag, count in report.weak_tags)
        or "まだ十分な記録がありません"
    )
    recommendation = report.recommended_problem_id or "すべての問題を完了しました"
    return (
        "## 学習レポート\n\n"
        f"- 取り組んだ問題: {report.attempted_count}\n"
        f"- 解けた問題: {report.solved_count}\n"
        f"- 正答率: {report.correctness_rate:.0%}\n"
        f"- 平均ヒント数: {report.average_hint_count:.2f}\n"
        f"- 平均提出回数: {report.average_attempt_count:.2f}\n"
        f"- ギブアップ数: {report.give_up_count}\n"
        f"- ヒント利用後の正解割合: {report.solve_after_hint_rate:.0%}\n"
        f"- 根拠付きResearch回数: {report.research_run_count}\n"
        f"- Research根拠取得率: {report.research_grounded_rate:.0%}\n"
        f"- Research平均応答時間: {report.average_research_latency_ms:.0f} ms\n"
        f"- 苦手タグ: {weak}\n"
        f"- 次の推奨問題: `{recommendation}`"
    )


def format_quiz_result(result: QuizResult | PersonalizedQuizResult) -> str:
    """Render deterministic grading while escaping all authored display text."""

    sections = [f"## 小テスト結果: {result.score}/{result.total}"]
    for index, item in enumerate(result.feedback, start=1):
        mark = "✅" if item.correct else "❌"
        detail = (
            f"### {mark} 問{index}: {escape(item.prompt)}\n\n"
            f"あなたの回答: {escape(item.selected_text)}"
        )
        if not item.correct:
            detail += f"\n\n正答: {escape(item.correct_text)}"
        detail += f"\n\n{escape(item.explanation)}"
        sections.append(detail)
    if result.quota is not None and result.quota.pruned_count:
        sections.append(
            f"容量上限を保つため、古い復習履歴を{result.quota.pruned_count}件整理しました。"
        )
    return "\n\n".join(sections)


def format_quiz_history(page: QuizHistoryPage) -> str:
    """Render one bounded page from detailed, validated answer snapshots."""

    if not page.attempts:
        return "まだ保存済みの小テスト履歴はありません。"
    sections = [
        (
            f"## 小テスト履歴（{page.page + 1}ページ目）\n\n"
            f"全{page.total_count}回"
        )
    ]
    for attempt in page.attempts:
        details = [
            (
                f"### {attempt.attempted_at.astimezone().strftime('%Y-%m-%d %H:%M:%S')} "
                f"— {attempt.score}/{attempt.total}"
            )
        ]
        for index, item in enumerate(attempt.feedback, start=1):
            mark = "✅" if item.correct else "❌"
            line = (
                f"- {mark} 問{index}: {escape(item.prompt)}"
                f" / 回答: {escape(item.selected_text)}"
            )
            if not item.correct:
                line += f" / 正答: {escape(item.correct_text)}"
            details.append(line)
        sections.append("\n\n".join(details))
    return "\n\n".join(sections)


def format_review_quota(page: QuizHistoryPage | CodeReviewHistoryPage) -> str:
    """Expose logical usage and warnings without SQLite implementation details."""

    used_mib = page.quota.used_bytes / (1024 * 1024)
    limit_mib = page.quota.limit_bytes / (1024 * 1024)
    prefix = "⚠️ " if page.quota.warning else ""
    message = (
        f"{prefix}復習履歴の使用量: {used_mib:.1f} MiB / {limit_mib:.0f} MiB"
    )
    if page.quota.warning:
        message += "（80%を超えています。上限超過時は古い履歴から整理されます。）"
    return message


def format_code_review(entry: CodeReviewEntry) -> str:
    """Render structured provider text without allowing generated HTML."""

    review = entry.review
    sections = [
        "## アルゴリズムの復習",
        escape(review.algorithm_recap),
    ]
    if review.strengths:
        sections.extend(
            [
                "## 良い点",
                "\n".join(f"- {escape(strength)}" for strength in review.strengths),
            ]
        )
    improvements = "\n\n".join(
        (
            f"### {index}. {escape(point.title)}"
            f"（{escape(point.category.value)}）\n\n{escape(point.feedback)}"
        )
        for index, point in enumerate(review.improvements, start=1)
    )
    sections.extend(["## 優先して改善する点", improvements])
    return "\n\n".join(sections)


def format_code_review_history(page: CodeReviewHistoryPage) -> str:
    """Render the current bounded page of persisted, source-free review text."""

    if not page.entries:
        return "まだ保存済みのAIコードレビューはありません。"
    sections = [
        f"## AIコードレビュー履歴（全{page.total_count}件）",
    ]
    for entry in page.entries:
        timestamp = entry.reviewed_at.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        sections.append(
            f"### {timestamp} — {escape(entry.review.provider)} / "
            f"{escape(entry.review.model_name)}\n\n{format_code_review(entry)}"
        )
    return "\n\n".join(sections)
