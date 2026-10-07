"""GDB backend, driven through the GDB/MI interface."""

from __future__ import annotations

import itertools
import json
import logging
import os
import select
import signal
import threading
import time
import tty
from typing import Any

from pygdbmi.gdbcontroller import GdbController

from .base import BUSY_NOTE, DebuggerError, DebuggerSession, join_output, running_note

logger = logging.getLogger(__name__)

# How long to wait for GDB to answer setup commands.
STARTUP_TIMEOUT = 10.0
POLL_INTERVAL = 0.1


def mi_quote(text: str) -> str:
    """Quote a string as a GDB/MI c-string."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class _Reply:
    """Output collected while one command runs."""

    def __init__(self) -> None:
        self.console: list[str] = []
        self.program: list[str] = []
        self.notes: list[str] = []
        self.result: dict[str, Any] | None = None


class GDBSession(DebuggerSession):
    kind = "gdb"

    def __init__(self, gdb_path: str = "gdb") -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._tokens = itertools.count(1)
        self._state = "no process"
        self._pty_master: int | None = None
        self._pty_slave: int | None = None
        try:
            self._gdb = GdbController(command=[gdb_path, "--quiet", "--interpreter=mi3"])
        except Exception as exc:
            raise DebuggerError(f"could not start {gdb_path}: {exc}") from exc

        try:
            self._gdb.get_gdb_response(timeout_sec=1, raise_error_on_timeout=False)
            for setting in ("confirm off", "pagination off", "width 0", "height 0"):
                self._run_mi(f"-gdb-set {setting}")
            self._setup_inferior_tty()
        except Exception:
            self.close()
            raise

    def _setup_inferior_tty(self) -> None:
        # Give the target its own terminal so its output is kept apart from
        # GDB/MI records and it can never read our commands from stdin.
        if not hasattr(os, "openpty"):
            return
        master, slave = os.openpty()
        tty.setraw(slave)
        os.set_blocking(master, False)
        self._pty_master, self._pty_slave = master, slave
        reply = self._run_mi(f"-inferior-tty-set {os.ttyname(slave)}")
        if reply.result is None or reply.result.get("message") == "error":
            logger.warning("could not give the target its own terminal")

    @property
    def alive(self) -> bool:
        process = getattr(self._gdb, "gdb_process", None)
        return process is not None and process.poll() is None

    @property
    def state(self) -> str:
        return self._state

    def load_program(self, program: str, args: str | None = None) -> str:
        with self._lock:
            reply = self._run_mi(f"-file-exec-and-symbols {mi_quote(program)}")
            if reply.result and reply.result["message"] == "error":
                raise DebuggerError(reply.result["payload"].get("msg", "could not load program"))
            if args:
                self._run_mi(f"-exec-arguments {args}")
        self.program = program
        return join_output("".join(reply.console)) if reply.console else f"Loaded {program}"

    def execute(self, command: str, timeout: float) -> str:
        command = command.strip()
        with self._lock:
            reply = _Reply()
            deadline = time.monotonic() + timeout
            if self._state == "running":
                self._wait_for_stop(reply, deadline)
                if self._state == "running":
                    reply.notes.append(f"[command not sent: {command!r}]")
                    reply.notes.append(running_note(timeout))
                    return self._render(reply, command)

            token = next(self._tokens)
            self._write(f"{token}{command}")
            self._read_until(reply, deadline, lambda: reply.result is not None, token)
            if reply.result is None:
                reply.notes.append(f"[no reply from GDB after {timeout:g}s]")
            elif self._state == "running":
                self._wait_for_stop(reply, deadline)
                if self._state == "running":
                    reply.notes.append(running_note(timeout))
            return self._render(reply, command)

    def interrupt(self) -> None:
        if self._state != "running" or not self.alive:
            return
        # GDB runs CLI execution commands synchronously, so it does not read
        # new MI commands until the target stops. SIGINT works like Ctrl-C.
        self._gdb.gdb_process.send_signal(signal.SIGINT)

    def wait_for_stop(self, timeout: float) -> str:
        """Collect output until the target stops, for use after interrupt()."""
        if not self._lock.acquire(timeout=1):
            return BUSY_NOTE
        try:
            reply = _Reply()
            self._wait_for_stop(reply, time.monotonic() + timeout)
            if self._state == "running":
                reply.notes.append(running_note(timeout))
            return self._render(reply, "")
        finally:
            self._lock.release()

    def close(self) -> None:
        try:
            if self.alive and self._state == "running":
                self._gdb.gdb_process.send_signal(signal.SIGINT)
            self._gdb.exit()
        except Exception as exc:
            logger.debug("error while closing GDB: %s", exc)
        for fd in (self._pty_master, self._pty_slave):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._pty_master = self._pty_slave = None

    # Internal helpers

    def _write(self, line: str) -> None:
        if not self.alive:
            raise DebuggerError("GDB has exited; start a new session")
        try:
            self._gdb.write(line, read_response=False)
        except (BrokenPipeError, OSError) as exc:
            raise DebuggerError(f"lost connection to GDB: {exc}") from exc

    def _run_mi(self, command: str) -> _Reply:
        reply = _Reply()
        token = next(self._tokens)
        self._write(f"{token}{command}")
        deadline = time.monotonic() + STARTUP_TIMEOUT
        self._read_until(reply, deadline, lambda: reply.result is not None, token)
        return reply

    def _wait_for_stop(self, reply: _Reply, deadline: float) -> None:
        self._read_until(reply, deadline, lambda: self._state != "running")

    def _read_until(self, reply: _Reply, deadline: float, done, token: int | None = None) -> None:
        while True:
            self._read_program_output(reply)
            if done():
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.alive:
                return
            try:
                records = self._gdb.get_gdb_response(
                    timeout_sec=min(POLL_INTERVAL, remaining), raise_error_on_timeout=False
                )
            except Exception as exc:
                raise DebuggerError(f"lost connection to GDB: {exc}") from exc
            for record in records:
                self._handle(record, reply, token)

    def _read_program_output(self, reply: _Reply) -> None:
        if self._pty_master is None:
            return
        while select.select([self._pty_master], [], [], 0)[0]:
            try:
                data = os.read(self._pty_master, 65536)
            except OSError:
                return
            if not data:
                return
            reply.program.append(data.decode(errors="replace"))

    def _handle(self, record: dict[str, Any], reply: _Reply, token: int | None) -> None:
        kind = record.get("type")
        payload = record.get("payload")
        if kind == "console":
            reply.console.append(payload or "")
        elif kind == "log":
            reply.console.append(payload or "")
        elif kind in ("output", "target"):
            reply.program.append(f"{payload}\n" if payload else "")
        elif kind == "notify":
            self._handle_notify(record.get("message"), payload or {}, reply)
        elif kind == "result":
            if token is not None and record.get("token") == token:
                reply.result = record
            if record.get("message") == "running":
                self._state = "running"

    def _handle_notify(self, message: str | None, payload: dict[str, Any], reply: _Reply) -> None:
        if message == "running":
            self._state = "running"
        elif message == "stopped":
            reason = payload.get("reason", "")
            self._state = "exited" if reason.startswith("exited") else "stopped"
        elif message == "thread-group-exited":
            self._state = "exited"

    def _render(self, reply: _Reply, command: str) -> str:
        lines = []
        for chunk in reply.console:
            # GDB echoes CLI commands back as log records.
            if chunk.strip() == command and command:
                continue
            lines.append(chunk)
        text = "".join(lines)

        notes = []
        result = reply.result
        if result is not None:
            payload = result.get("payload") or {}
            if result.get("message") == "error":
                msg = payload.get("msg", "unknown error")
                text = text.replace(msg + "\n", "")
                notes.append(f"Error: {msg}")
            elif command.startswith("-") and payload:
                text += json.dumps(payload, indent=1) + "\n"
        program = "".join(reply.program).replace("\r\n", "\n")
        return join_output(text, program, notes + reply.notes)
