from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse
import uvicorn
from database import db, init_db
from datetime import datetime
import os
import tempfile
from pathlib import Path

# Server Configuration (Environment Variables Only)
DATA_PATH = str(Path(os.getenv("DATA_PATH", "data")).expanduser().resolve())
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", 8000))
DATABASE_PATH = os.getenv("DATABASE_PATH", "psync.db")

app = FastAPI()

def validate_path(relative_path: str):
    """Ensures the path is not attempting to traverse outside the base."""
    if ".." in relative_path or os.path.isabs(relative_path):
        raise HTTPException(status_code=400, detail="Invalid path structure")
    return relative_path

@app.on_event("startup")
async def startup_event():
    """Initializes the database and ensures the data directory exists on startup."""
    init_db(DATABASE_PATH)
    os.makedirs(DATA_PATH, exist_ok=True)

@app.get("/files")
def get_files():
    """API endpoint to serve the JSON dump of all tracked files."""
    return db.get_all_files_data()

@app.get("/changelog")
def get_changelog(since_id: int = 0):
    """Returns all changes that occurred after the given log ID."""
    changes = db.get_changelog_since(since_id)
    return [
        {"id": c.id, "op": c.operation, "f": c.relative_path, "nf": c.new_relative_path, "h": c.full_hash, "s": c.size}
        for c in changes
    ]

@app.get("/revisions/{relative_path:path}")
def get_revisions(relative_path: str):
    """API endpoint to get the history of revisions for a specific file."""
    relative_path = validate_path(relative_path)
    file_record = db.get_file(relative_path)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    return [
        {
            "full_hash": rev.full_hash,
            "size": rev.size,
            "last_modified": rev.last_modified.isoformat(),
            "created_at": rev.created_at.isoformat(),
        }
        for rev in db.get_all_revisions(file_record)
    ]

@app.get("/download/{file_hash}")
async def download_file(file_hash: str):
    """
    Endpoint to download a file by its hash.
    """
    storage_path = os.path.join(DATA_PATH, file_hash)
    if not os.path.exists(storage_path):
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(storage_path)

@app.delete("/files/{relative_path:path}")
async def delete_file(relative_path: str):
    """
    Endpoint to mark a file as deleted on the server.
    """
    relative_path = validate_path(relative_path)
    affected = db.mark_active_file_deleted(relative_path)
    if affected == 0:
        return {"relative_path": relative_path, "status": "already_deleted"}
    
    # Log the deletion
    db.log_change(operation='deleted', relative_path=relative_path)
    
    return {"relative_path": relative_path, "status": "deleted"}

@app.post("/move")
async def move_file(
    old_path: str = Form(...),
    new_path: str = Form(...)
):
    """
    Endpoint to handle file moves. 
    Marks the old path as deleted and creates/updates the new path with the same content.
    """
    old_path = validate_path(old_path)
    new_path = validate_path(new_path)

    if old_path == new_path:
        return {"status": "no-op", "message": "Paths are identical"}

    success = db.move_path(old_path, new_path)
    if not success:
        raise HTTPException(status_code=404, detail="No active files found at source path")

    # Log the move
    db.log_change(
        operation='moved', relative_path=old_path, new_relative_path=new_path
    )

    return {"status": "moved", "from": old_path, "to": new_path}

@app.post("/upload")
async def upload_file(
    file: UploadFile,
    relative_path: str = Form(...),
    file_hash: str = Form(...),
    last_modified: float = Form(...)
):
    """
    Endpoint to upload new or changed files.
    Stores the file using its hash as the filename and updates the database.
    """
    relative_path = validate_path(relative_path)
    # Store the file with its hash as the name
    storage_path = os.path.join(DATA_PATH, file_hash)
    size = 0

    if not os.path.exists(storage_path):
        # Atomic write using a temporary file to prevent race conditions or partial writes
        fd, temp_path = tempfile.mkstemp(dir=DATA_PATH)
        try:
            with os.fdopen(fd, 'wb') as f:
                while chunk := await file.read(65536):
                    size += len(chunk)
                    f.write(chunk)
            os.replace(temp_path, storage_path)
        except Exception:
            if os.path.exists(temp_path):
                os.remove(temp_path)
            raise
            
    file_record, created = db.get_or_create_file(relative_path)
    
    # Optimization: skip the DB round-trip for latest revision if the file was just created
    latest = None
    if not created:
        latest = db.get_latest_revision(file_record)
    
    # Only create a new revision if the file is new, was deleted, or the content hash changed
    if created or file_record.is_deleted or not latest or latest.full_hash != file_hash:
        db.update_file_status(file_record, is_deleted=False)
        
        db.create_file_revision(
            file_record,
            file_hash,
            size,
            datetime.fromtimestamp(last_modified)
        )
        
        # Log the update
        db.log_change(
            operation='updated',
            relative_path=relative_path,
            full_hash=file_hash,
            size=size
        )
        
    return {"relative_path": relative_path, "hash": file_hash, "status": "processed"}

def run_server(host: str = SERVER_HOST, port: int = SERVER_PORT):
    """Starts the FastAPI server using uvicorn."""
    uvicorn.run(app, host=host, port=port)