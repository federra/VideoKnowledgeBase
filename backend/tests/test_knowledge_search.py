"""Filter-bound cursor regression; no DB or external calls."""

from types import SimpleNamespace
from uuid import uuid4

import pytest


def test_filter_field_boundaries_cannot_reuse_cursor():
    from app.collection.paging import page
    from app.contracts.api import KnowledgeQuery
    from app.knowledge.http import filter_scope
    from app.security.errors import Denied

    a = KnowledgeQuery(business_code="motion_comic", tag="stage:a", q="bc", limit=1)
    b = KnowledgeQuery(business_code="motion_comic", tag="stage:ab", q="c", limit=1)

    class C:
        def exec_driver_sql(self, *_):
            return SimpleNamespace(scalar_one=lambda: 1)

    p = SimpleNamespace(org_id=uuid4(), member_id=uuid4())
    data = {
        "items": [
            {"id": str(uuid4()), "created_at": "2026-10-17T00:00:00Z"},
            {"id": str(uuid4()), "created_at": "2026-10-16T00:00:00Z"},
        ]
    }
    first = page(
        C(), p, data, kind=filter_scope("searchKnowledge", a), business="motion_comic", limit=1
    )
    with pytest.raises(Denied, match="CURSOR_EXPIRED"):
        page(
            C(),
            p,
            data,
            kind=filter_scope("searchKnowledge", b),
            business="motion_comic",
            limit=1,
            cursor=first["next_cursor"],
        )
