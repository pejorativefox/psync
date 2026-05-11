#!/usr/bin/env python3

import argparse
import logging
import fnmatch
import tomllib
import sys
import cProfile
import json
import os
from datetime import datetime
from pathlib import Path
import time
from typing import Dict

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import xxhash

from database import db, File, FileRevision, ApplicationState, init_db, close_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

def process_file_change(path: str, base_path: str, ignore_patterns: list[str], event_type: str, source_path: str = ""):
    """Central logic to handle file creation, modification, or movement."""
    if is_ignored(path, base_path, ignore_patterns):
        return

    rel_path = str(Path(path).relative_to(base_path))
    file_obj, created = File.get_or_create(
        relative_path=rel_path,
        base_path=base_path
    )

    fi = FileInformation(path)
    latest = file_obj.latest_revision

    recreated = file_obj.is_deleted
    if created or recreated or latest is None or latest.full_hash != fi.hash:
        file_obj.is_deleted = False
        file_obj.updated_at = datetime.now()
        file_obj.save()
        FileRevision.create(
            file=file_obj,
            full_hash=fi.hash,
            short_hash=fi.short_hash,
            size=fi.size,
            last_modified=fi.last_modified
        )
        log_msg = f"{event_type}: {rel_path}"
        if source_path:
            log_msg += f" (from {source_path})"
        logger.info(f"{log_msg} [Revision: {fi.short_hash}]")

def scan_untracked_files(base_path: str, ignore_patterns: list[str]):
    """Scans the directory for new or restored files and updates the database."""
    logger.info(f"Scanning {base_path} for untracked files and updates...")
    with db.atomic():
        for ff in Path(base_path).rglob('*'):
            if ff.is_file():
                process_file_change(str(ff), base_path, ignore_patterns, "Indexed")

def generate_json_dump():
    """
    Generates a JSON packet of all files in the database and their latest revisions.
    """
    init_db()
    files_data = []
    for file_record in File.select():
        latest = file_record.latest_revision
        if latest:
            files_data.append({
                "f": file_record.relative_path,
                "h": latest.full_hash
            })
    return json.dumps(files_data)

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

