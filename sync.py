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
        start_time = datetime.now()
        if pull_only:
            logger.info("Checking for remote changes from other clients...")
        else:
            logger.info("Starting full synchronization...")
            scan_files(config)

        logger.debug("Downloading missing files from server...")
        download_missing_from_server(config)

        if not pull_only:
            logger.info("Uploading missing files to server (this may take a while for large files)...")
            upload_missing_to_server(config)

        duration = (datetime.now() - start_time).total_seconds()
        logger.info("Synchronization completed successfully in %.2f seconds.", duration)

        # Update the last sync time in the database
        ApplicationState.replace(key='last_sync', value=datetime.now()).execute()
    finally:
        _sync_lock.release()