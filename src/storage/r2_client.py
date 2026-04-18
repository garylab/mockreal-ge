from __future__ import annotations

from datetime import datetime

import boto3
from botocore.config import Config

from src.config import settings
from loguru import logger as log


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.r2_endpoint,
            aws_access_key_id=settings.r2_access_key_id,
            aws_secret_access_key=settings.r2_secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )
    return _client


def upload_image(image_bytes: bytes, filename: str, content_type: str = "image/jpeg") -> str:
    now = datetime.utcnow()
    key = f"images/{now.year}/{now.month:02d}/{filename}"
    _get_client().put_object(
        Bucket=settings.r2_bucket,
        Key=key,
        Body=image_bytes,
        ContentType=content_type,
    )
    public_url = f"{settings.r2_public_url}/{key}"
    log.info("Uploaded {} -> {}", key, public_url)
    return public_url
