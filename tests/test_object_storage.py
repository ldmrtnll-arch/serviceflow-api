from functools import partial
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from apps.tickets.exceptions import AttachmentStorageError
from apps.tickets.object_storage import S3ObjectStorage


@pytest.fixture
def storage_clients(monkeypatch, settings):
    settings.S3_ENDPOINT_URL = "http://minio:9000"
    settings.S3_PUBLIC_ENDPOINT_URL = "http://localhost:9000"
    settings.S3_BUCKET_NAME = "private-bucket"
    settings.S3_PRESIGNED_URL_EXPIRATION = 123
    internal = Mock()
    public = Mock()
    monkeypatch.setattr(
        "apps.tickets.object_storage.boto3.client", Mock(side_effect=[internal, public])
    )
    return S3ObjectStorage(), internal, public


def test_s3_adapter_uploads_with_content_type(storage_clients):
    storage, internal, _ = storage_clients
    file = Mock()
    storage.upload(key="tickets/key", file_obj=file, content_type="application/pdf")
    file.seek.assert_called_once_with(0)
    internal.upload_fileobj.assert_called_once_with(
        file, "private-bucket", "tickets/key", ExtraArgs={"ContentType": "application/pdf"}
    )


def test_s3_adapter_deletes_object(storage_clients):
    storage, internal, _ = storage_clients
    storage.delete(key="tickets/key")
    internal.delete_object.assert_called_once_with(Bucket="private-bucket", Key="tickets/key")


def test_s3_client_construction_uses_resilience_settings(monkeypatch, settings):
    settings.S3_CONNECT_TIMEOUT_SECONDS = 2
    settings.S3_READ_TIMEOUT_SECONDS = 7
    settings.S3_MAX_ATTEMPTS = 4
    client_factory = Mock(side_effect=[Mock(), Mock()])
    monkeypatch.setattr("apps.tickets.object_storage.boto3.client", client_factory)
    S3ObjectStorage()
    config = client_factory.call_args_list[0].kwargs["config"]
    assert config.connect_timeout == 2
    assert config.read_timeout == 7
    assert config.retries == {"mode": "adaptive", "max_attempts": 4}


def test_s3_adapter_presigns_public_url_with_expiration_and_filename(storage_clients):
    storage, _, public = storage_clients
    public.generate_presigned_url.return_value = "http://localhost:9000/signed"
    result = storage.generate_download_url(key="tickets/key", filename="relatório final.pdf")
    assert result.expires_in == 123
    call = public.generate_presigned_url.call_args
    assert call.kwargs["ExpiresIn"] == 123
    assert (
        "filename*=UTF-8''relat%C3%B3rio%20final.pdf"
        in call.kwargs["Params"]["ResponseContentDisposition"]
    )


@pytest.mark.parametrize("method", ["upload", "delete", "presign"])
def test_s3_adapter_sanitizes_provider_errors(storage_clients, method):
    storage, internal, public = storage_clients
    error = ClientError({"Error": {"Code": "SecretProviderError", "Message": "secret"}}, "S3")
    if method == "upload":
        internal.upload_fileobj.side_effect = error
        call = partial(storage.upload, key="key", file_obj=Mock(), content_type="text/plain")
    elif method == "delete":
        internal.delete_object.side_effect = error
        call = partial(storage.delete, key="key")
    else:
        public.generate_presigned_url.side_effect = error
        call = partial(storage.generate_download_url, key="key", filename="file.txt")
    with pytest.raises(AttachmentStorageError, match="temporarily unavailable"):
        call()
