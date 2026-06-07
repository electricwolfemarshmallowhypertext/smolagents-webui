from pathlib import Path
import sys


SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from smolagents_webui.server import SmolagentsWebUIServer, default_data_dir


def test_default_data_dir_is_not_workspace_runtime_dir():
    data_dir = default_data_dir().resolve()
    workspace_runtime_dir = (Path.cwd() / ".smolagents-webui").resolve()

    assert data_dir.name == "smolagents-webui"
    assert data_dir != workspace_runtime_dir


def test_server_handles_windows_client_abort_without_traceback():
    assert "ConnectionAbortedError" in SmolagentsWebUIServer.handle_error.__code__.co_names
