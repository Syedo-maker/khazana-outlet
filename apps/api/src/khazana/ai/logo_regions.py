"""Where a logo blur has to go, worked out by arithmetic.

The model only says roughly where a mark is. How far the blur extends past
that, and whether the result hid the mark, are decided here, so the eval
grades the same geometry the blur will apply.

Every value is a fraction of the image, from 0 to 1, with the origin at the
top left. Fractions survive the photograph being resized.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise

# Model boxes are approximate, and a blur that stops one letter short still
# shows the brand. Each side grows by this share of the box's own size.
PADDING_RATIO = 0.30
# A tiny mark gets a proportionally tiny margin, so there is also a floor.
MIN_PADDING = 0.015

# How much of a mark has to sit under the blur for it to count as hidden.
MIN_MARK_COVERAGE = 0.95


@dataclass(frozen=True, slots=True)
class Box:
    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def area(self) -> float:
        return self.width * self.height


FULL_IMAGE = Box(0.0, 0.0, 1.0, 1.0)


def clip(box: Box, to: Box = FULL_IMAGE) -> Box:
    """The part of ``box`` inside ``to``, zero sized when they do not meet."""
    left = max(box.x, to.x)
    top = max(box.y, to.y)
    right = max(left, min(box.right, to.right))
    bottom = max(top, min(box.bottom, to.bottom))
    return Box(left, top, right - left, bottom - top)


def pad(box: Box) -> Box:
    """Grow a box by the safety margin, staying inside the image."""
    margin_x = max(box.width * PADDING_RATIO, MIN_PADDING)
    margin_y = max(box.height * PADDING_RATIO, MIN_PADDING)
    return clip(
        Box(
            box.x - margin_x,
            box.y - margin_y,
            box.width + 2 * margin_x,
            box.height + 2 * margin_y,
        )
    )


def union_area(boxes: Iterable[Box], within: Box = FULL_IMAGE) -> float:
    """Area covered by any of the boxes, counting overlaps once."""
    clipped = [part for part in (clip(box, within) for box in boxes) if part.area > 0]
    xs = sorted({edge for box in clipped for edge in (box.x, box.right)})
    ys = sorted({edge for box in clipped for edge in (box.y, box.bottom)})

    area = 0.0
    for left, right in pairwise(xs):
        for top, bottom in pairwise(ys):
            if any(
                box.x <= left and box.right >= right and box.y <= top and box.bottom >= bottom
                for box in clipped
            ):
                area += (right - left) * (bottom - top)
    return area


def coverage(mark: Box, blurred: Sequence[Box]) -> float:
    """The share of ``mark`` that sits under the blurred boxes."""
    visible_mark = clip(mark)
    if visible_mark.area == 0:
        return 1.0
    return union_area(blurred, within=visible_mark) / visible_mark.area
