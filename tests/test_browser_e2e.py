"""Opt-in Playwright regression for the rendered tutoring workspace."""

import os
import re
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page, Request, expect

from algohint.domain.enums import HintTrigger
from tests.e2e_support import (
    DeterministicGeminiProvider,
    running_e2e_app,
)

pytestmark = [
    pytest.mark.browser_e2e,
    pytest.mark.skipif(
        os.environ.get("ALGOHINT_RUN_BROWSER_E2E") != "1",
        reason="set ALGOHINT_RUN_BROWSER_E2E=1 after installing Chromium",
    ),
    pytest.mark.filterwarnings(
        "ignore:.*future.no_silent_downcasting.*:pandas.errors.Pandas4Warning"
    ),
    pytest.mark.filterwarnings(
        "ignore:The copy keyword is deprecated.*:pandas.errors.Pandas4Warning"
    ),
]


@pytest.fixture
def browser_app(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[str, DeterministicGeminiProvider]]:
    """Serve isolated real UI callbacks while keeping the LLM deterministic."""

    monkeypatch.setenv("GRADIO_ANALYTICS_ENABLED", "False")
    with running_e2e_app(tmp_path / "browser-e2e-data") as (_, local_url, provider):
        yield local_url, provider


def _select_dropdown(page: Page, elem_id: str, option_name: str | re.Pattern[str]) -> None:
    """Select a Gradio dropdown using stable application-owned IDs."""

    dropdown = page.locator(f"#{elem_id}")
    dropdown.get_by_role("combobox").click()
    page.get_by_role("option", name=option_name).click()


def _record_unexpected_failed_request(request: Request, failures: list[str]) -> None:
    """Ignore Gradio's expected queue-stream reconnects, but retain real failures.

    Gradio closes and reopens ``queue/data`` event streams after queued callbacks.
    Chromium reports that normal lifecycle as ``requestfailed`` even though the
    callback completed successfully and no HTTP error response occurred.
    """

    request_url = request.url
    if "/gradio_api/queue/data" not in request_url:
        failures.append(f"{request.method} {request_url}")


def test_hint_coach_in_rendered_browser(
    page: Page,
    browser_app: tuple[str, DeterministicGeminiProvider],
) -> None:
    """Exercise consent, judge diagnostics, every hint trigger, and cleanup."""

    local_url, provider = browser_app
    console_errors: list[str] = []
    failed_requests: list[str] = []
    bad_responses: list[str] = []
    page.on(
        "console",
        lambda message: console_errors.append(message.text) if message.type == "error" else None,
    )
    page.on(
        "requestfailed",
        lambda request: _record_unexpected_failed_request(request, failed_requests),
    )
    page.on(
        "response",
        lambda response: (
            bad_responses.append(f"{response.status} {response.url}")
            if response.url.startswith(local_url) and response.status >= 400
            else None
        ),
    )

    page.goto(local_url)
    expect(page.get_by_role("heading", name="AlgoHint Coach")).to_be_visible()
    expect(page.locator("#profile-selector").get_by_role("combobox")).to_have_value("開発テスト")
    page.get_by_role("tab", name="問題演習").click()

    _select_dropdown(
        page,
        "problem-selector",
        re.compile("L0.*二つの数の合計"),
    )
    expect(page.get_by_text("二つの数の合計", exact=False).first).to_be_visible()

    _select_dropdown(page, "provider-selector", "GPT-5.6")
    expect(page.locator("#cloud-consent input")).not_to_be_checked()
    _select_dropdown(page, "provider-selector", "Gemini")
    expect(page.locator("#provider-status")).to_contain_text("利用可能")

    page.locator("#cloud-consent input").check()
    page.locator("#stuck-hint").click()
    expect(page.locator("#tutor-status")).to_contain_text("ヒントを表示しました")
    expect(page.locator("#tutor-chat")).to_contain_text("gemini / gemini-e2e")

    question = page.locator("#tutor-question textarea")
    question.fill("どの変数を追えばよいですか？")
    page.locator("#ask-question").click()
    expect(page.locator("#tutor-status")).to_contain_text("ヒントを表示しました")
    expect(question).to_have_value("")

    editor = page.locator("#code-editor .cm-content")
    expect(editor).to_be_visible()
    editor.fill("raise ValueError('visible sample failure')")
    page.locator("#sample-submit").click()
    expect(page.locator("#submission-result")).to_contain_text("RE")

    page.locator("#result-hint").click()
    expect(page.locator("#tutor-status")).to_contain_text("ヒントを表示しました")
    expect(page.locator("#tutor-chat")).to_contain_text("この実行結果についてヒントがほしい")
    assert [request.trigger for request in provider.requests] == [
        HintTrigger.STUCK,
        HintTrigger.QUESTION,
        HintTrigger.JUDGE_RESULT,
    ]
    assert provider.requests[-1].diagnostic_summary == "ValueError"
    assert "visible sample failure" in (provider.requests[-1].diagnostic_details or "")

    page.locator("#clear-tutor-history").click()
    expect(page.locator("#tutor-status")).to_contain_text("クリア")
    expect(page.locator("#tutor-chat")).not_to_contain_text("gemini / gemini-e2e")

    assert console_errors == []
    assert failed_requests == []
    assert bad_responses == []
