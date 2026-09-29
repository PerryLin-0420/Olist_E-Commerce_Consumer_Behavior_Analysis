"""Step 04: data quality checks on the staging DB.

PK / FK / NOT NULL constraints are already enforced by DuckDB during step 02.
This step reconciles the load against the source files (hard checks, fail the
pipeline) and reports known data issues (soft checks, logged only).
"""
import sys

import duckdb

from config import RAW_DIR, STAGING_DB_PATH, TABLES, get_logger

log = get_logger("04_quality_check")

# (table, column) holding money values loaded as DECIMAL(12, 2)
MONEY_COLUMNS = [
    ("order_items", "price"),
    ("order_items", "freight_value"),
    ("order_payments", "payment_value"),
]

# Known issues worth tracking: (description, query returning a single count)
SOFT_CHECKS = [
    ("products whose category has no English translation",
     """SELECT count(*) FROM products p
        WHERE p.product_category_name IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM product_category_name_translation t
                          WHERE t.product_category_name = p.product_category_name)"""),
    ("products with NULL category",
     "SELECT count(*) FROM products WHERE product_category_name IS NULL"),
    ("customer zip prefixes missing from geolocation_zip",
     """SELECT count(DISTINCT customer_zip_code_prefix) FROM customers c
        WHERE NOT EXISTS (SELECT 1 FROM geolocation_zip g
                          WHERE g.geolocation_zip_code_prefix = c.customer_zip_code_prefix)"""),
    ("seller zip prefixes missing from geolocation_zip",
     """SELECT count(DISTINCT seller_zip_code_prefix) FROM sellers s
        WHERE NOT EXISTS (SELECT 1 FROM geolocation_zip g
                          WHERE g.geolocation_zip_code_prefix = s.seller_zip_code_prefix)"""),
    ("geolocation exact duplicate rows",
     "SELECT count(*) - (SELECT count(*) FROM (SELECT DISTINCT * FROM geolocation)) FROM geolocation"),
    ("geolocation points outside Brazil bounding box",
     """SELECT count(*) FROM geolocation
        WHERE geolocation_lat NOT BETWEEN -34.0 AND 5.5
           OR geolocation_lng NOT BETWEEN -74.0 AND -34.0"""),
    ("orders without items",
     "SELECT count(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM order_items i WHERE i.order_id = o.order_id)"),
    ("orders without payments",
     "SELECT count(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM order_payments p WHERE p.order_id = o.order_id)"),
    ("orders without reviews",
     "SELECT count(*) FROM orders o WHERE NOT EXISTS (SELECT 1 FROM order_reviews r WHERE r.order_id = o.order_id)"),
    ("delivered orders missing order_delivered_customer_date",
     "SELECT count(*) FROM orders WHERE order_status = 'delivered' AND order_delivered_customer_date IS NULL"),
    ("customer_unique_id with more than one customer_id (repeat buyers)",
     """SELECT count(*) FROM (SELECT customer_unique_id FROM customers
                             GROUP BY 1 HAVING count(*) > 1)"""),
]


def csv_path(filename: str) -> str:
    return (RAW_DIR / filename).as_posix()


def main() -> int:
    if not STAGING_DB_PATH.exists():
        log.error("Staging DB not found: %s (run step 02 first)", STAGING_DB_PATH)
        return 1

    con = duckdb.connect(str(STAGING_DB_PATH), read_only=True)
    failures = 0
    try:
        # Hard check 1: row counts match source files exactly
        for table, filename in TABLES:
            src = con.execute(
                f"SELECT count(*) FROM read_csv('{csv_path(filename)}', header=true, all_varchar=true)"
            ).fetchone()[0]
            dst = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            status = "OK" if src == dst else "FAIL"
            failures += src != dst
            log.info("[%s] row count %-35s csv=%d db=%d", status, table, src, dst)

        # Hard check 2: money values have at most 2 decimals, so DECIMAL(12, 2) is lossless
        filenames = dict(TABLES)
        for table, column in MONEY_COLUMNS:
            bad = con.execute(f"""
                SELECT count(*) FROM read_csv('{csv_path(filenames[table])}', header=true, all_varchar=true)
                WHERE NOT regexp_full_match({column}, '-?\\d+(\\.\\d{{1,2}})?')
            """).fetchone()[0]
            status = "OK" if bad == 0 else "FAIL"
            failures += bad > 0
            log.info("[%s] %s.%s values with >2 decimals or non-numeric: %d", status, table, column, bad)

        # Soft checks: known data issues, logged for analysts
        for desc, query in SOFT_CHECKS:
            log.info("[INFO] %-66s %d", desc, con.execute(query).fetchone()[0])
    except duckdb.Error as exc:
        log.error("Quality check errored: %s", exc)
        return 1
    finally:
        con.close()

    if failures:
        log.error("Quality check failed: %d hard check(s) failed", failures)
        return 1
    log.info("All hard quality checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
