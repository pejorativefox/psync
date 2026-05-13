import logging
from datetime import datetime
from file_info import (
    scan_files, upload_missing_to_server, 
    download_missing_from_server
)
from database import ApplicationState, init_db

logger = logging.getLogger(__name__)

def sync():
    """Performs a full synchronization between local and server."""
    init_db()
    logger.info("Starting synchronization...")
    scan_files()
    download_missing_from_server()
    upload_missing_to_server()

    # Update the last sync time in the database
    ApplicationState.replace(key='last_sync', value=datetime.now()).execute()