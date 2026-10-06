"""Registry of active debugger sessions, shared by every tool."""

from __future__ import annotations

import logging
import threading

from .backends import DebuggerError, DebuggerSession

logger = logging.getLogger(__name__)


class SessionRegistry:
    def __init__(self) -> None:
        self._sessions: dict[str, DebuggerSession] = {}
        self._lock = threading.Lock()

    def add(self, session: DebuggerSession) -> None:
        with self._lock:
            self._sessions[session.id] = session

    def get(self, session_id: str) -> DebuggerSession:
        self.prune()
        with self._lock:
            session = self._sessions.get(session_id.strip())
        if session is None:
            known = ", ".join(self._sessions) or "none"
            raise DebuggerError(
                f"no session {session_id!r} (active sessions: {known}). Use debugger_start to create one."
            )
        return session

    def remove(self, session_id: str) -> DebuggerSession | None:
        with self._lock:
            return self._sessions.pop(session_id.strip(), None)

    def list(self) -> list[DebuggerSession]:
        self.prune()
        with self._lock:
            return list(self._sessions.values())

    def prune(self) -> None:
        """Forget sessions whose debugger process has died."""
        with self._lock:
            dead = [sid for sid, session in self._sessions.items() if not session.alive]
            for sid in dead:
                logger.info("session %s: debugger exited", sid)
                self._sessions.pop(sid).close()

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            session.close()
