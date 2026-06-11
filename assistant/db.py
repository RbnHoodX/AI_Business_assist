"""SQLite access: schema introspection + guarded read-only query execution."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from . import config

# A compact, human-readable schema description handed to the model for both
# routing and text-to-SQL. Kept in sync with data/build_database.py.
SCHEMA_DESCRIPTION = """\
Tables (SQLite):

customers(id TEXT PK, name TEXT, country TEXT, account_owner TEXT)

contracts(id TEXT PK, customer_id TEXT -> customers.id, title TEXT,
          status TEXT [active|expired|draft], start_date TEXT 'YYYY-MM-DD',
          end_date TEXT 'YYYY-MM-DD', annual_value INTEGER (USD),
          document_file TEXT -- linked PDF, e.g. 'contract_C001.pdf')

payments(id TEXT PK, customer_id TEXT -> customers.id,
         contract_id TEXT -> contracts.id, amount INTEGER (USD),
         due_date TEXT 'YYYY-MM-DD', paid_date TEXT NULL,
         status TEXT [paid|overdue|scheduled])

projects(id TEXT PK, customer_id TEXT -> customers.id, name TEXT,
         status TEXT [active|completed|on_hold], start_date TEXT 'YYYY-MM-DD',
         document_file TEXT -- linked PDF, e.g. 'project_P001.pdf')

Notes:
- Dates are ISO strings; compare with date('YYYY-MM-DD') or julianday().
- Treat the current date as the literal '{reference_date}'.
- 'overdue payments' => payments.status = 'overdue'.
- contracts.document_file / projects.document_file link a row to its PDF, which
  is how structured rows are matched to document text.
""".format(reference_date=config.REFERENCE_DATE)

_WRITE = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|pragma|"
    r"vacuum|reindex|truncate)\b",
    re.IGNORECASE,
)


def is_safe_select(sql: str) -> tuple[bool, str]:
    """Allow a single read-only SELECT/CTE statement only."""
    stripped = sql.strip().rstrip(";").strip()
    if not stripped:
        return False, "empty query"
    if ";" in stripped:
        return False, "multiple statements are not allowed"
    if _WRITE.search(stripped):
        return False, "only read-only SELECT queries are allowed"
    if not re.match(r"^(select|with)\b", stripped, re.IGNORECASE):
        return False, "query must start with SELECT or WITH"
    return True, ""


def run_select(sql: str) -> list[dict[str, Any]]:
    """Execute a validated SELECT against a read-only connection."""
    ok, reason = is_safe_select(sql)
    if not ok:
        raise ValueError(f"Unsafe SQL rejected: {reason}")
    # Open read-only so even a hypothetical bypass cannot mutate data.
    uri = f"file:{config.DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.row_factory = sqlite3.Row
        limited = sql.strip().rstrip(";")
        if not re.search(r"\blimit\b", limited, re.IGNORECASE):
            limited = f"{limited}\nLIMIT {config.SQL_ROW_LIMIT}"
        cur = conn.execute(limited)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
