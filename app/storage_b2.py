import logging
import uuid
import requests
import json
from typing import Tuple
from .config import B2_ENDPOINT

LOG = logging.getLogger(__name__)

def _get_worker_url(path: str) -> str:
    if not B2_ENDPOINT:
        raise RuntimeError("B2_S3_ENDPOINT is not configured")
    base = B2_ENDPOINT.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path

def upload_cv_bytes(file_bytes: bytes, filename: str, content_type: str = "application/pdf", user_id: str = "unknown") -> str:
    if content_type != "application/pdf":
        raise ValueError("Only PDF files are allowed")
    
    key = f"cvs/{user_id}/{uuid.uuid4().hex}_{filename}"
    url = _get_worker_url(f"/upload?filename={key}")
    try:
        resp = requests.post(
            url, 
            data=file_bytes,
            headers={"Origin": "https://saa-ssender-sale.vercel.app"}
        )
        resp.raise_for_status()
    except Exception as e:
        LOG.exception("Failed to upload CV to B2 via worker: %s", e)
        raise
    return key

def download_cv_bytes(key: str) -> Tuple[bytes, str]:
    url = _get_worker_url(f"/download?filename={key}")
    try:
        resp = requests.get(url, headers={"Origin": "https://saa-ssender-sale.vercel.app"})
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "application/octet-stream")
        return resp.content, content_type
    except Exception as e:
        LOG.exception("Failed to download CV from B2 via worker: %s", e)
        raise

def presign_upload(filename: str, content_type: str = "application/pdf", expires: int = 300, user_id: str = "unknown") -> dict:
    if content_type != "application/pdf":
        raise ValueError("Only PDF files are allowed")
    
    key = f"cvs/{user_id}/{uuid.uuid4().hex}_{filename}"
    # Return the direct worker POST endpoint
    url = _get_worker_url(f"/upload?filename={key}")
    return {"upload_url": url, "key": key}

def get_b2_status() -> dict:
    # Use the /list endpoint to get stats (worker expects GET)
    url = _get_worker_url("/list")
    try:
        resp = requests.get(url, headers={"Origin": "https://saa-ssender-sale.vercel.app"})
        
        if not resp.ok:
            return {"ok": False, "error": f"Worker returned status {resp.status_code}"}
            
        data = resp.json()
        files = data.get("files", [])
        
        file_count = len(files)
        total_size = sum([f.get("contentLength", 0) for f in files])
        folders = set()
        for f in files:
            key = f.get("fileName", "")
            if '/' in key:
                prefix = key.rsplit('/', 1)[0]
                folders.add(prefix)
                
        return {
            "ok": True,
            "bucket": "ssender-worker", # Not exposed by worker
            "file_count": file_count,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "folder_count": len(folders)
        }
    except Exception as e:
        LOG.error("B2 status check failed: %s", e)
        return {"ok": False, "error": str(e)}

def delete_cv(key: str):
    if not key:
        return
    url = _get_worker_url("/delete")
    try:
        # First, find fileId (worker expects GET for /list)
        list_url = _get_worker_url("/list")
        list_resp = requests.get(list_url, headers={"Origin": "https://saa-ssender-sale.vercel.app"})
        if not list_resp.ok:
            return
        files = list_resp.json().get("files", [])
        file_id = None
        for f in files:
            if f.get("fileName") == key:
                file_id = f.get("fileId")
                break
                
        if file_id:
            del_resp = requests.post(url, json={"fileName": key, "fileId": file_id}, headers={"Origin": "https://saa-ssender-sale.vercel.app"})
            del_resp.raise_for_status()
            LOG.info("Successfully deleted old CV via worker: %s", key)
        else:
            LOG.warning("File not found for deletion: %s", key)
            
    except Exception as e:
        LOG.warning("Failed to delete older CV (%s) via worker: %s", key, e)