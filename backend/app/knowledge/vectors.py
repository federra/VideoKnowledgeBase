"""Provider-neutral embedding interface. No configured provider, dispatch or automatic calls."""

import hashlib
import math
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from sqlalchemy.dialects.postgresql import insert as upsert

from app.core.models import metadata
from app.knowledge.search import index_publication
from app.knowledge.service import published
from app.security.errors import Denied


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str
    version: str
    dimensions: int

    def __post_init__(self):
        if (
            not self.model.strip()
            or not self.version.strip()
            or type(self.dimensions) is not int
            or not 1 <= self.dimensions <= 16000
        ):
            raise ValueError("Explicit model, version and dimensions required.")


class EmbeddingProvider(Protocol):
    config: EmbeddingConfig

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def checked_vector(value, dimensions):
    if (
        not isinstance(value, list)
        or len(value) != dimensions
        or any(type(x) not in (int, float) or not math.isfinite(x) for x in value)
    ):
        raise ValueError("Invalid embedding.")
    result = [float(x) for x in value]
    if not any(result) or not math.isfinite(sum(x * x for x in result)):
        raise ValueError("Nonzero finite embedding required.")
    return result


def chunks(text):
    return [(n, min(n + 800, len(text))) for n in range(0, len(text), 800)]


def store(c, p, publication_id, config, vectors):
    docid = index_publication(c, p, publication_id)
    doc = c.exec_driver_sql(
        "SELECT document_text FROM search_documents WHERE org_id=%s AND id=%s", (p.org_id, docid)
    ).scalar_one()
    parts = chunks(doc)
    if len(parts) != len(vectors):
        raise ValueError("One vector per exact chunk required.")
    checked = [checked_vector(v, config.dimensions) for v in vectors]
    for n, ((a, b), vector) in enumerate(zip(parts, checked, strict=True)):
        t = metadata.tables["embeddings"]
        existing = c.exec_driver_sql(
            "SELECT dimensions FROM embeddings WHERE org_id=%s AND search_document_id=%s AND chunk_no=%s AND embedding_model=%s AND model_version=%s",
            (p.org_id, docid, n, config.model, config.version),
        ).scalar_one_or_none()
        if existing is not None and existing != config.dimensions:
            raise ValueError("Model space changed without a version change.")
        c.execute(
            upsert(t)
            .values(
                id=uuid4(),
                org_id=p.org_id,
                search_document_id=docid,
                chunk_no=n,
                start_offset=a,
                end_offset=b,
                embedding_model=config.model,
                model_version=config.version,
                dimensions=config.dimensions,
                embedding=vector,
                content_sha256=hashlib.sha256(doc[a:b].encode()).hexdigest(),
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "org_id",
                    "search_document_id",
                    "chunk_no",
                    "embedding_model",
                    "model_version",
                ]
            )
        )
    return docid


def nearest(c, p, business, config, query_vector, limit=20):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("Invalid limit.")
    vector = checked_vector(query_vector, config.dimensions)
    rows = c.exec_driver_sql(
        "SELECT k.id,d.revision_id,e.embedding <=> %s::vector AS distance FROM embeddings e JOIN search_documents d ON d.org_id=e.org_id AND d.id=e.search_document_id JOIN knowledge_items k ON k.org_id=d.org_id AND k.published_publication_id=d.publication_id WHERE e.org_id=%s AND e.embedding_model=%s AND e.model_version=%s AND e.dimensions=%s ORDER BY distance,k.id,e.chunk_no",
        (
            "[" + ",".join(map(str, vector)) + "]",
            p.org_id,
            config.model,
            config.version,
            config.dimensions,
        ),
    ).mappings()
    result = []
    seen = set()
    for row in rows:
        if row["id"] in seen:
            continue
        try:
            item = published(c, p, row["id"])
        except Denied as ex:
            if ex.code == "NOT_FOUND":
                continue
            raise
        if business not in item["business_codes"] or item["revision_id"] != row["revision_id"]:
            continue
        seen.add(row["id"])
        result.append({"item": item, "distance": float(row["distance"])})
        if len(result) == limit:
            break
    return result
