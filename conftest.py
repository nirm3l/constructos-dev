from __future__ import annotations

import sys
from pathlib import Path


# Tests import modules like `main` / `features.*` which live under `app/`.
# When running pytest from repo root, ensure `app/` is on sys.path.
_ROOT = Path(__file__).resolve().parent
_APP_DIR = _ROOT / "app"
if _APP_DIR.is_dir():
    sys.path.insert(0, str(_APP_DIR))

