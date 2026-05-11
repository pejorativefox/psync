from fastapi import FastAPI
import uvicorn
from database import init_db, File

app = FastAPI()

@app.get("/files")
def get_files():
    """API endpoint to serve the JSON dump of all tracked files."""
    init_db()
    return File.get_all_files_data()

def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Starts the FastAPI server using uvicorn."""
    uvicorn.run(app, host=host, port=port)