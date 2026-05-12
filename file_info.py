import xxhash
from pathlib import Path
from datetime import datetime
import logging
import fnmatch
import os
import requests

from database import db, File, FileRevision
from config import SETTINGS, BASE_PATH

logger = logging.getLogger(__name__)

def get_hash(filename):
    """
    Generates an xxh64 hash for the given file.
    
    Args:
        filename (str): The path to the file to hash.
    Returns:
        str: The hexadecimal representation of the hash.
    """
    hasher = xxhash.xxh64()
    with open(filename, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def get_short_hash(filename):
    """
    Generates an xxh32 hash for the given file.
    
    Args:
        filename (str): The path to the file to hash.
    Returns:
        str: The hexadecimal representation of the hash.
    """
    hasher = xxhash.xxh32()
    with open(filename, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()

def is_ignored(path: str):
    """
    Checks if a given file path should be ignored based on a list of patterns.

    Args:
        path (str): The absolute path to the file or directory.
    Returns:
        bool: True if the path should be ignored, False otherwise.
    """
    ignore_patterns = SETTINGS.get("core", {}).get("ignore", [])
    if not ignore_patterns:
        return False
    try:
        rel_path = os.path.relpath(path, BASE_PATH)
    except ValueError:
        # Path is not relative to base_path, e.g., on a different drive or invalid path
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

def upload_to_server(path: str, rel_path: str, file_hash: str):
    """
    Sends a POST request to the server's /up endpoint to upload a file.
    """
    core_settings = SETTINGS.get("core", {})
    host = core_settings.get("server_hostname", "127.0.0.1")
    port = core_settings.get("server_port", 8000)
    url = f"http://{host}:{port}/up"

    try:
        with open(path, "rb") as f:
            files = {"file": (os.path.basename(path), f)}
            data = {"relative_path": rel_path, "file_hash": file_hash}
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to upload {rel_path} to server: {e}")

def process_file_change(path: str, event_type: str, source_path: str = ""):
    """
    Central logic to handle file creation, modification, or movement, updating the database.

    Args:
        path (str): The path to the file that changed.
        event_type (str): The type of file system event (e.g., "Created", "Modified", "Indexed").
        source_path (str, optional): The original path for 'moved' events. Defaults to "".
    """
    if is_ignored(path):
        return

    rel_path = str(Path(path).relative_to(BASE_PATH))
    file_obj, created = File.get_or_create(
        relative_path=rel_path,
        base_path=BASE_PATH
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
        
        # Upload the file to the server
        upload_to_server(path, rel_path, fi.hash)
        
        log_msg = f"{event_type}: {rel_path}"
        if source_path:
            log_msg += f" (from {source_path})"
        logger.info(f"{log_msg} [Revision: {fi.short_hash}]")

class FileInformation(object):
    """Encapsulates file metadata and provides lazy-loaded hashing functionality."""
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
        return False
    
    def dump(self):
        """Prints metadata details to standard output."""
        print("Path:", self.file_path)
        print("Hash:", self.hash)
        print("SHash:", self.short_hash)
        print("Size:", self.size)
        print("Last Accessed:", self.last_accessed)
        print("Last Modified:", self.last_modified)
    
    @property
    def hash(self):
        if self._hash is None:
            self._hash = get_hash(self.file_path)
        return self._hash
    
    @property
    def short_hash(self):
        if self._short_hash is None:
            self._short_hash = get_short_hash(self.file_path)
        return self._short_hash

def scan_files():
    """Scans the directory for new, modified, or deleted files and updates the database."""
    logger.info(f"Scanning {BASE_PATH} for changes...")
    found_rel_paths = set()

    with db.atomic():
        # Scan disk for new and modified files
        for ff in Path(BASE_PATH).rglob('*'):
            if ff.is_file() and not is_ignored(str(ff)):
                rel_path = str(ff.relative_to(BASE_PATH))
                process_file_change(str(ff), "Indexed")
                found_rel_paths.add(rel_path)

        # Check database for files that no longer exist on disk
        active_db_files = File.select().where((File.base_path == BASE_PATH) & (File.is_deleted == False))
        for file_record in active_db_files:
            if file_record.relative_path not in found_rel_paths:
                file_record.is_deleted = True
                file_record.updated_at = datetime.now()
                file_record.save()
                logger.info(f"Detected deletion during scan: {file_record.relative_path}")

def get_server_files():
    """Fetches the list of files currently known by the server."""
    core_settings = SETTINGS.get("core", {})
    host = core_settings.get("server_hostname", "127.0.0.1")
    port = core_settings.get("server_port", 8000)
    url = f"http://{host}:{port}/files"

    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Failed to retrieve file list from server: {e}")
        return []

def upload_missing_to_server():
    """
    Compares local database state with the server's file list and uploads 
    any files that are missing or have mismatched hashes on the server.
    """
    server_files = get_server_files()
    # Create a lookup for active server files: {relative_path: hash}
    server_inventory = {f['f']: f['h'] for f in server_files if not f.get('d', False)}

    # Get all local files that are not marked as deleted in our DB
    local_files = File.select().where(File.is_deleted == False)
    
    for file_record in local_files:
        latest = file_record.latest_revision
        if not latest:
            continue
            
        rel_path = file_record.relative_path
        if rel_path not in server_inventory or server_inventory[rel_path] != latest.full_hash:
            abs_path = os.path.join(BASE_PATH, rel_path)
            if os.path.exists(abs_path):
                logger.info(f"Uploading missing/mismatched file: {rel_path}")
                upload_to_server(abs_path, rel_path, latest.full_hash)