from __future__ import annotations

import errno
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Condition, RLock, Timer
from typing import Any

from smolagents_webui.serialization import to_json_compatible


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class SessionRecord:
    session_id: str
    title: str
    created_at: str
    updated_at: str
    run_count: int = 0
    is_running: bool = False
    events: list[dict[str, Any]] = field(default_factory=list)
    next_seq: int = 1
    agent_state: dict[str, Any] = field(default_factory=dict)
    last_error: str | None = None
    last_prompt: str | None = None

    def as_summary(self) -> dict[str, Any]:
        return {
            "id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "run_count": self.run_count,
            "is_running": self.is_running,
            "last_error": self.last_error,
            "last_prompt": self.last_prompt,
            "event_count": len(self.events),
        }


class SessionStore:
    """Thread-safe in-memory session store with JSON persistence."""

    def __init__(
        self,
        file_path: Path,
        max_events_per_session: int = 2000,
        persist_debounce_seconds: float = 0.75,
    ):
        self._file_path = file_path
        self._lock = RLock()
        self._events_available = Condition(self._lock)
        self._sessions: dict[str, SessionRecord] = {}
        self._max_events_per_session = max(200, max_events_per_session)
        self._persist_debounce_seconds = max(0.0, persist_debounce_seconds)
        self._persist_timer: Timer | None = None
        self._persist_dirty = False
        self._load()

    def _load(self) -> None:
        if not self._file_path.exists():
            return
        try:
            raw = json.loads(self._file_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # Ignore corrupt persistence files and start with a clean in-memory store.
            return

        sessions_payload = raw.get("sessions", {})
        if not isinstance(sessions_payload, dict):
            return
        for session_id, payload in sessions_payload.items():
            try:
                record = SessionRecord(
                    session_id=session_id,
                    title=str(payload.get("title", "Untitled Session")),
                    created_at=str(payload.get("created_at", utc_now_iso())),
                    updated_at=str(payload.get("updated_at", utc_now_iso())),
                    run_count=int(payload.get("run_count", 0)),
                    is_running=bool(payload.get("is_running", False)),
                    events=list(payload.get("events", [])),
                    next_seq=1,
                    agent_state=dict(payload.get("agent_state", {})),
                    last_error=payload.get("last_error"),
                    last_prompt=payload.get("last_prompt"),
                )
            except (TypeError, ValueError, AttributeError):
                continue

            if len(record.events) > self._max_events_per_session:
                record.events = record.events[-self._max_events_per_session :]
            last_seq = int(record.events[-1]["seq"]) if record.events else 0
            payload_next_seq = int(payload.get("next_seq", last_seq + 1))
            record.next_seq = max(payload_next_seq, last_seq + 1)
            self._sessions[session_id] = record

    def _is_transient_replace_error(self, exc: OSError) -> bool:
        if isinstance(exc, PermissionError):
            return True
        winerror = getattr(exc, "winerror", None)
        if winerror in {5, 32, 33}:
            return True
        return exc.errno in {errno.EACCES, errno.EPERM, errno.EBUSY}

    def _persist_locked(self) -> None:
        self._file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "sessions": {
                session_id: {
                    "title": record.title,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                    "run_count": record.run_count,
                    "is_running": record.is_running,
                    "events": record.events,
                    "next_seq": record.next_seq,
                    "agent_state": record.agent_state,
                    "last_error": record.last_error,
                    "last_prompt": record.last_prompt,
                }
                for session_id, record in self._sessions.items()
            }
        }
        payload_text = json.dumps(payload, indent=2)
        temp_fd, temp_path_str = tempfile.mkstemp(
            prefix=f"{self._file_path.name}.",
            suffix=".tmp",
            dir=str(self._file_path.parent),
            text=True,
        )
        temp_path = Path(temp_path_str)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as handle:
                handle.write(payload_text)
                handle.flush()
                os.fsync(handle.fileno())

            retry_delays = [0.0, 0.01, 0.02, 0.05, 0.1, 0.2]
            for attempt, delay in enumerate(retry_delays):
                if delay > 0:
                    time.sleep(delay)
                try:
                    os.replace(temp_path, self._file_path)
                    self._persist_dirty = False
                    return
                except (PermissionError, OSError) as exc:
                    is_last_attempt = attempt == len(retry_delays) - 1
                    if is_last_attempt or not self._is_transient_replace_error(exc):
                        raise
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _flush_persist_from_timer(self) -> None:
        with self._events_available:
            self._persist_timer = None
            if not self._persist_dirty:
                return
            try:
                self._persist_locked()
            except OSError:
                # Keep dirty flag so the next mutation retries persistence.
                self._persist_dirty = True

    def _schedule_persist_locked(self, *, force: bool = False) -> None:
        self._persist_dirty = True
        if force or self._persist_debounce_seconds == 0:
            if self._persist_timer is not None:
                self._persist_timer.cancel()
                self._persist_timer = None
            self._persist_locked()
            return

        if self._persist_timer is not None:
            return

        self._persist_timer = Timer(self._persist_debounce_seconds, self._flush_persist_from_timer)
        self._persist_timer.daemon = True
        self._persist_timer.start()

    def _get_session_locked(self, session_id: str) -> SessionRecord:
        if session_id not in self._sessions:
            raise KeyError(f"Unknown session: {session_id}")
        return self._sessions[session_id]

    def create_session(self, title: str | None = None) -> dict[str, Any]:
        with self._lock:
            now = utc_now_iso()
            session_id = uuid.uuid4().hex
            fallback_title = f"Session {len(self._sessions) + 1}"
            record = SessionRecord(
                session_id=session_id,
                title=title.strip() if title and title.strip() else fallback_title,
                created_at=now,
                updated_at=now,
            )
            self._sessions[session_id] = record
            self._schedule_persist_locked()
            return record.as_summary()

    def list_sessions(self) -> list[dict[str, Any]]:
        with self._lock:
            records = sorted(self._sessions.values(), key=lambda item: item.updated_at, reverse=True)
            return [record.as_summary() for record in records]

    def get_session(self, session_id: str, event_limit: int | None = None, before_seq: int | None = None) -> dict[str, Any]:
        with self._lock:
            record = self._get_session_locked(session_id)
            if event_limit is None:
                events = list(record.events)
                has_older_events = False
            else:
                events, has_older_events = self._slice_events(record.events, limit=event_limit, before_seq=before_seq)
            return {
                **record.as_summary(),
                "events": events,
                "has_older_events": has_older_events,
                "agent_state": dict(record.agent_state),
                "next_seq": record.next_seq,
            }

    def get_events(self, session_id: str, after_seq: int = 0, limit: int | None = None) -> list[dict[str, Any]]:
        with self._lock:
            record = self._get_session_locked(session_id)
            events = [event for event in record.events if int(event["seq"]) > after_seq]
            if limit is not None:
                return events[: max(1, limit)]
            return events

    def get_events_before(
        self,
        session_id: str,
        *,
        before_seq: int | None = None,
        limit: int = 200,
    ) -> tuple[list[dict[str, Any]], bool]:
        with self._lock:
            record = self._get_session_locked(session_id)
            return self._slice_events(record.events, limit=limit, before_seq=before_seq)

    def _slice_events(
        self,
        events: list[dict[str, Any]],
        *,
        limit: int,
        before_seq: int | None,
    ) -> tuple[list[dict[str, Any]], bool]:
        safe_limit = max(1, limit)
        end_index = len(events)
        if before_seq is not None:
            for index, event in enumerate(events):
                if int(event["seq"]) >= before_seq:
                    end_index = index
                    break

        start_index = max(0, end_index - safe_limit)
        has_older_events = start_index > 0
        return list(events[start_index:end_index]), has_older_events

    def wait_for_events(self, session_id: str, after_seq: int, timeout_seconds: float = 20.0) -> list[dict[str, Any]]:
        deadline = time.monotonic() + timeout_seconds
        with self._events_available:
            record = self._get_session_locked(session_id)
            while True:
                events = [event for event in record.events if int(event["seq"]) > after_seq]
                if events:
                    return events
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return []
                self._events_available.wait(timeout=remaining)

    def append_event(self, session_id: str, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._events_available:
            record = self._get_session_locked(session_id)
            event = {
                "seq": record.next_seq,
                "type": event_type,
                "timestamp": utc_now_iso(),
                "payload": to_json_compatible(payload or {}),
            }
            record.events.append(event)
            if len(record.events) > self._max_events_per_session:
                overflow = len(record.events) - self._max_events_per_session
                del record.events[:overflow]
            record.next_seq += 1
            record.updated_at = utc_now_iso()
            self._schedule_persist_locked()
            self._events_available.notify_all()
            return event

    def mark_run_started(self, session_id: str, prompt: str) -> None:
        with self._events_available:
            record = self._get_session_locked(session_id)
            record.run_count += 1
            record.is_running = True
            record.last_error = None
            record.last_prompt = prompt
            record.updated_at = utc_now_iso()
            self._schedule_persist_locked()
            self._events_available.notify_all()

    def mark_run_finished(self, session_id: str, *, error: str | None = None) -> None:
        with self._events_available:
            record = self._get_session_locked(session_id)
            record.is_running = False
            record.last_error = error
            record.updated_at = utc_now_iso()
            self._schedule_persist_locked()
            self._events_available.notify_all()

    def update_agent_state(self, session_id: str, state: dict[str, Any]) -> None:
        with self._events_available:
            record = self._get_session_locked(session_id)
            record.agent_state = to_json_compatible(state) if isinstance(state, dict) else {}
            record.updated_at = utc_now_iso()
            self._schedule_persist_locked()
            self._events_available.notify_all()

    def get_agent_state(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._get_session_locked(session_id)
            return dict(record.agent_state)

    def close(self) -> None:
        with self._events_available:
            if self._persist_timer is not None:
                self._persist_timer.cancel()
                self._persist_timer = None
            if self._persist_dirty:
                self._persist_locked()
