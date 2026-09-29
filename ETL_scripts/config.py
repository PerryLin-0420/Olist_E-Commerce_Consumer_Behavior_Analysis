"""Shared paths, table registry and logging setup for the Olist ETL pipeline."""
import logging
import sys
from pathlib import Path

ETL_DIR = Path(__file__).resolve().parent
PROJECT_DIR = ETL_DIR.parent
RAW_DIR = PROJECT_DIR / "Raw_data"
DB_DIR = PROJECT_DIR / "DB"
SQL_DIR = ETL_DIR / "sql"
LOG_DIR = ETL_DIR / "logs"

DB_PATH = DB_DIR / "olist.duckdb"
# All build steps write to the staging file; it replaces DB_PATH only after checks pass
STAGING_DB_PATH = DB_DIR / "olist_staging.duckdb"

# Load order matters: parent tables must be loaded before tables referencing them
TABLES = [
    ("customers", "olist_customers_dataset.csv"),
    ("sellers", "olist_sellers_dataset.csv"),
    ("product_category_name_translation", "product_category_name_translation.csv"),
    ("products", "olist_products_dataset.csv"),
    ("orders", "olist_orders_dataset.csv"),
    ("order_items", "olist_order_items_dataset.csv"),
    ("order_payments", "olist_order_payments_dataset.csv"),
    ("order_reviews", "olist_order_reviews_dataset.csv"),
    ("geolocation", "olist_geolocation_dataset.csv"),
]


def get_logger(name: str) -> logging.Logger:
    """Return a logger writing to both stdout and ETL_scripts/logs/etl.log."""
    LOG_DIR.mkdir(exist_ok=True)
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")
    for handler in (
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "etl.log", encoding="utf-8"),
    ):
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    return logger
