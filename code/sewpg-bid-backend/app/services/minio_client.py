from __future__ import annotations

import logging
from datetime import timedelta
from io import BytesIO
from typing import Any, BinaryIO

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger(__name__)


class MinioClient:
    def __init__(self) -> None:
        endpoint = settings.minio_endpoint
        if endpoint.startswith("http://"):
            endpoint = endpoint[7:]
            secure = False
        elif endpoint.startswith("https://"):
            endpoint = endpoint[8:]
            secure = True
        else:
            secure = False

        self.client = Minio(
            endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=secure,
        )
        self.buckets = settings.minio_buckets

    def ensure_bucket(self, bucket: str) -> None:
        try:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
                logger.info("Created MinIO bucket: %s", bucket)
        except S3Error as exc:
            logger.warning("MinIO bucket check failed: %s", exc)

    def put_object(
        self,
        bucket: str,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        self.ensure_bucket(bucket)
        stream = BytesIO(data)
        self.client.put_object(
            bucket,
            key,
            stream,
            length=len(data),
            content_type=content_type,
        )
        logger.info("Uploaded to MinIO: %s/%s (%d bytes)", bucket, key, len(data))
        return key

    def put_object_stream(
        self,
        bucket: str,
        key: str,
        stream: BinaryIO,
        length: int,
        content_type: str = "application/octet-stream",
    ) -> str:
        self.ensure_bucket(bucket)
        self.client.put_object(
            bucket,
            key,
            stream,
            length=length,
            content_type=content_type,
        )
        logger.info("Uploaded stream to MinIO: %s/%s (%d bytes)", bucket, key, length)
        return key

    def get_object(self, bucket: str, key: str) -> bytes:
        resp = self.client.get_object(bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def get_object_response(self, bucket: str, key: str):
        return self.client.get_object(bucket, key)

    def get_presigned_url(self, bucket: str, key: str, expires: int = 3600) -> str:
        ttl = expires if isinstance(expires, timedelta) else timedelta(seconds=int(expires))
        return self.client.presigned_get_object(bucket, key, expires=ttl)

    def remove_object(self, bucket: str, key: str) -> None:
        self.client.remove_object(bucket, key)

    def object_exists(self, bucket: str, key: str) -> bool:
        try:
            self.client.stat_object(bucket, key)
            return True
        except S3Error:
            return False


minio_client = MinioClient()