def get_hash(filename):
    hasher = xxhash.xxh64()
    with open(filename, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def get_short_hash(filename):
    hasher = xxhash.xxh32()
    with open(filename, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

class FileInformation(object):
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self._hash = None
        self._short_hash = None
        metadata = self.file_path.stat()
        self.size = metadata.st_size
        self.last_accessed = datetime.fromtimestamp(metadata.st_atime)
        self.last_modified = datetime.fromtimestamp(metadata.st_mtime)
    
    def __eq__(self, other):
        if isinstance(other, self.__class__):
            if self.size != other.size:
                return False
            return self.hash == other.hash
        else:
            return False
    
    def dump(self):
        print("Path:", self.file_path)
        print("Hash:", self.hash)
        print("SHash:", self.short_hash)
        print("Size:", self.size)
        print("Last Accessed:", self.last_accessed)
        print("Last Modified:", self.last_modified)
    
    @property
    def hash(self):
        if self._hash == None:
            self._hash = get_hash(self.file_path)
        return self._hash
    
    @property
    def short_hash(self):
        if self._short_hash == None:
            self._short_hash = get_short_hash(self.file_path)
        return self._short_hash

def load_settings():
    with open("settings.toml", "rb") as settings_fd:
        return tomllib.load(settings_fd)

def is_ignored(path: str, base_path: str, ignore_patterns: list[str]):
    if not ignore_patterns:
        return False
    try:
        rel_path = os.path.relpath(path, base_path)
    except ValueError:
        return False

    parts = Path(rel_path).parts
    for pattern in ignore_patterns:
        p = pattern.rstrip('/')
        # Check if any directory in the path matches the pattern
        if any(fnmatch.fnmatch(part, p) for part in parts):
            return True
        # Check if the filename or relative path matches
        if fnmatch.fnmatch(rel_path, p) or fnmatch.fnmatch(os.path.basename(path), p):
            return True
    return False

class SyncHandler(FileSystemEventHandler):
    def __init__(self, base_path: str, ignore_patterns: list[str]):
        super().__init__()
        self.base_path = base_path
        self.ignore_patterns = ignore_patterns

    def on_modified(self, event):
        if not event.is_directory:
            process_file_change(str(event.src_path), self.base_path, self.ignore_patterns, "Modified")

    def on_created(self, event):
        if not event.is_directory:
            process_file_change(str(event.src_path), self.base_path, self.ignore_patterns, "Created")

    def on_deleted(self, event):
        if not event.is_directory and not is_ignored(str(event.src_path), self.base_path, self.ignore_patterns):
            rel_path = str(Path(str(event.src_path)).relative_to(self.base_path))
            File.update(is_deleted=True, updated_at=datetime.now()).where(
                (File.relative_path == rel_path) & (File.base_path == self.base_path)
            ).execute()
            logger.info(f"Deleted: {rel_path}")

    def on_moved(self, event):
        if not event.is_directory:
            # Mark the source path as deleted
            if not is_ignored(str(event.src_path), self.base_path, self.ignore_patterns):
                rel_src = str(Path(str(event.src_path)).relative_to(self.base_path))
                File.update(is_deleted=True, updated_at=datetime.now()).where(
                    (File.relative_path == rel_src) & (File.base_path == self.base_path)
                ).execute()
            
            process_file_change(str(event.dest_path), self.base_path, self.ignore_patterns, "Moved", source_path=str(event.src_path))

def sync():
    init_db()
    logger.info("Starting synchronization...")
    settings_data = load_settings()
    ignore_patterns = settings_data.get("core", {}).get("ignore", [])

    # Use paths from configuration or arguments
    folder1_base = Path('/home/daspork/repos/test/folder1')
    folder2_base = Path('/home/daspork/repos/test/folder2')

    scan_untracked_files(str(folder1_base), ignore_patterns)

    files1: Dict[str, FileInformation] = {}
    files2: Dict[str, FileInformation] = {}

    for ff in folder1_base.rglob('*'):
        if ff.is_file() and not is_ignored(str(ff), str(folder1_base), ignore_patterns):
            rel_path = str(ff.relative_to(folder1_base))
            files1[rel_path] = FileInformation(str(ff))

    for ff in folder2_base.rglob('*'):
        if ff.is_file() and not is_ignored(str(ff), str(folder2_base), ignore_patterns):
            rel_path = str(ff.relative_to(folder2_base))
            files2[rel_path] = FileInformation(str(ff))

    for path, fi in files1.items():
        if path in files2:
            a = fi
            b = files2[path]
            if a == b:
                # print("GOOD:", path)
                pass
            else:
                print(" BAD:", path)
        else:
            print("MISSING:", path)

    # Update the last sync time in the database
    ApplicationState.replace(key='last_sync', value=datetime.now()).execute()

    print("Num Files path 1", len(files1))
    print("Num Files path 2", len(files2))

def watch():
    init_db()
    settings_data = load_settings()
    core_settings = settings_data.get("core", {})
    base_path = str(Path(core_settings.get("base_path", ".")).expanduser().resolve())
    ignore_patterns = core_settings.get("ignore", [])

    scan_untracked_files(base_path, ignore_patterns)

    event_handler = SyncHandler(base_path, ignore_patterns)
    observer = Observer()
    observer.schedule(event_handler, base_path, recursive=True)

    logger.info(f"Starting watch mode on: {base_path}")
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Psync: A simple file synchronization tool.")
    parser.add_argument("--sync", action="store_true", help="Perform a one-time synchronization")
    parser.add_argument("--watch", action="store_true", help="Watch the directories for changes")
    parser.add_argument("--dump-json", action="store_true", help="Dump all file information from the database as pretty-printed JSON")
    parser.add_argument("--dump-delta", action="store_true", help="Dump files changed since the last sync as JSON")
    parser.add_argument("-p", "--profile", action="store_true", help="Run the profiler to find bottlenecks")
    args = parser.parse_args()

    if args.watch:
        watch()
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