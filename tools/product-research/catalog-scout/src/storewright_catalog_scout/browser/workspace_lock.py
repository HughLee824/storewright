from __future__ import annotations

from pathlib import Path

from filelock import FileLock, Timeout


class WorkspaceBusyError(RuntimeError):
    """Another browser-mutating Catalog Scout command owns the workspace."""


def acquire_workspace_lock(path: Path) -> FileLock:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path))
    try:
        lock.acquire(timeout=0)
    except Timeout as error:
        raise WorkspaceBusyError(
            "WORKSPACE_BUSY: another run, resume, or browser login is already active"
        ) from error
    return lock
