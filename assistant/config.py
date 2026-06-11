"""Central configuration for the Business Knowledge Assistant POC."""
from __future__ import annotations

import os
from pathlib import Path

# --- Paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PDF_DIR = DATA_DIR / "pdfs"
DB_PATH = DATA_DIR / "business.db"


def _load_dotenv() -> None:
    """Minimal .env loader (KEY=VALUE per line); no external dependency.
    Does not overwrite variables already present in the environment."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()

# --- Model -------------------------------------------------------------------
# Opus 4.8 is the most capable model and handles both English and Hebrew well.
MODEL = os.environ.get("ASSISTANT_MODEL", "claude-opus-4-8")

# Adaptive thinking improves grounding quality but is incompatible with forcing
# a specific tool (which we rely on for guaranteed-structured output). Off by
# default for deterministic, demo-friendly behaviour. Set ASSISTANT_THINKING=1
# to let the synthesizer reason with adaptive thinking (auto tool choice).
USE_THINKING = os.environ.get("ASSISTANT_THINKING", "0") == "1"

# --- Reference "today" -------------------------------------------------------
# Pinned so that date-relative questions ("expiring in the next 90 days") return
# the same rows every run, independent of the wall clock. The text-to-SQL step
# is told to treat this as CURRENT_DATE.
REFERENCE_DATE = os.environ.get("ASSISTANT_REFERENCE_DATE", "2026-06-10")

# --- Retrieval ---------------------------------------------------------------
DOC_TOP_K = int(os.environ.get("ASSISTANT_DOC_TOP_K", "6"))
SQL_ROW_LIMIT = int(os.environ.get("ASSISTANT_SQL_ROW_LIMIT", "200"))
