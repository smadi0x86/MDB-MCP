"""Behaviour every backend must share, run against both GDB and LLDB."""

import pytest
from conftest import BACKENDS

from mdb_mcp.backends import DebuggerError, create_session

pytestmark = pytest.mark.parametrize("kind", BACKENDS)

COMMANDS = {
    "gdb": {"break": "break {}", "locals": "info locals", "print": "print {}"},
    "lldb": {"break": "breakpoint set --name {}", "locals": "frame variable", "print": "expression -- {}"},
}


@pytest.fixture
def session_factory():
    created = []

    def make(kind, program=None, args=None):
        session = create_session(kind)
        created.append(session)
        if program:
            session.load_program(str(program), args)
        return session

    yield make
    for session in created:
        session.close()


def test_run_to_completion_shows_program_output(kind, session_factory, programs):
    session = session_factory(kind, programs["example"])
    output = session.execute("run", timeout=30)
    assert "Factorial of 5 is 120" in output
    assert "program output" in output
    assert session.state == "exited"


def test_breakpoint_and_backtrace(kind, session_factory, programs):
    cmd = COMMANDS[kind]
    session = session_factory(kind, programs["example"])
    session.execute(cmd["break"].format("factorial"), timeout=10)
    output = session.execute("run", timeout=30)
    assert "factorial" in output
    assert session.state == "stopped"
    assert "main" in session.execute("bt", timeout=10)
    assert "5" in session.execute(cmd["print"].format("n"), timeout=10)


def test_crash_is_reported(kind, session_factory, programs):
    session = session_factory(kind, programs["crash"])
    output = session.execute("run", timeout=30)
    assert "SIGSEGV" in output or "EXC_BAD_ACCESS" in output
    assert "alice is 31 years old" in output
    assert session.state == "stopped"


def test_slow_program_reaches_breakpoint(kind, session_factory, programs):
    # The target sleeps for 2s before hitting the breakpoint.
    session = session_factory(kind, programs["spin"])
    session.execute(COMMANDS[kind]["break"].format("target"), timeout=10)
    output = session.execute("run", timeout=30)
    assert "target" in output
    assert session.state == "stopped"


def test_timeout_then_interrupt(kind, session_factory, programs):
    session = session_factory(kind, programs["spin"])
    output = session.execute("run", timeout=3)
    assert "still running" in output
    assert session.state == "running"

    refused = session.execute(COMMANDS[kind]["locals"], timeout=1)
    assert "command not sent" in refused

    session.interrupt()
    stopped = session.wait_for_stop(timeout=10)
    assert "main" in stopped
    assert session.state == "stopped"
    assert "main" in session.execute("bt", timeout=10)


def test_invalid_command_reports_error(kind, session_factory):
    session = session_factory(kind)
    output = session.execute("definitely-not-a-command", timeout=5)
    assert "rror" in output


def test_missing_program_raises(kind, session_factory, tmp_path):
    session = session_factory(kind)
    with pytest.raises(DebuggerError):
        session.load_program(str(tmp_path / "missing"))


def test_close_kills_debugger(kind, session_factory, programs):
    session = session_factory(kind, programs["spin"])
    session.execute("run", timeout=1)
    session.close()
    assert not session.alive
