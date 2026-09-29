"""Step 03: build derived tables (sql/derived.sql) inside the staging DB."""
import sys

import duckdb

from config import SQL_DIR, STAGING_DB_PATH, get_logger

log = get_logger("03_build_derived")


def main() -> int:
    if not STAGING_DB_PATH.exists():
        log.error("Staging DB not found: %s (run step 02 first)", STAGING_DB_PATH)
        return 1

    con = duckdb.connect(str(STAGING_DB_PATH))
    try:
        con.execute((SQL_DIR / "derived.sql").read_text(encoding="utf-8"))
        rows = con.execute("SELECT count(*) FROM geolocation_zip").fetchone()[0]
        log.info("Built geolocation_zip: %d zip prefixes", rows)
        con.execute("CHECKPOINT")
    except duckdb.Error as exc:
        log.error("Derived build failed: %s", exc)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
