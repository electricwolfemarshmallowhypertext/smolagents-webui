from pathlib import Path
import shutil
import sys
import uuid

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"
if str(SRC_ROOT) in sys.path:
    sys.path.remove(str(SRC_ROOT))
sys.path.insert(0, str(SRC_ROOT))

from smolagents_webui.workspace import WorkspaceBrowser


def test_workspace_tree_lists_existing_repo():
    browser = WorkspaceBrowser(Path.cwd())
    tree = browser.list_tree(depth=1)

    assert tree["kind"] == "directory"
    assert isinstance(tree.get("children", []), list)
    assert len(tree["children"]) > 0


def test_workspace_tree_blocks_path_escape():
    browser = WorkspaceBrowser(Path.cwd())
    with pytest.raises(ValueError):
        browser.list_tree(relative_path="../", depth=1)


def test_workspace_recent_files_returns_items():
    browser = WorkspaceBrowser(Path.cwd())
    files = browser.list_recent_files(limit=5, scan_limit=2000)
    assert isinstance(files, list)
    assert len(files) > 0
    assert "path" in files[0]
    assert "modified_at" in files[0]


def test_workspace_hides_runtime_and_smoke_directories():
    workspace_root = Path.cwd() / f"workspace-ignore-test-{uuid.uuid4().hex}"
    workspace_root.mkdir()
    ignored_names = [
        ".smolagents-webui",
        ".manual-smoke-data",
        ".runtime-smoke-data",
        ".shutdown-smoke-data2",
        "smolui-smoke-abcd",
    ]
    try:
        for name in ignored_names:
            folder = workspace_root / name
            folder.mkdir()
            (folder / "sessions.json").write_text("{}", encoding="utf-8")

        (workspace_root / "real-file.txt").write_text("real", encoding="utf-8")

        browser = WorkspaceBrowser(workspace_root)
        tree = browser.list_tree(depth=1)
        child_names = {child["name"] for child in tree.get("children", [])}
        recent_paths = {file["path"] for file in browser.list_recent_files(limit=20)}

        assert child_names == {"real-file.txt"}
        assert recent_paths == {"real-file.txt"}
    finally:
        if workspace_root.exists():
            shutil.rmtree(workspace_root)


def test_workspace_tree_handles_unreadable_directories(monkeypatch):
    workspace_root = Path.cwd() / f"workspace-unreadable-test-{uuid.uuid4().hex}"
    workspace_root.mkdir()
    original_iterdir = Path.iterdir

    def guarded_iterdir(path):
        if path == workspace_root:
            raise PermissionError("blocked by test")
        return original_iterdir(path)

    try:
        monkeypatch.setattr(Path, "iterdir", guarded_iterdir)

        browser = WorkspaceBrowser(workspace_root)
        tree = browser.list_tree(depth=1)

        assert tree["kind"] == "directory"
        assert tree["children"] == []
        assert tree["truncated"] is False
        assert tree["error"] == "Unable to read directory: PermissionError"
    finally:
        if workspace_root.exists():
            shutil.rmtree(workspace_root)

