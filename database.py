import peewee
from datetime import datetime
import os
from pathlib import Path
from platformdirs import user_data_dir

# Database setup
_db = peewee.Proxy()

class BaseModel(peewee.Model):
    """A base model that will use our SQLite database."""
    class Meta:
        database = _db

class File(BaseModel):
    """
    Represents a file being tracked by psync.
    A file is uniquely identified by its relative_path within a specific base_path.
    """
    relative_path = peewee.CharField(unique=True)
    is_deleted = peewee.BooleanField(default=False)
    updated_at = peewee.DateTimeField(default=datetime.now)

    @property
    def latest_revision(self):
        """Returns the most recent FileRevision for this file."""
        return FileRevision.select().where(FileRevision.file == self).order_by(FileRevision.created_at.desc()).first()

    @property
    def all_revisions(self):
        """Returns all FileRevision records for this file, ordered by creation date descending."""
        return FileRevision.select().where(FileRevision.file == self).order_by(FileRevision.created_at.desc())
    
    @classmethod
    def get_all_files_data(cls):
        """Returns canonical data for all files, optimized with prefetch to avoid N+1 queries."""
        # Fetch all files and their revisions in two batch queries instead of N+1 queries
        query = cls.select()
        revisions = FileRevision.select().order_by(FileRevision.created_at.desc())
        files_with_revisions = peewee.prefetch(query, revisions)

        files_data = []
        for file_record in files_with_revisions:
            # 'revisions' list is pre-populated by prefetch
            latest = file_record.revisions[0] if file_record.revisions else None
            if latest:
                files_data.append({
                    "f": file_record.relative_path,
                    "h": latest.full_hash,
                    "d": file_record.is_deleted
                })
        return files_data
        

class FileRevision(BaseModel):
    """Represents a specific version or revision of a File."""
    file = peewee.ForeignKeyField(File, backref='revisions')
    full_hash = peewee.CharField() # Stores the xxh64 hash
    size = peewee.IntegerField() # Size of the file in bytes
    last_modified = peewee.DateTimeField() # Last modified timestamp from the file system
    created_at = peewee.DateTimeField(default=datetime.now) # Timestamp when this revision record was created

    class Meta:
        indexes = (
            (('file', 'created_at'), False), # Composite index to speed up history lookups
        )

class ApplicationState(BaseModel):
    """Stores general application metadata and state."""
    key = peewee.CharField(unique=True)
    value = peewee.CharField()

class ChangeLog(BaseModel):
    """A log of all changes occurring on the server to be replayed by clients."""
    # ID is automatic incremental primary key
    operation = peewee.CharField() # 'updated', 'deleted', 'moved'
    relative_path = peewee.CharField()
    new_relative_path = peewee.CharField(null=True) # Used for moves
    full_hash = peewee.CharField(null=True)
    size = peewee.IntegerField(null=True)
    created_at = peewee.DateTimeField(default=datetime.now)

class Database:
    """Facade for database operations."""
    def atomic(self):
        return _db.atomic()

    def init_db(self, db_path=None):
        """Initializes the database connection and ensures tables are created."""
        if db_path is None:
            db_path = os.environ.get("DATABASE_PATH")
            if not db_path:
                db_path = Path(user_data_dir("psync")) / "psync.db"
            
        # Initialize the proxy if it hasn't been already
        if _db.obj is None:
            db_dir = os.path.dirname(os.path.abspath(db_path))
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
                
            _db.initialize(peewee.SqliteDatabase(db_path, pragmas={
                'journal_mode': 'wal',
                'cache_size': -1 * 64000,
                'foreign_keys': 1,
                'busy_timeout': 5000,
            }))

        _db.connect(reuse_if_open=True)
        _db.create_tables([File, FileRevision, ApplicationState, ChangeLog])

    def close(self):
        """Closes the database connection."""
        _db.close()

    def get_or_create_file(self, relative_path: str):
        return File.get_or_create(relative_path=relative_path)

    def get_file(self, relative_path: str):
        return File.get_or_none(File.relative_path == relative_path)

    def get_active_files(self):
        return File.select().where(File.is_deleted == False)

    def get_active_files_by_prefix(self, prefix: str):
        return File.select().where(
            (File.is_deleted == False) &
            ((File.relative_path == prefix) | (File.relative_path.startswith(prefix + "/")))
        )

    def active_files_exist_by_prefix(self, prefix: str) -> bool:
        return self.get_active_files_by_prefix(prefix).exists()

    def mark_file_deleted(self, relative_path: str) -> int:
        query = File.update(is_deleted=True, updated_at=datetime.now()).where(
            File.relative_path == relative_path
        )
        return query.execute()

    def mark_active_file_deleted(self, relative_path: str) -> int:
        query = File.update(is_deleted=True, updated_at=datetime.now()).where(
            (File.relative_path == relative_path) & (File.is_deleted == False)
        )
        return query.execute()

    def update_file_status(self, file_obj: File, is_deleted: bool):
        file_obj.is_deleted = is_deleted # pyright: ignore[reportAttributeAccessIssue]
        file_obj.updated_at = datetime.now() # pyright: ignore[reportAttributeAccessIssue]
        file_obj.save()

    def get_all_files_data(self):
        return File.get_all_files_data()

    def get_latest_revision(self, file_obj: File):
        return file_obj.latest_revision

    def get_all_revisions(self, file_obj: File):
        return file_obj.all_revisions

    def create_file_revision(self, file_obj: File, full_hash: str, size: int, last_modified: datetime):
        return FileRevision.create(
            file=file_obj,
            full_hash=full_hash,
            size=size,
            last_modified=last_modified
        )

    def get_app_state(self, key: str):
        record = ApplicationState.get_or_none(ApplicationState.key == key)
        return record.value if record else None

    def set_app_state(self, key: str, value: str):
        ApplicationState.insert(key=key, value=value).on_conflict_replace().execute()

    def get_changelog_since(self, since_id: int):
        return ChangeLog.select().where(ChangeLog.id > since_id).order_by(ChangeLog.id.asc()) # pyright: ignore[reportAttributeAccessIssue]

    def log_change(self, operation: str, relative_path: str, new_relative_path: str = None, full_hash: str = None, size: int = None): # pyright: ignore[reportArgumentType]
        return ChangeLog.create(
            operation=operation,
            relative_path=relative_path,
            new_relative_path=new_relative_path,
            full_hash=full_hash,
            size=size
        )

db = Database()
init_db = db.init_db
close_db = db.close