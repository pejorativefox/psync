#!/usr/bin/env python3

import argparse
import glob
import tomllib
import cProfile
import hashlib
import os
from datetime import datetime
from pathlib import Path
import time
from typing import Dict

import watchdog
import xxhash

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

def sync():
    settings_data = load_settings()

    # Use paths from configuration or arguments
    folder1_base = Path('/home/daspork/repos/test/folder1')
    folder2_base = Path('/home/daspork/repos/test/folder2')

    files1: Dict[str, FileInformation] = {}
    files2: Dict[str, FileInformation] = {}

    for ff in folder1_base.rglob('*'):
        if ff.is_file():
            rel_path = str(ff.relative_to(folder1_base))
            files1[rel_path] = FileInformation(str(ff))

    for ff in folder2_base.rglob('*'):
        if ff.is_file():
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
    print("Starting watch mode...")
    # This is a placeholder for the future watchdog observer implementation.
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nWatcher stopped.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Psync: A simple file synchronization tool.")
    parser.add_argument("--sync", action="store_true", help="Perform a one-time synchronization")
    parser.add_argument("--watch", action="store_true", help="Watch the directories for changes")
    parser.add_argument("-p", "--profile", action="store_true", help="Run the profiler to find bottlenecks")
    args = parser.parse_args()

    # Priority is given to watch mode; otherwise, it defaults to the sync logic.
    if args.watch:
        watch()
    else:
        if args.profile:
            profiler = cProfile.Profile()
            profiler.enable()
            sync()
            profiler.disable()
            profiler.print_stats(sort='cumulative')
        else:
            sync()