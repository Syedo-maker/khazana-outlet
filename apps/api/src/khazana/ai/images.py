"""Image preparation for vision calls.

This module exists because of one number in docs/ai-architecture.md: image
tokens dominate the cost of the photo to listing call. A 4000 pixel phone
photograph and a 1024 pixel one produce the same quality draft and very
different bills, so nothing reaches a model without passing through here.

Three jobs:

1. Shrink to the longest edge a vision model actually uses, then compress.
2. Cap how many photographs go in one call, keeping the most informative.
3. Report what the compression actually saved, so the saving is measured
   rather than assumed.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, floor

from ..models.enums import PhotoKind
from .logo_regions import Box

logger = logging.getLogger(__name__)

# Beyond roughly 1024 pixels on the long edge, a vision model gains very
# little on product photographs and the token count keeps rising. Measured
# again in week 7 against real brand photographs before this is treated as
# settled.
MAX_EDGE_PX = 1024
JPEG_QUALITY = 80

# The most pixels a photograph may declare before it is decoded. A 10 MB PNG
# can claim to be 30,000 pixels square, which is gigabytes once decoded: a
# decompression bomb. A 48 megapixel phone photo is the largest honest
# upload, so the cap sits just above it.
MAX_PIXELS = 50_000_000

# The cost model assumes four photographs per listing. More than that is
# usually several shots of the same garment and buys nothing.
MAX_IMAGES_PER_CALL = 4

# Coarse enough that a logo cannot be read back out of a protected photograph.
BLUR_BLOCK_PX = 24
BLUR_RADIUS_PX = 10

# When a brand uploads a full set, these are the views that carry the most
# information for a draft listing, in order. The label shot matters more than
# a second front view because it carries fibre, size and care text.
PREFERRED_ORDER: tuple[PhotoKind, ...] = (
    PhotoKind.FRONT,
    PhotoKind.LABEL,
    PhotoKind.FULL_LOT,
    PhotoKind.DEFECT,
    PhotoKind.BACK,
    PhotoKind.SIZE_SPREAD,
    PhotoKind.PACKAGING,
)


@dataclass(frozen=True, slots=True)
class PreparedImage:
    data: bytes
    width: int
    height: int
    original_bytes: int

    @property
    def saved_bytes(self) -> int:
        return max(0, self.original_bytes - len(self.data))

    @property
    def saved_percent(self) -> float:
        if not self.original_bytes:
            return 0.0
        return round(self.saved_bytes / self.original_bytes * 100, 1)


class ImageError(ValueError):
    pass


def _open(raw: bytes) -> object:
    """Open an image without trusting its declared size.

    The size check happens on the header, before the pixels are decoded, so a
    decompression bomb is refused without the memory it would take to find out.
    """
    from PIL import Image, UnidentifiedImageError

    try:
        opened = Image.open(io.BytesIO(raw))
        if opened.width * opened.height > MAX_PIXELS:
            raise ImageError(
                "That image is too large to process. Upload a photograph of at most "
                f"{MAX_PIXELS // 1_000_000} megapixels."
            )
        opened.load()
    except Image.DecompressionBombError as exc:
        raise ImageError("That image is too large to process.") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageError("That file could not be read as an image. Upload a JPEG or PNG.") from exc
    return opened


def prepare(raw: bytes) -> PreparedImage:
    """Resize and recompress one photograph for a vision call.

    Converts to RGB first. A PNG with transparency or a CMYK scan from a
    print shop both fail JPEG encoding otherwise, and brands upload both.

    Re-encoding drops every metadata block, including the GPS position a phone
    writes into a photo taken in a warehouse. The orientation the camera
    recorded is applied to the pixels first, so dropping it does not leave a
    portrait photo lying on its side.
    """
    from PIL import Image, ImageOps

    original_bytes = len(raw)
    opened = _open(raw)
    assert isinstance(opened, Image.Image)

    # A separate name from `opened`, because convert and resize each return a
    # new Image rather than mutating the one the file was read into.
    image: Image.Image = ImageOps.exif_transpose(opened) or opened

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")

    longest = max(image.width, image.height)
    if longest > MAX_EDGE_PX:
        scale = MAX_EDGE_PX / longest
        image = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    data = buffer.getvalue()

    return PreparedImage(
        data=data,
        width=image.width,
        height=image.height,
        original_bytes=original_bytes,
    )


def blur_regions(raw: bytes, boxes: Sequence[Box]) -> bytes:
    """Return a copy of a photograph with each box made unreadable.

    Pixelated first, then blurred. A blur alone can leave large lettering
    legible, while reducing the region to a few blocks removes the detail
    before the blur smooths the edges.
    """
    from PIL import Image, ImageFilter

    opened = _open(raw)
    assert isinstance(opened, Image.Image)
    image = opened.convert("RGB")
    for box in boxes:
        left = max(0, floor(box.x * image.width))
        top = max(0, floor(box.y * image.height))
        right = min(image.width, ceil(box.right * image.width))
        bottom = min(image.height, ceil(box.bottom * image.height))
        width = right - left
        height = bottom - top
        if width <= 0 or height <= 0:
            continue

        region = image.crop((left, top, right, bottom))
        blocks = (max(1, width // BLUR_BLOCK_PX), max(1, height // BLUR_BLOCK_PX))
        hidden = region.resize(blocks, Image.Resampling.BOX).resize(
            (width, height), Image.Resampling.NEAREST
        )
        image.paste(hidden.filter(ImageFilter.GaussianBlur(BLUR_RADIUS_PX)), (left, top))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue()


def select_for_call(
    photos: list[tuple[PhotoKind, bytes]],
    limit: int = MAX_IMAGES_PER_CALL,
) -> list[tuple[PhotoKind, bytes]]:
    """Pick which photographs to send, best view first.

    Deduplicates by kind: two front shots are one view, not two, and sending
    both doubles the image tokens for no extra information.
    """
    by_kind: dict[PhotoKind, bytes] = {}
    for kind, raw in photos:
        by_kind.setdefault(kind, raw)

    ordered = [(kind, by_kind[kind]) for kind in PREFERRED_ORDER if kind in by_kind]
    # Anything with a kind not in the preference list still gets a chance,
    # after the known views.
    ordered += [(kind, raw) for kind, raw in by_kind.items() if kind not in PREFERRED_ORDER]

    return ordered[:limit]


def prepare_batch(photos: list[tuple[PhotoKind, bytes]]) -> tuple[list[bytes], dict[str, int]]:
    """Select, prepare and report.

    Returns the image payloads and a small stats dictionary that the caller
    logs alongside the AI job, so the compression saving appears next to the
    call it paid for rather than in a separate place nobody looks.
    """
    chosen = select_for_call(photos)
    prepared = [prepare(raw) for _kind, raw in chosen]

    stats = {
        "photos_supplied": len(photos),
        "photos_sent": len(prepared),
        "bytes_before": sum(p.original_bytes for p in prepared),
        "bytes_after": sum(len(p.data) for p in prepared),
    }
    stats["bytes_saved"] = stats["bytes_before"] - stats["bytes_after"]

    if stats["bytes_before"]:
        logger.info(
            "prepared %d of %d photographs, %d KB to %d KB (%.0f%% smaller)",
            stats["photos_sent"],
            stats["photos_supplied"],
            stats["bytes_before"] // 1024,
            stats["bytes_after"] // 1024,
            stats["bytes_saved"] / stats["bytes_before"] * 100,
        )

    return [p.data for p in prepared], stats
