"""Exercise the complete tutoring flow through Gradio's public API client."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from gradio_client import Client

from algohint.domain.enums import HintTrigger, JudgeStatus
from tests.e2e_support import (
    PROFILE_ID,
    PROBLEM_ID,
    DeterministicGeminiProvider,
    running_e2e_app,
)

pytestmark = [
    pytest.mark.filterwarnings(
        "ignore:.*future.no_silent_downcasting.*:pandas.errors.Pandas4Warning"
    ),
    pytest.mark.filterwarnings(
        "ignore:The copy keyword is deprecated.*:pandas.errors.Pandas4Warning"
    ),
]


def _chat_text(message: dict[str, object]) -> str:
    """Normalize Gradio's rich-text wire shape for content assertions."""

    content = message["content"]
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return str(content)


@pytest.fixture
def api_harness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[Client, DeterministicGeminiProvider]]:
    """Run an isolated queued Gradio server and always release its thread."""

    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    with running_e2e_app(tmp_path / "api-e2e-data") as (_, local_url, provider):
        client = Client(local_url, verbose=False, analytics_enabled=False)
        yield client, provider


def test_tutor_flow_through_named_gradio_apis(
    api_harness: tuple[Client, DeterministicGeminiProvider],
) -> None:
    """Verify consent, every hint trigger, state handoff, and history clearing."""

    gradio_client, provider = api_harness
    selected = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        api_name="/select_problem",
    )
    assert "二つの数の合計" in selected[0]
    assert selected[2] == []

    provider_status, consent = gradio_client.predict(
        PROFILE_ID,
        "gemini",
        api_name="/select_hint_provider",
    )
    assert "Gemini" in provider_status
    assert consent is False

    rejected = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        "",
        "",
        False,
        api_name="/request_stuck_hint",
    )
    assert rejected[0] == []
    assert "同意" in rejected[1]
    assert provider.requests == []

    stuck = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        "",
        "",
        True,
        api_name="/request_stuck_hint",
    )
    assert len(stuck[0]) == 2
    assert "gemini / gemini-e2e" in _chat_text(stuck[0][1])
    assert "回答を表示しました" in stuck[1]

    asked = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        "print(0)",
        "どの変数を追えばよいですか？",
        True,
        api_name="/ask_tutor",
    )
    assert len(asked[0]) == 4
    assert "回答を表示しました" in asked[1]
    assert asked[2] == ""

    execution = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        "print(0)",
        api_name="/run_samples",
    )
    assert "WA" in execution

    result_hint = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        "print(0)",
        "",
        True,
        api_name="/request_result_hint",
    )
    assert len(result_hint[0]) == 6
    assert "gemini / gemini-e2e" in _chat_text(result_hint[0][-1])
    assert [request.trigger for request in provider.requests] == [
        HintTrigger.STUCK,
        HintTrigger.QUESTION,
        HintTrigger.JUDGE_RESULT,
    ]
    assert provider.requests[-1].judge_status is JudgeStatus.WA

    completed = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        "a, b = map(int, input().split())\nprint(a + b)",
        api_name="/submit_solution",
    )
    assert "AC" in completed
    locked_explanation = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        api_name="/show_explanation",
    )
    assert "固定小テスト" in locked_explanation

    quiz = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        "add-once",
        "two-in-one-out",
        "constant",
        "negative-mix",
        "convert-int",
        api_name="/grade_review_quiz",
    )
    assert "5/5" in quiz[0]
    assert "全1回" in quiz[1]

    generated_quiz = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        True,
        api_name="/regenerate_personalized_quiz",
    )
    assert "AI小テスト2問を準備しました" in generated_quiz
    assert len(provider.quiz_requests) == 1

    review = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        "a, b = map(int, input().split())\nprint(a + b)",
        True,
        api_name="/retry_code_review",
    )
    assert "アルゴリズムの復習" in review[0]
    assert "コードレビューを表示しました" in review[1]
    assert "全1件" in review[2]
    assert len(provider.review_requests) == 1

    saved_review = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        api_name="/show_saved_code_reviews",
    )
    assert "アルゴリズムの復習" in saved_review[0]
    assert "保存済みAIレビューを表示しました" in saved_review[1]

    cleared = gradio_client.predict(
        PROFILE_ID,
        PROBLEM_ID,
        api_name="/clear_tutor_history",
    )
    assert cleared[0] == []
    assert "クリア" in cleared[1]
