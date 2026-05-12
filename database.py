import peewee
from datetime import datetime
import os

# Database setup
db_path = os.environ.get("DATABASE_PATH", "psync.db")

db = peewee.SqliteDatabase(db_path, pragmas={
    'journal_mode': 'wal',      # Write-Ahead Logging for much faster writes
    'cache_size': -1 * 64000,   # 64MB cache
    'foreign_keys': 1,
})

class BaseModel(peewee.Model):
    """A base model that will use our SQLite database."""
    class Meta:
        database = db

class File(BaseModel):
    """
    Represents a file being tracked by psync.
    A file is uniquely identified by its relative_path within a specific base_path.
    """
    relative_path = peewee.CharField()
    base_path = peewee.CharField()
    is_deleted = peewee.BooleanField(default=False)
    updated_at = peewee.DateTimeField(default=datetime.now)
    
    class Meta:
        # Ensure that the combination of relative_path and base_path is unique
        indexes = (
            (('relative_path', 'base_path'), True),
        )

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
    short_hash = peewee.CharField() # Stores the xxh32 hash
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
    value = peewee.DateTimeField()

def init_db():
    """Initializes the database connection and ensures tables are created."""
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    db.connect(reuse_if_open=True)
    db.create_tables([File, FileRevision, ApplicationState])

def close_db():
    """Closes the database connection."""
    db.close()