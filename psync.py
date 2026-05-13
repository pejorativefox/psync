#!/usr/bin/env python3

import argparse
import logging
import sys
import json
from datetime import datetime
from pathlib import Path
import time

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from server import run_server
from file_info import process_file_change, scan_files, upload_missing_to_server, download_missing_from_server, handle_deletion, handle_move
from database import File, ApplicationState, init_db, close_db
from config import BASE_PATH

# Configure logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

_keep_watching = True

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
    init_db()
    logger.info("Starting synchronization...")
    scan_files()
    download_missing_from_server()
    upload_missing_to_server()

    # Update the last sync time in the database
    ApplicationState.replace(key='last_sync', value=datetime.now()).execute()

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

def start_server():
    """Starts the FastAPI server."""
    logger.info("Starting API server...")
    run_server()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Psync: A simple file synchronization tool.")
    parser.add_argument("--sync", action="store_true", help="Perform a one-time synchronization")
    parser.add_argument("--watch", action="store_true", help="Watch the directories for changes")
    parser.add_argument("--gui", action="store_true", help="Start the Qt GUI application")
    parser.add_argument("--server", action="store_true", help="Start the FastAPI server")
    args = parser.parse_args()

    if args.watch:
        watch()
    elif args.gui:
        from tray import main as run_gui
        run_gui()
    elif args.server:
        start_server()
    elif args.sync:
        sync()
    else:
        from tray import main as run_gui
        run_gui()
    
    close_db()