#!/usr/bin/env python3

import argparse
import logging
import sys
import cProfile
import json
from datetime import datetime
from pathlib import Path
import time

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from server import run_server
from file_info import process_file_change, scan_files, is_ignored, upload_missing_to_server
from database import File, ApplicationState, init_db, close_db
from config import BASE_PATH

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

def generate_json_dump():
    """Generates a JSON packet of all files in the database and their latest revisions."""
    init_db()
    return json.dumps(File.get_all_files_data())

def generate_delta_json_dump():
    """Generates a JSON packet of files changed since the last sync."""
    init_db()
    state = ApplicationState.get_or_none(ApplicationState.key == 'last_sync')
    if not state:
        logger.warning("No previous sync record found.")
        return json.dumps([])

    files_data = []
    # Query files that were updated (modified or deleted) after the last sync
    files_changed = File.select().where(File.updated_at > state.value)
    for file_record in files_changed:
        latest = file_record.latest_revision
        files_data.append({
            "f": file_record.relative_path,
            "h": latest.full_hash if latest else None,
            "d": file_record.is_deleted
        })
    return json.dumps(files_data)

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
        if not event.is_directory and not is_ignored(str(event.src_path)):
            rel_path = str(Path(str(event.src_path)).relative_to(BASE_PATH))
            File.update(is_deleted=True, updated_at=datetime.now()).where(
                (File.relative_path == rel_path) & (File.base_path == BASE_PATH)
            ).execute()
            logger.info(f"Deleted: {rel_path}")

    def on_moved(self, event):
        if not event.is_directory:
            # Mark the source path as deleted
            if not is_ignored(str(event.src_path)):
                rel_src = str(Path(str(event.src_path)).relative_to(BASE_PATH))
                File.update(is_deleted=True, updated_at=datetime.now()).where(
                    (File.relative_path == rel_src) & (File.base_path == BASE_PATH)
                ).execute()
            
            process_file_change(str(event.dest_path), "Moved", source_path=str(event.src_path))

def sync():
    init_db()
    logger.info("Starting synchronization...")
    scan_files()

    # Update the last sync time in the database
    ApplicationState.replace(key='last_sync', value=datetime.now()).execute()

def watch():
    init_db()
    scan_files()
    upload_missing_to_server()

    event_handler = SyncHandler()
    observer = Observer()
    observer.schedule(event_handler, BASE_PATH, recursive=True)

    logger.info(f"Starting watch mode on: {BASE_PATH}")
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
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
    parser.add_argument("--server", action="store_true", help="Start the FastAPI server")
    parser.add_argument("--dump-json", action="store_true", help="Dump all file information from the database as pretty-printed JSON")
    parser.add_argument("--dump-delta", action="store_true", help="Dump files changed since the last sync as JSON")
    parser.add_argument("--profile", action="store_true", help="Run the profiler to find bottlenecks")
    args = parser.parse_args()

    if args.watch:
        watch()
    elif args.server:
        start_server()
    elif args.sync:
        if args.profile:
            profiler = cProfile.Profile()
            profiler.enable()
            sync()
            profiler.disable()
            profiler.print_stats(sort='cumulative')
        else:
            sync()
    elif args.dump_json:
        json_output = generate_json_dump()
        print(json_output)
    elif args.dump_delta:
        json_output = generate_delta_json_dump()
        print(json_output)
    else:
        parser.print_help()
    
    close_db()