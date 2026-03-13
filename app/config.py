# AI GC START
from __future__ import annotations

import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", BASE_DIR / "data")).resolve()
DB_PATH = Path(os.environ.get("APP_DB_PATH", DATA_DIR / "app.db")).resolve()
DEFAULT_LLM_TIMEOUT_SECONDS = float(os.environ.get("APP_LLM_TIMEOUT_SECONDS", "60"))

DATA_DIR.mkdir(parents=True, exist_ok=True)
# AI GC END
