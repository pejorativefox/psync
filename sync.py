import logging
from datetime import datetime
from file_info import (
    scan_files, upload_missing_to_server, 
    download_missing_from_server
)
from database import ApplicationState

logger = logging.getLogger(__name__)

def sync(config):
    """Performs a full synchronization between local and server."""
    logger.info("Starting synchronization...")
    scan_files(config)
    download_missing_from_server(config)
    upload_missing_to_server(config)

    # Update the last sync time in the database
    ApplicationState.replace(key='last_sync', value=datetime.now()).execute()