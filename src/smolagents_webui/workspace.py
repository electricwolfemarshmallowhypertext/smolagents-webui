from __future__ import annotations

import heapq
import time
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class WorkspaceBrowser:
    """Workspace tree browser with path traversal protection."""

    def __init__(self, workspace_root: Path, max_entries_per_directory: int = 250):
        self.workspace_root = workspace_root.resolve()
        self.max_entries_per_directory = max_entries_per_directory
        self._ignored_dir_names = {
            ".git",
            ".manual-smoke-data",
            ".runtime-smoke-data",
            ".smolagents-webui",
        }
        self._cache_ttl_seconds = 2.0
        self._cache: dict[tuple[Any, ...], tuple[float, Any]] = {}

    def _should_skip(self, path: Path) -> bool:
        return (
            path.name in self._ignored_dir_names
            or path.name.startswith(".shutdown-smoke-data")
            or path.name.startswith("smolui-smoke-")
        )

    def _get_cached(self, key: tuple[Any, ...]) -> Any | None:
        cached = self._cache.get(key)
        if cached is None:
            return None
        cached_at, value = cached
        if time.monotonic() - cached_at > self._cache_ttl_seconds:
            self._cache.pop(key, None)
            return None
        return deepcopy(value)

    def _set_cached(self, key: tuple[Any, ...], value: Any) -> None:
        self._cache[key] = (time.monotonic(), deepcopy(value))

    def _resolve_workspace_path(self, relative_path: str) -> Path:
        clean_relative = relative_path.strip().lstrip("/\\")
        target = (self.workspace_root / clean_relative).resolve()
        if target != self.workspace_root and self.workspace_root not in target.parents:
            raise ValueError("Requested path escapes the workspace root.")
        return target

    def _relative(self, path: Path) -> str:
        if path == self.workspace_root:
            return ""
        return str(path.relative_to(self.workspace_root)).replace("\\", "/")

    def _build_node(self, path: Path, depth: int) -> dict[str, Any]:
        try:
            path_is_dir = path.is_dir()
            path_is_file = path.is_file()
            path_stat = path.stat()
        except OSError as exc:
            return {
                "name": path.name if path != self.workspace_root else self.workspace_root.name,
                "path": self._relative(path),
                "kind": "unknown",
                "size": None,
                "modified_at": None,
                "error": f"Unable to read workspace path: {exc.__class__.__name__}",
            }

        path_type = "directory" if path_is_dir else "file"
        node: dict[str, Any] = {
            "name": path.name if path != self.workspace_root else self.workspace_root.name,
            "path": self._relative(path),
            "kind": path_type,
            "size": path_stat.st_size if path_is_file else None,
            "modified_at": datetime.fromtimestamp(path_stat.st_mtime, tz=timezone.utc).isoformat(),
        }

        if path_is_dir and depth > 0:
            children: list[dict[str, Any]] = []
            try:
                entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
            except OSError as exc:
                node["children"] = children
                node["truncated"] = False
                node["error"] = f"Unable to read directory: {exc.__class__.__name__}"
                return node
            for child in entries:
                if self._should_skip(child):
                    continue
                if len(children) >= self.max_entries_per_directory:
                    break
                children.append(self._build_node(child, depth - 1))
            node["children"] = children
            node["truncated"] = len(entries) > len(children)

        return node

    def list_tree(self, relative_path: str = "", depth: int = 2) -> dict[str, Any]:
        cache_key = ("tree", relative_path, depth)
        cached_tree = self._get_cached(cache_key)
        if cached_tree is not None:
            return cached_tree

        target = self._resolve_workspace_path(relative_path)
        if not target.exists():
            raise FileNotFoundError(f"Path does not exist: {relative_path}")
        tree = self._build_node(target, depth=max(0, depth))
        self._set_cached(cache_key, tree)
        return tree

    def list_recent_files(self, limit: int = 20, scan_limit: int = 5000) -> list[dict[str, Any]]:
        safe_limit = max(1, limit)
        cache_key = ("recent", safe_limit, scan_limit)
        cached = self._get_cached(cache_key)
        if cached is not None:
            return cached

        stack = [self.workspace_root]
        scanned = 0
        top_files: list[tuple[float, Path, int]] = []
        early_cutoff = min(scan_limit, max(1000, safe_limit * 200))

        while stack and scanned < scan_limit:
            current = stack.pop()
            try:
                entries = list(current.iterdir())
            except OSError:
                continue

            for entry in entries:
                if self._should_skip(entry):
                    continue
                scanned += 1
                if scanned > scan_limit:
                    break
                if entry.is_dir():
                    stack.append(entry)
                elif entry.is_file():
                    try:
                        stat = entry.stat()
                    except OSError:
                        continue
                    row = (stat.st_mtime, entry, stat.st_size)
                    if len(top_files) < safe_limit:
                        heapq.heappush(top_files, row)
                    elif row[0] > top_files[0][0]:
                        heapq.heapreplace(top_files, row)

                if scanned >= early_cutoff and len(top_files) >= safe_limit:
                    break
            if scanned >= early_cutoff and len(top_files) >= safe_limit:
                break

        ranked = sorted(top_files, key=lambda item: item[0], reverse=True)
        results = [
            {
                "path": self._relative(path),
                "name": path.name,
                "modified_at": datetime.fromtimestamp(modified, tz=timezone.utc).isoformat(),
                "size": size,
            }
            for modified, path, size in ranked
        ]
        self._set_cached(cache_key, results)
        return results
