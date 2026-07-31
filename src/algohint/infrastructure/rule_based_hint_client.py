"""Safe deterministic hint provider used by the MVP."""

from algohint.domain.enums import JudgeStatus
from algohint.domain.models import Hint, Problem


class RuleBasedHintClient:
    """Select authored hints first, then add non-prescriptive judge guidance."""

    _status_advice = {
        JudgeStatus.WA: "期待する入出力の対応と、最小ケース・境界ケースを手計算で確認してみましょう。",
        JudgeStatus.RE: "入力の個数、型変換、添字の範囲、空のデータを扱う箇所を順に確認してみましょう。",
        JudgeStatus.TLE: "制約をもう一度読み、入力サイズに対して繰り返し回数が増えすぎていないか考えてみましょう。",
        JudgeStatus.CE: "括弧、コロン、インデント、変数名を小さな単位で見直してみましょう。",
        JudgeStatus.IE: "判定側で問題が起きました。コードを変えずに、もう一度実行して状況を確認してください。",
    }

    def generate(self, problem: Problem, hint_count: int, status: JudgeStatus | None) -> Hint:
        """Return the next authored hint, optionally prefixed by result-oriented advice."""

        authored = problem.hints[min(hint_count, len(problem.hints) - 1)]
        if status in self._status_advice:
            return authored.model_copy(
                update={"text": f"{self._status_advice[status]}\n\n{authored.text}"}
            )
        return authored
