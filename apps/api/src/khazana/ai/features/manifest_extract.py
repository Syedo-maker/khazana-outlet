"""Manifest extraction and repair.

A brand sends a spreadsheet. It has merged cells, a logo in the first four
rows, subtotals in the middle, three spellings of the same colour, and a grand
total that does not match the rows. This module turns that into manifest lines
the catalogue can accept, or says clearly why it cannot.

The governing rule, enforced here and not only asked for in the prompt: the
extractor proposes, a human disposes. Nothing is silently reconciled. When the
lines do not sum to the declared total, that difference is reported and the
lines are left as they were read.

Two things are done in code rather than by the model, because they are
deterministic and a model is the wrong tool for arithmetic:

- the sum, and the comparison against the declared total
- merging duplicate size and colour pairs
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ...core.errors import ValidationFailed
from ...models.enums import AiFeature
from ..gateway import AiResult, run_feature
from ..schemas import ManifestDraft, ManifestLineDraft

logger = logging.getLogger(__name__)

PROMPT = "manifest_extract"

# A spreadsheet beyond this is not a lot manifest, it is a year of stock, and
# sending it would be an expensive way to find that out.
MAX_ROWS = 400
MAX_CHARS = 60_000


@dataclass(slots=True)
class ExtractionOutcome:
    lines: list[ManifestLineDraft]
    result: AiResult
    declared_total: int | None
    line_total: int
    balanced: bool
    corrections: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Set when the file was not UTF-8, so the caller can warn about mojibake.
    fallback_encoding: str | None = None
    confidence: float = 0.0

    @property
    def difference(self) -> int | None:
        """How far out the file is. Positive means the rows exceed the total."""
        if self.declared_total is None:
            return None
        return self.line_total - self.declared_total

    @property
    def needs_review(self) -> bool:
        """Anything other than a clean, balanced, confident read."""
        return (
            not self.balanced
            or bool(self.corrections)
            or self.confidence < 0.7
            or self.fallback_encoding is not None
        )

    def summary(self) -> str:
        if self.declared_total is None:
            return (
                f"{len(self.lines)} lines, {self.line_total} pieces, "
                "no total stated in the file."
            )
        if self.balanced:
            return f"{len(self.lines)} lines, {self.line_total} pieces, matching the file total."
        return (
            f"{len(self.lines)} lines summing to {self.line_total} pieces, but the file "
            f"states {self.declared_total}. Difference of {self.difference:+d}."
        )


def read_table(data: bytes, filename: str) -> tuple[str, int, str]:
    """Turn an uploaded file into plain text rows for the prompt.

    CSV is parsed here. Excel needs openpyxl, which is not a dependency yet,
    so an xlsx upload gets a clear instruction rather than a stack trace. That
    is a deliberate scope choice for week 9: most brands can export CSV, and
    adding a binary parser is a separate decision with its own attack surface.
    """
    lower = filename.lower()

    if lower.endswith((".xlsx", ".xls")):
        raise ValidationFailed(
            "Excel files are not supported yet. In Excel choose File, then Save As, "
            "then CSV, and upload that."
        )

    if not lower.endswith((".csv", ".tsv", ".txt")):
        raise ValidationFailed("Upload a CSV file exported from your spreadsheet.")

    try:
        text = data.decode("utf-8-sig")
        encoding = "utf-8"
    except UnicodeDecodeError:
        # Older Windows Excel exports Arabic script as cp1256, so a file that
        # is not valid UTF-8 gets one fallback rather than an outright
        # rejection.
        #
        # The fallback is reported, not silent, and that matters: cp1256 maps
        # almost every byte to some character, so it will happily decode a
        # file that was really Windows-1252 or UTF-16 and hand back plausible
        # looking nonsense. A caller that does not know which encoding was
        # used cannot warn anyone to check the colour names. cp1256 also
        # cannot represent every Urdu letter, so UTF-8 stays the ask.
        try:
            text = data.decode("cp1256")
            encoding = "cp1256"
        except UnicodeDecodeError as exc:
            raise ValidationFailed(
                "That file's text encoding could not be read. Re-save it as CSV UTF-8."
            ) from exc

    delimiter = "\t" if lower.endswith(".tsv") else ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    rows = [row for row in rows if any(cell.strip() for cell in row)]

    if not rows:
        raise ValidationFailed("That file has no rows in it.")
    if len(rows) > MAX_ROWS:
        raise ValidationFailed(
            f"That file has {len(rows)} rows. The limit is {MAX_ROWS}. "
            "Split it into one file per lot."
        )

    rendered = "\n".join(" | ".join(cell.strip() for cell in row) for row in rows)
    if len(rendered) > MAX_CHARS:
        rendered = rendered[:MAX_CHARS] + "\n[truncated]"

    return rendered, len(rows), encoding


def extract(
    db: Session,
    *,
    data: bytes,
    filename: str,
    brand_id: str,
    user_id: str | None = None,
    lot_id: str | None = None,
    record_fixture: bool = False,
) -> ExtractionOutcome:
    """Extract a manifest from an uploaded spreadsheet."""
    table_text, row_count, encoding = read_table(data, filename)

    result = run_feature(
        db,
        AiFeature.MANIFEST_EXTRACT,
        prompt_name=PROMPT,
        prompt_values={
            "filename": _safe_name(filename),
            "row_count": row_count,
            "table_text": table_text,
        },
        brand_id=brand_id,
        user_id=user_id,
        entity_type="lot" if lot_id else "upload",
        entity_id=lot_id,
        record_fixture=record_fixture,
    )

    draft = result.output
    assert isinstance(draft, ManifestDraft)

    lines, merge_notes = merge_duplicates(draft.lines)
    line_total = sum(line.pieces for line in lines)
    corrections = [*draft.proposed_corrections, *merge_notes]

    balanced = draft.declared_total is None or line_total == draft.declared_total
    if not balanced:
        difference = line_total - (draft.declared_total or 0)
        corrections.append(
            f"The rows sum to {line_total} pieces but the file states "
            f"{draft.declared_total}. Difference of {difference:+d}. Nothing has "
            "been changed to hide this."
        )

    notes = list(draft.notes)
    if encoding != "utf-8":
        # Surfaced rather than swallowed. A wrong guess here produces readable
        # nonsense instead of an error, so a person has to look.
        notes.insert(
            0,
            f"This file was not valid UTF-8 and was read as {encoding}. Check the "
            "size and colour names carefully, and ask the brand to re-save as "
            "CSV UTF-8 next time.",
        )

    return ExtractionOutcome(
        lines=lines,
        result=result,
        declared_total=draft.declared_total,
        line_total=line_total,
        balanced=balanced,
        corrections=corrections,
        notes=notes,
        fallback_encoding=None if encoding == "utf-8" else encoding,
        confidence=draft.confidence,
    )


def merge_duplicates(
    lines: list[ManifestLineDraft],
) -> tuple[list[ManifestLineDraft], list[str]]:
    """Combine repeated size and colour pairs, and say that it happened.

    Done in code rather than by the model: it is pure arithmetic, it must be
    exact, and the database has a unique constraint on the pair that would
    reject duplicates anyway, with a far worse error message.
    """
    merged: dict[tuple[str, str], ManifestLineDraft] = {}
    notes: list[str] = []

    for line in lines:
        key = (line.size.strip(), line.color.strip().lower())
        existing = merged.get(key)
        if existing is None:
            merged[key] = ManifestLineDraft(size=key[0], color=key[1], pieces=line.pieces)
        else:
            combined = existing.pieces + line.pieces
            notes.append(
                f"{key[0]} in {key[1]} appeared more than once and the counts were "
                f"added together, giving {combined}."
            )
            merged[key] = ManifestLineDraft(size=key[0], color=key[1], pieces=combined)

    return list(merged.values()), notes


def to_manifest_rows(
    outcome: ExtractionOutcome, *, lot_id: str, brand_id: str
) -> list[dict[str, object]]:
    """Shape the accepted lines for insertion.

    Deliberately returns plain dictionaries rather than ORM objects. The
    extraction is a proposal; the service layer decides whether and when it
    becomes rows, after a human has accepted it.
    """
    return [
        {
            "lot_id": lot_id,
            "brand_id": brand_id,
            "size": line.size[:32],
            "color": line.color[:48],
            "pieces": line.pieces,
        }
        for line in outcome.lines
    ]


def _safe_name(filename: str) -> str:
    """Strip a path and bound the length before a filename enters a prompt."""
    tail = filename.replace("\\", "/").rsplit("/", 1)[-1]
    return tail[:120]
