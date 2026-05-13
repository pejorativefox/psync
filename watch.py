import logging
import time
from watchdog.observers import Observer
from sync import sync, SyncHandler
from config import BASE_PATH

logger = logging.getLogger(__name__)

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