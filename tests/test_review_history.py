from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from algohint.application.profile_service import ProfileService
from algohint.domain.enums import (
    CodeReviewCategory,
    CompletionReason,
    ReviewHistoryKind,
)
from algohint.domain.models import (
    CodeReviewEntry,
    CodeReviewPoint,
    GeneratedCodeReview,
    QuizAttempt,
    StoredQuizFeedback,
)
from algohint.infrastructure.filesystem_paths import DataPaths
from algohint.infrastructure.json_learning_log_repository import JsonLearningLogRepository
from algohint.infrastructure.json_profile_repository import JsonProfileRepository
from algohint.infrastructure.sqlite_review_history_repository import (
    SqliteReviewHistoryRepository,
)


def make_attempt(attempted_at: datetime, marker: str) -> QuizAttempt:
    feedback = tuple(
        StoredQuizFeedback(
            question_id=f"question-{index}",
            prompt=f"設問 {index} {marker}",
            selected_option_id="selected",
            selected_text="選択した回答",
            correct_option_id="correct",
            correct_text="正しい回答",
            correct=False,
            explanation="復習のための解説",
        )
        for index in range(5)
    )
    return QuizAttempt(
        attempted_at=attempted_at,
        material_version=1,
        score=0,
        feedback=feedback,
    )


def make_code_review(reviewed_at: datetime, marker: str) -> CodeReviewEntry:
    return CodeReviewEntry(
        reviewed_at=reviewed_at,
        completion_reason=CompletionReason.FULL_AC,
        review=GeneratedCodeReview(
            algorithm_recap=f"アルゴリズムの復習 {marker}",
            strengths=("簡潔です。",),
            improvements=(
                CodeReviewPoint(
                    category=CodeReviewCategory.READABILITY,
                    title="命名",
                    feedback="変数の役割が伝わる名前を維持しましょう。",
                ),
            ),
            provider="fake",
            model_name="fake-review",
        ),
    )


def make_repositories(tmp_path: Path):
    paths = DataPaths(tmp_path / "data")
    profiles = JsonProfileRepository(paths)
    logs = JsonLearningLogRepository(paths, profiles)
    profile_service = ProfileService(profiles, logs)
    return paths, profiles, profile_service


def test_quiz_attempt_round_trips_as_newest_first_snapshot(tmp_path: Path) -> None:
    paths, profiles, profile_service = make_repositories(tmp_path)
    profile = profile_service.create_profile("学習者")
    repository = SqliteReviewHistoryRepository(paths, profiles)
    older = make_attempt(datetime.now(UTC) - timedelta(minutes=1), "older")
    newer = make_attempt(datetime.now(UTC), "newer")

    repository.save_quiz_attempt(profile.profile_id, "l0_two_values", older)
    status = repository.save_quiz_attempt(
        profile.profile_id,
        "l0_two_values",
        newer,
    )
    records = repository.list_records(
        profile.profile_id,
        "l0_two_values",
        kind=ReviewHistoryKind.QUIZ_ATTEMPT.value,
        limit=20,
        offset=0,
    )

    assert len(records) == 2
    assert QuizAttempt.model_validate_json(records[0].payload_json) == newer
    assert status.used_bytes > 0
    assert not status.warning


