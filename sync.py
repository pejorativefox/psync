import logging
from datetime import datetime
from watchdog.events import FileSystemEventHandler
from file_info import (
    process_file_change, scan_files, upload_missing_to_server, 
    download_missing_from_server, handle_deletion, handle_move
)
from database import ApplicationState, init_db

logger = logging.getLogger(__name__)

class SyncHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()

    def on_modified(self, event):
        if not event.is_directory:
            process_file_change(str(event.src_path), "Modified")

    def on_created(self, event):
        if not event.is_directory:
            process_file_change(str(event.src_path), "Created")

    def on_deleted(self, event):
        if not event.is_directory:
            handle_deletion(str(event.src_path))

    def on_moved(self, event):
        handle_move(str(event.src_path), str(event.dest_path))

def sync():
    """Performs a full synchronization between local and server."""
    init_db()
    logger.info("Starting synchronization...")
    scan_files()
    download_missing_from_server()
    upload_missing_to_server()

    # Update the last sync time in the database
    ApplicationState.replace(key='last_sync', value=datetime.now()).execute()