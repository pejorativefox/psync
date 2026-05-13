import logging
import threading
from datetime import datetime
from file_info import (
    scan_files, upload_missing_to_server, 
    download_missing_from_server
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
        if pull_only:
            logger.info("Checking for remote changes from other clients...")
        else:
            logger.info("Starting full synchronization...")
            scan_files(config)

        download_missing_from_server(config)

        if not pull_only:
            upload_missing_to_server(config)

        # Update the last sync time in the database
        ApplicationState.replace(key='last_sync', value=datetime.now()).execute()
    finally:
        _sync_lock.release()