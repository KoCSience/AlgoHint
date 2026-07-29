"""Profile selection use case."""

from datetime import UTC, datetime

from algohint.domain.enums import HintProviderId
from algohint.domain.models import Profile, ProfilePreferences
from algohint.domain.ports import LearningLogRepository, ProfileRepository

DEVELOPMENT_PROFILE_ID = "development-test-profile"
DEVELOPMENT_PROFILE_NAME = "開発テスト"


class ProfileService:
    """Create local identities without introducing authentication or accounts."""

    def __init__(
        self,
        profiles: ProfileRepository,
        logs: LearningLogRepository,
        *,
        development_mode: bool = False,
        default_provider: HintProviderId = HintProviderId.OPENAI,
    ) -> None:
        self._profiles = profiles
        self._logs = logs
        self._development_mode = development_mode
        self._default_preferences = ProfilePreferences(hint_provider=default_provider)

    def list_profiles(self) -> list[Profile]:
        return [
            profile
            for profile in self._profiles.list_profiles()
            if self._development_mode or not profile.is_development
        ]

    def create_profile(self, display_name: str) -> Profile:
        profile = self._profiles.create_profile(display_name, self._default_preferences)
        self._ensure_log(profile.profile_id)
        return profile

    def get_profile(self, profile_id: str) -> Profile:
        """Return profile metadata for UI preference synchronization."""

        profile = self._profiles.get_profile(profile_id)
        if profile.is_development and not self._development_mode:
            raise KeyError("Unknown profile")
        return profile

    def default_profile(self) -> Profile | None:
        """Return the reserved development identity or the first normal profile."""

        if self._development_mode:
            return self._ensure_development_profile()
        profiles = self.list_profiles()
        return profiles[0] if profiles else None

    def set_hint_provider(self, profile_id: str, provider: HintProviderId) -> Profile:
        """Persist a preference without treating it as cloud-send consent."""

        profile = self._profiles.get_profile(profile_id)
        updated = profile.model_copy(
            update={"preferences": ProfilePreferences(hint_provider=provider)}
        )
        self._profiles.save_profile(updated)
        return updated

    def _ensure_development_profile(self) -> Profile:
        try:
            return self._profiles.get_profile(DEVELOPMENT_PROFILE_ID)
        except KeyError:
            profile = Profile(
                profile_id=DEVELOPMENT_PROFILE_ID,
                display_name=DEVELOPMENT_PROFILE_NAME,
                created_at=datetime.now(UTC),
                preferences=self._default_preferences,
                is_development=True,
            )
            self._profiles.save_profile(profile)
            self._ensure_log(profile.profile_id)
            return profile

    def _ensure_log(self, profile_id: str) -> None:
        """Create the aggregate record when a profile has no log file yet."""

        log = self._logs.load_log(profile_id)
        self._logs.save_log(log)
