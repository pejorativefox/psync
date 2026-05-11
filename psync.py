#!/usr/bin/env python3

import argparse
import logging
import fnmatch
import tomllib
import sys
import cProfile
import os
from datetime import datetime
from pathlib import Path
import time
from typing import Dict

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import xxhash

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
logger = logging.getLogger(__name__)

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
        if not event.is_directory and not is_ignored(str(event.src_path), self.base_path, self.ignore_patterns):
            fi = FileInformation(str(event.src_path))
            logger.info(f"Modified: {event.src_path} [Hash: {fi.short_hash}]")

    def on_created(self, event):
        if not event.is_directory and not is_ignored(str(event.src_path), self.base_path, self.ignore_patterns):
            fi = FileInformation(str(event.src_path))
            logger.info(f"Created: {event.src_path} [Hash: {fi.short_hash}]")

    def on_deleted(self, event):
        if not event.is_directory and not is_ignored(str(event.src_path), self.base_path, self.ignore_patterns):
            # FileInformation cannot be created for deleted files as they no longer exist on disk.
            logger.info(f"Deleted: {event.src_path}")

    def on_moved(self, event):
        if not event.is_directory and not is_ignored(str(event.dest_path), self.base_path, self.ignore_patterns):
            fi = FileInformation(str(event.dest_path))
            logger.info(f"Moved: {event.src_path} to {event.dest_path} [Hash: {fi.short_hash}]")

def sync():
    logger.info("Starting synchronization...")
    settings_data = load_settings()
    ignore_patterns = settings_data.get("core", {}).get("ignore", [])

    # Use paths from configuration or arguments
    folder1_base = Path('/home/daspork/repos/test/folder1')
    folder2_base = Path('/home/daspork/repos/test/folder2')

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
    print("Num Files path 1", len(files1))
    print("Num Files path 2", len(files2))

def watch():
    settings_data = load_settings()
    core_settings = settings_data.get("core", {})
    base_path = str(Path(core_settings.get("base_path", ".")).expanduser().resolve())
    ignore_patterns = core_settings.get("ignore", [])

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
    else:
        parser.print_help()