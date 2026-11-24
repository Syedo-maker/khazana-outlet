"""Reading an uploaded file without trusting its size.

``await upload.read()`` reads the whole file into memory before anything can
look at how big it is, so the size checks in ``storage.validate_upload`` ran
only after a 2 GB upload had already been loaded. This reads in chunks and
stops one chunk past the limit. The proxy in front of the API caps the request
body as well; this is the second line, for when the API is reached directly.
"""

from __future__ import annotations

from fastapi import UploadFile

from ..core.errors import TooLarge
from ..storage import MAX_UPLOAD_BYTES

CHUNK_BYTES = 1024 * 1024


async def read_upload(upload: UploadFile, *, limit: int = MAX_UPLOAD_BYTES) -> bytes:
    """The file's bytes, or a 413 as soon as it passes ``limit``."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(CHUNK_BYTES):
        total += len(chunk)
        if total > limit:
            raise TooLarge(
                f"That file is larger than {limit // 1024 // 1024} MB, the most accepted here."
            ).as_http()
        chunks.append(chunk)
    return b"".join(chunks)
