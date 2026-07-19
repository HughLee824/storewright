#!/usr/bin/env python3
"""Compatibility entry point for the repository-level release tool."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
RELEASE_SCRIPT = REPO_ROOT / "scripts" / "release.py"


if __name__ == "__main__":
    raise SystemExit(
        subprocess.call([sys.executable, str(RELEASE_SCRIPT), "catalog-scout", *sys.argv[1:]])
    )
