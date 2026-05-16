import xxhash
from pathlib import Path
from datetime import datetime
import logging
import fnmatch
import os

from database import db
from client import ServerClient

logger = logging.getLogger(__name__)

def get_hash(filename, chunk_size=1048576):
    """
    Generates an xxh64 hash for the given file.
    
    Args:
        filename (str): The path to the file to hash.
        chunk_size (int): Size of chunks to read (default 1MB).
    Returns:
        str: xxh64_hex
    """
    hasher64 = xxhash.xxh64()
    with open(filename, "rb") as f:
        while chunk := f.read(chunk_size):
            hasher64.update(chunk)
    return hasher64.hexdigest()

def is_ignored(path: str, config, rel_path: str = None): # pyright: ignore[reportArgumentType]
    """
    Checks if a given file path should be ignored based on a list of patterns.

    Args:
        path (str): The absolute path to the file or directory.
        rel_path (str, optional): The pre-calculated relative path.
    Returns:
        bool: True if the path should be ignored, False otherwise.
    """
    if path.endswith('.psync_tmp') or (rel_path and rel_path.endswith('.psync_tmp')):
        return True

    ignore_patterns = config.ignore_patterns
    if not ignore_patterns:
        return False
    
    if rel_path is None:
        try:
            rel_path = os.path.relpath(path, config.base_path)
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

def upload_to_server(path: str, rel_path: str, file_hash: str, last_modified: datetime, config) -> bool:
    """
    Sends a POST request to the server's /up endpoint to upload a file.
    Returns True if successful, False otherwise.
    """
    client = ServerClient(config)
    try:
        start_time = datetime.now()
        size_mb = os.path.getsize(path) / (1024 * 1024)
        logger.info(f"Commencing upload for {rel_path} ({size_mb:.2f} MB)...")
        client.upload_file(path, rel_path, file_hash, last_modified.timestamp())
        duration = (datetime.now() - start_time).total_seconds()
        logger.info(f"Successfully uploaded {rel_path} in {duration:.2f}s")
        return True
    except Exception as e:
        logger.error(f"Upload failed for {rel_path}: {e}")
        return False

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
    file_obj, created = db.get_or_create_file(rel_path)

    fi = FileInformation(path)
    latest = db.get_latest_revision(file_obj)

    recreated = file_obj.is_deleted
    if created or recreated or latest is None or latest.full_hash != fi.hash:
        # Upload the file to the server FIRST to prevent false-sync states
        if not skip_upload:
            if not upload_to_server(path, rel_path, str(fi.hash), fi.last_modified, config):
                logger.warning(f"Upload failed for {rel_path}. Skipping local DB update to retry later.")
                return

        db.update_file_status(file_obj, is_deleted=False)
        db.create_file_revision(
            file_obj,
            fi.hash, # pyright: ignore[reportArgumentType]
            fi.size,
            fi.last_modified
        )
        
        log_msg = f"{event_type}: {rel_path}"
        if source_path:
            log_msg += f" (from {source_path})"
        logger.info(f"{log_msg} [Revision: {fi.hash}]")

def handle_move(src_path: str, dest_path: str, config, notify_server: bool = True):
    """
    Handles a file move event by updating the local database and 
    notifying the server via a specialized move endpoint.
    
    Args:
        notify_server (bool): If False, avoids notifying the server (used for remote log replay).
    """
    rel_src = None
    try:
        rel_src = str(Path(src_path).relative_to(config.base_path))
        src_tracked = not is_ignored(src_path, config, rel_path=rel_src)
    except ValueError:
        src_tracked = False

    rel_dst = None
    try:
        rel_dst = str(Path(dest_path).relative_to(config.base_path))
        dest_tracked = not is_ignored(dest_path, config, rel_path=rel_dst)
    except ValueError:
        dest_tracked = False

    if not src_tracked and not dest_tracked:
        return
        
    if not src_tracked and dest_tracked:
        if os.path.isdir(dest_path):
            for root, _, files in os.walk(dest_path):
                for f in files:
                    process_file_change(os.path.join(root, f), "Created", config, skip_upload=not notify_server)
        else:
            process_file_change(dest_path, "Created", config, skip_upload=not notify_server)
        return
        
    if src_tracked and not dest_tracked:
        handle_deletion(src_path, config, notify_server=notify_server)
        return

    if rel_src == rel_dst:
        return

    if notify_server:
        # Notify server of the move first
        client = ServerClient(config)
        try:
            client.move_file(str(rel_src), str(rel_dst))
        except Exception as e:
            logger.error(f"Failed to notify server of move from {rel_src}: {e}")
            # Fallback to standard change processing on next pass or right now
            process_file_change(dest_path, "Moved", config, source_path=src_path)
            return

    # Try to perform an optimized move in the local DB
    success = False
    with db.atomic():
        # Find all files that are either the file itself or children of the moved directory
        targets = list(db.get_active_files_by_prefix(str(rel_src)))

        for old_file in targets:
            latest = db.get_latest_revision(old_file)
            if latest:
                if old_file.relative_path == rel_src:
                    target_path = rel_dst
                else:
                    suffix = old_file.relative_path[len(str(rel_src)):]
                    target_path = rel_dst + suffix

                db.update_file_status(old_file, is_deleted=True)

                new_file, _ = db.get_or_create_file(str(target_path))
                db.update_file_status(new_file, is_deleted=False)

                db.create_file_revision(
                    new_file,
                    latest.full_hash,
                    latest.size,
                    latest.last_modified
                )
                success = True

    if not success and os.path.isdir(dest_path):
        return # Nothing in DB to move for this directory

    if not success and not notify_server:
        process_file_change(dest_path, "Moved", config, source_path=src_path, skip_upload=True)
    elif not success and notify_server:
        process_file_change(dest_path, "Moved", config, source_path=src_path)