def test_quota_warns_and_prunes_oldest_record_for_only_that_profile(
    tmp_path: Path,
) -> None:
    paths, profiles, profile_service = make_repositories(tmp_path)
    measuring_profile = profile_service.create_profile("計測用")
    measuring = SqliteReviewHistoryRepository(paths, profiles, quota_bytes=1_000_000)
    one_record = measuring.save_quiz_attempt(
        measuring_profile.profile_id,
        "l0_two_values",
        make_attempt(datetime.now(UTC), "measure"),
    ).used_bytes

    limited_profile = profile_service.create_profile("制限対象")
    other_profile = profile_service.create_profile("別プロフィール")
    limited = SqliteReviewHistoryRepository(
        paths,
        profiles,
        quota_bytes=one_record * 2 + 10,
        warning_ratio=0.5,
    )
    base = datetime.now(UTC)
    limited.save_quiz_attempt(
        other_profile.profile_id,
        "l0_two_values",
        make_attempt(base - timedelta(days=2), "other"),
    )
    limited.save_quiz_attempt(
        limited_profile.profile_id,
        "l0_two_values",
        make_attempt(base - timedelta(days=2), "oldest"),
    )
    limited.save_quiz_attempt(
        limited_profile.profile_id,
        "l0_two_values",
        make_attempt(base - timedelta(days=1), "middle"),
    )
    status = limited.save_quiz_attempt(
        limited_profile.profile_id,
        "l0_two_values",
        make_attempt(base, "newest"),
    )

    assert status.pruned_count == 1
    assert status.warning
    assert (
        limited.count_records(
            limited_profile.profile_id,
            "l0_two_values",
            kind=ReviewHistoryKind.QUIZ_ATTEMPT.value,
        )
        == 2
    )
    assert (
        limited.count_records(
            other_profile.profile_id,
            "l0_two_values",
            kind=ReviewHistoryKind.QUIZ_ATTEMPT.value,
        )
        == 1
    )


def test_parallel_attempts_are_not_lost(tmp_path: Path) -> None:
    paths, profiles, profile_service = make_repositories(tmp_path)
    profile = profile_service.create_profile("学習者")
    repository = SqliteReviewHistoryRepository(paths, profiles)
    base = datetime.now(UTC)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [
            executor.submit(
                repository.save_quiz_attempt,
                profile.profile_id,
                "l0_two_values",
                make_attempt(base + timedelta(seconds=index), str(index)),
            )
            for index in range(8)
        ]
        for future in futures:
            future.result(timeout=10)

    assert (
        repository.count_records(
            profile.profile_id,
            "l0_two_values",
            kind=ReviewHistoryKind.QUIZ_ATTEMPT.value,
        )
        == 8
    )


def test_quota_prunes_oldest_across_quiz_and_code_review_kinds(
    tmp_path: Path,
) -> None:
    paths, profiles, profile_service = make_repositories(tmp_path)
    measuring_profile = profile_service.create_profile("種類別計測")
    measuring = SqliteReviewHistoryRepository(paths, profiles, quota_bytes=1_000_000)
    base = datetime.now(UTC)
    after_review = measuring.save_code_review(
        measuring_profile.profile_id,
        "l0_two_values",
        make_code_review(base, "measure"),
    ).used_bytes
    after_both = measuring.save_quiz_attempt(
        measuring_profile.profile_id,
        "l0_two_values",
        make_attempt(base, "measure"),
    ).used_bytes
    quiz_bytes = after_both - after_review

    target = profile_service.create_profile("種類横断")
    limited = SqliteReviewHistoryRepository(
        paths,
        profiles,
        quota_bytes=after_review + quiz_bytes * 2 - 1,
    )
    limited.save_code_review(
        target.profile_id,
        "l0_two_values",
        make_code_review(base - timedelta(days=2), "measure"),
    )
    limited.save_quiz_attempt(
        target.profile_id,
        "l0_two_values",
        make_attempt(base - timedelta(days=1), "measure"),
    )
    status = limited.save_quiz_attempt(
        target.profile_id,
        "l0_two_values",
        make_attempt(base, "measure"),
    )

    assert status.pruned_count == 1
    assert (
        limited.count_records(
            target.profile_id,
            "l0_two_values",
            kind=ReviewHistoryKind.CODE_REVIEW.value,
        )
        == 0
    )
    assert (
        limited.count_records(
            target.profile_id,
            "l0_two_values",
            kind=ReviewHistoryKind.QUIZ_ATTEMPT.value,
        )
        == 2
    )
