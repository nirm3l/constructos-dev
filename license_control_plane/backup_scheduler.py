from __future__ import annotations

import logging
import os
import signal
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


LOGGER = logging.getLogger("lcp-backup")


def _env_int(name: str, default: int, minimum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip()
    if not normalized:
        return default
    try:
        value = int(normalized)
    except ValueError:
        LOGGER.warning("Invalid integer for %s=%r, using default=%d", name, raw, default)
        return default
    return max(minimum, value)


def _backup_once(
    source_db_path: Path,
    backup_dir: Path,
    backup_prefix: str,
    busy_timeout_ms: int,
) -> Path | None:
    if not source_db_path.exists():
        LOGGER.warning("Source DB not found yet: %s", source_db_path)
        return None

    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = backup_dir / f"{backup_prefix}-{timestamp}.sqlite3"
    tmp_path = backup_dir / f".{backup_prefix}-{timestamp}.tmp"

    source_uri = f"file:{source_db_path.as_posix()}?mode=ro"
    with sqlite3.connect(source_uri, uri=True, timeout=max(1.0, busy_timeout_ms / 1000.0)) as source_conn:
        source_conn.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
        with sqlite3.connect(tmp_path) as backup_conn:
            source_conn.backup(backup_conn)
            backup_conn.commit()

    tmp_path.replace(output_path)
    LOGGER.info("Created backup: %s", output_path)
    return output_path


def _prune_backups(backup_dir: Path, backup_prefix: str, retention_seconds: int) -> int:
    if retention_seconds <= 0 or not backup_dir.exists():
        return 0
    cutoff_timestamp = time.time() - retention_seconds
    removed = 0
    pattern = f"{backup_prefix}-*.sqlite3"
    for backup_file in backup_dir.glob(pattern):
        try:
            if backup_file.stat().st_mtime < cutoff_timestamp:
                backup_file.unlink(missing_ok=True)
                removed += 1
        except FileNotFoundError:
            continue
    if removed:
        LOGGER.info("Pruned %d old backup file(s)", removed)
    return removed


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LCP_BACKUP_LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    source_db_path = Path(os.getenv("LCP_BACKUP_SOURCE_DB_PATH", "/data/license-control-plane.db"))
    backup_dir = Path(os.getenv("LCP_BACKUP_DIR", "/backups"))
    backup_prefix = os.getenv("LCP_BACKUP_FILE_PREFIX", "license-control-plane").strip() or "license-control-plane"
    interval_seconds = _env_int("LCP_BACKUP_INTERVAL_SECONDS", default=3600, minimum=60)
    retention_hours = _env_int("LCP_BACKUP_RETENTION_HOURS", default=168, minimum=1)
    startup_delay_seconds = _env_int("LCP_BACKUP_STARTUP_DELAY_SECONDS", default=15, minimum=0)
    busy_timeout_ms = _env_int("LCP_BACKUP_BUSY_TIMEOUT_MS", default=5000, minimum=1000)
    retention_seconds = retention_hours * 3600

    LOGGER.info(
        "Starting backup scheduler: source=%s backup_dir=%s interval=%ss retention=%sh",
        source_db_path,
        backup_dir,
        interval_seconds,
        retention_hours,
    )

    stop_event = threading.Event()

    def _request_stop(signum: int, _frame: object) -> None:
        LOGGER.info("Received signal %s, stopping backup scheduler", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, _request_stop)
    signal.signal(signal.SIGINT, _request_stop)

    if startup_delay_seconds > 0:
        LOGGER.info("Startup delay: %ss", startup_delay_seconds)
        if stop_event.wait(startup_delay_seconds):
            return 0

    while not stop_event.is_set():
        try:
            _backup_once(
                source_db_path=source_db_path,
                backup_dir=backup_dir,
                backup_prefix=backup_prefix,
                busy_timeout_ms=busy_timeout_ms,
            )
            _prune_backups(
                backup_dir=backup_dir,
                backup_prefix=backup_prefix,
                retention_seconds=retention_seconds,
            )
        except Exception:  # pragma: no cover - operational logging fallback
            LOGGER.exception("Backup iteration failed")
        if stop_event.wait(interval_seconds):
            break

    LOGGER.info("Backup scheduler stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