def delete_from_server(rel_path: str, config) -> bool:
    """Sends a DELETE request to the server. Returns True on success."""
    client = ServerClient(config)
    try:
        client.delete_file(rel_path)
        return True
    except Exception as e:
        logger.error(f"Failed to notify server of deletion for {rel_path}: {e}")
        return False

def handle_deletion(path: str, config, notify_server: bool = True):
    """Marks a file as deleted locally and notifies the server."""
    if is_ignored(path, config):
        return

    try:
        rel_path = str(Path(path).relative_to(config.base_path))
    except ValueError:
        return

    # Update local DB for the file, or all files under the directory
    targets = list(db.get_active_files_by_prefix(rel_path))
    for file_record in targets:
        f_rel_path = file_record.relative_path
        
        if notify_server:
            if not delete_from_server(f_rel_path, config):
                logger.warning(f"Skipping local deletion record for {f_rel_path} due to server error.")
                continue

        affected = db.mark_active_file_deleted(f_rel_path)
        
        if affected > 0:
            logger.info(f"Deleted: {f_rel_path}")

def remove_empty_dirs(path: str, base_path: str):
    """Recursively removes empty directories from the given path up to the base_path."""
    dir_path = Path(path).parent.resolve()
    base_dir = Path(base_path).resolve()
    while dir_path != base_dir and dir_path.is_relative_to(base_dir):
        try:
            dir_path.rmdir()
            dir_path = dir_path.parent
        except OSError:
            break

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

    # Removed db.atomic() to prevent blocking the DB during network uploads
    # Scan disk for new and modified files
    for ff in Path(config.base_path).rglob('*'):
        rel_path = str(ff.relative_to(config.base_path))
        if ff.is_file() and not is_ignored(str(ff), config, rel_path=rel_path):
            process_file_change(str(ff), "Indexed", config)
            found_rel_paths.add(rel_path)

    # Check database for files that no longer exist on disk
    active_db_files = list(db.get_active_files())
    for file_record in active_db_files:
        if file_record.relative_path not in found_rel_paths:
            if delete_from_server(file_record.relative_path, config):
                db.update_file_status(file_record, is_deleted=True)
                logger.info(f"Detected deletion during scan: {file_record.relative_path}")

