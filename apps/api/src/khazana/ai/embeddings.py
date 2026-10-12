"""Image and text embeddings for visual and semantic search.

This is the one part of the AI layer that is not Claude. Anthropic has no
embeddings endpoint, so vectors come from a self hosted open model of the
SigLIP or CLIP class. That has three consequences worth stating plainly:

1. It is the only AI component with a fixed hosting cost rather than a per
   call cost, so it is budgeted separately.
2. Switching model changes the vector dimension, and mixing dimensions in one
   similarity query returns nonsense rather than an error. The dimension and
   the model name are therefore stored on every row and filtered on.
3. Nothing in this project has a GPU attached yet, so the default provider is
   a deterministic local one. It is a real, usable stand in for development
   and tests, and it is explicitly not a semantic model: see the class
   docstring for exactly what it can and cannot do.

Similarity search runs in PostgreSQL through pgvector. On SQLite the vector
column degrades to JSON, which stores and retrieves but cannot be searched, so
the search functions here require PostgreSQL and say so.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Embedding, Lot
from ..models.enums import EmbeddingOwner, LotStatus, Visibility

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SearchHit:
    lot: Lot
    distance: float

    @property
    def similarity(self) -> float:
        """Cosine distance turned into a 0 to 1 score for display.

        pgvector cosine distance runs 0 to 2, where 0 is identical. The
        interface shows a similarity, so the conversion lives here rather than
        being repeated at every call site with a different formula.
        """
        return max(0.0, min(1.0, 1.0 - self.distance / 2))


class EmbeddingProvider(ABC):
    """What any embedding backend must offer."""

    name: str
    dim: int

    @abstractmethod
    def embed_text(self, text_value: str) -> list[float]: ...

    @abstractmethod
    def embed_image(self, data: bytes) -> list[float]: ...


class HashingProvider(EmbeddingProvider):
    """A deterministic stand in, for development and tests.

    What it is: a hashed bag of character trigrams projected onto a fixed
    number of dimensions, then L2 normalised. Identical inputs give identical
    vectors, and inputs sharing many trigrams land near each other, so the
    whole storage and search path can be built and tested without a GPU.

    What it is not: semantic. It has no idea that kurta and shirt are related,
    or that two photographs show the same garment. For an image it hashes the
    bytes, so a recompressed copy of the same photograph is a different
    vector.

    It exists so that Phase 2 can ship a working search pipeline now and swap
    in a real model by changing one setting. Anything that reads a result from
    this provider and calls it semantic similarity is wrong.
    """

    name = "hashing-stub-v1"

    def __init__(self, dim: int = 768) -> None:
        self.dim = dim

    def embed_text(self, text_value: str) -> list[float]:
        cleaned = re.sub(r"\s+", " ", text_value.lower().strip())
        if not cleaned:
            return [0.0] * self.dim

        vector = [0.0] * self.dim
        padded = f"  {cleaned}  "
        for index in range(len(padded) - 2):
            trigram = padded[index : index + 3]
            digest = hashlib.sha256(trigram.encode()).digest()
            slot = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[slot] += sign
        return _normalise(vector)

    def embed_image(self, data: bytes) -> list[float]:
        # Hashing raw bytes, which is honest about what this can do: it finds
        # the identical file again and nothing else.
        vector = [0.0] * self.dim
        digest = hashlib.sha256(data).digest()
        for index in range(0, len(digest), 2):
            slot = int.from_bytes(digest[index : index + 2], "big") % self.dim
            vector[slot] += 1.0
        return _normalise(vector)


class RemoteProvider(EmbeddingProvider):
    """A self hosted embedding service, reached over HTTP.

    The expected contract is a small service wrapping a SigLIP or CLIP class
    model, exposing POST /embed/text and POST /embed/image. Keeping it behind
    HTTP rather than importing a model into this process is deliberate: the
    API should not carry a multi gigabyte dependency, and the embedding
    service can be scaled or switched off on its own.
    """

    def __init__(self, base_url: str, model: str, dim: int, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.name = model
        self.dim = dim
        self.timeout = timeout

    def embed_text(self, text_value: str) -> list[float]:
        return self._post("/embed/text", {"text": text_value})

    def embed_image(self, data: bytes) -> list[float]:
        import base64

        return self._post("/embed/image", {"image_base64": base64.b64encode(data).decode()})

    def _post(self, path: str, payload: dict[str, str]) -> list[float]:
        try:
            response = httpx.post(f"{self.base_url}{path}", json=payload, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise EmbeddingError(
                f"The embedding service at {self.base_url} did not answer: {exc}"
            ) from exc

        vector = response.json().get("embedding")
        if not isinstance(vector, list) or len(vector) != self.dim:
            got = len(vector) if isinstance(vector, list) else "no"
            raise EmbeddingError(
                f"The embedding service returned {got} dimensions, expected "
                f"{self.dim}. Check that the configured model matches."
            )
        return [float(value) for value in vector]


class EmbeddingError(RuntimeError):
    pass


_provider: EmbeddingProvider | None = None


def get_provider() -> EmbeddingProvider:
    global _provider
    if _provider is not None:
        return _provider

    settings = get_settings()
    if settings.embedding_service_url:
        _provider = RemoteProvider(
            base_url=settings.embedding_service_url,
            model=settings.embedding_model,
            dim=settings.embedding_dim,
        )
    else:
        logger.info(
            "no EMBEDDING_SERVICE_URL set, using the deterministic stub provider. "
            "Results are not semantic."
        )
        _provider = HashingProvider(dim=settings.embedding_dim)
    return _provider


def reset_provider() -> None:
    """Drop the cached provider. Used by tests that change configuration."""
    global _provider
    _provider = None


def lot_text(lot: Lot, category_name: str | None = None) -> str:
    """The text that represents a lot in semantic search.

    Built from fields a buyer would actually search on. The brand name is
    deliberately excluded: an unbranded listing must not become findable by
    brand name through the search index, which would quietly defeat the
    protection the brand was promised.
    """
    parts = [
        lot.title or "",
        category_name or "",
        lot.season or "",
        f"condition grade {lot.condition_grade.value}",
        lot.stock_city or "",
        lot.description or "",
    ]
    return " ".join(part for part in parts if part).strip()


def index_lot(db: Session, lot: Lot, *, category_name: str | None = None) -> Embedding:
    """Create or refresh the text vector for a lot."""
    provider = get_provider()
    vector = provider.embed_text(lot_text(lot, category_name))

    row = db.scalars(
        select(Embedding).where(
            Embedding.owner_type == EmbeddingOwner.LOT_TEXT,
            Embedding.owner_id == lot.id,
            Embedding.model == provider.name,
        )
    ).first()

    if row is None:
        row = Embedding(
            owner_type=EmbeddingOwner.LOT_TEXT,
            owner_id=lot.id,
            brand_id=lot.brand_id,
            lot_id=lot.id,
            model=provider.name,
            dim=provider.dim,
            vector=vector,
        )
        db.add(row)
    else:
        row.vector = vector
        row.dim = provider.dim

    db.flush()
    return row


def index_photo(db: Session, *, photo_id: str, lot: Lot, data: bytes) -> Embedding:
    """Create or refresh the image vector for one photograph."""
    provider = get_provider()
    vector = provider.embed_image(data)

    row = db.scalars(
        select(Embedding).where(
            Embedding.owner_type == EmbeddingOwner.LOT_PHOTO,
            Embedding.owner_id == photo_id,
            Embedding.model == provider.name,
        )
    ).first()

    if row is None:
        row = Embedding(
            owner_type=EmbeddingOwner.LOT_PHOTO,
            owner_id=photo_id,
            brand_id=lot.brand_id,
            lot_id=lot.id,
            model=provider.name,
            dim=provider.dim,
            vector=vector,
        )
        db.add(row)
    else:
        row.vector = vector
        row.dim = provider.dim

    db.flush()
    return row


def supports_similarity(db: Session) -> bool:
    """Whether this database can actually run a vector search.

    SQLite stores the vector as JSON and cannot search it. Callers check this
    and fall back to keyword search rather than returning an empty result that
    looks like no matches.
    """
    return db.bind is not None and db.bind.dialect.name == "postgresql"


def search(
    db: Session,
    query_vector: list[float],
    *,
    owner_type: EmbeddingOwner = EmbeddingOwner.LOT_TEXT,
    limit: int = 20,
    visible_only: bool = True,
    exclude_brand_id: str | None = None,
) -> list[SearchHit]:
    """Nearest lots by cosine distance.

    Two filters are not optional and are applied in SQL rather than afterwards.

    ``visible_only`` keeps draft, pending and withdrawn lots out of buyer
    results. Filtering after the fact would silently shrink a page of results
    and, worse, would let an unapproved listing leak if a caller forgot.

    ``exclude_brand_id`` supports the brand facing use of this search, where a
    brand looking for comparable lots must not be shown another brand's stock.
    """
    if not supports_similarity(db):
        raise EmbeddingError(
            "Vector search needs PostgreSQL with pgvector. On SQLite the vector "
            "column stores and retrieves but cannot be searched, so callers should "
            "fall back to keyword search."
        )

    provider = get_provider()

    conditions = [
        "e.owner_type = :owner_type",
        "e.model = :model",
        "e.dim = :dim",
        "l.deleted_at IS NULL",
    ]
    params: dict[str, object] = {
        "owner_type": owner_type.value,
        "model": provider.name,
        "dim": provider.dim,
        "query": str(query_vector),
        "limit": limit,
    }

    if visible_only:
        conditions.append("l.status = :live")
        conditions.append("l.approved_at IS NOT NULL")
        conditions.append("l.visibility <> :unbranded_hidden")
        params["live"] = LotStatus.LIVE.value
        # Private lots are excluded from general search. They are reachable
        # only through the verified reseller path, which is a Phase 3 query.
        params["unbranded_hidden"] = Visibility.PRIVATE.value

    if exclude_brand_id is not None:
        conditions.append("l.brand_id <> :exclude_brand")
        params["exclude_brand"] = exclude_brand_id

    statement = text(
        f"""
        SELECT l.id AS lot_id, (e.vector <=> CAST(:query AS vector)) AS distance
        FROM embeddings e
        JOIN lots l ON l.id = e.lot_id
        WHERE {" AND ".join(conditions)}
        ORDER BY distance ASC
        LIMIT :limit
        """  # noqa: S608  conditions are built from constants, values are bound
    )

    rows = db.execute(statement, params).all()
    if not rows:
        return []

    lots = {
        lot.id: lot
        for lot in db.scalars(select(Lot).where(Lot.id.in_([row.lot_id for row in rows]))).all()
    }
    return [
        SearchHit(lot=lots[row.lot_id], distance=float(row.distance))
        for row in rows
        if row.lot_id in lots
    ]


def search_by_text(db: Session, query: str, **kwargs: object) -> list[SearchHit]:
    return search(db, get_provider().embed_text(query), **kwargs)  # type: ignore[arg-type]


def search_by_image(db: Session, data: bytes, **kwargs: object) -> list[SearchHit]:
    kwargs.setdefault("owner_type", EmbeddingOwner.LOT_PHOTO)
    return search(db, get_provider().embed_image(data), **kwargs)  # type: ignore[arg-type]


def _normalise(vector: list[float]) -> list[float]:
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude == 0:
        return vector
    return [value / magnitude for value in vector]
