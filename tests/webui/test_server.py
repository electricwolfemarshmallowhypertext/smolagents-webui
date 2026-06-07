from pathlib import Path
import http.client
import json
import sys
import threading


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) in sys.path:
    sys.path.remove(str(SRC_ROOT))
sys.path.insert(0, str(SRC_ROOT))

from smolagents_webui.server import SmolagentsWebUIServer, WebUIState, default_data_dir
from smolagents_webui.store import SessionStore
from smolagents_webui.workspace import WorkspaceBrowser


class HoldingRunner:
    def __init__(self, store: SessionStore):
        self.store = store

    def start_run(self, session_id, prompt, config):
        run_id = self.store.try_start_run(session_id, prompt, config)
        self.store.append_event(session_id, "run_started", {"run_id": run_id, "prompt": prompt, "config": config})


def serve_test_app(store: SessionStore, runner=None):
    state = WebUIState(
        store=store,
        runner=runner or HoldingRunner(store),
        workspace=WorkspaceBrowser(Path.cwd()),
        static_root=Path.cwd() / "src" / "smolagents_webui" / "static",
    )
    server = SmolagentsWebUIServer(("127.0.0.1", 0), state)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def request_json(port: int, method: str, path: str, body: dict | None = None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        payload = json.dumps(body or {}).encode("utf-8")
        headers = {"Content-Type": "application/json", "Content-Length": str(len(payload))}
        connection.request(method, path, body=payload if method != "GET" else None, headers=headers if method != "GET" else {})
        response = connection.getresponse()
        response_body = response.read().decode("utf-8")
        return response.status, json.loads(response_body) if response_body else {}
    finally:
        connection.close()


def test_default_data_dir_is_not_workspace_runtime_dir():
    data_dir = default_data_dir().resolve()
    workspace_runtime_dir = (Path.cwd() / ".smolagents-webui").resolve()

    assert data_dir.name == "smolagents-webui"
    assert data_dir != workspace_runtime_dir


def test_server_handles_windows_client_abort_without_traceback():
    assert "ConnectionAbortedError" in SmolagentsWebUIServer.handle_error.__code__.co_names


def test_concurrent_run_posts_allow_one_start_and_one_conflict():
    store = SessionStore(Path("unused-server-sessions.json"))
    store._persist_locked = lambda: None  # type: ignore[method-assign]
    session_id = store.create_session("Concurrent")["id"]
    server, thread = serve_test_app(store)
    statuses: list[int] = []
    barrier = threading.Barrier(2)
    lock = threading.Lock()

    def post_run() -> None:
        barrier.wait()
        status, _payload = request_json(
            server.server_port,
            "POST",
            f"/api/sessions/{session_id}/runs",
            {"prompt": "hello", "config": {"provider": "openai"}},
        )
        with lock:
            statuses.append(status)

    try:
        threads = [threading.Thread(target=post_run), threading.Thread(target=post_run)]
        for worker in threads:
            worker.start()
        for worker in threads:
            worker.join()

        assert sorted(statuses) == [202, 409]
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_sse_stream_replays_redacted_event_payloads():
    store = SessionStore(Path("unused-sse-sessions.json"))
    store._persist_locked = lambda: None  # type: ignore[method-assign]
    session_id = store.create_session("SSE")["id"]
    store.append_event(
        session_id,
        "run_started",
        {
            "config": {
                "api_key": "raw-api-key",
                "nested": {"Authorization": "Bearer raw-token"},
            }
        },
    )
    server, thread = serve_test_app(store)
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
    try:
        connection.request("GET", f"/api/sessions/{session_id}/stream?after=0")
        response = connection.getresponse()
        assert response.status == 200
        raw_lines = []
        for _ in range(20):
            line = response.fp.readline().decode("utf-8", errors="replace")
            raw_lines.append(line)
            if "[redacted]" in line:
                break
        raw_sse = "".join(raw_lines)
        assert "raw-api-key" not in raw_sse
        assert "Bearer raw-token" not in raw_sse
        assert "[redacted]" in raw_sse
    finally:
        connection.close()
        server.shutdown()
        thread.join(timeout=5)


def test_health_includes_storage_warning_for_corrupt_history():
    file_path = Path.cwd() / "server-corrupt-sessions.json"
    file_path.write_text("{broken", encoding="utf-8")
    store = SessionStore(file_path)
    store._persist_locked = lambda: None  # type: ignore[method-assign]
    server, thread = serve_test_app(store)
    try:
        status, payload = request_json(server.server_port, "GET", "/api/health")
        assert status == 200
        assert payload["storage_warning"] == "Session history was corrupt and was backed up."
    finally:
        server.shutdown()
        thread.join(timeout=5)
        if file_path.exists():
            file_path.unlink()
        for backup_path in Path.cwd().glob("server-corrupt-sessions.corrupt.*.json"):
            backup_path.unlink()