def upload_missing_to_server(config):
    """
    Compares local database state with the server's file list and uploads 
    any files that are missing or have mismatched hashes on the server.
    """
    logger.info("Checking server for missing or mismatched files...")
    client = ServerClient(config)
    try:
        server_files = client.get_server_files()
    except Exception:
        logger.error("Could not retrieve file list from server. Aborting upload reconciliation.")
        return

    # Create a lookup for active server files: {relative_path: hash}
    server_inventory = {f['f']: f['h'] for f in server_files if not f.get('d', False)}

    # Get all local files that are not marked as deleted in our DB
    local_files = db.get_active_files()
    
    uploaded_count = 0
    for file_record in local_files:
        latest = db.get_latest_revision(file_record)
        if not latest:
            continue
            
        rel_path = file_record.relative_path
        if rel_path not in server_inventory or server_inventory[rel_path] != latest.full_hash:
            abs_path = os.path.join(config.base_path, rel_path)
            if os.path.isfile(abs_path):
                logger.info(f"Uploading missing/mismatched file: {rel_path}")
                if upload_to_server(abs_path, rel_path, latest.full_hash, latest.last_modified, config):
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
    client = ServerClient(config)
    try:
        server_files = client.get_server_files()
    except Exception:
        logger.error("Could not retrieve file list from server. Aborting download reconciliation.")
        return

    downloaded_count = 0
    deleted_count = 0
    for s_file in server_files:
        rel_path = s_file['f']
        abs_path = os.path.join(config.base_path, rel_path)

        # Fetch local record to check for resurrection or deletion race conditions
        file_record = db.get_file(rel_path)

        if s_file.get('d', False):
            # Handle file deleted on server
            if os.path.exists(abs_path) and os.path.isfile(abs_path):
                local_hash = get_hash(abs_path)
                server_deleted_hash = s_file.get('h')
                
                if server_deleted_hash and local_hash != server_deleted_hash:
                    logger.warning(f"Conflict: {rel_path} was modified locally. Skipping server deletion to prevent data loss.")
                    continue
                    
                latest = db.get_latest_revision(file_record) if file_record else None
                if latest and local_hash != latest.full_hash:
                    logger.warning(f"Conflict: {rel_path} has unindexed local changes. Skipping server deletion.")
                    continue

                logger.info(f"Removing file deleted on server: {rel_path}")
                try:
                    os.remove(abs_path)
                    remove_empty_dirs(abs_path, config.base_path)
                except Exception as e:
                    logger.error(f"Failed to delete local file {rel_path}: {e}")
            
            # Ensure local DB reflects the deletion
            affected = db.mark_active_file_deleted(rel_path)
            if affected > 0:
                deleted_count += 1
        else:
            server_hash = s_file['h']
            needs_download = False

            latest = db.get_latest_revision(file_record) if file_record else None
            local_hash = get_hash(abs_path) if os.path.isfile(abs_path) else None

            if not os.path.exists(abs_path):
                # If missing locally but active on server, we need to download it.
                if file_record and file_record.is_deleted:
                    # Skip if we just deleted it locally to prevent immediate resurrection
                    if (datetime.now() - file_record.updated_at).total_seconds() < 10:
                        continue
                needs_download = True
            else:
                if local_hash != server_hash:
                    # Conflict detection: skip download if local file has un-synced changes
                    if latest and local_hash != latest.full_hash:
                        logger.warning(f"Conflict: {rel_path} was modified locally. Skipping download to prevent data loss.")
                        continue
                        
                    if file_record:
                        known_hashes = {r.full_hash for r in db.get_all_revisions(file_record)}
                        if server_hash in known_hashes and local_hash != server_hash:
                            logger.info(f"Local version of {rel_path} is newer than server. Skipping download.")
                            continue
                    needs_download = True
                elif file_record and file_record.is_deleted:
                    # File matches server but is incorrectly flagged as deleted locally
                    process_file_change(abs_path, "Restored", config, skip_upload=True)

            if needs_download:
                logger.info(f"Downloading missing/mismatched file from server: {rel_path}")
                temp_path = abs_path + ".psync_tmp"
                if download_file_from_server(server_hash, temp_path, config):
                    try:
                        downloaded_hash = get_hash(temp_path)
                        if downloaded_hash != server_hash:
                            logger.error(f"Hash mismatch on downloaded file {rel_path}. Aborting replace.")
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                            continue
                            
                        current_local_hash = get_hash(abs_path) if os.path.isfile(abs_path) else None
                        if current_local_hash != local_hash:
                            logger.warning(f"Conflict: {rel_path} modified locally during download. Aborting overwrite to prevent data loss.")
                            if os.path.exists(temp_path):
                                os.remove(temp_path)
                            continue

                        os.replace(temp_path, abs_path)
                        process_file_change(abs_path, "Downloaded", config, skip_upload=True)
                        downloaded_count += 1
                    except Exception as e:
                        logger.error(f"Failed to finalize download for {rel_path}: {e}")
                        if os.path.exists(temp_path):
                            os.remove(temp_path)

    if downloaded_count == 0 and deleted_count == 0:
        logger.info("Local storage is already up to date with server.")
    else:
        logger.info(f"Download reconciliation complete. {downloaded_count} files downloaded, {deleted_count} files removed.")

