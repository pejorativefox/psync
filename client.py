import requests
import logging
import os

logger = logging.getLogger(__name__)

class ServerClient:
    """
    A client for interacting with the Psync server API.
    Encapsulates URL construction and common request patterns.
    """
    def __init__(self, config):
        self.config = config
        self.base_url = f"http://{config.server_hostname}:{config.server_port}"

    def _make_request(self, method, endpoint, **kwargs):
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            response = requests.request(method, url, timeout=kwargs.pop('timeout', 60), **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Server request failed for {method} {url}: {e}")
            raise

    def upload_file(self, path: str, rel_path: str, file_hash: str, last_modified: float):
        """Sends a POST request to the server's /upload endpoint to upload a file."""
        with open(path, "rb") as f:
            files = {"file": (os.path.basename(path), f)}
            data = {
                "relative_path": rel_path, 
                "file_hash": file_hash,
                "last_modified": last_modified
            }
            self._make_request("POST", "/upload", files=files, data=data, timeout=(300, 3600))
        logger.info(f"Uploaded {rel_path} to server.")

    def delete_file(self, rel_path: str):
        """Sends a DELETE request to the server to mark a file as deleted."""
        self._make_request("DELETE", f"/files/{rel_path}")
        logger.info(f"Notified server of deletion for {rel_path}.")

    def move_file(self, old_path: str, new_path: str):
        """Notifies the server of a file move."""
        data = {"old_path": old_path, "new_path": new_path}
        self._make_request("POST", "/move", data=data)
        logger.info(f"Notified server of move: {old_path} -> {new_path}.")

    def get_server_files(self):
        """Fetches the list of files currently known by the server."""
        response = self._make_request("GET", "/files")
        return response.json()

    def get_changelog(self, since_id: int):
        """Fetches the change log from the server starting after since_id."""
        response = self._make_request("GET", f"/changelog?since_id={since_id}")
        return response.json()

    def get_revisions(self, rel_path: str):
        """Fetches the revision history for a specific file."""
        response = self._make_request("GET", f"/revisions/{rel_path}")
        return response.json()

    def download_file(self, file_hash: str, local_path: str):
        """Downloads a file from the server by its hash."""
        url = f"{self.base_url}/download/{file_hash}" # Direct URL for streaming
        try:
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            logger.info(f"Downloaded hash {file_hash} to {local_path}.")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to download hash {file_hash} to {local_path}: {e}")
            raise