import logging
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from file_info import process_file_change, handle_deletion, handle_move
from sync import sync
from config import BASE_PATH

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
        
_keep_watching = True

def stop_watching():
    """Signals the watch loop to terminate."""
    global _keep_watching
    _keep_watching = False

def watch():
    global _keep_watching
    _keep_watching = True
    sync()

    event_handler = SyncHandler()
    observer = Observer()
    observer.schedule(event_handler, BASE_PATH, recursive=True)

    logger.info(f"Starting watch mode on: {BASE_PATH}")
    observer.start()

    try:
        while _keep_watching:
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()