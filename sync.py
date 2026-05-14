import logging
import threading
from datetime import datetime
from file_info import (
    scan_files, upload_missing_to_server, 
    sync_from_remote_log
)
from database import ApplicationState

logger = logging.getLogger(__name__)

_sync_lock = threading.Lock()

def sync(config, pull_only=False):
    """Performs synchronization between local and server."""
    if not _sync_lock.acquire(blocking=False):
        logger.info("Synchronization already in progress. Skipping concurrent request.")
        return

    try:
        start_time = datetime.now()
        # Check if we have a remote log cursor. If not, we need a full reconciliation.
        cursor_rec = ApplicationState.get_or_none(ApplicationState.key == 'remote_log_id')
        needs_reconciliation = cursor_rec is None

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
        ApplicationState.replace(key='last_sync', value=datetime.now().isoformat()).execute()
    finally:
        _sync_lock.release()