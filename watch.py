import logging
import time
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from file_info import process_file_change, handle_deletion, handle_move
from sync import sync

logger = logging.getLogger(__name__)


class SyncHandler(FileSystemEventHandler):
    def __init__(self, config):
        super().__init__()
        self.config = config

    def on_modified(self, event):
        if not event.is_directory:
            process_file_change(str(event.src_path), "Modified", config=self.config)

    def on_created(self, event):
        if not event.is_directory:
            process_file_change(str(event.src_path), "Created", config=self.config)

    def on_deleted(self, event):
        if not event.is_directory:
            handle_deletion(str(event.src_path), config=self.config)

    def on_moved(self, event):
        handle_move(str(event.src_path), str(event.dest_path), config=self.config)
        
_stop_event = threading.Event()

def stop_watching():
    """Signals the watch loop to terminate."""
    _stop_event.set()

def watch(config):
    _stop_event.clear()
    sync(config)

    event_handler = SyncHandler(config)
    observer = Observer()
    observer.schedule(event_handler, config.base_path, recursive=True)

    logger.info(f"Starting watch mode on: {config.base_path}")
    observer.start()

    try:
        while not _stop_event.is_set():
            _stop_event.wait(1)
    finally:
        observer.stop()
        observer.join()