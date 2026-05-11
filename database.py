import peewee
from datetime import datetime

# Database setup
db = peewee.SqliteDatabase('psync.db')

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
        files_data = []
        for file_record in cls.select():
            latest = file_record.latest_revision
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

class ApplicationState(BaseModel):
    """Stores general application metadata and state."""
    key = peewee.CharField(unique=True)
    value = peewee.DateTimeField()

def init_db():
    """Initializes the database connection and ensures tables are created."""
    db.connect(reuse_if_open=True)
    db.create_tables([File, FileRevision, ApplicationState])

def close_db():
    """Closes the database connection."""
    db.close()