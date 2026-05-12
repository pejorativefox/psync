from fastapi import FastAPI, UploadFile, Form, HTTPException
from fastapi.responses import FileResponse
import uvicorn
from database import init_db, File, FileRevision
from config import DATA_PATH, BASE_PATH
from datetime import datetime
import xxhash
import os

app = FastAPI()

@app.get("/files")
def get_files():
    """API endpoint to serve the JSON dump of all tracked files."""
    init_db()
    return File.get_all_files_data()

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
    init_db()
    query = File.update(is_deleted=True, updated_at=datetime.now()).where(
        (File.relative_path == relative_path) & (File.base_path == BASE_PATH)
    )
    affected = query.execute()
    if affected == 0:
        raise HTTPException(status_code=404, detail="File not found")
    return {"relative_path": relative_path, "status": "deleted"}

@app.post("/up")
async def upload_file(
    file: UploadFile,
    relative_path: str = Form(...),
    file_hash: str = Form(...)
):
    """
    Endpoint to upload new or changed files.
    Stores the file using its hash as the filename and updates the database.
    """
    init_db()
    
    content = await file.read()
    short_hash = xxhash.xxh32(content).hexdigest()
    size = len(content)
    
    # Ensure data directory exists
    os.makedirs(DATA_PATH, exist_ok=True)
    
    # Store the file with its hash as the name
    storage_path = os.path.join(DATA_PATH, file_hash)
    if not os.path.exists(storage_path):
        with open(storage_path, "wb") as f:
            f.write(content)
            
    file_record, created = File.get_or_create(
        relative_path=relative_path,
        base_path=BASE_PATH
    )
    
    latest = file_record.latest_revision
    
    # Only create a new revision if the file is new, was deleted, or the content hash changed
    if created or file_record.is_deleted or not latest or latest.full_hash != file_hash:
        file_record.is_deleted = False
        file_record.updated_at = datetime.now()
        file_record.save()
        
        FileRevision.create(
            file=file_record,
            full_hash=file_hash,
            short_hash=short_hash,
            size=size,
            last_modified=datetime.now()
        )
        
    return {"relative_path": relative_path, "hash": file_hash, "status": "processed"}

def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Starts the FastAPI server using uvicorn."""
    init_db()
    uvicorn.run(app, host=host, port=port)