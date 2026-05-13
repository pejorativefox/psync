import logging
from datetime import datetime
from file_info import (
    scan_files, upload_missing_to_server, 
    download_missing_from_server
)
from database import ApplicationState

logger = logging.getLogger(__name__)

def sync(config, pull_only=False):
    """Performs synchronization between local and server."""
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