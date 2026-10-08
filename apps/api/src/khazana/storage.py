"""Object storage for lot photographs and documents.

One interface, two implementations. Local disk in development so nothing
depends on a cloud account that does not exist yet, S3 compatible storage in
production. The backend is chosen by configuration and nothing above this
module knows which one is in use.

Keys are generated here, never supplied by a caller. A caller supplied key is
a path traversal waiting to happen, and a brand uploading a file called
``../../etc/passwd`` should not be interesting.
"""

from __future__ import annotations

import hashlib
import logging
import re
import uuid
from pathlib import Path
from typing import Protocol

from .config import get_settings

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_DOCUMENT_TYPES = {"application/pdf", "image/jpeg", "image/png"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9/_-]{0,250}\.[a-z0-9]{1,8}$")

EXTENSIONS = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
}


class StorageError(RuntimeError):
    pass


class Backend(Protocol):
    def write(self, key: str, data: bytes, content_type: str) -> None: ...
    def read(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


def build_key(*, prefix: str, brand_id: str, content_type: str) -> str:
    """Generate a storage key.

    Shape: ``<prefix>/<brand id>/<random>.<ext>``. The brand identifier is in
    the path so that a bulk delete for one brand is a prefix operation, and
    so a stray object can be traced to its owner.
    """
    extension = EXTENSIONS.get(content_type)
    if extension is None:
        raise StorageError(f"Unsupported content type {content_type!r}.")
    safe_prefix = re.sub(r"[^a-z0-9_-]", "", prefix.lower()) or "misc"
    safe_brand = re.sub(r"[^a-zA-Z0-9-]", "", brand_id)[:36] or "unknown"
    return f"{safe_prefix}/{safe_brand}/{uuid.uuid4().hex}.{extension}"


def validate_upload(data: bytes, content_type: str, *, allowed: set[str]) -> None:
    """Check size and type before anything is written.

    The declared content type is checked against the file's own magic bytes.
    A browser or a script can claim anything, and an HTML file uploaded as
    ``image/png`` and later served back is a stored cross site scripting bug.
    """
    if not data:
        raise StorageError("The file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise StorageError(
            f"That file is {len(data) // 1024 // 1024} MB. The limit is "
            f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB."
        )
    if content_type not in allowed:
        raise StorageError(
            f"{content_type} is not accepted here. Allowed: {', '.join(sorted(allowed))}."
        )

    sniffed = sniff_type(data)
    if sniffed is None:
        raise StorageError("That file does not look like an image or a PDF.")
    if sniffed != content_type:
        raise StorageError(f"The file says it is {content_type} but its contents are {sniffed}.")


def sniff_type(data: bytes) -> str | None:
    """Identify a file from its leading bytes, not from its name."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    return None


def checksum(data: bytes) -> str:
    """Content hash, used to spot the same photograph uploaded twice."""
    return hashlib.sha256(data).hexdigest()


class LocalBackend:
    """Files under a directory. Development and tests only."""

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        if not KEY_PATTERN.match(key):
            raise StorageError(f"Refusing a malformed storage key: {key!r}")
        target = (self.root / key).resolve()
        # Belt and braces. The key pattern already forbids dot segments, but
        # a containment check costs nothing and this is the class of bug that
        # ends badly.
        if not str(target).startswith(str(self.root)):
            raise StorageError("Refusing a key that escapes the storage root.")
        return target

    def write(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def read(self, key: str) -> bytes:
        path = self._path(key)
        if not path.exists():
            raise FileNotFoundError(key)
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        path.unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3Backend:
    """S3 compatible storage. Works with AWS, Cloudflare R2 and MinIO.

    Not exercised by the test suite, which runs against the local backend.
    It is wired up now so that Phase 5 deployment is configuration rather
    than a code change.
    """

    def __init__(self, *, endpoint: str | None, bucket: str, key: str, secret: str) -> None:
        import boto3

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint or None,
            aws_access_key_id=key,
            aws_secret_access_key=secret,
        )

    def write(self, key: str, data: bytes, content_type: str) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def read(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(key) from exc
        return bytes(response["Body"].read())

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
        except Exception:
            return False
        return True


_backend: Backend | None = None


def get_backend() -> Backend:
    global _backend
    if _backend is not None:
        return _backend

    settings = get_settings()
    if settings.storage_backend == "s3":
        if not settings.s3_bucket or not settings.s3_access_key or not settings.s3_secret_key:
            raise StorageError("STORAGE_BACKEND is s3 but the bucket or credentials are not set.")
        _backend = S3Backend(
            endpoint=settings.s3_endpoint,
            bucket=settings.s3_bucket,
            key=settings.s3_access_key,
            secret=settings.s3_secret_key,
        )
    else:
        _backend = LocalBackend(settings.storage_local_path)
    return _backend


def reset_backend() -> None:
    """Drop the cached backend. Used by tests that change configuration."""
    global _backend
    _backend = None


def put_object(key: str, data: bytes, content_type: str) -> None:
    get_backend().write(key, data, content_type)


def read_object(key: str) -> bytes:
    return get_backend().read(key)


def delete_object(key: str) -> None:
    get_backend().delete(key)
