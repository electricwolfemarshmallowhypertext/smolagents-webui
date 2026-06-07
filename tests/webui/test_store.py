from pathlib import Path
import json
import sys
import uuid

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from smolagents_webui.store import SessionStore


def make_store_without_disk_writes() -> SessionStore:
    store = SessionStore(Path("unused-sessions.json"))
    store._persist_locked = lambda: None  # type: ignore[method-assign]
    return store


def test_store_tracks_session_events_and_state():
    store = make_store_without_disk_writes()

    session = store.create_session("Demo Session")
    session_id = session["id"]

    first = store.append_event(session_id, "run_started", {"prompt": "hello"})
    second = store.append_event(session_id, "assistant_delta", {"text": "hi"})

    assert first["seq"] == 1
    assert second["seq"] == 2

    store.mark_run_started(session_id, "hello")
    store.update_agent_state(session_id, {"answer": 42})
    store.mark_run_finished(session_id)

    loaded = store.get_session(session_id)
    assert loaded["title"] == "Demo Session"
    assert loaded["run_count"] == 1
    assert loaded["events"][-1]["seq"] == 2
    assert loaded["agent_state"]["answer"] == 42
    assert loaded["is_running"] is False


def test_wait_for_events_returns_incremental_slice():
    store = make_store_without_disk_writes()
    session_id = store.create_session()["id"]

    store.append_event(session_id, "evt", {"n": 1})
    store.append_event(session_id, "evt", {"n": 2})

    events = store.wait_for_events(session_id, after_seq=1, timeout_seconds=0.01)
    assert len(events) == 1
    assert events[0]["payload"]["n"] == 2


def test_store_ignores_corrupt_persistence_file():
    file_path = Path.cwd() / f"corrupt-sessions-{uuid.uuid4().hex}.json"
    file_path.write_text("{this-is-not-json", encoding="utf-8")
    try:
        store = SessionStore(file_path)
        assert store.list_sessions() == []
    finally:
        if file_path.exists():
            file_path.unlink()


def test_store_caps_event_history_per_session():
    file_path = Path.cwd() / f"sessions-cap-{uuid.uuid4().hex}.json"
    max_events = 200
    store = SessionStore(file_path=file_path, max_events_per_session=max_events, persist_debounce_seconds=0)
    try:
        session_id = store.create_session("Cap Test")["id"]

        for idx in range(max_events + 5):
            store.append_event(session_id, "evt", {"n": idx})

        loaded = store.get_session(session_id)
        seqs = [event["seq"] for event in loaded["events"]]
        assert len(seqs) == max_events
        assert seqs[0] == 6
        assert seqs[-1] == max_events + 5
        assert loaded["next_seq"] == max_events + 6
    finally:
        store.close()
        if file_path.exists():
            file_path.unlink()


def test_store_event_pagination_and_close_flush():
    file_path = Path.cwd() / f"sessions-pagination-{uuid.uuid4().hex}.json"
    store = SessionStore(file_path=file_path, persist_debounce_seconds=60)
    try:
        session_id = store.create_session("Pagination Test")["id"]

        for idx in range(10):
            store.append_event(session_id, "evt", {"n": idx})

        latest_slice = store.get_session(session_id, event_limit=4)
        assert [event["seq"] for event in latest_slice["events"]] == [7, 8, 9, 10]
        assert latest_slice["has_older_events"] is True

        older_slice = store.get_session(session_id, event_limit=4, before_seq=7)
        assert [event["seq"] for event in older_slice["events"]] == [3, 4, 5, 6]
        assert older_slice["has_older_events"] is True

        head_slice, has_older = store.get_events_before(session_id, before_seq=3, limit=5)
        assert [event["seq"] for event in head_slice] == [1, 2]
        assert has_older is False

        assert file_path.exists() is False
        store.close()
        assert file_path.exists() is True
    finally:
        if file_path.exists():
            file_path.unlink()


def test_store_redacts_api_key_from_run_started_payload_and_persistence():
    file_path = Path.cwd() / f"sessions-redaction-{uuid.uuid4().hex}.json"
    secret_value = "live-api-key-value"
    store = SessionStore(file_path=file_path, persist_debounce_seconds=0)
    try:
        session_id = store.create_session("Redaction Test")["id"]

        event = store.append_event(
            session_id,
            "run_started",
            {
                "prompt": "hello",
                "config": {
                    "provider": "openai",
                    "api_key": secret_value,
                    "model_id": "gpt-4o-mini",
                },
            },
        )

        assert event["payload"]["config"]["api_key"] == "[redacted]"
        assert secret_value not in json.dumps(store.get_session(session_id))

        store.close()
        persisted = file_path.read_text(encoding="utf-8")
        assert secret_value not in persisted
        assert '"api_key": "[redacted]"' in persisted
    finally:
        store.close()
        if file_path.exists():
            file_path.unlink()


def test_store_recursively_redacts_token_and_authorization_like_fields():
    store = make_store_without_disk_writes()
    session_id = store.create_session("Nested Redaction Test")["id"]

    event = store.append_event(
        session_id,
        "details",
        {
            "nested": {
                "Token": "nested-token-value",
                "headers": {
                    "Authorization": "Bearer abc",
                    "x_bearer_hint": "bearer-value",
                },
                "items": [{"client_secret": "client-secret-value"}],
            },
            "safe": "visible",
        },
    )

    payload = event["payload"]
    assert payload["nested"]["Token"] == "[redacted]"
    assert payload["nested"]["headers"]["Authorization"] == "[redacted]"
    assert payload["nested"]["headers"]["x_bearer_hint"] == "[redacted]"
    assert payload["nested"]["items"][0]["client_secret"] == "[redacted]"
    assert payload["safe"] == "visible"
    assert "nested-token-value" not in json.dumps(payload)
    assert "Bearer abc" not in json.dumps(payload)


def test_store_redacts_secret_values_loaded_from_existing_persistence():
    file_path = Path.cwd() / f"sessions-legacy-redaction-{uuid.uuid4().hex}.json"
    secret_value = "legacy-api-key-value"
    legacy_payload = {
        "sessions": {
            "abc": {
                "title": "Legacy",
                "created_at": "2026-01-01T00:00:00+00:00",
                "updated_at": "2026-01-01T00:00:00+00:00",
                "run_count": 1,
                "is_running": False,
                "events": [
                    {
                        "seq": 1,
                        "type": "run_started",
                        "timestamp": "2026-01-01T00:00:00+00:00",
                        "payload": {"config": {"api_key": secret_value}},
                    }
                ],
                "next_seq": 2,
                "agent_state": {"access_token": secret_value},
                "last_error": None,
                "last_prompt": "hello",
            }
        }
    }
    file_path.write_text(json.dumps(legacy_payload), encoding="utf-8")
    try:
        store = SessionStore(file_path=file_path, persist_debounce_seconds=0)
        loaded = store.get_session("abc")

        assert loaded["events"][0]["payload"]["config"]["api_key"] == "[redacted]"
        assert loaded["agent_state"]["access_token"] == "[redacted]"
        assert secret_value not in json.dumps(loaded)
    finally:
        store.close()
        if file_path.exists():
            file_path.unlink()
