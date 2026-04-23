#!/usr/bin/env python3
"""
One-off: rewrite fixture lead emails in SQLite for local reply-thread testing.

Reads LOCAL_DB_PATH from environment (same as the app). Loads .env from the
repository root if present.

Usage (from sda_platform, where sda_local.db usually lives):
  uv run python scripts/update_lead_email_once.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

# Rows matching any of these are rewritten to NEW_EMAIL (local reply-thread testing).
OLD_EMAILS = (
    "marshall.syahrial@commonsecuritization.com",
    "shamali.kather@73strings.com",
)
NEW_EMAIL = "naheemquadri3410@gmail.com"


def _load_env() -> None:
    here = Path(__file__).resolve()
    for candidate in (
        here.parents[2] / ".env",  # agents/.env when script is at sda_platform/scripts/
        here.parents[1] / ".env",  # sda_platform/.env
        Path.cwd() / ".env",
    ):
        if candidate.is_file():
            load_dotenv(candidate, override=False)
            break
    load_dotenv(override=False)


def main() -> int:
    _load_env()
    raw = os.getenv("LOCAL_DB_PATH", "./sda_local.db")
    db_path = Path(raw).expanduser()
    if not db_path.is_absolute():
        db_path = (Path.cwd() / db_path).resolve()

    now = datetime.now(timezone.utc).isoformat()

    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        total = 0
        for old in OLD_EMAILS:
            cur.execute(
                "UPDATE leads SET email = ?, updated_at = ? WHERE email = ? COLLATE NOCASE",
                (NEW_EMAIL, now, old),
            )
            n = cur.rowcount
            total += n
            if n:
                print(f"Updated {n} row(s): {old!r} -> {NEW_EMAIL}")

        conn.commit()
        if total == 0:
            print(f"No matching leads ({OLD_EMAILS}) in {db_path}", file=sys.stderr)
            return 1
        print(f"Database: {db_path}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
