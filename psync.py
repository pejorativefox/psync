#!/usr/bin/env python3

import argparse
import glob
import tomllib
import hashlib
import os
from pathlib import Path
import time
from typing import Dict

import watchdog

def get_hash(filename):
    with open(filename, "rb") as f:
        digest = hashlib.file_digest(f, hashlib.sha256)
        h = digest.hexdigest()
    return h

def get_short_hash(filename):
    with open(filename, "rb") as f:
        digest = hashlib.file_digest(f, hashlib.shake_128)
        h = digest.hexdigest(4)
    return h

class FileInformation(object):
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self._hash = None
        self._short_hash = None
        metadata = self.file_path.stat()
        self.size = metadata.st_size
        self.last_accessed = metadata.st_atime
        self.last_modified = metadata.st_mtime
    
    def __eq__(self, other):
        if isinstance(other, self.__class__):
            return self.hash == other.hash
        else:
            return False
    
    def dump(self):
        print(self.file_path)
        print(self.hash)
        print(self.short_hash)
        print(self.size)
        print(self.last_accessed)
        print(self.last_modified)
    
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

with open("settings.toml", "rb") as settings_fd:
    settings_data = tomllib.load(settings_fd)
    
print("using path:", settings_data["core"]["base_path"])
print(get_hash("settings.toml"))
print(get_short_hash("settings.toml"))

file_info = FileInformation("settings.toml")
file_info.dump()

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
            print("GOOD:", path)
        else:
            print(" BAD:", path)