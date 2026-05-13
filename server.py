from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse
import uvicorn
from database import db, init_db, File, FileRevision
from datetime import datetime
import xxhash
import os
from pathlib import Path
from contextlib import asynccontextmanager

# Server Configuration (Environment Variables Only)
DATA_PATH = str(Path(os.getenv("DATA_PATH", "data")).expanduser().resolve())
BASE_PATH = str(Path(os.getenv("BASE_PATH", ".")).expanduser().resolve())
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", 8000))
DATABASE_PATH = os.getenv("DATABASE_PATH", "psync.db")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initializes the database and ensures the data directory exists on startup."""
    init_db(DATABASE_PATH)
    os.makedirs(DATA_PATH, exist_ok=True)
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/files")
def get_files():
    """API endpoint to serve the JSON dump of all tracked files."""
    return File.get_all_files_data()

@app.get("/revisions/{relative_path:path}")
def get_revisions(relative_path: str):
    """API endpoint to get the history of revisions for a specific file."""
    file_record = File.get_or_none(
        (File.relative_path == relative_path) & (File.base_path == BASE_PATH)
    )
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    return [
        {
            "full_hash": rev.full_hash,
            "size": rev.size,
            "last_modified": rev.last_modified.isoformat(),
            "created_at": rev.created_at.isoformat(),
        }
        for rev in file_record.all_revisions
    ]

@app.get("/down/{file_hash}")
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
    query = File.update(is_deleted=True, updated_at=datetime.now()).where(
        (File.relative_path == relative_path) & (File.base_path == BASE_PATH)
    )
    affected = query.execute()
    if affected == 0:
        raise HTTPException(status_code=404, detail="File not found")
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
    if old_path == new_path:
        return {"status": "no-op", "message": "Paths are identical"}

    with db.atomic():
        # Find all files that are either the file itself or children of the moved directory
        targets = File.select().where(
            (File.base_path == BASE_PATH) & 
            (File.is_deleted == False) &
            ((File.relative_path == old_path) | (File.relative_path.startswith(old_path + "/")))
        )

        if not targets.exists():
            raise HTTPException(status_code=404, detail="No active files found at source path")

        for old_file in targets:
            latest = old_file.latest_revision
            if not latest:
                continue

            # Determine the new path for this specific file
            if old_file.relative_path == old_path:
                target_path = new_path
            else:
                # Replace the old directory prefix with the new directory prefix
                suffix = old_file.relative_path[len(old_path):]
                target_path = new_path + suffix

            old_file.is_deleted = True
            old_file.updated_at = datetime.now()
            old_file.save()

            new_file, _ = File.get_or_create(relative_path=target_path, base_path=BASE_PATH)
            new_file.is_deleted = False
            new_file.updated_at = datetime.now()
            new_file.save()

            FileRevision.create(
                file=new_file,
                full_hash=latest.full_hash,
                size=latest.size,
                last_modified=latest.last_modified
            )
    return {"status": "moved", "from": old_path, "to": new_path}

@app.post("/up")
def upload_file(
    file: UploadFile,
    relative_path: str = Form(...),
    file_hash: str = Form(...)
):
    """
    Endpoint to upload new or changed files.
    Stores the file using its hash as the filename and updates the database.
    """
    # Store the file with its hash as the name
    storage_path = os.path.join(DATA_PATH, file_hash)
    size = 0

    if not os.path.exists(storage_path):
        with open(storage_path, "wb") as f:
            while chunk := file.file.read(65536):
                size += len(chunk)
                f.write(chunk)
            
    file_record, created = File.get_or_create(
        relative_path=relative_path,
        base_path=BASE_PATH
    )
    
    # Optimization: skip the DB round-trip for latest revision if the file was just created
    latest = None
    if not created:
        latest = file_record.latest_revision
    
    # Only create a new revision if the file is new, was deleted, or the content hash changed
    if created or file_record.is_deleted or not latest or latest.full_hash != file_hash:
        file_record.is_deleted = False
        file_record.updated_at = datetime.now()
        file_record.save()
        
        FileRevision.create(
            file=file_record,
            full_hash=file_hash,
            size=size,
            last_modified=datetime.now()
        )
        
    return {"relative_path": relative_path, "hash": file_hash, "status": "processed"}

def run_server(host: str = SERVER_HOST, port: int = SERVER_PORT):
    """Starts the FastAPI server using uvicorn."""
    uvicorn.run(app, host=host, port=port)