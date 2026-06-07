from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from smolagents_webui.config import AgentRunConfig
from smolagents_webui.runner import AgentRunner
from smolagents_webui.store import AlreadyRunningError, SessionStore
from smolagents_webui.workspace import WorkspaceBrowser


@dataclass(slots=True)
class WebUIState:
    store: SessionStore
    runner: AgentRunner
    workspace: WorkspaceBrowser
    static_root: Path


class SmolagentsWebUIServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], state: WebUIState):
        super().__init__(server_address, SmolagentsWebUIHandler)
        self.state = state

    def handle_error(self, request: Any, client_address: tuple[str, int]) -> None:
        _, exc, _ = sys.exc_info()
        if isinstance(exc, ConnectionAbortedError):
            return
        super().handle_error(request, client_address)


class SmolagentsWebUIHandler(BaseHTTPRequestHandler):
    server_version = "SmolagentsWebUI/0.1"
    max_request_body_bytes = 1_000_000

    @property
    def app_state(self) -> WebUIState:
        return self.server.state  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        route = parsed.path

        if route == "/":
            self._serve_static_file("index.html")
            return

        if route.startswith("/static/"):
            relative_path = route.removeprefix("/static/")
            self._serve_static_file(relative_path)
            return

        if route == "/api/health":
            payload = {"status": "ok"}
            if self.app_state.store.storage_warning:
                payload["storage_warning"] = self.app_state.store.storage_warning
            self._send_json(HTTPStatus.OK, payload)
            return

        if route == "/api/sessions":
            self._send_json(HTTPStatus.OK, {"sessions": self.app_state.store.list_sessions()})
            return

        if route == "/api/workspace/tree":
            self._handle_workspace_tree(parsed.query)
            return

        if route == "/api/workspace/recent":
            self._handle_workspace_recent(parsed.query)
            return

        if match := re.fullmatch(r"/api/sessions/([a-f0-9]+)", route):
            self._handle_get_session(match.group(1), parsed.query)
            return

        if match := re.fullmatch(r"/api/sessions/([a-f0-9]+)/events", route):
            self._handle_get_events(match.group(1), parsed.query)
            return

        if match := re.fullmatch(r"/api/sessions/([a-f0-9]+)/stream", route):
            self._handle_stream(match.group(1), parsed.query)
            return

        if match := re.fullmatch(r"/api/sessions/([a-f0-9]+)/state", route):
            self._handle_get_state(match.group(1))
            return

        self._send_error_json(HTTPStatus.NOT_FOUND, "Route not found.")

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        route = parsed.path
        payload = self._read_json_body()
        if payload is None:
            return

        if route == "/api/sessions/clear":
            deleted_count = self.app_state.store.clear_sessions()
            self._send_json(HTTPStatus.OK, {"ok": True, "deleted_count": deleted_count})
            return

        if route == "/api/sessions":
            title = payload.get("title")
            session = self.app_state.store.create_session(title=str(title) if title is not None else None)
            self._send_json(HTTPStatus.CREATED, {"session": session})
            return

        if match := re.fullmatch(r"/api/runs/([a-f0-9]+)/cancel", route):
            self._handle_cancel_run(match.group(1))
            return

        if match := re.fullmatch(r"/api/sessions/([a-f0-9]+)/runs", route):
            self._handle_start_run(match.group(1), payload)
            return

        self._send_error_json(HTTPStatus.NOT_FOUND, "Route not found.")

    def do_DELETE(self) -> None:
        parsed = urlsplit(self.path)
        route = parsed.path

        if route == "/api/sessions":
            deleted_count = self.app_state.store.clear_sessions()
            self._send_json(HTTPStatus.OK, {"ok": True, "deleted_count": deleted_count})
            return

        if match := re.fullmatch(r"/api/sessions/([a-f0-9]+)", route):
            try:
                self.app_state.store.delete_session(match.group(1))
            except KeyError:
                self._send_error_json(HTTPStatus.NOT_FOUND, "Session not found.")
                return
            except AlreadyRunningError as exc:
                self._send_error_json(HTTPStatus.CONFLICT, str(exc))
                return
            self._send_json(HTTPStatus.OK, {"ok": True})
            return

        self._send_error_json(HTTPStatus.NOT_FOUND, "Route not found.")

    def _handle_workspace_tree(self, query: str) -> None:
        params = parse_qs(query)
        relative_path = params.get("path", [""])[0]
        depth_raw = params.get("depth", ["2"])[0]
        try:
            depth = max(0, min(5, int(depth_raw)))
        except ValueError:
            depth = 2
        try:
            tree = self.app_state.workspace.list_tree(relative_path=relative_path, depth=depth)
            self._send_json(HTTPStatus.OK, {"tree": tree})
        except FileNotFoundError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Workspace path not found.")
        except ValueError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    def _handle_workspace_recent(self, query: str) -> None:
        params = parse_qs(query)
        limit_raw = params.get("limit", ["20"])[0]
        try:
            limit = max(1, min(200, int(limit_raw)))
        except ValueError:
            limit = 20
        files = self.app_state.workspace.list_recent_files(limit=limit)
        self._send_json(HTTPStatus.OK, {"files": files})

    def _handle_get_session(self, session_id: str, query: str) -> None:
        params = parse_qs(query)
        event_limit_raw = params.get("event_limit", ["200"])[0]
        before_raw = params.get("before", [None])[0]
        try:
            event_limit = max(1, min(500, int(event_limit_raw)))
        except ValueError:
            event_limit = 200
        before_seq = None
        if before_raw is not None and before_raw != "":
            try:
                before_seq = int(before_raw)
            except ValueError:
                before_seq = None

        try:
            session = self.app_state.store.get_session(session_id, event_limit=event_limit, before_seq=before_seq)
        except KeyError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Session not found.")
            return
        self._send_json(HTTPStatus.OK, {"session": session})

    def _handle_get_events(self, session_id: str, query: str) -> None:
        params = parse_qs(query)
        after_raw = params.get("after", ["0"])[0]
        before_raw = params.get("before", [None])[0]
        limit_raw = params.get("limit", ["200"])[0]
        try:
            limit = max(1, min(500, int(limit_raw)))
        except ValueError:
            limit = 200

        if before_raw is not None and before_raw != "":
            try:
                before_seq = int(before_raw)
            except ValueError:
                before_seq = None
            if before_seq is None:
                self._send_error_json(HTTPStatus.BAD_REQUEST, "Invalid before parameter.")
                return
            try:
                events, has_older_events = self.app_state.store.get_events_before(
                    session_id,
                    before_seq=before_seq,
                    limit=limit,
                )
            except KeyError:
                self._send_error_json(HTTPStatus.NOT_FOUND, "Session not found.")
                return
            self._send_json(HTTPStatus.OK, {"events": events, "has_older_events": has_older_events})
            return

        try:
            after_seq = int(after_raw)
        except ValueError:
            after_seq = 0
        try:
            events = self.app_state.store.get_events(session_id, after_seq=after_seq, limit=limit)
        except KeyError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Session not found.")
            return
        self._send_json(HTTPStatus.OK, {"events": events})

    def _handle_get_state(self, session_id: str) -> None:
        try:
            state = self.app_state.store.get_agent_state(session_id)
        except KeyError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Session not found.")
            return
        self._send_json(HTTPStatus.OK, {"state": state})

    def _handle_start_run(self, session_id: str, payload: dict[str, Any]) -> None:
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Prompt is required.")
            return

        config = AgentRunConfig.from_payload(payload.get("config"))
        try:
            self.app_state.runner.start_run(session_id, prompt, config)
        except KeyError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Session not found.")
            return
        except AlreadyRunningError as exc:
            self._send_error_json(HTTPStatus.CONFLICT, str(exc))
            return

        self._send_json(HTTPStatus.ACCEPTED, {"ok": True})

    def _handle_cancel_run(self, run_id: str) -> None:
        try:
            session_id = self.app_state.store.request_run_cancel(run_id)
        except KeyError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Active run not found.")
            return
        self._send_json(HTTPStatus.ACCEPTED, {"ok": True, "session_id": session_id, "run_id": run_id})

    def _handle_stream(self, session_id: str, query: str) -> None:
        params = parse_qs(query)
        after_raw = params.get("after", ["0"])[0]
        try:
            after_seq = int(after_raw)
        except ValueError:
            after_seq = 0

        try:
            self.app_state.store.get_session(session_id)
        except KeyError:
            self._send_error_json(HTTPStatus.NOT_FOUND, "Session not found.")
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            cursor = after_seq
            while True:
                events = self.app_state.store.wait_for_events(session_id, after_seq=cursor, timeout_seconds=15.0)
                if not events:
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue

                for event in events:
                    data = json.dumps(event, ensure_ascii=False)
                    self.wfile.write(f"id: {event['seq']}\n".encode("utf-8"))
                    self.wfile.write(b"event: message\n")
                    for line in data.splitlines() or [""]:
                        self.wfile.write(f"data: {line}\n".encode("utf-8"))
                    self.wfile.write(b"\n")
                    self.wfile.flush()
                    cursor = int(event["seq"])
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _read_json_body(self) -> dict[str, Any] | None:
        content_length = self.headers.get("Content-Length")
        if content_length is None:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Missing Content-Length header.")
            return None
        try:
            body_size = int(content_length)
        except ValueError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Invalid Content-Length header.")
            return None
        if body_size > self.max_request_body_bytes:
            self._send_error_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Request body too large.")
            return None
        raw_body = self.rfile.read(body_size)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Request body must be valid JSON.")
            return None
        if not isinstance(payload, dict):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "JSON body must be an object.")
            return None
        return payload

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json(status, {"error": message})

    def _serve_static_file(self, relative_path: str) -> None:
        safe_relative = relative_path.strip().lstrip("/\\")
        target = (self.app_state.static_root / safe_relative).resolve()
        static_root = self.app_state.static_root.resolve()
        if target != static_root and static_root not in target.parents:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "Invalid static asset path.")
            return

        if not target.exists() or not target.is_file():
            self._send_error_json(HTTPStatus.NOT_FOUND, "Static asset not found.")
            return

        content_type, _ = mimetypes.guess_type(str(target))
        body = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        # Keep default server logging quiet for chat-style usage.
        return


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the smolagents standalone WebUI.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind the WebUI server.")
    parser.add_argument("--port", type=int, default=7865, help="Port to bind the WebUI server.")
    parser.add_argument(
        "--workspace-root",
        default=".",
        help="Workspace root shown in the file browser and used for path sandboxing.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Directory used to persist sessions (defaults to the user app data directory).",
    )
    return parser.parse_args()


def default_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "smolagents-webui"

    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "smolagents-webui"


def main() -> None:
    args = parse_args()
    workspace_root = Path(args.workspace_root).resolve()
    data_dir = Path(args.data_dir).resolve() if args.data_dir else default_data_dir()

    store = SessionStore(file_path=data_dir / "sessions.json")
    runner = AgentRunner(store=store)
    workspace = WorkspaceBrowser(workspace_root=workspace_root)
    static_root = Path(__file__).resolve().parent / "static"

    server = SmolagentsWebUIServer(
        (args.host, args.port),
        state=WebUIState(
            store=store,
            runner=runner,
            workspace=workspace,
            static_root=static_root,
        ),
    )
    print(f"smolagents WebUI running on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nsmolagents WebUI stopped.")
    finally:
        server.server_close()
        store.close()


if __name__ == "__main__":
    main()
