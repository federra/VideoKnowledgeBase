"""Read batching in isolated PG must keep private-source ownership exact."""

from uuid import uuid4

import pytest
from sqlalchemy import event

from app.security.authorization import Authorizer
from app.security.read_authorizer import ReadAuthorizer
from app.security.sessions import MemberPrincipal
from tests.integration.test_schema import base, connection

pytestmark = pytest.mark.database
__all__ = ["connection"]


def test_shared_raw_personal_dependencies_use_bounded_queries(connection):
    c = connection
    org, member, _ = base(c)
    p = MemberPrincipal(org, member)
    ids = []
    for _ in range(25):
        ident = uuid4()
        ids.append(ident)
        c.exec_driver_sql(
            "INSERT INTO raw_assets(id,org_id,origin,asset_kind,submitted_by,body_text,sha256,captured_at) VALUES(%s,%s,'manual','text',%s,'shared',%s,clock_timestamp())",
            (ident, org, member, "a" * 64),
        )
    expected = {r: tuple(Authorizer(c, p).personal_dependencies("raw_assets", r)) for r in ids}
    az = ReadAuthorizer(c, p)
    queries = []

    def track(conn, cursor, statement, parameters, context, many):
        queries.append(statement)

    event.listen(c, "before_cursor_execute", track)
    try:
        assert {r: tuple(az.personal_dependencies("raw_assets", r)) for r in ids} == expected
    finally:
        event.remove(c, "before_cursor_execute", track)
    assert len(queries) <= 4
