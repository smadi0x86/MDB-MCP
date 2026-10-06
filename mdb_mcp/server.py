"""MCP server exposing GDB and LLDB debugging sessions."""

from __future__ import annotations

import atexit
import logging
import sys
from pathlib import Path
from typing import Annotated, Literal

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__
from .backends import KINDS, DebuggerError, create_session, detect, resolve_kind
from .sessions import SessionRegistry

logger = logging.getLogger("mdb_mcp")

INSTRUCTIONS = """\
Debug native programs (C, C++, Rust, Go, ...) with GDB or LLDB.

Typical flow: debugger_start (optionally with the program path) ->
debugger_command with ordinary GDB or LLDB commands such as `break main`,
`run`, `bt`, `info locals` / `frame variable`, `x/16gx $sp` ->
debugger_terminate when finished. Commands that resume the target wait for
it to stop (up to `timeout` seconds). If it keeps running, use
debugger_interrupt to pause it.
"""

mcp = FastMCP("mdb", instructions=INSTRUCTIONS)
sessions = SessionRegistry()
atexit.register(sessions.close_all)

SessionId = Annotated[str, Field(description="Session ID returned by debugger_start.")]


async def _in_thread(func, *args):
    """Run blocking debugger I/O off the event loop, so other tools
    (debugger_interrupt in particular) keep working meanwhile."""
    try:
        return await anyio.to_thread.run_sync(func, *args)
    except DebuggerError as exc:
        return f"Error: {exc}"


@mcp.tool(
    title="Debugger status",
    annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
)
async def debugger_status() -> str:
    """Show which debuggers are installed and list active sessions."""

    def status() -> str:
        lines = [f"mdb-mcp {__version__}", "", "Debuggers:"]
        for kind in KINDS:
            info = detect(kind)
            if info.available:
                lines.append(f"  {kind}: available - {info.version or info.path}")
            else:
                lines.append(f"  {kind}: unavailable - {info.problem}")
        active = sessions.list()
        lines += ["", "Sessions:" if active else "No active sessions."]
        lines += [f"  {session.describe()}" for session in active]
        return "\n".join(lines)

    return await _in_thread(status)


@mcp.tool(title="Start debugger session")
async def debugger_start(
    debugger: Annotated[
        Literal["auto", "gdb", "lldb"],
        Field(description="Which debugger to use. 'auto' prefers LLDB on macOS and GDB elsewhere."),
    ] = "auto",
    program: Annotated[
        str | None,
        Field(description="Absolute path of an executable to load. Optional; can also be loaded later."),
    ] = None,
    args: Annotated[
        str | None,
        Field(description="Command-line arguments for the program, as one string."),
    ] = None,
) -> str:
    """Start a new GDB or LLDB session and return its session ID."""

    def start() -> str:
        kind = resolve_kind(debugger)
        path = None
        if program:
            path = Path(program).expanduser().resolve()
            if not path.is_file():
                raise DebuggerError(f"program not found: {path}")
        session = create_session(kind)
        try:
            loaded = session.load_program(str(path), args) if path else None
        except Exception:
            session.close()
            raise
        sessions.add(session)
        lines = [f"Started {kind} session {session.id} ({detect(kind).version})."]
        if loaded:
            lines.append(loaded)
        lines.append(f"Use debugger_command with session_id={session.id!r} to run {kind} commands.")
        return "\n".join(lines)

    return await _in_thread(start)


@mcp.tool(title="Run debugger command")
async def debugger_command(
    session_id: SessionId,
    command: Annotated[
        str,
        Field(description="A native command for the session's debugger, e.g. `break main`, `run`, `bt`, `x/8gx $rsp`."),
    ],
    timeout: Annotated[
        float,
        Field(ge=1, le=600, description="Seconds to wait for the target to stop when the command resumes it."),
    ] = 10,
) -> str:
    """Run one GDB or LLDB command and return its output.

    Execution commands (run, continue, next, step, finish, ...) wait until
    the target stops or the timeout passes. The program's own stdout/stderr
    is shown under a 'program output' heading.
    """

    def run() -> str:
        return sessions.get(session_id).execute(command, timeout)

    return await _in_thread(run)


@mcp.tool(title="Interrupt target")
async def debugger_interrupt(
    session_id: SessionId,
    timeout: Annotated[float, Field(ge=1, le=60, description="Seconds to wait for the target to stop.")] = 5,
) -> str:
    """Pause a running target (like Ctrl-C) and show where it stopped."""

    def interrupt() -> str:
        session = sessions.get(session_id)
        if session.state != "running":
            return f"Target is not running (state: {session.state})."
        session.interrupt()
        return session.wait_for_stop(timeout)

    return await _in_thread(interrupt)


@mcp.tool(
    title="End debugger session",
    annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
async def debugger_terminate(session_id: SessionId) -> str:
    """Kill the debugged program and close the session."""

    def terminate() -> str:
        session = sessions.remove(session_id)
        if session is None:
            return f"No session {session_id!r}; nothing to do."
        session.close()
        return f"Session {session_id} closed."

    return await _in_thread(terminate)


@mcp.resource("debugger://sessions", title="Active debugger sessions", mime_type="text/plain")
def list_sessions() -> str:
    """Active sessions, one per line: ID, debugger, state, program."""
    active = sessions.list()
    if not active:
        return "No active sessions."
    return "\n".join(session.describe() for session in active)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if len(sys.argv) > 1 and sys.argv[1] in ("-V", "--version"):
        print(f"mdb-mcp {__version__}")
        return
    mcp.run()
