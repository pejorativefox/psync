import xxhash
from pathlib import Path
from datetime import datetime
import logging
import fnmatch
import os

from database import db, File, FileRevision
from client import ServerClient

logger = logging.getLogger(__name__)

def get_hash(filename):
    """
    Generates an xxh64 hash for the given file.
    
    Args:
        filename (str): The path to the file to hash.
    Returns:
        str: xxh64_hex
    """
    hasher64 = xxhash.xxh64()
    with open(filename, "rb") as f:
        while chunk := f.read(65536):
            hasher64.update(chunk)
    return hasher64.hexdigest()

def is_ignored(path: str, config):
    """
    Checks if a given file path should be ignored based on a list of patterns.

    Args:
        path (str): The absolute path to the file or directory.
    Returns:
        bool: True if the path should be ignored, False otherwise.
    """
    ignore_patterns = config.ignore_patterns
    if not ignore_patterns:
        return False
    try:
        rel_path = os.path.relpath(path, config.base_path)
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

def upload_to_server(path: str, rel_path: str, file_hash: str, config):
    """
    Sends a POST request to the server's /up endpoint to upload a file.
    """
    client = ServerClient(config)
    try:
        client.upload_file(path, rel_path, file_hash)
    except Exception as e:
        logger.error(f"Failed to upload {rel_path}: {e}")

def process_file_change(path: str, event_type: str, config, source_path: str = "", skip_upload: bool = False):
    """
    Central logic to handle file creation, modification, or movement, updating the database.

    Args:
        path (str): The path to the file that changed.
        event_type (str): The type of file system event (e.g., "Created", "Modified", "Indexed").
        source_path (str, optional): The original path for 'moved' events. Defaults to "".
        skip_upload (bool): If True, skips uploading the file to the server. Defaults to False.
    """
    if is_ignored(path, config):
        return

    # Ensure the file still exists before processing. Temporary files (like .part)
    # are often deleted or moved before the event handler can run.
    if not os.path.exists(path) or not os.path.isfile(path):
        return

    rel_path = str(Path(path).relative_to(config.base_path))
    file_obj, created = File.get_or_create(
        relative_path=rel_path,
        base_path=config.base_path
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
            size=fi.size,
            last_modified=fi.last_modified
        )
        
        # Upload the file to the server
        if not skip_upload:
            upload_to_server(path, rel_path, str(fi.hash), config)
        
        log_msg = f"{event_type}: {rel_path}"
        if source_path:
            log_msg += f" (from {source_path})"
        logger.info(f"{log_msg} [Revision: {fi.hash}]")

def handle_move(src_path: str, dest_path: str, config):
    """
    Handles a file move event by updating the local database and 
    notifying the server via a specialized move endpoint.
    """
    if is_ignored(src_path, config) and is_ignored(dest_path, config):
        return
        
    if is_ignored(src_path, config):
        process_file_change(dest_path, "Created", config)
        return
        
    if is_ignored(dest_path, config):
        handle_deletion(src_path, config)
        return

    try:
        rel_src = str(Path(src_path).relative_to(config.base_path))
        rel_dst = str(Path(dest_path).relative_to(config.base_path))
    except (ValueError, Exception):
        return

    if rel_src == rel_dst:
        return

    # Try to perform an optimized move in the local DB
    success = False
    with db.atomic():
        # Find all files that are either the file itself or children of the moved directory
        targets = File.select().where(
            (File.base_path == config.base_path) & 
            (File.is_deleted == False) &
            ((File.relative_path == rel_src) | (File.relative_path.startswith(rel_src + "/")))
        )

        for old_file in targets:
            latest = old_file.latest_revision
            if latest:
                if old_file.relative_path == rel_src:
                    target_path = rel_dst
                else:
                    suffix = old_file.relative_path[len(rel_src):]
                    target_path = rel_dst + suffix

                old_file.is_deleted = True
                old_file.updated_at = datetime.now()
                old_file.save()

                new_file, _ = File.get_or_create(relative_path=target_path, base_path=config.base_path)
                new_file.is_deleted = False
                new_file.updated_at = datetime.now()
                new_file.save()

                FileRevision.create(
                    file=new_file,
                    full_hash=latest.full_hash,
                    size=latest.size,
                    last_modified=latest.last_modified
                )
                success = True

    if not success and os.path.isdir(dest_path):
        return # Nothing in DB to move for this directory

    if success:
        # Notify server of the move
        client = ServerClient(config)
        try:
            client.move_file(rel_src, rel_dst)
            return
        except Exception as e:
            logger.error(f"Failed to notify server of move from {rel_src}: {e}")
    
    # Fallback to standard change processing (hash + upload) if optimized move fails
    process_file_change(dest_path, "Moved", config, source_path=src_path)

def delete_from_server(rel_path: str, config):
    """Sends a DELETE request to the server to mark a file as deleted."""
    client = ServerClient(config)
    try:
        client.delete_file(rel_path)
    except Exception as e:
        logger.error(f"Failed to notify server of deletion for {rel_path}: {e}")

