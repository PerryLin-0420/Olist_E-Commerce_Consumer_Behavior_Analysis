"""Step 02: create a fresh staging DuckDB file and load every raw CSV into it."""
import sys
import time

import duckdb

from config import DB_DIR, RAW_DIR, SQL_DIR, STAGING_DB_PATH, TABLES, get_logger

log = get_logger("02_load_raw")


def column_spec(con: duckdb.DuckDBPyConnection, table: str) -> str:
    """Return a read_csv columns struct literal matching the table's declared types."""
    rows = con.execute(f"DESCRIBE {table}").fetchall()
    return "{" + ", ".join(f"'{name}': '{dtype}'" for name, dtype, *_ in rows) + "}"


def main() -> int:
    DB_DIR.mkdir(exist_ok=True)
    STAGING_DB_PATH.unlink(missing_ok=True)

    con = duckdb.connect(str(STAGING_DB_PATH))
    try:
        con.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
        log.info("Schema created in %s", STAGING_DB_PATH)

        for table, filename in TABLES:
            start = time.perf_counter()
            path = (RAW_DIR / filename).as_posix()
            # Explicit column types; any unparsable value aborts the load
            con.execute(f"""
                INSERT INTO {table}
                SELECT * FROM read_csv(
                    '{path}',
                    header = true,
                    columns = {column_spec(con, table)},
                    timestampformat = '%Y-%m-%d %H:%M:%S'
                )
            """)
            rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            log.info("Loaded %-35s %9d rows (%.1fs)", table, rows, time.perf_counter() - start)

        con.execute("CHECKPOINT")
    except duckdb.Error as exc:
        log.error("Load failed: %s", exc)
        return 1
    finally:
        con.close()

    log.info("Raw load complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
