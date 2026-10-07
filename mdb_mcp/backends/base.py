"""Common interface shared by the GDB and LLDB backends."""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod

MAX_OUTPUT_CHARS = 30_000


class DebuggerError(Exception):
    """Raised when a debugger cannot be started or stops responding."""


class DebuggerSession(ABC):
    """One running debugger instance driven by the server."""

    kind: str

    def __init__(self) -> None:
        self.id = uuid.uuid4().hex[:8]
        self.created_at = time.time()
        self.program: str | None = None

    @property
    @abstractmethod
    def alive(self) -> bool:
        """Whether the underlying debugger process is still running."""

    @property
    @abstractmethod
    def state(self) -> str:
        """Target state: 'no process', 'running', 'stopped' or 'exited'."""

    @abstractmethod
    def load_program(self, program: str, args: str | None = None) -> str:
        """Load an executable (and optional arguments) into the debugger."""

    @abstractmethod
    def execute(self, command: str, timeout: float) -> str:
        """Run a native debugger command and return its output.

        If the command resumes the target, wait up to ``timeout`` seconds
        for it to stop again before returning.
        """

    @abstractmethod
    def interrupt(self) -> None:
        """Pause a running target. Safe to call from another thread."""

    @abstractmethod
    def wait_for_stop(self, timeout: float) -> str:
        """Wait for the target to stop (after interrupt()) and report where."""

    @abstractmethod
    def close(self) -> None:
        """Kill the target and the debugger."""

    def describe(self) -> str:
        program = self.program or "no program loaded"
        return f"{self.id}  {self.kind:<4}  {self.state:<10}  {program}"


BUSY_NOTE = "Interrupt sent. Another command is still waiting on this session and will report where the target stopped."


def running_note(timeout: float) -> str:
    return (
        f"[target is still running after {timeout:g}s. Call debugger_interrupt "
        "to pause it, or call debugger_command again to keep waiting]"
    )


def join_output(
    debugger_output: str,
    program_output: str = "",
    notes: list[str] | None = None,
) -> str:
    """Combine debugger output, program output and notes into one reply."""
    parts = []
    if debugger_output.strip():
        parts.append(debugger_output.rstrip())
    if program_output:
        parts.append("--- program output ---\n" + program_output.rstrip())
    parts.extend(notes or [])
    text = "\n".join(parts) if parts else "(no output)"
    if len(text) > MAX_OUTPUT_CHARS:
        dropped = len(text) - MAX_OUTPUT_CHARS
        text = text[:MAX_OUTPUT_CHARS] + f"\n[output truncated, {dropped} more characters]"
    return text
