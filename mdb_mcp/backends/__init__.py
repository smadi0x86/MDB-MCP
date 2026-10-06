"""Debugger discovery and session creation."""

from __future__ import annotations

import functools
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .base import DebuggerError, DebuggerSession

__all__ = [
    "DebuggerError",
    "DebuggerInfo",
    "DebuggerSession",
    "create_session",
    "detect",
    "resolve_kind",
]

KINDS = ("gdb", "lldb")
PATH_ENV = {"gdb": "MDB_GDB_PATH", "lldb": "MDB_LLDB_PATH"}

# Places LLDB is commonly installed outside PATH.
LLDB_FALLBACKS = (
    "/opt/homebrew/opt/llvm/bin/lldb",
    "/usr/local/opt/llvm/bin/lldb",
)


@dataclass(frozen=True)
class DebuggerInfo:
    kind: str
    path: str | None
    version: str | None
    problem: str | None = None

    @property
    def available(self) -> bool:
        return self.path is not None and self.problem is None


def _find(kind: str) -> str | None:
    configured = os.environ.get(PATH_ENV[kind])
    if configured:
        return shutil.which(configured) or (configured if Path(configured).is_file() else None)
    found = shutil.which(kind)
    if found or kind != "lldb":
        return found
    if platform.system() == "Darwin":
        try:
            xcrun = subprocess.run(["xcrun", "--find", "lldb"], capture_output=True, text=True, timeout=10)
            if xcrun.returncode == 0 and xcrun.stdout.strip():
                return xcrun.stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            pass
    return next((path for path in LLDB_FALLBACKS if Path(path).is_file()), None)


def _version(path: str) -> str | None:
    try:
        result = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    lines = result.stdout.strip().splitlines()
    return lines[0] if result.returncode == 0 and lines else None


def _lldb_python_problem(path: str) -> str | None:
    """Check that this LLDB can run the Python worker."""
    try:
        result = subprocess.run(
            [path, "--no-lldbinit", "--batch", "-o", "script import lldb; print('mdb-ok')"],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not run {path}: {exc}"
    if "mdb-ok" in result.stdout:
        return None
    return (
        "LLDB was found but its Python scripting support does not work "
        "(on Debian/Ubuntu install the python3-lldb package that matches your LLDB version)"
    )


@functools.cache
def detect(kind: str) -> DebuggerInfo:
    """Find a debugger and check that it is usable. Cached per process."""
    path = _find(kind)
    if path is None:
        hint = f"set {PATH_ENV[kind]} if it is installed outside PATH"
        return DebuggerInfo(kind, None, None, f"{kind} not found ({hint})")
    version = _version(path)
    problem = _lldb_python_problem(path) if kind == "lldb" else None
    return DebuggerInfo(kind, path, version, problem)


def resolve_kind(requested: str) -> str:
    """Turn 'auto', 'gdb' or 'lldb' into an available debugger kind."""
    requested = requested.lower()
    if requested in KINDS:
        info = detect(requested)
        if not info.available:
            raise DebuggerError(info.problem or f"{requested} is not available")
        return requested
    if requested != "auto":
        raise DebuggerError(f"unknown debugger {requested!r}; use 'auto', 'gdb' or 'lldb'")
    order = ("lldb", "gdb") if platform.system() == "Darwin" else ("gdb", "lldb")
    for kind in order:
        if detect(kind).available:
            return kind
    raise DebuggerError("no debugger available; install GDB or LLDB")


def create_session(kind: str) -> DebuggerSession:
    path = detect(kind).path
    if kind == "gdb":
        from .gdb import GDBSession

        return GDBSession(path)
    from .lldb import LLDBSession

    return LLDBSession(path)
