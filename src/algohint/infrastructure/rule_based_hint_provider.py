"""Deterministic fallback implementing the provider-neutral hint contract."""

from algohint.domain.enums import JudgeStatus
from algohint.domain.models import (
    GeneratedHint,
    HintGenerationRequest,
    ProviderAvailability,
)


class RuleBasedHintProvider:
    """Return authored content so provider outages never block local learning."""

    _status_advice = {
        JudgeStatus.WA: "期待する入出力の対応と、最小ケース・境界ケースを手計算で確認しましょう。",
        JudgeStatus.RE: "入力の個数、型変換、添字の範囲、空のデータを扱う箇所を順に確認しましょう。",
        JudgeStatus.TLE: "制約を読み直し、入力サイズに対して繰り返し回数が増えすぎないか確認しましょう。",
        JudgeStatus.CE: "括弧、コロン、インデント、変数名を小さな単位で見直しましょう。",
        JudgeStatus.IE: "コードを変えずに再実行し、同じ診断になるか確認してください。",
    }

    def availability(self) -> ProviderAvailability:
        """Rule-based content is always available and remains on this device."""

        return ProviderAvailability(available=True)

    def generate(self, request: HintGenerationRequest) -> GeneratedHint:
        """Combine the authored stage with a non-prescriptive Judge observation."""

        text = request.authored_hint.text
        advice = (
            self._status_advice.get(request.judge_status)
            if request.judge_status is not None
            else None
        )
        if advice:
            text = f"{advice}\n\n{text}"
        return GeneratedHint(
            text=text,
            category=request.authored_hint.category,
            provider="rule_based",
            model_name="authored-v1",
        )
