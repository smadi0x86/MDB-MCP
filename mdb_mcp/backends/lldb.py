"""LLDB backend.

LLDB runs in its own process (``lldb --batch``) with ``lldb_worker`` loaded
into its embedded Python. Importing the ``lldb`` module into the server
instead would tie the server to LLDB's Python version, and some LLDB builds
abort the whole interpreter when imported from an outside Python.
"""

from __future__ import annotations

import json
import logging
import os
import select
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from .base import BUSY_NOTE, DebuggerError, DebuggerSession, join_output, running_note

logger = logging.getLogger(__name__)

STARTUP_TIMEOUT = 30.0
# Extra time allowed on top of a command's own timeout before the worker is
# considered hung.
REPLY_GRACE = 15.0
WORKER_DIR = Path(__file__).parent


def lldb_quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


class LLDBSession(DebuggerSession):
    kind = "lldb"

    def __init__(self, lldb_path: str = "lldb") -> None:
        super().__init__()
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._state = "no process"
        self._buffer = b""

        self._stderr = tempfile.TemporaryFile()
        to_worker_r, to_worker_w = os.pipe()
        from_worker_r, from_worker_w = os.pipe()
        script = (
            f"script import sys; sys.path.insert(0, {str(WORKER_DIR)!r}); "
            f"import lldb_worker; lldb_worker.main({to_worker_r}, {from_worker_w})"
        )
        try:
            self._proc = subprocess.Popen(
                [lldb_path, "--no-lldbinit", "--batch", "-o", script],
                pass_fds=(to_worker_r, from_worker_w),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=self._stderr,
                start_new_session=True,
            )
        except OSError as exc:
            for fd in (to_worker_r, to_worker_w, from_worker_r, from_worker_w):
                os.close(fd)
            raise DebuggerError(f"could not start {lldb_path}: {exc}") from exc
        os.close(to_worker_r)
        os.close(from_worker_w)
        self._requests = os.fdopen(to_worker_w, "w")
        self._replies = from_worker_r

        ready = self._read_reply(STARTUP_TIMEOUT)
        if ready is None or ready.get("op") != "ready":
            stderr = self._stderr_tail()
            self.close()
            raise DebuggerError("LLDB started but its Python support did not load" + (f": {stderr}" if stderr else ""))
        self.version = ready.get("version", "")

    @property
    def alive(self) -> bool:
        return self._proc.poll() is None

    @property
    def state(self) -> str:
        return self._state

    def load_program(self, program: str, args: str | None = None) -> str:
        output = self._request("execute", STARTUP_TIMEOUT, command=f"target create {lldb_quote(program)}")
        if output.get("error"):
            raise DebuggerError(output["output"].strip() or "could not load program")
        if args:
            self._request("execute", STARTUP_TIMEOUT, command=f"settings set -- target.run-args {args}")
        self.program = program
        return output["output"].strip()

    def execute(self, command: str, timeout: float) -> str:
        reply = self._request("execute", timeout, command=command.strip())
        return self._render(reply, timeout, command)

    def interrupt(self) -> None:
        if self.alive:
            self._send({"op": "interrupt"})

    def wait_for_stop(self, timeout: float) -> str:
        if not self._lock.acquire(timeout=1):
            return BUSY_NOTE
        try:
            reply = self._request("wait", timeout, locked=True)
        finally:
            self._lock.release()
        return self._render(reply, timeout, "")

    def close(self) -> None:
        try:
            if self.alive:
                self._send({"op": "quit"})
                self._requests.close()
                self._proc.wait(timeout=5)
        except Exception as exc:
            logger.debug("LLDB did not exit cleanly: %s", exc)
        if self.alive:
            self._proc.kill()
            self._proc.wait()
        try:
            os.close(self._replies)
        except OSError:
            pass
        self._stderr.close()

    # Internal helpers

    def _render(self, reply: dict, timeout: float, command: str) -> str:
        notes = []
        if "not-sent" in reply["notes"]:
            notes.append(f"[command not sent: {command!r}]")
        if "not-sent" in reply["notes"] or "still-running" in reply["notes"]:
            notes.append(running_note(timeout))
        program = reply["program"].replace("\r\n", "\n")
        return join_output(reply["output"], program, notes)

    def _request(self, op: str, timeout: float, locked: bool = False, **fields) -> dict:
        if not locked:
            with self._lock:
                return self._request(op, timeout, locked=True, **fields)
        if not self.alive:
            raise DebuggerError("LLDB has exited; start a new session")
        self._send({"op": op, "timeout": timeout, **fields})
        reply = self._read_reply(timeout + REPLY_GRACE)
        if reply is None:
            self.close()
            raise DebuggerError("LLDB stopped responding; the session was closed")
        if "fatal" in reply:
            raise DebuggerError(f"LLDB worker error: {reply['fatal']}")
        self._state = reply.get("state", self._state)
        return reply

    def _send(self, message: dict) -> None:
        with self._write_lock:
            try:
                self._requests.write(json.dumps(message) + "\n")
                self._requests.flush()
            except (BrokenPipeError, OSError, ValueError) as exc:
                raise DebuggerError(f"lost connection to LLDB: {exc}") from exc

    def _read_reply(self, timeout: float) -> dict | None:
        deadline = time.monotonic() + timeout
        while b"\n" not in self._buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([self._replies], [], [], remaining)
            if not ready:
                return None
            chunk = os.read(self._replies, 65536)
            if not chunk:
                return None
            self._buffer += chunk
        line, self._buffer = self._buffer.split(b"\n", 1)
        return json.loads(line)

    def _stderr_tail(self) -> str:
        self._stderr.seek(0)
        return self._stderr.read().decode(errors="replace").strip()[-500:]
