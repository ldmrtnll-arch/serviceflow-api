import logging
from dataclasses import dataclass
from urllib.parse import quote

import boto3
from boto3.exceptions import Boto3Error
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from .exceptions import AttachmentStorageError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PresignedDownload:
    url: str
    expires_in: int


class S3ObjectStorage:
    def __init__(self):
        client_options = {
            "aws_access_key_id": settings.S3_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.S3_SECRET_ACCESS_KEY,
            "region_name": settings.S3_REGION_NAME,
            "config": Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                connect_timeout=settings.S3_CONNECT_TIMEOUT_SECONDS,
                read_timeout=settings.S3_READ_TIMEOUT_SECONDS,
                retries={"mode": "adaptive", "max_attempts": settings.S3_MAX_ATTEMPTS},
            ),
        }
        self.bucket = settings.S3_BUCKET_NAME
        self.expiration = settings.S3_PRESIGNED_URL_EXPIRATION
        self.client = boto3.client("s3", endpoint_url=settings.S3_ENDPOINT_URL, **client_options)
        self.public_client = boto3.client(
            "s3", endpoint_url=settings.S3_PUBLIC_ENDPOINT_URL, **client_options
        )

    def upload(self, *, key: str, file_obj, content_type: str) -> None:
        try:
            file_obj.seek(0)
            self.client.upload_fileobj(
                file_obj,
                self.bucket,
                key,
                ExtraArgs={"ContentType": content_type},
            )
        except (Boto3Error, BotoCoreError, ClientError) as exc:
            logger.exception("attachment_storage_upload_failed key=%s", key)
            raise AttachmentStorageError("Object storage is temporarily unavailable.") from exc

    def delete(self, *, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (Boto3Error, BotoCoreError, ClientError) as exc:
            logger.exception("attachment_storage_delete_failed key=%s", key)
            raise AttachmentStorageError("Object storage is temporarily unavailable.") from exc

    def generate_download_url(self, *, key: str, filename: str) -> PresignedDownload:
        filename = filename.replace("\r", "").replace("\n", "")
        safe_ascii = filename.encode("ascii", "ignore").decode() or "attachment"
        safe_ascii = safe_ascii.replace('"', "").replace("\\", "_")
        disposition = f"attachment; filename=\"{safe_ascii}\"; filename*=UTF-8''{quote(filename)}"
        try:
            url = self.public_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ResponseContentDisposition": disposition,
                },
                ExpiresIn=self.expiration,
            )
        except (Boto3Error, BotoCoreError, ClientError) as exc:
            logger.exception("attachment_storage_presign_failed key=%s", key)
            raise AttachmentStorageError("Object storage is temporarily unavailable.") from exc
        return PresignedDownload(url=url, expires_in=self.expiration)


def get_object_storage() -> S3ObjectStorage:
    return S3ObjectStorage()
