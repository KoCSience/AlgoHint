"""Constrained subprocess execution for local, educational code judging."""

import os
import resource
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from algohint.domain.enums import JudgeStatus
from algohint.domain.models import JudgePolicy


@dataclass(frozen=True)
class ExecutionOutcome:
    """Raw result used by LocalJudge before testcase comparison."""

    status: JudgeStatus
    stdout: str
    stderr: str
    elapsed_ms: int


class SubprocessExecutor:
    """Execute a submission with modest local limits, never as a public sandbox.

    ``python -I`` and a temporary working directory reduce accidental access to
    the application environment. Even when AlgoHint itself runs in Docker, the
    submission shares that application container and can reach its readable
    files. These limits therefore support trusted local learning; they are not a
    per-submission security boundary for untrusted public users.
    """

    @staticmethod
    def _limited_environment() -> dict[str, str]:
        return {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
        }

    @staticmethod
    def _resource_limits(policy: JudgePolicy) -> None:
        """Apply POSIX limits in the child process where they are available."""

        resource.setrlimit(
            resource.RLIMIT_CPU,
            (max(1, int(policy.timeout_seconds) + 1), max(2, int(policy.timeout_seconds) + 2)),
        )
        memory_bytes = policy.memory_limit_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
        resource.setrlimit(
            resource.RLIMIT_FSIZE, (policy.output_limit_bytes, policy.output_limit_bytes)
        )

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        encoded = text.encode("utf-8", errors="replace")
        return encoded[:limit].decode("utf-8", errors="replace")

    def run(self, source: str, input_text: str, policy: JudgePolicy) -> ExecutionOutcome:
        """Compile then execute source, mapping process failures to judge statuses."""

        if len(source.encode("utf-8")) > 65_536:
            return ExecutionOutcome(JudgeStatus.CE, "", "提出コードが長すぎます。", 0)
        with tempfile.TemporaryDirectory(prefix="algohint-judge-") as directory_name:
            directory = Path(directory_name)
            submission = directory / "submission.py"
            submission.write_text(source, encoding="utf-8")
            command = [sys.executable, "-I", str(submission)]
            compile_command = [sys.executable, "-I", "-m", "py_compile", str(submission)]
            preexec = self._resource_limits if os.name == "posix" else None
            try:
                compilation = subprocess.run(
                    compile_command,
                    cwd=directory,
                    capture_output=True,
                    text=True,
                    timeout=policy.timeout_seconds,
                    env=self._limited_environment(),
                    shell=False,
                    preexec_fn=(lambda: self._resource_limits(policy)) if preexec else None,
                )
                if compilation.returncode != 0:
                    return ExecutionOutcome(
                        JudgeStatus.CE,
                        "",
                        self._truncate(compilation.stderr, policy.output_limit_bytes),
                        0,
                    )
                started = time.monotonic()
                # Files, unlike pipes, are constrained by RLIMIT_FSIZE on POSIX.
                # This avoids buffering unbounded learner output in the web process.
                with (
                    (directory / "stdout.txt").open("w+b") as stdout_file,
                    (directory / "stderr.txt").open("w+b") as stderr_file,
                ):
                    process = subprocess.Popen(
                        command,
                        cwd=directory,
                        stdin=subprocess.PIPE,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        text=True,
                        env=self._limited_environment(),
                        shell=False,
                        preexec_fn=(lambda: self._resource_limits(policy)) if preexec else None,
                    )
                    try:
                        process.communicate(input=input_text, timeout=policy.timeout_seconds)
                    except subprocess.TimeoutExpired:
                        # Killing here, before the temporary directory is removed,
                        # prevents a timed-out learner process from surviving judge cleanup.
                        process.kill()
                        process.communicate()
                        raise
                    completed_returncode = process.returncode
                stdout = (directory / "stdout.txt").read_text(encoding="utf-8", errors="replace")
                stderr = (directory / "stderr.txt").read_text(encoding="utf-8", errors="replace")
                elapsed_ms = int((time.monotonic() - started) * 1000)
            except subprocess.TimeoutExpired:
                return ExecutionOutcome(JudgeStatus.TLE, "", "", int(policy.timeout_seconds * 1000))
            except OSError:
                return ExecutionOutcome(JudgeStatus.IE, "", "", 0)
            if completed_returncode != 0:
                return ExecutionOutcome(
                    JudgeStatus.RE,
                    self._truncate(stdout, policy.output_limit_bytes),
                    self._truncate(stderr, policy.output_limit_bytes),
                    elapsed_ms,
                )
            return ExecutionOutcome(
                JudgeStatus.AC,
                self._truncate(stdout, policy.output_limit_bytes),
                self._truncate(stderr, policy.output_limit_bytes),
                elapsed_ms,
            )
