"""Manifest extraction.

The rule under test throughout: the extractor proposes, a human disposes. A
manifest that was quietly adjusted to make the arithmetic work is worse than
one that openly does not add up, because the first one gets shipped and the
second one gets checked.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from khazana.ai.features import manifest_extract as feature
from khazana.ai.gateway import client, prompts
from khazana.ai.schemas import ManifestLineDraft
from khazana.core.errors import ValidationFailed

CSV_CLEAN = "size,colour,pieces\nS,black,20\nM,black,30\nL,navy,25\n"
CSV_MESSY = (
    "Meher Textiles stock sheet\n,,\nsize,colour,qty\nS,black,20\nS,Black,5\n,navy,10\nTOTAL,,60\n"
)


def stub(tmp_path, monkeypatch, *, csv_text: str, filename: str, content: dict) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(client, "FIXTURE_DIR", tmp_path)
    table_text, row_count, _encoding = feature.read_table(csv_text.encode(), filename)
    prompt = prompts.load(feature.PROMPT)
    user_text = prompt.render(filename=filename, row_count=row_count, table_text=table_text)
    key = client.fixture_key(
        feature="manifest_extract",
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        user_text=user_text,
        images=0,
    )
    path = tmp_path / "manifest_extract" / f"{key}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "model": "claude-opus-5-5",
                "content": content,
                "usage": {"input_tokens": 2100, "output_tokens": 340},
            }
        ),
        encoding="utf-8",
    )


class TestReadTable:
    def test_a_clean_csv_is_rendered_as_rows(self) -> None:
        text, rows, encoding = feature.read_table(CSV_CLEAN.encode(), "stock.csv")
        assert rows == 4
        assert encoding == "utf-8"
        assert "S | black | 20" in text

    def test_blank_rows_are_dropped(self) -> None:
        _text, rows, _encoding = feature.read_table(CSV_MESSY.encode(), "stock.csv")
        assert rows == 6

    def test_a_legacy_windows_encoding_still_reads(self) -> None:
        """A file that is not valid UTF-8 gets one fallback, not a rejection.

        Older Windows Excel writes Arabic script as cp1256. The fallback is
        deliberately narrow, and this test documents why: cp1256 is the
        Arabic codepage and cannot encode every Urdu letter, which is why the
        failure message still asks the brand for CSV UTF-8.
        """
        content = "size,colour,pieces\nM,سياه,15\n"
        raw = content.encode("cp1256")
        with pytest.raises(UnicodeDecodeError):
            raw.decode("utf-8")

        text, _rows, encoding = feature.read_table(raw, "stock.csv")
        assert "15" in text
        assert encoding == "cp1256"

    def test_a_fallback_decode_is_reported_rather_than_silent(self) -> None:
        """cp1256 maps almost every byte, so it never fails loudly.

        That is the real hazard here. A UTF-16 or Windows-1252 file decodes
        into plausible looking nonsense rather than raising, so the only safe
        answer is to report which encoding was used and let a person check the
        colour names.
        """
        raw = b"size,colour,pieces\nM," + bytes([0x81, 0x8D, 0x8F]) + b",5\n"
        with pytest.raises(UnicodeDecodeError):
            raw.decode("utf-8")

        text, _rows, encoding = feature.read_table(raw, "stock.csv")
        assert encoding == "cp1256"
        assert "5" in text

    def test_a_utf8_bom_does_not_corrupt_the_first_header(self) -> None:
        text, _rows, _encoding = feature.read_table(CSV_CLEAN.encode("utf-8-sig"), "stock.csv")
        assert text.startswith("size |")

    def test_excel_gets_an_instruction_not_a_crash(self) -> None:
        with pytest.raises(ValidationFailed, match="Save As"):
            feature.read_table(b"PK\x03\x04", "stock.xlsx")

    def test_an_unsupported_type_is_refused(self) -> None:
        with pytest.raises(ValidationFailed, match="CSV"):
            feature.read_table(b"x", "stock.pdf")

    def test_an_empty_file_is_refused(self) -> None:
        with pytest.raises(ValidationFailed, match="no rows"):
            feature.read_table(b"\n\n,,\n", "stock.csv")

    def test_an_oversized_file_is_refused_before_any_cost(self) -> None:
        big = "size,colour,pieces\n" + "".join(f"S,black,{i}\n" for i in range(500))
        with pytest.raises(ValidationFailed, match="limit is"):
            feature.read_table(big.encode(), "stock.csv")


class TestMergeDuplicates:
    def test_repeated_pairs_are_combined_and_reported(self) -> None:
        lines = [
            ManifestLineDraft(size="S", color="black", pieces=20),
            ManifestLineDraft(size="S", color="Black", pieces=5),
            ManifestLineDraft(size="M", color="navy", pieces=10),
        ]
        merged, notes = feature.merge_duplicates(lines)

        assert len(merged) == 2
        assert merged[0].pieces == 25
        assert len(notes) == 1
        assert "appeared more than once" in notes[0]

    def test_merging_is_silent_when_there_is_nothing_to_merge(self) -> None:
        lines = [
            ManifestLineDraft(size="S", color="black", pieces=20),
            ManifestLineDraft(size="M", color="navy", pieces=10),
        ]
        merged, notes = feature.merge_duplicates(lines)
        assert len(merged) == 2
        assert notes == []


class TestExtract:
    def test_a_balanced_file_needs_no_review(
        self, db: Session, two_brands, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        stub(
            tmp_path,
            monkeypatch,
            csv_text=CSV_CLEAN,
            filename="stock.csv",
            content={
                "lines": [
                    {"size": "S", "color": "black", "pieces": 20},
                    {"size": "M", "color": "black", "pieces": 30},
                    {"size": "L", "color": "navy", "pieces": 25},
                ],
                "declared_total": 75,
                "notes": [],
                "proposed_corrections": [],
                "confidence": 0.95,
            },
        )

        outcome = feature.extract(
            db, data=CSV_CLEAN.encode(), filename="stock.csv", brand_id=brand.id
        )

        assert outcome.balanced
        assert outcome.line_total == 75
        assert outcome.difference == 0
        assert not outcome.needs_review
        assert "matching the file total" in outcome.summary()

    def test_a_mismatch_is_reported_and_never_silently_fixed(
        self, db: Session, two_brands, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        """The most important test in this file.

        The file says 60, the rows say 35. The lines must come back as read,
        the difference must be stated, and nothing may be invented to close
        the gap.
        """
        (brand, _), _ = two_brands
        stub(
            tmp_path,
            monkeypatch,
            csv_text=CSV_MESSY,
            filename="stock.csv",
            content={
                "lines": [
                    {"size": "S", "color": "black", "pieces": 20},
                    {"size": "S", "color": "Black", "pieces": 5},
                    {"size": "One size", "color": "navy", "pieces": 10},
                ],
                "declared_total": 60,
                "notes": [],
                "proposed_corrections": ["A row had no size, recorded as One size."],
                "confidence": 0.6,
            },
        )

        outcome = feature.extract(
            db, data=CSV_MESSY.encode(), filename="stock.csv", brand_id=brand.id
        )

        assert not outcome.balanced
        assert outcome.line_total == 35
        assert outcome.declared_total == 60
        assert outcome.difference == -25
        assert outcome.needs_review
        assert any("Difference of -25" in c for c in outcome.corrections)
        assert any("Nothing has been changed" in c for c in outcome.corrections)

    def test_duplicates_are_merged_by_code_not_by_the_model(
        self, db: Session, two_brands, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        """Arithmetic is done in code, and the unique constraint is respected.

        Two rows for small black would be rejected by the database anyway,
        with a far worse message than this one.
        """
        (brand, _), _ = two_brands
        stub(
            tmp_path,
            monkeypatch,
            csv_text=CSV_MESSY,
            filename="stock.csv",
            content={
                "lines": [
                    {"size": "S", "color": "black", "pieces": 20},
                    {"size": "S", "color": "Black", "pieces": 5},
                ],
                "declared_total": 25,
                "notes": [],
                "proposed_corrections": [],
                "confidence": 0.8,
            },
        )

        outcome = feature.extract(
            db, data=CSV_MESSY.encode(), filename="stock.csv", brand_id=brand.id
        )

        assert len(outcome.lines) == 1
        assert outcome.lines[0].pieces == 25
        assert outcome.balanced
        assert any("appeared more than once" in c for c in outcome.corrections)

    def test_no_declared_total_is_not_an_error(
        self, db: Session, two_brands, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        stub(
            tmp_path,
            monkeypatch,
            csv_text=CSV_CLEAN,
            filename="stock.csv",
            content={
                "lines": [{"size": "S", "color": "black", "pieces": 20}],
                "declared_total": None,
                "notes": [],
                "proposed_corrections": [],
                "confidence": 0.9,
            },
        )

        outcome = feature.extract(
            db, data=CSV_CLEAN.encode(), filename="stock.csv", brand_id=brand.id
        )

        assert outcome.balanced
        assert outcome.difference is None
        assert "no total stated" in outcome.summary()

    def test_low_confidence_alone_triggers_review(
        self, db: Session, two_brands, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        stub(
            tmp_path,
            monkeypatch,
            csv_text=CSV_CLEAN,
            filename="stock.csv",
            content={
                "lines": [{"size": "S", "color": "black", "pieces": 20}],
                "declared_total": 20,
                "notes": ["The file had merged cells."],
                "proposed_corrections": [],
                "confidence": 0.4,
            },
        )

        outcome = feature.extract(
            db, data=CSV_CLEAN.encode(), filename="stock.csv", brand_id=brand.id
        )

        assert outcome.balanced
        assert outcome.needs_review
        assert outcome.notes == ["The file had merged cells."]

    def test_rows_are_shaped_for_insertion_without_being_inserted(
        self, db: Session, two_brands, tmp_path, monkeypatch
    ) -> None:  # type: ignore[no-untyped-def]
        (brand, _), _ = two_brands
        stub(
            tmp_path,
            monkeypatch,
            csv_text=CSV_CLEAN,
            filename="stock.csv",
            content={
                "lines": [{"size": "S", "color": "black", "pieces": 20}],
                "declared_total": 20,
                "notes": [],
                "proposed_corrections": [],
                "confidence": 0.9,
            },
        )

        outcome = feature.extract(
            db, data=CSV_CLEAN.encode(), filename="stock.csv", brand_id=brand.id
        )
        rows = feature.to_manifest_rows(outcome, lot_id="lot-1", brand_id=brand.id)

        assert rows == [
            {
                "lot_id": "lot-1",
                "brand_id": brand.id,
                "size": "S",
                "color": "black",
                "pieces": 20,
            }
        ]


def test_a_filename_cannot_carry_a_path_into_the_prompt() -> None:
    assert feature._safe_name("../../etc/passwd") == "passwd"
    assert feature._safe_name("C:\\Users\\x\\stock.csv") == "stock.csv"
