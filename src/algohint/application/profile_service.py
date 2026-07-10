"""Profile selection use case."""

from algohint.domain.models import Profile
from algohint.domain.ports import LearningLogRepository


class ProfileService:
    """Create local identities without introducing authentication or accounts."""

    def __init__(self, repository: LearningLogRepository) -> None:
        self._repository = repository

    def list_profiles(self) -> list[Profile]:
        return self._repository.list_profiles()

    def create_profile(self, display_name: str) -> Profile:
        return self._repository.create_profile(display_name)
