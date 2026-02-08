import logging
import boto3
from botocore.exceptions import ClientError
import uuid
from typing import Tuple
from .config import B2_KEY_ID, B2_APP_KEY, B2_BUCKET, B2_ENDPOINT

LOG = logging.getLogger(__name__)

def _get_s3_client():
    if not all([B2_KEY_ID, B2_APP_KEY, B2_BUCKET, B2_ENDPOINT]):
        raise RuntimeError("B2 S3 credentials are not configured")
    return boto3.client(
        "s3",
        endpoint_url=B2_ENDPOINT,
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APP_KEY,
    )

def upload_cv_bytes(file_bytes: bytes, filename: str, content_type: str = "application/pdf") -> str:
    client = _get_s3_client()
    key = f"cvs/{uuid.uuid4().hex}_{filename}"
    try:
        client.put_object(
            Bucket=B2_BUCKET,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
            ACL="private",
        )
    except ClientError as e:
        LOG.exception("Failed to upload CV to B2: %s", e)
        raise
    return key

def download_cv_bytes(key: str) -> Tuple[bytes, str]:
    client = _get_s3_client()
    try:
        resp = client.get_object(Bucket=B2_BUCKET, Key=key)
        body = resp["Body"].read()
        content_type = resp.get("ContentType", "application/octet-stream")
        return body, content_type
    except ClientError as e:
        LOG.exception("Failed to download CV from B2: %s", e)
        raise

def presign_upload(filename: str, content_type: str = "application/pdf", expires: int = 300) -> dict:
    """
    Returns a presigned PUT URL and the object key to use for the uploaded CV.
    Client should PUT the file bytes to this URL with Content-Type header matching content_type.
    """
    client = _get_s3_client()
    key = f"cvs/{uuid.uuid4().hex}_{filename}"
    try:
        url = client.generate_presigned_url('put_object',
            Params={'Bucket': B2_BUCKET, 'Key': key, 'ContentType': content_type},
            ExpiresIn=expires)
    except ClientError as e:
        LOG.exception("Failed to generate presigned URL: %s", e)
        raise
    return {"upload_url": url, "key": key}

def get_b2_status() -> dict:
    """
    Checks if B2 is reachable and configured, returns storage stats.
    """
    if not all([B2_KEY_ID, B2_APP_KEY, B2_BUCKET, B2_ENDPOINT]):
        return {"ok": False, "error": "Missing credentials"}
    
    try:
        client = _get_s3_client()
        # Verify access
        client.head_bucket(Bucket=B2_BUCKET)
        
        # Calculate stats
        paginator = client.get_paginator('list_objects_v2')
        total_size = 0
        file_count = 0
        folders = set()
        
        for page in paginator.paginate(Bucket=B2_BUCKET):
            if 'Contents' in page:
                for obj in page['Contents']:
                    file_count += 1
                    total_size += obj['Size']
                    # S3 doesn't have real folders, but we can count unique prefixes
                    key = obj['Key']
                    if '/' in key:
                        prefix = key.rsplit('/', 1)[0]
                        folders.add(prefix)
        
        return {
            "ok": True, 
            "bucket": B2_BUCKET,
            "file_count": file_count,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "folder_count": len(folders)
        }
    except Exception as e:
        LOG.error("B2 status check failed: %s", e)
        return {"ok": False, "error": str(e)}