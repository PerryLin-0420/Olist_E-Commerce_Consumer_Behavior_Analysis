"""Step 05: replace the production DB with the validated staging DB."""
import os
import sys

from config import DB_PATH, STAGING_DB_PATH, get_logger

log = get_logger("05_publish")


def main() -> int:
    if not STAGING_DB_PATH.exists():
        log.error("Staging DB not found: %s", STAGING_DB_PATH)
        return 1
    try:
        os.replace(STAGING_DB_PATH, DB_PATH)
    except PermissionError:
        log.error("Cannot replace %s: it is probably open in another program "
                  "(DBeaver, notebook, etc.). Close it and rerun.", DB_PATH)
        return 1
    size_mb = DB_PATH.stat().st_size / 1024 / 1024
    log.info("Published %s (%.1f MB)", DB_PATH, size_mb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