def handle_deletion(path: str, config):
    """Marks a file as deleted locally and notifies the server."""
    if is_ignored(path, config):
        return

    try:
        rel_path = str(Path(path).relative_to(config.base_path))
    except ValueError:
        return

    # Update local DB
    query = File.update(is_deleted=True, updated_at=datetime.now()).where(
        (File.relative_path == rel_path) & (File.base_path == config.base_path)
    )
    affected = query.execute()
    
    if affected > 0:
        logger.info(f"Deleted: {rel_path}")
        delete_from_server(rel_path, config)

class FileInformation(object):
    """Encapsulates file metadata and provides lazy-loaded hashing functionality."""
    def __init__(self, file_path: str):
        self.file_path = Path(file_path)
        self._hash = None
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
        print("Size:", self.size)
        print("Last Accessed:", self.last_accessed)
        print("Last Modified:", self.last_modified)
    
    @property
    def hash(self):
        if self._hash is None:
            self._compute_hashes()
        return self._hash
    
    def _compute_hashes(self):
        self._hash = get_hash(self.file_path)

def scan_files(config):
    """Scans the directory for new, modified, or deleted files and updates the database."""
    logger.info(f"Scanning {config.base_path} for changes...")
    found_rel_paths = set()

    with db.atomic():
        # Scan disk for new and modified files
        for ff in Path(config.base_path).rglob('*'):
            if ff.is_file() and not is_ignored(str(ff), config):
                rel_path = str(ff.relative_to(config.base_path))
                process_file_change(str(ff), "Indexed", config)
                found_rel_paths.add(rel_path)

        # Check database for files that no longer exist on disk
        active_db_files = File.select().where((File.base_path == config.base_path) & (File.is_deleted == False))
        for file_record in active_db_files:
            if file_record.relative_path not in found_rel_paths:
                file_record.is_deleted = True
                file_record.updated_at = datetime.now()
                file_record.save()
                logger.info(f"Detected deletion during scan: {file_record.relative_path}")
                delete_from_server(file_record.relative_path, config)

def get_server_files(config):
    """Fetches the list of files currently known by the server."""
    client = ServerClient(config)
    try:
        return client.get_server_files()
    except Exception:
        return []

def upload_missing_to_server(config):
    """
    Compares local database state with the server's file list and uploads 
    any files that are missing or have mismatched hashes on the server.
    """
    logger.info("Checking server for missing or mismatched files...")
    server_files = get_server_files(config)
    # Create a lookup for active server files: {relative_path: hash}
    server_inventory = {f['f']: f['h'] for f in server_files if not f.get('d', False)}

    # Get all local files that are not marked as deleted in our DB
    local_files = File.select().where((File.is_deleted == False) & (File.base_path == config.base_path))
    
    uploaded_count = 0
    for file_record in local_files:
        latest = file_record.latest_revision
        if not latest:
            continue
            
        rel_path = file_record.relative_path
        if rel_path not in server_inventory or server_inventory[rel_path] != latest.full_hash:
            abs_path = os.path.join(config.base_path, rel_path)
            if os.path.exists(abs_path):
                logger.info(f"Uploading missing/mismatched file: {rel_path}")
                upload_to_server(abs_path, rel_path, latest.full_hash, config)
                uploaded_count += 1

    if uploaded_count == 0:
        logger.info("Server is already up to date with local files.")
    else:
        logger.info(f"Upload reconciliation complete. {uploaded_count} files uploaded.")

def download_file_from_server(file_hash: str, local_path: str, config):
    """Downloads a file from the server by its hash."""
    client = ServerClient(config)
    try:
        return client.download_file(file_hash, local_path)
    except Exception:
        return False

def download_missing_from_server(config):
    """Fetches server file list and downloads anything missing or outdated locally."""
    logger.info("Checking local storage for missing or mismatched files from server...")
    server_files = get_server_files(config)
    
    downloaded_count = 0
    deleted_count = 0
    for s_file in server_files:
        rel_path = s_file['f']
        abs_path = os.path.join(config.base_path, rel_path)
        
        if s_file.get('d', False):
            # Handle file deleted on server
            if os.path.exists(abs_path) and os.path.isfile(abs_path):
                logger.info(f"Removing file deleted on server: {rel_path}")
                try:
                    os.remove(abs_path)
                except Exception as e:
                    logger.error(f"Failed to delete local file {rel_path}: {e}")
            
            # Ensure local DB reflects the deletion
            affected = File.update(is_deleted=True, updated_at=datetime.now()).where(
                (File.relative_path == rel_path) & (File.base_path == config.base_path) & (File.is_deleted == False)
            ).execute()
            if affected > 0:
                deleted_count += 1
            continue
            
        server_hash = s_file['h']
        needs_download = False
        if not os.path.exists(abs_path):
            needs_download = True
        else:
            # Calculate local hash to see if it matches the server
            if get_hash(abs_path) != server_hash:
                needs_download = True
        
        if needs_download:
            logger.info(f"Downloading missing/mismatched file from server: {rel_path}")
            if download_file_from_server(server_hash, abs_path, config):
                process_file_change(abs_path, "Downloaded", config, skip_upload=True)
                downloaded_count += 1

    if downloaded_count == 0 and deleted_count == 0:
        logger.info("Local storage is already up to date with server.")
    else:
        logger.info(f"Download reconciliation complete. {downloaded_count} files downloaded, {deleted_count} files removed.")