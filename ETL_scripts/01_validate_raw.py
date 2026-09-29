"""Step 01: verify every raw CSV exists and its header matches the target schema."""
import csv
import sys

import duckdb

from config import RAW_DIR, SQL_DIR, TABLES, get_logger

log = get_logger("01_validate_raw")


def expected_columns() -> dict[str, list[str]]:
    """Build the schema in memory and return {table: [column, ...]}."""
    con = duckdb.connect()
    con.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    cols = {}
    for table, _ in TABLES:
        cols[table] = [r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()]
    con.close()
    return cols


def main() -> int:
    schema_cols = expected_columns()
    errors = 0
    for table, filename in TABLES:
        path = RAW_DIR / filename
        if not path.exists():
            log.error("Missing raw file: %s", path)
            errors += 1
            continue
        # utf-8-sig strips the BOM present in the translation file
        with open(path, encoding="utf-8-sig", newline="") as f:
            header = next(csv.reader(f))
        if header != schema_cols[table]:
            log.error("Header mismatch in %s\n  csv:    %s\n  schema: %s",
                      filename, header, schema_cols[table])
            errors += 1
            continue
        size_mb = path.stat().st_size / 1024 / 1024
        log.info("OK %-40s -> %-35s (%.1f MB)", filename, table, size_mb)

    if errors:
        log.error("Raw validation failed with %d error(s)", errors)
        return 1
    log.info("All %d raw files validated", len(TABLES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
