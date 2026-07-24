from __future__ import annotations

import logging
import mimetypes
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO

from minio import Minio
from minio.commonconfig import CopySource
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

    def upload_file(
        self,
        bucket: str,
        key: str,
        path: Path,
        content_type: str | None = None,
    ) -> str:
        file_path = Path(path)
        guessed_type = content_type or mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        with file_path.open("rb") as handle:
            return self.put_object_stream(
                bucket,
                key,
                handle,
                file_path.stat().st_size,
                content_type=guessed_type,
            )

    def get_object(self, bucket: str, key: str) -> bytes:
        resp = self.client.get_object(bucket, key)
        try:
            return resp.read()
        finally:
            resp.close()
            resp.release_conn()

    def get_object_response(self, bucket: str, key: str):
        return self.client.get_object(bucket, key)

    def download_file(self, bucket: str, key: str, target_path: Path) -> Path:
        resp = self.client.get_object(bucket, key)
        target = Path(target_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target.with_suffix(f"{target.suffix}.download")
        try:
            with temp_path.open("wb") as handle:
                for chunk in resp.stream(64 * 1024):
                    if chunk:
                        handle.write(chunk)
            temp_path.replace(target)
            return target
        finally:
            resp.close()
            resp.release_conn()

    def copy_object(self, bucket: str, source_key: str, target_key: str) -> str:
        self.ensure_bucket(bucket)
        self.client.copy_object(bucket, target_key, CopySource(bucket, source_key))
        logger.info("Copied MinIO object: %s/%s -> %s/%s", bucket, source_key, bucket, target_key)
        return target_key

    def get_presigned_url(self, bucket: str, key: str, expires: int = 3600) -> str:
        ttl = expires if isinstance(expires, timedelta) else timedelta(seconds=int(expires))
        return self.client.presigned_get_object(bucket, key, expires=ttl)

    def remove_object(self, bucket: str, key: str) -> None:
        try:
            self.client.remove_object(bucket, key)
        except S3Error as exc:
            if getattr(exc, "code", "") == "NoSuchKey":
                return
            raise

    def object_exists(self, bucket: str, key: str) -> bool:
        try:
            self.client.stat_object(bucket, key)
            return True
        except S3Error:
            return False


minio_client = MinioClient()
