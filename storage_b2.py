"""
Backblaze B2 (S3-compatible) storage helper using boto3.

Environment variables expected:
- B2_S3_KEY_ID
- B2_S3_APP_KEY
- B2_S3_BUCKET
- B2_S3_ENDPOINT  (e.g. "https://s3.us-west-002.backblazeb2.com")
"""
import os
import logging
import boto3
from botocore.exceptions import ClientError
import uuid
from typing import Tuple

LOG = logging.getLogger(__name__)

B2_KEY_ID = os.getenv("B2_S3_KEY_ID")
B2_APP_KEY = os.getenv("B2_S3_APP_KEY")
B2_BUCKET = os.getenv("B2_S3_BUCKET")
B2_ENDPOINT = os.getenv("B2_S3_ENDPOINT")  # e.g. https://s3.us-west-002.backblazeb2.com

if not all([B2_KEY_ID, B2_APP_KEY, B2_BUCKET, B2_ENDPOINT]):
    LOG.warning("One or more B2 env vars missing (B2_S3_KEY_ID, B2_S3_APP_KEY, B2_S3_BUCKET, B2_S3_ENDPOINT)")

def _get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=B2_ENDPOINT,
        aws_access_key_id=B2_KEY_ID,
        aws_secret_access_key=B2_APP_KEY,
    )

def upload_cv_bytes(file_bytes: bytes, filename: str, content_type: str = "application/pdf") -> str:
    """
    Upload bytes to B2 bucket. Returns the object key.
    Key includes a random uuid prefix to avoid collisions.
    """
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
    """
    Download object from B2 by key.
    Returns (bytes, content_type).
    Raises on error.
    """
    client = _get_s3_client()
    try:
        resp = client.get_object(Bucket=B2_BUCKET, Key=key)
        body = resp["Body"].read()
        content_type = resp.get("ContentType", "application/octet-stream")
        return body, content_type
    except ClientError as e:
        LOG.exception("Failed to download CV from B2: %s", e)
        raise