def sync_from_remote_log(config):
    """
    Fetches the server's change log and replays events locally.
    This is much more efficient than a full server inventory scan.
    """
    client = ServerClient(config)
    
    # Get the last processed log ID from local state
    cursor_value = db.get_app_state('remote_log_id')
    
    # Fallback: if no cursor, we should probably do a full sync once
    if not cursor_value:
        logger.info("No remote log cursor found. Performing full reconciliation...")
        download_missing_from_server(config)
        # Set initial cursor to the highest current ID if possible, or 0
        # For simplicity here, we start from 0 if no record exists
        last_id = 0
    else:
        last_id = int(cursor_value) 

    changes = client.get_changelog(last_id)
    if not changes:
        return

    logger.info(f"Replaying {len(changes)} remote changes...")
    
    new_last_id = last_id
    for change in changes:
        op = change['op']
        rel_path = change['f']
        abs_path = os.path.join(config.base_path, rel_path)
        
        file_record = db.get_file(rel_path)
        latest = db.get_latest_revision(file_record) if file_record else None
        
        if op == 'updated':
            server_hash = change['h']
            local_hash = get_hash(abs_path) if os.path.isfile(abs_path) else None
            if local_hash != server_hash:
                if local_hash:
                    if latest and local_hash != latest.full_hash:
                        logger.warning(f"Conflict: {rel_path} modified locally. Skipping remote update.")
                        continue
                    if file_record:
                        known_hashes = {r.full_hash for r in db.get_all_revisions(file_record)}
                        if server_hash in known_hashes and local_hash != server_hash:
                            logger.info(f"Local {rel_path} is ahead of server. Skipping remote update.")
                            continue
                            
                temp_path = abs_path + ".psync_tmp"
                if download_file_from_server(server_hash, temp_path, config):
                    try:
                        downloaded_hash = get_hash(temp_path)
                        if downloaded_hash != server_hash:
                            logger.error(f"Hash mismatch on downloaded file {rel_path}. Aborting replace.")
                            if os.path.exists(temp_path): os.remove(temp_path)
                            continue

                        current_local_hash = get_hash(abs_path) if os.path.isfile(abs_path) else None
                        if current_local_hash != local_hash:
                            logger.warning(f"Conflict: {rel_path} modified locally during download. Aborting overwrite.")
                            if os.path.exists(temp_path): os.remove(temp_path)
                            continue

                        os.replace(temp_path, abs_path)
                        process_file_change(abs_path, "Downloaded", config, skip_upload=True)
                    except Exception as e:
                        logger.error(f"Failed to finalize download for {rel_path}: {e}")
                        if os.path.exists(temp_path):
                            os.remove(temp_path)
                    
        elif op == 'deleted':
            if os.path.isfile(abs_path):
                local_hash = get_hash(abs_path)
                server_deleted_hash = change.get('h')
                
                if server_deleted_hash and local_hash != server_deleted_hash:
                    logger.warning(f"Conflict: {rel_path} modified locally. Skipping remote deletion.")
                    continue
                    
                if latest and local_hash != latest.full_hash:
                    logger.warning(f"Conflict: {rel_path} modified locally. Skipping remote deletion.")
                    continue
                    
                try:
                    os.remove(abs_path)
                    remove_empty_dirs(abs_path, config.base_path)
                    handle_deletion(abs_path, config, notify_server=False)
                except Exception as e:
                    logger.error(f"Failed to delete {rel_path}: {e}")
                
        elif op == 'moved':
            new_rel_path = change['nf']
            new_abs_path = os.path.join(config.base_path, new_rel_path)
            
            if os.path.isfile(new_abs_path):
                target_hash = get_hash(new_abs_path)
                target_record = db.get_file(new_rel_path)
                t_latest = db.get_latest_revision(target_record) if target_record else None
                if not t_latest or target_hash != t_latest.full_hash:
                    logger.warning(f"Conflict: Target {new_rel_path} modified locally. Skipping move.")
                    continue
                    
            if os.path.isfile(abs_path):
                local_hash = get_hash(abs_path)
                server_source_hash = change.get('h')
                
                if server_source_hash and local_hash != server_source_hash:
                    logger.warning(f"Conflict: Source {rel_path} modified locally. Skipping move.")
                    continue
                    
                if latest and local_hash != latest.full_hash:
                    logger.warning(f"Conflict: Source {rel_path} modified locally. Skipping move.")
                    continue

                try:
                    os.makedirs(os.path.dirname(new_abs_path), exist_ok=True)
                    os.rename(abs_path, new_abs_path)
                    remove_empty_dirs(abs_path, config.base_path)
                    # Update local DB state
                    handle_move(abs_path, new_abs_path, config, notify_server=False)
                except Exception as e:
                    logger.error(f"Failed to move {rel_path} to {new_rel_path}: {e}")

        new_last_id = max(new_last_id, change['id'])

    # Update cursor
    db.set_app_state('remote_log_id', str(new_last_id))
    
    logger.info(f"Sync log replayed up to ID {new_last_id}")