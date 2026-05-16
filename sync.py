import logging
import threading
from datetime import datetime
from file_info import (
    scan_files, upload_missing_to_server, 
    sync_from_remote_log
)
from database import db

logger = logging.getLogger(__name__)

sync_lock = threading.Lock()

def sync(config, pull_only=False):
    """Performs synchronization between local and server."""
    if not sync_lock.acquire(blocking=False):
        logger.info("Synchronization already in progress. Skipping concurrent request.")
        return

    try:
        start_time = datetime.now()
        # Check if we have a remote log cursor. If not, we need a full reconciliation.
        cursor_value = db.get_app_state('remote_log_id')
        needs_reconciliation = cursor_value is None

        if pull_only:
            logger.info("Checking for remote changes from other clients...")
        else:
            logger.info("Starting synchronization...")
            scan_files(config)

        logger.debug("Replaying remote changes from server log...")
        sync_from_remote_log(config)

        # Only request the full file list for reconciliation if we don't have a reliable log cursor.
        # Regular uploads are handled by scan_files detecting content changes.
        if not pull_only and needs_reconciliation:
            logger.info("Performing first-time upload reconciliation...")
            upload_missing_to_server(config)

        duration = (datetime.now() - start_time).total_seconds()
        logger.info("Synchronization completed successfully in %.2f seconds.", duration)

        # Update the last sync time in the database
        db.set_app_state('last_sync', datetime.now().isoformat())
    finally:
        sync_lock.release()