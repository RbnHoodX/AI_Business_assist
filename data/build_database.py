"""Build a sanitized sample SQLite business database.

All data is fictional. Dates are chosen relative to the pinned reference date
(2026-06-10) so the example questions return meaningful rows.

Run:  python -m data.build_database
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assistant.config import DB_PATH  # noqa: E402

SCHEMA = """
DROP TABLE IF EXISTS payments;
DROP TABLE IF EXISTS contracts;
DROP TABLE IF EXISTS projects;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    country       TEXT,
    account_owner TEXT
);

CREATE TABLE contracts (
    id            TEXT PRIMARY KEY,
    customer_id   TEXT NOT NULL REFERENCES customers(id),
    title         TEXT NOT NULL,
    status        TEXT NOT NULL,             -- active | expired | draft
    start_date    TEXT NOT NULL,             -- ISO YYYY-MM-DD
    end_date      TEXT NOT NULL,
    annual_value  INTEGER,                   -- in USD
    document_file TEXT                       -- linked PDF in data/pdfs/
);

CREATE TABLE payments (
    id            TEXT PRIMARY KEY,
    customer_id   TEXT NOT NULL REFERENCES customers(id),
    contract_id   TEXT REFERENCES contracts(id),
    amount        INTEGER NOT NULL,          -- in USD
    due_date      TEXT NOT NULL,
    paid_date     TEXT,                      -- NULL if unpaid
    status        TEXT NOT NULL              -- paid | overdue | scheduled
);

CREATE TABLE projects (
    id            TEXT PRIMARY KEY,
    customer_id   TEXT NOT NULL REFERENCES customers(id),
    name          TEXT NOT NULL,
    status        TEXT NOT NULL,             -- active | completed | on_hold
    start_date    TEXT NOT NULL,
    document_file TEXT
);
"""

CUSTOMERS = [
    ("CUST001", "Riverstone Manufacturing", "USA", "Dana Levi"),
    ("CUST002", "Cobalt Software", "UK", "Dana Levi"),
    ("CUST003", "Greenfield Logistics", "USA", "Omer Cohen"),
    ("CUST004", "Halcyon Media", "Germany", "Omer Cohen"),
    ("CUST005", "Meridian Retail", "USA", "Dana Levi"),
    ("CUST006", "Galil Technologies / טכנולוגיות גליל", "Israel", "Noa Bar"),
]

# Reference "today" = 2026-06-10. "Next 90 days" window ends 2026-09-08.
CONTRACTS = [
    # id,      customer,   title,                              status,   start,        end,          value,   pdf
    ("C001", "CUST001", "Riverstone Master Services Agreement", "active", "2024-07-16", "2026-07-15", 240000, "contract_C001.pdf"),
    ("C002", "CUST002", "Cobalt SaaS Subscription",            "active", "2025-02-21", "2026-08-20", 120000, "contract_C002.pdf"),
    ("C003", "CUST003", "Greenfield Support & Maintenance",    "active", "2025-12-02", "2026-12-01",  60000, "contract_C003.pdf"),
    ("C004", "CUST004", "Halcyon Data Processing Agreement",   "active", "2024-07-01", "2026-06-30",  90000, "contract_C004.pdf"),
    ("C005", "CUST005", "Meridian Software License",           "active", "2025-03-02", "2027-03-01", 300000, "contract_C005.pdf"),
    ("C006", "CUST006", "Galil Cyber Services / שירותי סייבר", "active", "2024-08-06", "2026-08-05", 150000, "contract_C006.pdf"),
]

# overdue = due_date before 2026-06-10 and not paid.
PAYMENTS = [
    ("PAY001", "CUST001", "C001", 20000, "2026-05-01", None,         "overdue"),
    ("PAY002", "CUST002", "C002", 10000, "2026-04-15", "2026-04-14", "paid"),
    ("PAY003", "CUST003", "C003",  5000, "2026-05-20", None,         "overdue"),
    ("PAY004", "CUST004", "C004",  7500, "2026-07-01", None,         "scheduled"),
    ("PAY005", "CUST005", "C005", 25000, "2026-03-10", None,         "overdue"),
    ("PAY006", "CUST006", "C006", 12500, "2026-05-05", None,         "overdue"),
    ("PAY007", "CUST001", "C001", 20000, "2026-02-01", "2026-02-03", "paid"),
]

PROJECTS = [
    ("P001", "CUST001", "Riverstone Cloud Migration",     "active",    "2026-01-10", "project_P001.pdf"),
    ("P002", "CUST002", "Cobalt ERP Rollout",             "active",    "2025-11-01", "project_P002.pdf"),
    ("P003", "CUST003", "Greenfield Data Lake",           "completed", "2025-03-01", "project_P003.pdf"),
    ("P004", "CUST006", "Galil Cyber Defense / הגנת סייבר", "active",   "2026-02-15", "project_P004.pdf"),
]


def build() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA)
        conn.executemany("INSERT INTO customers VALUES (?,?,?,?)", CUSTOMERS)
        conn.executemany("INSERT INTO contracts VALUES (?,?,?,?,?,?,?,?)", CONTRACTS)
        conn.executemany("INSERT INTO payments VALUES (?,?,?,?,?,?,?)", PAYMENTS)
        conn.executemany("INSERT INTO projects VALUES (?,?,?,?,?,?)", PROJECTS)
        conn.commit()
    finally:
        conn.close()
    print(f"Built database at {DB_PATH}")
    print(f"  customers={len(CUSTOMERS)} contracts={len(CONTRACTS)} "
          f"payments={len(PAYMENTS)} projects={len(PROJECTS)}")


if __name__ == "__main__":
    build()
