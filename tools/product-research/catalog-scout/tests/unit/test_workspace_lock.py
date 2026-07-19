from pathlib import Path

import pytest

from storewright_catalog_scout.browser.workspace_lock import (
    WorkspaceBusyError,
    acquire_workspace_lock,
)


def test_workspace_lock_rejects_a_second_owner(tmp_path: Path) -> None:
    path = tmp_path / "catalog-scout.lock"
    first = acquire_workspace_lock(path)
    try:
        with pytest.raises(WorkspaceBusyError):
            acquire_workspace_lock(path)
    finally:
        first.release()

    second = acquire_workspace_lock(path)
    second.release()
