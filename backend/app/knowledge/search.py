"""Deterministic text indexing; never generates external embeddings."""

import unicodedata
from uuid import UUID

from app.collection.service import insert
from app.security.authorization import Authorizer
from app.security.errors import Denied

INDEX_VERSION = "nfkc-char-v1"


def normalize(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def document(revision):
    return "\n".join([revision["title"], revision["body_text"], revision.get("limitations") or ""])


def index_publication(c, p, publication_id):
    from app.security.sessions import refresh
    from app.security.storage import lock_org

    lock_org(c, p.org_id)
    refresh(c, p)
    az = Authorizer(c, p)
    pub = (
        c.exec_driver_sql(
            "SELECT * FROM knowledge_publications WHERE org_id=%s AND id=%s",
            (p.org_id, UUID(str(publication_id))),
        )
        .mappings()
        .one_or_none()
    )
    if not pub:
        raise Denied("NOT_FOUND")
    identity = az.read("knowledge_items", pub["knowledge_id"])
    if identity["published_publication_id"] != pub["id"]:
        raise Denied("VERSION_CONFLICT")
    rev = az.read("knowledge_revisions", pub["revision_id"])
    if not az.allowed("knowledge.publish", az.scopes("knowledge_revisions", rev)):
        raise Denied("ACCESS_DENIED")
    old = c.exec_driver_sql(
        "SELECT id FROM search_documents WHERE org_id=%s AND publication_id=%s AND index_config_version=%s",
        (p.org_id, pub["id"], INDEX_VERSION),
    ).scalar_one_or_none()
    if old:
        return old
    text = document(rev)
    # Explicit character bigrams; no claim that `simple` tokenizes Chinese words.
    folded = normalize(text)
    tokens = " ".join(folded[i : i + 2] for i in range(max(1, len(folded) - 1)))
    vector = c.exec_driver_sql("SELECT to_tsvector('simple',%s)", (tokens,)).scalar_one()
    return insert(
        c,
        "search_documents",
        p.org_id,
        publication_id=pub["id"],
        revision_id=rev["id"],
        document_text=text,
        search_vector=vector,
        index_config_version=INDEX_VERSION,
    )
