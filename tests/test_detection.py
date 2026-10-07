import pytest

from mdb_mcp import backends
from mdb_mcp.backends import DebuggerError, DebuggerInfo, resolve_kind


@pytest.fixture
def fake_detect(monkeypatch):
    infos = {}

    def detect(kind):
        return infos[kind]

    monkeypatch.setattr(backends, "detect", detect)
    return infos


def test_unknown_debugger_is_rejected():
    with pytest.raises(DebuggerError, match="unknown debugger"):
        resolve_kind("windbg")


def test_auto_prefers_gdb_on_linux(fake_detect, monkeypatch):
    monkeypatch.setattr(backends.platform, "system", lambda: "Linux")
    fake_detect["gdb"] = DebuggerInfo("gdb", "/usr/bin/gdb", "GNU gdb 15")
    fake_detect["lldb"] = DebuggerInfo("lldb", "/usr/bin/lldb", "lldb 18")
    assert resolve_kind("auto") == "gdb"


def test_auto_prefers_lldb_on_macos(fake_detect, monkeypatch):
    monkeypatch.setattr(backends.platform, "system", lambda: "Darwin")
    fake_detect["gdb"] = DebuggerInfo("gdb", "/usr/bin/gdb", "GNU gdb 15")
    fake_detect["lldb"] = DebuggerInfo("lldb", "/usr/bin/lldb", "lldb 18")
    assert resolve_kind("auto") == "lldb"


def test_auto_falls_back(fake_detect, monkeypatch):
    monkeypatch.setattr(backends.platform, "system", lambda: "Darwin")
    fake_detect["gdb"] = DebuggerInfo("gdb", "/usr/bin/gdb", "GNU gdb 15")
    fake_detect["lldb"] = DebuggerInfo("lldb", "/usr/bin/lldb", "lldb 18", problem="no python")
    assert resolve_kind("auto") == "gdb"


def test_explicit_unavailable_debugger_explains_why(fake_detect):
    fake_detect["lldb"] = DebuggerInfo("lldb", None, None, problem="lldb not found")
    with pytest.raises(DebuggerError, match="lldb not found"):
        resolve_kind("lldb")


def test_nothing_available(fake_detect):
    fake_detect["gdb"] = DebuggerInfo("gdb", None, None, problem="missing")
    fake_detect["lldb"] = DebuggerInfo("lldb", None, None, problem="missing")
    with pytest.raises(DebuggerError, match="no debugger available"):
        resolve_kind("auto")


def test_path_override(monkeypatch, tmp_path):
    fake = tmp_path / "my-gdb"
    fake.write_text("#!/bin/sh\necho 'GNU gdb (fake) 99'\n")
    fake.chmod(0o755)
    monkeypatch.setenv("MDB_GDB_PATH", str(fake))
    backends.detect.cache_clear()
    try:
        info = backends.detect("gdb")
        assert info.path == str(fake)
        assert info.version == "GNU gdb (fake) 99"
    finally:
        backends.detect.cache_clear()
