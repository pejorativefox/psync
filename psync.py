#!/usr/bin/env python3

import argparse
import logging
import sys
from pathlib import Path
import time

from watchdog.observers import Observer

from server import run_server
from sync import sync, SyncHandler
from database import close_db
from config import BASE_PATH

# Configure logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
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
        logger.info("Starting GUI...")
        from gui import main as run_gui
        run_gui()
    elif args.server:
        logger.info("Starting API server...")
        run_server()
    elif args.sync:
        sync()
    else:
        logger.info("Starting GUI...")
        from gui import main as run_gui
        run_gui()
    
    close_db()